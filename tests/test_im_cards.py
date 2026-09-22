"""AI 卡片会话：协议字段、节流策略与长度约束。

这三件事都是「配额与正确性」的直接来源：场域写错卡片投不出去，``guid`` 复用会让
更新被吞掉，节流失效会把一次回复放大成几十次接口调用。
"""

import asyncio

import pytest

from app.im.cards import (
    ENV_CARD_LEVEL,
    ENV_CARD_LEVEL_PREFIX,
    LEVEL_STAGED,
    LEVEL_STREAM,
    LEVEL_TWO_STATE,
    MAX_CARD_CONTENT_CHARS,
    ThrottlePolicy,
    card_channel,
    card_level,
    clamp_card_content,
    policy_for,
)
from app.im.cards import dingtalk as card_link
from app.im.credentials import ChannelCredential


def _credential() -> ChannelCredential:
    return ChannelCredential(
        channel_id="chan_1", app_id="app_1", tenant_key="corp_1", app_secret="secret"
    )


class FakeResponse:
    def __init__(self, status_code: int = 200, payload=None):
        self.status_code = status_code
        self._payload = {"success": True} if payload is None else payload

    def json(self):
        return self._payload


class FakeHttp:
    """按顺序吐出预置响应，并记录每次请求。"""

    def __init__(self, responses=None):
        self.requests: list[tuple[str, str, dict]] = []
        self._responses = list(responses or [])

    async def post(self, url, json=None, headers=None):
        self.requests.append(("POST", url, json))
        return self._take()

    async def put(self, url, json=None, headers=None):
        self.requests.append(("PUT", url, json))
        return self._take()

    def _take(self):
        return self._responses.pop(0) if self._responses else FakeResponse()

    def urls_ending(self, suffix: str) -> list[tuple[str, str, dict]]:
        return [item for item in self.requests if item[1].endswith(suffix)]


@pytest.fixture(autouse=True)
def _clean_token_cache():
    card_link.reset_token_cache()
    yield
    card_link.reset_token_cache()


def _session(http, *, space_type="IM_ROBOT", space_id="staff_1", policy=None):
    return card_link.DingtalkCardSession(
        http=http,
        credential=_credential(),
        template_id="tpl_1",
        space_type=space_type,
        space_id=space_id,
        policy=policy or policy_for(LEVEL_STREAM),
    )


def _token_response() -> FakeResponse:
    return FakeResponse(payload={"accessToken": "tok", "expireIn": 7200})


# ------------------------------------------------------------------ 投放场域


def test_open_writes_robot_space_and_template_variable():
    http = FakeHttp([_token_response(), FakeResponse()])
    session = _session(http)

    asyncio.run(session.open("正在处理"))

    method, url, body = http.requests[-1]
    assert method == "POST"
    assert url.endswith("/v1.0/card/instances/createAndDeliver")
    assert body["cardTemplateId"] == "tpl_1"
    assert body["outTrackId"] == session.out_track_id
    # 单聊场域用员工 userId，不是 conversationId。
    assert body["openSpaceId"] == "dtv1.card//IM_ROBOT.staff_1"
    # 变量名必须与模板一致；投放阶段就把初始文案带上，省掉一条独立提示消息。
    assert body["cardData"]["cardParamMap"] == {"content": "正在处理"}
    assert body["imRobotOpenDeliverModel"] == {"spaceType": "IM_ROBOT"}
    assert "imGroupOpenDeliverModel" not in body
    assert session.opened is True


def test_group_space_carries_robot_code():
    http = FakeHttp([_token_response(), FakeResponse()])
    session = _session(http, space_type="IM_GROUP", space_id="cid_1")

    asyncio.run(session.open("hi"))

    body = http.requests[-1][2]
    assert body["openSpaceId"] == "dtv1.card//IM_GROUP.cid_1"
    assert body["imGroupOpenDeliverModel"] == {"robotCode": "app_1"}
    assert "imRobotOpenDeliverModel" not in body


