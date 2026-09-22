"""飞书卡片会话：四步协议、sequence 递增、内容合并与表格降级。

这里覆盖的每一条都对应一个「错了就会让用户看到异常」的点：
- sequence 不严格递增 → 飞书直接拒绝（300317），卡片停在半路；
- 内容没变还发 → 白花一次接口调用；
- 上游给的是纯增量而我们当全量用 → 丢字；
- 表格超限不降级 → 整张卡片创建失败（OpenClaw 生产日志里的 230099/11310）；
- 收尾失败不抛 → 用户什么都收不到。
"""

import asyncio

import pytest

from app.im.cards import (
    LEVEL_STREAM,
    LEVEL_TWO_STATE,
    WORKING_TEXT,
    ThrottlePolicy,
    merge_streaming_text,
    policy_for,
)
from app.im.cards import feishu as card_link
from app.im.credentials import ChannelCredential

CARD_ID = "7355439197428236291"


def _credential() -> ChannelCredential:
    return ChannelCredential(
        channel_id="chan_1", app_id="app_1", tenant_key="corp_1", app_secret="secret"
    )


class FakeResponse:
    def __init__(self, status_code: int = 200, payload=None):
        self.status_code = status_code
        self._payload = {"code": 0} if payload is None else payload

    def json(self):
        return self._payload


class FakeHttp:
    """按顺序吐出预置响应，并记录每次请求（含 params）。"""

    def __init__(self, responses=None):
        self.requests: list[tuple[str, str, dict, dict]] = []
        self._responses = list(responses or [])

    async def post(self, url, json=None, headers=None, params=None):
        self.requests.append(("POST", url, json, params))
        return self._take()

    async def put(self, url, json=None, headers=None, params=None):
        self.requests.append(("PUT", url, json, params))
        return self._take()

    async def patch(self, url, json=None, headers=None, params=None):
        self.requests.append(("PATCH", url, json, params))
        return self._take()

    async def delete(self, url, headers=None):
        self.requests.append(("DELETE", url, {}, None))
        return self._take()

    def _take(self):
        return self._responses.pop(0) if self._responses else FakeResponse()

    def urls_containing(self, needle: str) -> list[tuple[str, str, dict, dict]]:
        return [item for item in self.requests if needle in item[1]]


def _token_response() -> FakeResponse:
    return FakeResponse(payload={"code": 0, "tenant_access_token": "tok", "expire": 7200})


def _created_response(card_id: str = CARD_ID) -> FakeResponse:
    return FakeResponse(payload={"code": 0, "data": {"card_id": card_id}})


def _sent_response() -> FakeResponse:
    return FakeResponse(payload={"code": 0, "data": {"message_id": "om_1"}})


@pytest.fixture(autouse=True)
def _clean_token_cache():
    card_link.reset_token_cache()
    yield
    card_link.reset_token_cache()


def _session(http, *, reply_to="om_user", policy=None, receive_id="oc_1"):
    return card_link.FeishuCardSession(
        http=http,
        credential=_credential(),
        receive_id=receive_id,
        receive_id_type="chat_id",
        reply_to=reply_to,
        policy=policy or policy_for(LEVEL_STREAM),
    )


# ------------------------------------------------------------------ 投放


def test_open_creates_streaming_card_and_replies_to_user_message():
    http = FakeHttp([_token_response(), _created_response(), _sent_response()])
    session = _session(http)

    asyncio.run(session.open("正在处理，请稍候…"))

    method, url, body, _ = http.requests[-1]
    assert method == "POST"
    # 回复用户那条消息，卡片落在原话题里。
    assert url.endswith("/im/v1/messages/om_user/reply")
    assert body["msg_type"] == "interactive"
    assert CARD_ID in body["content"]
    assert session.opened is True
    # 卡片会话的对外标识就是 card_id，供落库排障。
    assert session.out_track_id == CARD_ID


