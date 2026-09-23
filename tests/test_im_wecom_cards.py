"""企微流式会话（``cards/wecom.py``）的单元测试。

覆盖纯逻辑：**字节**截断的边界（UTF-8 多字节序列不能被劈开）、开流幂等、
节流档位、同 id 全量替换的帧形状、收尾与失败态。

真机投递、企微 Markdown 与飞书的差异留在现场验证。
"""

import asyncio

import pytest

from app.im.cards import TRUNCATED_SUFFIX, WORKING_TEXT, ThrottlePolicy
from app.im.cards.wecom import (
    WECOM_MAX_STREAM_BYTES,
    WecomCardError,
    WecomCardSession,
    clamp_stream_bytes,
)


class _Recorder:
    """记录会话发出的每一帧 ``(req_id, body)``。"""

    def __init__(self):
        self.frames: list[tuple[str, dict]] = []

    async def __call__(self, req_id, body):
        self.frames.append((req_id, body))
        return {"errcode": 0}

    def bodies(self) -> list[dict]:
        return [body for _, body in self.frames]


def _policy(**overrides) -> ThrottlePolicy:
    values = {"min_interval_seconds": 0.0, "min_delta_chars": 0, "max_updates": None}
    values.update(overrides)
    return ThrottlePolicy(**values)


def _session(recorder, **overrides) -> WecomCardSession:
    values = {
        "send_reply": recorder,
        "req_id": "req_1",
        "chat_id": "user_1",
        "chat_type": "p2p",
        "policy": _policy(),
        "stream_id": "stream_fixed",
    }
    values.update(overrides)
    return WecomCardSession(**values)


# ------------------------------------------------------------ 字节截断


def test_short_text_is_not_truncated():
    text, truncated = clamp_stream_bytes("你好，世界")
    assert (text, truncated) == ("你好，世界", False)