def test_open_failure_raises_so_caller_can_fall_back():
    http = FakeHttp([_token_response(), FakeResponse(403, {"success": False})])
    session = _session(http)

    with pytest.raises(card_link.DingtalkCardError):
        asyncio.run(session.open("x"))
    assert session.opened is False


# ------------------------------------------------------------------ accessToken


def test_access_token_is_cached_across_operations():
    http = FakeHttp([_token_response(), FakeResponse(), FakeResponse()])
    session = _session(http)

    asyncio.run(session.open("a"))
    asyncio.run(session.finalize("b"))

    assert len(http.urls_ending("/oauth2/accessToken")) == 1
    assert session.finalized is True


def test_token_failure_raises():
    http = FakeHttp([FakeResponse(500, {})])

    with pytest.raises(card_link.DingtalkCardError):
        asyncio.run(_session(http).open("x"))


# -------------------------------------------------------------------- 流式更新


def test_streaming_update_sends_full_content_with_fresh_guid():
    http = FakeHttp([_token_response(), FakeResponse(), FakeResponse(), FakeResponse()])
    session = _session(http)

    asyncio.run(session.open("a"))
    asyncio.run(session.push("ab"))
    asyncio.run(session.finalize("abc"))

    updates = [item[2] for item in http.urls_ending("/v1.0/card/streaming")]
    assert len(updates) == 2
    assert all(item["isFull"] is True for item in updates)
    assert all(item["key"] == "content" for item in updates)
    # guid 复用会让服务端把后续更新当成重复请求吞掉。
    assert updates[0]["guid"] != updates[1]["guid"]
    assert updates[0]["isFinalize"] is False
    assert updates[1]["isFinalize"] is True
    assert updates[1]["isError"] is False
    assert updates[1]["content"] == "abc"


def test_push_respects_min_delta():
    policy = ThrottlePolicy(min_interval_seconds=0.0, min_delta_chars=10, max_updates=5)
    http = FakeHttp([_token_response(), FakeResponse(), FakeResponse()])
    session = _session(http, policy=policy)

    asyncio.run(session.open("0123456789"))
    asyncio.run(session.push("0123456789"))
    asyncio.run(session.push("0123456789abc"))
    asyncio.run(session.push("0123456789abcdefghij"))

    pushes = http.urls_ending("/v1.0/card/streaming")
    assert len(pushes) == 1
    assert pushes[0][2]["content"] == "0123456789abcdefghij"
    assert session.update_count == 1


def test_push_stops_at_max_updates():
    policy = ThrottlePolicy(min_interval_seconds=0.0, min_delta_chars=1, max_updates=2)
    http = FakeHttp([_token_response()] + [FakeResponse()] * 3)
    session = _session(http, policy=policy)

    asyncio.run(session.open("a"))
    for length in (2, 3, 4, 5, 6):
        asyncio.run(session.push("x" * length))

    assert len(http.urls_ending("/v1.0/card/streaming")) == 2
    assert session.update_count == 2


def test_two_state_level_never_pushes():
    assert policy_for(LEVEL_TWO_STATE).max_updates == 0
    http = FakeHttp([_token_response(), FakeResponse()])
    session = _session(http, policy=policy_for(LEVEL_TWO_STATE))

    asyncio.run(session.open("正在处理"))
    for length in (20, 60, 200):
        asyncio.run(session.push("x" * length))

    assert http.urls_ending("/v1.0/card/streaming") == []


def test_push_after_finalize_is_ignored():
    http = FakeHttp([_token_response(), FakeResponse(), FakeResponse()])
    session = _session(http)

    asyncio.run(session.open("a"))
    asyncio.run(session.finalize("done"))
    asyncio.run(session.push("迟到的增量"))

    assert len(http.urls_ending("/v1.0/card/streaming")) == 1