def test_open_embeds_card_json_with_streaming_mode_and_initial_text():
    http = FakeHttp([_token_response(), _created_response(), _sent_response()])
    session = _session(http)

    asyncio.run(session.open("正在处理"))

    _, url, body, _ = http.requests[1]
    assert url.endswith("/cardkit/v1/cards")
    assert body["type"] == "card_json"
    import json

    card = json.loads(body["data"])
    # streaming_mode 必须开，否则后续流式更新直接 300309 报错。
    assert card["config"]["streaming_mode"] is True
    # 打字机密度是卡片配置项，不是代码参数。两个字段**必须成对出现** ——
    # 真机实测只给一个会报 11311（printFrequencyMs or printStep is nil）。
    streaming = card["config"]["streaming_config"]
    assert streaming["print_step"] == {"default": card_link.PRINT_STEP}
    assert streaming["print_frequency_ms"] == {"default": card_link.PRINT_FREQUENCY_MS}
    # 显式写 fast：客户端各版本默认值可能不同，官方也建议前置指定。
    assert streaming["print_strategy"] == "fast"
    assert card["body"]["elements"][0]["element_id"] == "content"
    assert card["body"]["elements"][0]["content"] == "正在处理"


def test_default_print_rate_keeps_up_with_the_model():
    """上屏速率必须 ≥ 模型产出速率，否则每次推送都要"追赶"上屏积压。

    真机实测（data/db/traces.db 的 llm 事件）本项目模型约 130~300 字/秒：
    425 字 / 2.07s、790 字 / 3.01s。上屏慢于它时，收尾关流式那一刻会把没打完
    的部分整块落地 —— 观感就是「打几个字 → 一大段蹦出来」。
    """
    rate = card_link.print_rate_chars_per_second()

    assert rate >= 300.0, f"默认上屏速率 {rate} 字/秒追不上模型产出"


def test_print_rate_can_be_raised_to_match_a_faster_model(monkeypatch):
    """上屏速率 = print_step / print_frequency_ms；这个旋钮要真的接上。"""
    monkeypatch.setenv("IM_FEISHU_PRINT_FREQUENCY_MS", "20")
    monkeypatch.setenv("IM_FEISHU_PRINT_STEP", "12")

    assert card_link.print_rate_chars_per_second() == 600.0


def test_print_rate_env_falls_back_on_bad_values(monkeypatch):
    for bad in ("", "fast", "0", "-2"):
        monkeypatch.setenv("IM_FEISHU_PRINT_STEP", bad)
        assert card_link.print_config()[1] == card_link.PRINT_STEP
    monkeypatch.delenv("IM_FEISHU_PRINT_STEP")

    monkeypatch.setenv("IM_FEISHU_PRINT_FREQUENCY_MS", "abc")
    assert card_link.print_config()[0] == card_link.PRINT_FREQUENCY_MS


def test_finalize_waits_for_the_typewriter_before_closing(monkeypatch):
    """收尾是「写全量 → 立刻关流式」，而关流式会终止打字机。

    所以要先留出时间让本次新增的字符打完，否则它们会在关流式那一刻整块落地
    —— 这正是「最后一大段突然蹦出来」的来源。
    """
    slept: list[float] = []
    marks: list[int] = []

    async def fake_sleep(seconds):
        slept.append(seconds)
        marks.append(len(http.requests))

    monkeypatch.setattr(card_link.asyncio, "sleep", fake_sleep)
    http = FakeHttp([_token_response(), _created_response(), _sent_response()])
    session = _session(http)
    asyncio.run(session.open(WORKING_TEXT))
    asyncio.run(session.push("一" * 400))  # 先有一次中间推送，之后写入属"续打"
    slept.clear()
    marks.clear()

    asyncio.run(session.finalize("一" * 800))  # 新增 400 字

    expected = 400 / card_link.print_rate_chars_per_second()
    assert slept == [pytest.approx(expected)]
    # 顺序必须是「先写内容、再等、最后关流式」；反了就白等。
    assert marks[0] == len(http.requests) - 1
    assert http.requests[-1][0] == "PATCH"
    assert http.requests[-1][1].endswith("/settings")