def test_text_exactly_at_the_limit_is_not_truncated():
    text = "好" * (WECOM_MAX_STREAM_BYTES // 3)  # 20478 字节，仍在限内
    clamped, truncated = clamp_stream_bytes(text)
    assert truncated is False
    assert clamped == text


def test_long_text_is_truncated_by_bytes():
    clamped, truncated = clamp_stream_bytes("好" * 8000)  # 24000 字节

    assert truncated is True
    assert clamped.endswith(TRUNCATED_SUFFIX)
    assert len(clamped.encode("utf-8")) <= WECOM_MAX_STREAM_BYTES


def test_truncation_never_splits_a_multibyte_character():
    """20480 不是 3 的倍数，按字节硬切会留下半个汉字。

    半个汉字的字节序列是**非法 UTF-8**：轻则被服务端拒帧，重则让客户端把一个
    残码点渲染成"�"。所以截断必须落在码点边界上。
    """
    clamped, _ = clamp_stream_bytes("好" * 8000)
    head = clamped[: -len(TRUNCATED_SUFFIX)] if clamped.endswith(TRUNCATED_SUFFIX) else clamped

    assert set(head) == {"好"}
    head.encode("utf-8").decode("utf-8")  # 合法 UTF-8，不会抛异常


def test_truncation_without_notice_omits_the_suffix():
    clamped, truncated = clamp_stream_bytes("好" * 8000, with_notice=False)

    assert truncated is True
    assert TRUNCATED_SUFFIX not in clamped
    assert len(clamped.encode("utf-8")) <= WECOM_MAX_STREAM_BYTES


# ------------------------------------------------------------ 开流


def test_open_emits_an_unfinished_stream_frame():
    async def scenario():
        recorder = _Recorder()
        session = _session(recorder)
        await session.open("正在处理，请稍候…")
        return recorder.frames, session

    frames, session = asyncio.run(scenario())
    assert frames[0][0] == "req_1"
    assert frames[0][1] == {
        "msgtype": "stream",
        "stream": {
            "id": "stream_fixed",
            "finish": False,
            "content": "正在处理，请稍候…",
        },
    }
    assert session.opened is True
    assert session.update_count == 0


def test_open_after_prestart_is_a_no_op():
    async def scenario():
        recorder = _Recorder()
        session = _session(recorder)
        await session.prestart("正在处理，请稍候…")
        await session.open("正在处理，请稍候…")
        return recorder.frames

    # Provider 抢窗口时已经开过流了；再开一次会让用户看到两条气泡。
    assert len(asyncio.run(scenario())) == 1


def test_push_before_open_does_nothing():
    async def scenario():
        recorder = _Recorder()
        session = _session(recorder)
        await session.push("内容")
        return recorder.frames

    assert asyncio.run(scenario()) == []


def test_generated_stream_id_is_prefixed():
    session = WecomCardSession(
        send_reply=_Recorder(),
        req_id="r",
        chat_id="c",
        chat_type="p2p",
        policy=_policy(),
    )
    # 与官方 SDK 的 generateReqId('stream') 同格式，便于和服务端日志对账。
    assert session.out_track_id.startswith("stream_")


# ------------------------------------------------------------ 推送与节流


def test_push_keeps_the_same_stream_id_and_sends_full_content():
    async def scenario():
        recorder = _Recorder()
        session = _session(recorder)
        await session.open("处理中")
        # 上游 on_delta 给的就是**累积全文**（企微的 content 语义也是全量替换），
        # 所以 merge_streaming_text 在这里退化为直接返回 current。
        await session.push("处理中第一段")
        await session.push("处理中第一段第二段")
        return recorder.bodies(), session

    bodies, session = asyncio.run(scenario())
    assert [body["stream"]["id"] for body in bodies] == ["stream_fixed"] * 3
    assert [body["stream"]["finish"] for body in bodies] == [False, False, False]
    # content 是**全量**而非增量：客户端据此整段替换该气泡。
    assert [body["stream"]["content"] for body in bodies] == [
        "处理中",
        "处理中第一段",
        "处理中第一段第二段",
    ]
    assert session.update_count == 2


def test_push_merges_incremental_upstream():
    async def scenario():
        recorder = _Recorder()
        session = _session(recorder)
        await session.open("")
        await session.push("第一段")
        await session.push("第二段")  # 假装上游给的是纯增量
        return recorder.bodies()[-1]["stream"]["content"]

    # 宁多几个字，也不要因为合并失败丢掉已经吐出来的内容。
    assert asyncio.run(scenario()) == "第一段第二段"


def test_two_state_policy_skips_intermediate_updates():
    async def scenario():
        recorder = _Recorder()
        session = _session(recorder, policy=_policy(max_updates=0))
        await session.open("处理中")
        await session.push("中间内容")
        await session.finalize("最终结果")
        return recorder.bodies(), session

    bodies, session = asyncio.run(scenario())
    # 只有开流与收尾两帧；占位文案要一直挂到收尾才被替换 —— 这是"总共两次调用"
    # 这个档位的既定代价，不是缺陷（想要"开始回复就换掉占位"用 staged / stream）。
    assert [body["stream"]["content"] for body in bodies] == ["处理中", "最终结果"]
    assert session.update_count == 0


def test_min_interval_throttles_pushes():
    async def scenario():
        recorder = _Recorder()
        session = _session(recorder, policy=_policy(min_interval_seconds=60.0))
        await session.open("处理中")
        await session.push("第一段")
        await session.push("第一段第二段")
        return recorder.bodies(), session

    bodies, session = asyncio.run(scenario())
    # 两帧 = 开流 + 首帧正文。首帧是把占位文案换掉的状态切换，不受间隔约束
    # （见 test_first_content_frame_ignores_the_throttle）；从第二帧起才被节流。
    assert len(bodies) == 2
    assert session.update_count == 1


def test_max_updates_caps_the_push_count():
    async def scenario():
        recorder = _Recorder()
        session = _session(recorder, policy=_policy(max_updates=2))
        # 从空串起步，让每次推送都真的"更长"——`min_delta_chars` 会把变短的内容
        # 挡在门外（钉钉同款判定），那是另一个测试的事。
        await session.open("")
        for index in range(5):
            await session.push("x" * (index + 1))
        return session

    assert asyncio.run(scenario()).update_count == 2


def test_intermediate_push_omits_the_truncation_notice():
    async def scenario():
        recorder = _Recorder()
        session = _session(recorder)
        await session.open("处理中")
        await session.push("好" * 8000)
        return recorder.bodies()[-1]["stream"]["content"]

    # 执行中还没有"补发"这回事，提前显示提示会让人以为已经被截断了。
    assert TRUNCATED_SUFFIX not in asyncio.run(scenario())


# ------------------------------------------------------------ 占位文案

# 真机反馈（2026-09-23）：气泡里的「正在处理，请稍候…」要等到回答写完才消失。
# 根因是 `stream.content` 的全量替换语义撞上了写错的合并基线 —— 占位文案被当成
# 正文的上一版，首帧于是推成「正在处理，请稍候…正文」，只有 `finalize` 的纯正文
# 覆盖才能把它抹掉。下面两个用例把「占位文案不进基线」与「首帧不受节流」钉住。


def test_placeholder_text_is_not_merged_into_the_reply():
    """占位文案只落在气泡上，不能被拼进正文。

    走的是真机的调用序列：Provider 抢窗口 ``prestart`` → Worker 拿到同一会话再
    ``open``（幂等空操作）→ 逐段 ``push`` → ``finalize``。
    """

    async def scenario():
        recorder = _Recorder()
        session = _session(recorder)
        await session.prestart(WORKING_TEXT)  # Provider 抢 5 秒窗口
        await session.open(WORKING_TEXT)  # Worker 的统一流程，应为空操作
        await session.push("你好")
        await session.push("你好，有什么可以帮你？")
        await session.finalize("你好，有什么可以帮你？")
        return [body["stream"]["content"] for body in recorder.bodies()], session

    contents, session = asyncio.run(scenario())
    assert contents == [
        WORKING_TEXT,
        "你好",
        "你好，有什么可以帮你？",
        "你好，有什么可以帮你？",
    ]
    # 除开流那一帧，后面每一帧都不该再出现占位文案。
    assert all(WORKING_TEXT not in text for text in contents[1:])
    # 开流那次不算更新（update_count 只数中间推送）。
    assert session.update_count == 2


def test_first_content_frame_ignores_the_throttle():
    """首帧真实内容是状态切换，间隔与最小增量都不该拦它。

    旧逻辑把这一帧也按增量算：占位文案在基线里占掉 10 个字符，比
    ``min_delta_chars`` 还短的回复就**永远**攒不出这一帧 —— 占位文案只能拖到收尾。
    """

    async def scenario():
        recorder = _Recorder()
        session = _session(
            recorder,
            policy=_policy(min_interval_seconds=60.0, min_delta_chars=32, max_updates=6),
        )
        await session.prestart(WORKING_TEXT)
        await session.push("好的")  # 2 个字符，远小于 min_delta；间隔也还没到
        await session.push("好的，已经帮你处理完了")  # 第二帧起才受节流约束
        return [body["stream"]["content"] for body in recorder.bodies()], session

    contents, session = asyncio.run(scenario())
    assert contents == [WORKING_TEXT, "好的"]
    assert session.update_count == 1


# ------------------------------------------------------------ 收尾与失败


def test_finalize_locks_the_bubble():
    async def scenario():
        recorder = _Recorder()
        session = _session(recorder)
        await session.open("处理中")
        truncated = await session.finalize("最终结果")
        return recorder.bodies()[-1], session, truncated

    body, session, truncated = asyncio.run(scenario())
    assert body["stream"]["finish"] is True
    assert body["stream"]["content"] == "最终结果"
    assert session.finalized is True
    assert truncated is False


def test_finalize_reports_truncation_so_the_worker_can_resend():
    async def scenario():
        recorder = _Recorder()
        session = _session(recorder)
        await session.open("处理中")
        truncated = await session.finalize("好" * 8000)
        return recorder.bodies()[-1], truncated

    body, truncated = asyncio.run(scenario())
    # 返回值驱动 Worker 补发完整内容（企微侧改走主动推送），必须如实反映被裁。
    assert truncated is True
    assert len(body["stream"]["content"].encode("utf-8")) <= WECOM_MAX_STREAM_BYTES


def test_finalize_before_open_raises():
    async def scenario():
        session = _session(_Recorder())
        await session.finalize("结果")

    with pytest.raises(WecomCardError):
        asyncio.run(scenario())


def test_fail_closes_the_bubble():
    async def scenario():
        recorder = _Recorder()
        session = _session(recorder)
        await session.open("处理中")
        await session.fail("处理失败，请稍后重试。")
        return recorder.bodies()[-1], session

    body, session = asyncio.run(scenario())
    assert body["stream"]["finish"] is True
    assert body["stream"]["content"] == "处理失败，请稍后重试。"
    assert session.finalized is True


def test_fail_swallows_transport_errors():
    class _BrokenAfterOpen:
        def __init__(self):
            self.calls = 0

        async def __call__(self, req_id, body):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("link down")
            return {"errcode": 0}

    async def scenario():
        session = _session(_BrokenAfterOpen())
        await session.open("处理中")
        await session.fail("失败")  # 不应抛出：失败态更新失败也不能再打断调用方
        return session

    assert asyncio.run(scenario()).finalized is True


def test_push_errors_do_not_break_execution():
    class _Broken:
        async def __call__(self, req_id, body):
            raise RuntimeError("link down")

    async def scenario():
        session = _session(_Broken())
        await session.push("内容")  # 未开流 + 发送必失败，两者都不该抛出
        return session

    assert asyncio.run(scenario()).update_count == 0