def test_push_failure_does_not_raise():
    """流式更新是旁路：失败只记日志，收尾那次会把完整内容补上。"""
    http = FakeHttp(
        [_token_response(), FakeResponse(), FakeResponse(500, {"success": False})]
    )
    session = _session(http, policy=ThrottlePolicy(0.0, 1, 5))

    asyncio.run(session.open("a"))
    asyncio.run(session.push("ab"))

    assert session.update_count == 0


def test_finalize_failure_raises_so_caller_can_fall_back():
    http = FakeHttp(
        [_token_response(), FakeResponse(), FakeResponse(500, {"success": False})]
    )
    session = _session(http)

    asyncio.run(session.open("a"))
    with pytest.raises(card_link.DingtalkCardError):
        asyncio.run(session.finalize("done"))
    assert session.finalized is False


def test_fail_marks_card_without_raising():
    http = FakeHttp(
        [_token_response(), FakeResponse(), FakeResponse(500, {"success": False})]
    )
    session = _session(http)

    asyncio.run(session.open("a"))
    asyncio.run(session.fail("处理失败"))

    assert session.finalized is True


# ---------------------------------------------------------------- 长度与档位


def test_long_reply_is_clamped_for_card():
    text = "x" * (MAX_CARD_CONTENT_CHARS + 500)

    display, truncated = clamp_card_content(text)

    assert truncated is True
    assert len(display) <= MAX_CARD_CONTENT_CHARS
    assert "完整结果见下方消息" in display


def test_card_limit_leaves_headroom_over_real_replies():
    """回归：上限曾被设成 1000，把 1248 字符的正常回复误判为超长。

    表现是卡片被截断 + 额外补发一条文本，用户侧看到两条重复消息。
    """
    realistic_reply = "x" * 1248

    assert clamp_card_content(realistic_reply) == (realistic_reply, False)


def test_intermediate_clamp_omits_notice():
    """执行中的推送被截断时不该出现「另发」提示 —— 那时还没决定补发。"""
    text = "x" * (MAX_CARD_CONTENT_CHARS + 500)

    display, truncated = clamp_card_content(text, with_notice=False)

    assert truncated is True
    assert len(display) == MAX_CARD_CONTENT_CHARS
    assert "另" not in display


def test_short_reply_is_untouched():
    assert clamp_card_content("短回复") == ("短回复", False)


def test_levels_are_ordered_by_call_volume():
    stream = policy_for(LEVEL_STREAM)
    staged = policy_for(LEVEL_STAGED)

    # 「不限次数」是最密的一档：只有它没有上限，其余档都有正数上限。
    assert stream.max_updates is None
    assert staged.max_updates is not None and staged.max_updates > 0
    assert stream.min_interval_seconds < staged.min_interval_seconds


def test_unlimited_policy_pushes_past_the_old_cap():
    """``max_updates=None`` 表示不限次数，上限完全交给间隔。

    这条守着「回复后半段不再静默」：此前 ``stream`` 档封顶 40 次，长回复在第 40
    次之后就不再推送，收尾那次 PUT 会把攒下的内容一次性甩上屏 —— 观感就是
    「打几个字 → 卡住 → 一大段突然蹦出来」。
    """
    policy = ThrottlePolicy(0.0, 1, None)
    http = FakeHttp([_token_response()])
    session = _session(http, policy=policy)

    asyncio.run(session.open("正在处理"))
    # 每次比上次长 1 个字符，确保满足 min_delta_chars。
    for index in range(60):
        asyncio.run(session.push("内" * (10 + index)))

    assert session.update_count == 60
    assert len(http.urls_ending("/v1.0/card/streaming")) == 60


def test_unknown_level_falls_back_to_default():
    assert policy_for("not-a-level") == policy_for(LEVEL_STAGED)


# ------------------------------------------------------------------ 档位解析