def test_finalize_skips_catchup_cap_for_huge_pending(monkeypatch):
    """等待是观感优化，不能拖着回复不交付 —— 必须封顶。"""
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(card_link.asyncio, "sleep", fake_sleep)
    http = FakeHttp(
        [_token_response(), _created_response(), _sent_response()]
        + [FakeResponse() for _ in range(4)]
    )
    session = _session(http)
    asyncio.run(session.open(WORKING_TEXT))
    asyncio.run(session.push("一" * 10))
    slept.clear()

    asyncio.run(session.finalize("一" * 60_000))

    assert slept == [card_link.CATCHUP_MAX_SECONDS]


def test_finalize_does_not_wait_when_nothing_was_pushed_yet(monkeypatch):
    """首次写入与初始文案没有前缀关系，属协议规定的全屏直出。

    那种情况下没有"未上屏"的概念，等待纯属白等。
    """
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(card_link.asyncio, "sleep", fake_sleep)
    http = FakeHttp([_token_response(), _created_response(), _sent_response()])
    session = _session(http)
    asyncio.run(session.open(WORKING_TEXT))

    assert session.update_count == 0
    asyncio.run(session.finalize("直接给出的答案"))

    assert slept == []


def test_open_without_reply_target_creates_message_in_chat():
    http = FakeHttp([_token_response(), _created_response(), _sent_response()])
    session = _session(http, reply_to=None)

    asyncio.run(session.open("hi"))

    method, url, body, params = http.requests[-1]
    assert url.endswith("/im/v1/messages")
    assert params == {"receive_id_type": "chat_id"}
    assert body["receive_id"] == "oc_1"


def test_open_failure_raises_so_caller_can_fall_back():
    http = FakeHttp([_token_response(), FakeResponse(403, {"code": 99991672})])
    session = _session(http)

    with pytest.raises(card_link.FeishuCardError) as excinfo:
        asyncio.run(session.open("hi"))

    assert excinfo.value.code == 99991672
    assert session.opened is False


def test_send_failure_raises_even_though_card_entity_exists():
    http = FakeHttp([_token_response(), _created_response(), FakeResponse(400, {"code": 230002})])
    session = _session(http)

    with pytest.raises(card_link.FeishuCardError):
        asyncio.run(session.open("hi"))


# ------------------------------------------------------------------ 流式与 sequence


def test_sequence_increases_strictly_across_updates_and_close():
    http = FakeHttp([_token_response(), _created_response(), _sent_response()])
    session = _session(http, policy=ThrottlePolicy(0.0, 0, 10))
    asyncio.run(session.open("起"))

    asyncio.run(session.push("起步"))
    asyncio.run(session.push("起步走"))
    asyncio.run(session.finalize("起步走了"))

    contents = [item[2]["sequence"] for item in http.urls_containing("/elements/content/content")]
    closes = [item[2]["sequence"] for item in http.urls_containing("/settings")]
    # 建卡占第 1 个序号；内容更新与收尾**共享同一个自增序列**（钉钉那边是各自独立的
    # guid，这里不行 —— 飞书要求同卡片操作严格递增，跳号或重复都会被拒）。
    assert contents == [2, 3, 4]
    assert closes == [5]
    assert sorted(contents + closes) == [2, 3, 4, 5]


def test_uuid_is_derived_from_card_and_sequence():
    http = FakeHttp([_token_response(), _created_response(), _sent_response()])
    session = _session(http, policy=ThrottlePolicy(0.0, 0, 10))
    asyncio.run(session.open("起"))
    asyncio.run(session.push("起步"))

    update = http.urls_containing("/elements/content/content")[-1]
    assert update[2]["uuid"] == f"s_{CARD_ID}_2"