@pytest.fixture
def clean_level_env(monkeypatch):
    """清掉两个档位环境变量，让渠道默认值生效。"""
    monkeypatch.delenv(ENV_CARD_LEVEL, raising=False)
    monkeypatch.delenv(f"{ENV_CARD_LEVEL_PREFIX}FEISHU", raising=False)
    monkeypatch.delenv(f"{ENV_CARD_LEVEL_PREFIX}DINGTALK", raising=False)


def test_feishu_defaults_to_the_densest_level(clean_level_env):
    """飞书流式更新不计 QPS 配额，省调用没有收益，所以默认用最密档。

    钉钉仍留在 `staged` —— 它的入站额度是真要省的。
    """
    assert card_level("feishu") == LEVEL_STREAM
    assert card_level("dingtalk") == LEVEL_STAGED
    assert card_level() == LEVEL_STAGED


def test_channel_level_overrides_global(monkeypatch, clean_level_env):
    """渠道级覆盖优先于全局：同一份部署里两个渠道要能各自定密度。"""
    monkeypatch.setenv(ENV_CARD_LEVEL, LEVEL_STAGED)
    monkeypatch.setenv(f"{ENV_CARD_LEVEL_PREFIX}FEISHU", LEVEL_TWO_STATE)

    assert card_level("feishu") == LEVEL_TWO_STATE
    assert card_level("dingtalk") == LEVEL_STAGED


def test_global_level_still_wins_over_channel_default(monkeypatch, clean_level_env):
    monkeypatch.setenv(ENV_CARD_LEVEL, LEVEL_TWO_STATE)

    assert card_level("feishu") == LEVEL_TWO_STATE


def test_global_level_masking_a_channel_default_is_logged(monkeypatch, clean_level_env, caplog):
    """全局值压掉渠道默认时必须留痕。

    这是个真实踩过的坑：.env 里一行历史遗留的 `IM_CARD_LEVEL=staged` 让
    `CHANNEL_DEFAULT_LEVELS` 整段失效，而表面上一切正常 —— 卡片照发，只是
    观感没变，排查时完全看不出配置被谁覆盖了。
    """
    monkeypatch.setattr(
        "app.im.cards._MASKED_LEVEL_WARNED", set(), raising=False
    )
    monkeypatch.setenv(ENV_CARD_LEVEL, LEVEL_STAGED)

    with caplog.at_level("WARNING", logger="app.im.cards"):
        assert card_level("feishu") == LEVEL_STAGED

    assert any("覆盖了渠道默认" in record.message for record in caplog.records)


def test_no_warning_when_global_matches_the_channel_default(monkeypatch, clean_level_env, caplog):
    """全局值与渠道默认一致时不该刷告警 —— 那是正常配置。"""
    monkeypatch.setattr(
        "app.im.cards._MASKED_LEVEL_WARNED", set(), raising=False
    )
    monkeypatch.setenv(ENV_CARD_LEVEL, LEVEL_STREAM)

    with caplog.at_level("WARNING", logger="app.im.cards"):
        assert card_level("feishu") == LEVEL_STREAM

    assert not any("覆盖了渠道默认" in record.message for record in caplog.records)


def test_invalid_channel_level_is_ignored(monkeypatch, clean_level_env):
    monkeypatch.setenv(f"{ENV_CARD_LEVEL_PREFIX}FEISHU", "turbo")

    assert card_level("feishu") == LEVEL_STREAM


def test_card_channel_reads_provider_id():
    class Declared:
        PROVIDER_ID = "  Feishu "

    class Undeclared:
        pass

    assert card_channel(Declared()) == "feishu"
    assert card_channel(Undeclared()) == ""


def test_registry_provider_ids_match_their_keys():
    """`PROVIDER_ID` 是档位解析的锚点，必须与注册表的键一致。"""
    from app.im.providers import PROVIDERS

    for key, cls in PROVIDERS.items():
        assert cls.PROVIDER_ID == key