def test_push_skips_when_content_did_not_change():
    http = FakeHttp([_token_response(), _created_response(), _sent_response()])
    session = _session(http, policy=ThrottlePolicy(0.0, 0, 10))
    asyncio.run(session.open("同"))
    before = len(http.requests)

    asyncio.run(session.push("同"))

    assert len(http.requests) == before
    assert session.update_count == 0


def test_push_respects_throttle_policy():
    http = FakeHttp([_token_response(), _created_response(), _sent_response()])
    # 最小间隔很长 → 第二次推送必然被挡下。
    session = _session(http, policy=ThrottlePolicy(999.0, 0, 10))
    asyncio.run(session.open("起"))

    asyncio.run(session.push("起步"))
    asyncio.run(session.push("起步走"))

    assert session.update_count == 1


def test_two_state_policy_never_pushes():
    http = FakeHttp([_token_response(), _created_response(), _sent_response()])
    session = _session(http, policy=policy_for(LEVEL_TWO_STATE))
    asyncio.run(session.open("起"))

    asyncio.run(session.push("起步"))

    assert session.update_count == 0


def test_push_failure_does_not_raise():
    """流式更新是旁路：失败只记日志，收尾那次会把完整内容补上。"""
    http = FakeHttp([_token_response(), _created_response(), _sent_response(),
                     FakeResponse(500, {"code": 200120})])
    session = _session(http, policy=ThrottlePolicy(0.0, 0, 10))
    asyncio.run(session.open("起"))

    asyncio.run(session.push("起步"))

    assert session.update_count == 0


def test_push_after_finalize_is_ignored():
    http = FakeHttp([_token_response(), _created_response(), _sent_response()])
    session = _session(http, policy=ThrottlePolicy(0.0, 0, 10))
    asyncio.run(session.open("起"))
    asyncio.run(session.finalize("完成"))
    before = len(http.requests)

    asyncio.run(session.push("完成以后"))

    assert len(http.requests) == before


# ------------------------------------------------------------------ 收尾与失败态


def test_finalize_writes_content_and_closes_streaming():
    http = FakeHttp([_token_response(), _created_response(), _sent_response()])
    session = _session(http, policy=ThrottlePolicy(0.0, 0, 10))
    asyncio.run(session.open("起"))

    truncated = asyncio.run(session.finalize("最终答案"))

    # 飞书不截断：元素 content 上限 100000 字符，实测 15000 字符／88KB 卡 JSON 均通过。
    assert truncated is False
    close = http.urls_containing("/settings")[-1]
    import json

    settings = json.loads(close[2]["settings"])
    assert settings["config"]["streaming_mode"] is False
    # 会话列表预览要换成正文摘要，否则聊天列表里会一直挂着「生成中」。
    assert settings["config"]["summary"]["content"] == "最终答案"
    assert session.finalized is True


def test_initial_working_text_never_leaks_into_final_content():
    """初始文案「正在处理…」与答案没有前缀关系，绝不能被合并进正文。

    这是合并逻辑最容易踩的坑：把初始文案当合并基线，兜底分支就会把它和答案
    拼成「正在处理，请稍候…答案」。
    """
    http = FakeHttp([_token_response(), _created_response(), _sent_response()])
    session = _session(http)
    asyncio.run(session.open(WORKING_TEXT))

    asyncio.run(session.finalize("这是答案"))

    content = http.urls_containing("/elements/content/content")[-1][2]["content"]
    assert content == "这是答案"


def test_finalize_failure_raises_so_caller_can_deliver_by_text():
    http = FakeHttp([_token_response(), _created_response(), _sent_response(),
                     FakeResponse(400, {"code": 200860})])
    session = _session(http)
    asyncio.run(session.open("起"))

    with pytest.raises(card_link.FeishuCardError):
        asyncio.run(session.finalize("结果"))

    assert session.finalized is False


def test_finalize_skips_redundant_content_write_when_unchanged():
    http = FakeHttp([_token_response(), _created_response(), _sent_response()])
    session = _session(http, policy=ThrottlePolicy(0.0, 0, 10))
    asyncio.run(session.open("起"))
    asyncio.run(session.push("最终答案"))

    asyncio.run(session.finalize("最终答案"))

    # 内容已经在卡片上了，收尾只需要关流式，不必再写一遍。
    assert len(http.urls_containing("/elements/content/content")) == 1
    assert len(http.urls_containing("/settings")) == 1


def test_fail_closes_streaming_even_when_content_write_fails():
    """卡片绝不能停在「生成中」—— 这比显示一句失败文案更让人困惑。"""
    http = FakeHttp([_token_response(), _created_response(), _sent_response(),
                     FakeResponse(500, {"code": 200120})])
    session = _session(http)
    asyncio.run(session.open("起"))

    asyncio.run(session.fail("处理失败"))

    assert len(http.urls_containing("/settings")) == 1
    assert session.finalized is True


def test_finalize_before_open_raises():
    session = _session(FakeHttp())

    with pytest.raises(card_link.FeishuCardError):
        asyncio.run(session.finalize("结果"))


# ------------------------------------------------------------------ 内容合并


@pytest.mark.parametrize(
    "previous,current,expected",
    [
        # 上游给累积全文（我们的实际情况）：直接采用。
        ("你好", "你好呀", "你好呀"),
        # 上游给纯增量：必须拼上去，不能当作全量覆盖。
        ("你好", "呀", "你好呀"),
        # 重复投递同一份内容。
        ("你好", "你好", "你好"),
        # 尾首重叠去重。
        ("这是", "这是一个", "这是一个"),
        ("前文内容", "内容结束", "前文内容结束"),
        # 空值兜底。
        ("已有", "", "已有"),
        ("", "新内容", "新内容"),
    ],
)
def test_merge_streaming_text(previous, current, expected):
    assert merge_streaming_text(previous, current) == expected


def test_merge_streaming_text_matches_prefix_then_never_loses_text():
    """前缀关系被破坏时也不能丢字 —— 宁可多几个字。"""
    merged = merge_streaming_text("ABC", "XYZ")
    assert "ABC" in merged and "XYZ" in merged


# ------------------------------------------------------------------ 表格降级


def _table(n: int) -> str:
    return f"| 表{n}A | 表{n}B |\n|---|---|\n| a{n} | b{n} |"


def test_tables_within_limit_are_left_alone():
    text = "\n\n".join(_table(i + 1) for i in range(3))

    assert card_link.sanitize_markdown_for_card(text) == text


def test_tables_beyond_limit_are_wrapped_in_code_block():
    text = "\n\n".join(_table(i + 1) for i in range(5))

    result = card_link.sanitize_markdown_for_card(text)

    # 前 3 张仍是真表格（可正常渲染），后 2 张退化为代码块。
    assert result.count("```") == 4
    assert _table(3) in result
    assert f"```\n{_table(4)}\n```" in result
    assert f"```\n{_table(5)}\n```" in result


def test_tables_inside_code_blocks_do_not_count():
    """代码块里的示例表格不会被解析成卡片表格，所以不该消耗额度。"""
    text = "\n\n".join(f"```\n{_table(i + 1)}\n```" for i in range(5))

    assert card_link.find_markdown_tables_outside_code_blocks(text) == []
    assert card_link.sanitize_markdown_for_card(text) == text


def test_summary_is_single_line_and_truncated():
    assert card_link.truncate_summary("第一行\n第二行") == "第一行 第二行"
    long_text = "字" * 80
    summary = card_link.truncate_summary(long_text)
    assert len(summary) == card_link.SUMMARY_MAX_CHARS
    assert summary.endswith("...")
