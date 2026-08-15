"""自动上下文压缩能力验证（deepagents 0.7.5 内置 SummarizationMiddleware）。

项目 `compiler.compile_agent` 调 `create_deep_agent` 时不传 `middleware=`，
deepagents 的 graph 构建（graph.py:841-846）会把
`create_summarization_middleware(model, backend)` **无条件**注入每个员工主栈。
本测试锁定该压缩链路的触发 / 折叠 / 落盘行为，防止升级框架或更换编排时
静默丢失「超长对话自动摘要」能力（对应能力入口见 compiler.py:397）。
"""
import asyncio

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend, StateBackend
from deepagents.middleware.summarization import create_summarization_middleware


class FakeModel(BaseChatModel):
    """最小可编译模型：不联网，ainvoke 固定返回摘要文本。"""

    profile: dict | None = None

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="FAKE_SUMMARY"))])

    async def ainvoke(self, input, **kwargs):
        return AIMessage(content="FAKE_SUMMARY")


def _human(text: str) -> HumanMessage:
    return HumanMessage(content=text)


def _mk(profile=None):
    """构造 (model, 与项目同源的 SummarizationMiddleware 实例)。"""
    model = FakeModel(profile=profile)
    return model, create_summarization_middleware(model, StateBackend())


def _tool_msg(args: dict) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "write_file", "args": args, "id": "call_1", "type": "tool_call"}],
    )


# --- 触发阈值 --------------------------------------------------------------


def test_default_token_trigger_fires_above_threshold():
    """无 profile 的模型 → 默认 17 万 token 阈值，超过才压缩。"""
    _, mw = _mk()
    assert mw._should_summarize([_human("你好")], 169_999) is False
    assert mw._should_summarize([_human("你好")], 170_000) is True
    # 保留最近 6 条
    assert mw._lc_helper.keep == ("messages", 6)


def test_fraction_trigger_uses_model_profile():
    """有 max_input_tokens profile 的模型 → 按上下文比例（85%）触发。"""
    _, mw = _mk(profile={"max_input_tokens": 10_000})
    assert mw._should_summarize([_human("hi")], 8_499) is False
    assert mw._should_summarize([_human("hi")], 8_500) is True
    assert mw._lc_helper.keep == ("fraction", 0.10)


# --- 工具参数瘦身（truncate_args，低于全量压缩的第二档） --------------------


def test_truncate_args_clips_old_tool_args_only():
    """消息 ≥20 条先触发工具参数截断：旧消息大参数缩短，最近 20 条不动。"""
    _, mw = _mk()
    big = {"content": "x" * 5000}
    msgs = [_tool_msg(big) for _ in range(25)]
    total = mw.token_counter(msgs)
    assert mw._should_truncate_args(msgs, total) is True
    truncated, modified = mw._truncate_args(msgs, total)
    assert modified is True
    # 前 5 条（早于保留窗口）被截断
    assert truncated[0].tool_calls[0]["args"]["content"].startswith("x" * 20 + "...")
    assert len(truncated[0].tool_calls[0]["args"]["content"]) < 100
    # 最后 20 条保持原样
    assert truncated[-1].tool_calls[0]["args"]["content"] == "x" * 5000


# --- 摘要生成 + 历史落盘 ----------------------------------------------------


def test_summary_generation_and_offload(tmp_path):
    """触发后：旧消息被摘要替换，完整历史 offload 到 backend 可随时读回。"""
    backend = FilesystemBackend(root_dir=str(tmp_path))
    _, mw = _mk()
    msgs = [_human(f"问题{i}：" + "，".join(["生产订单进度"] * 60)) for i in range(10)]
    to_summarize, to_keep = mw._partition_messages(msgs, 8)
    assert len(to_summarize) == 8 and len(to_keep) == 2

    summary = asyncio.run(mw._acreate_summary(to_summarize))
    assert summary == "FAKE_SUMMARY"

    path = mw._offload_to_backend(backend, to_summarize)
    assert path and path.startswith("/conversation_history/") and path.endswith(".md")
    resp = backend.download_files([path])
    assert resp[0].content is not None
    assert "问题0" in resp[0].content.decode("utf-8")

    summary_msgs = mw._build_new_messages_with_path(summary, path)
    assert summary_msgs[0].additional_kwargs.get("lc_source") == "summarization"


def test_effective_messages_collapse_to_summary_plus_tail():
    """折叠后模型看到的有效消息 = 摘要 + 保留窗口（原始 log 不丢）。"""
    _, mw = _mk()
    msgs = [_human(f"m{i}") for i in range(10)]
    summary_msg = HumanMessage(content="摘要", additional_kwargs={"lc_source": "summarization"})
    event = {"cutoff_index": 7, "summary_message": summary_msg, "file_path": None}
    eff = mw._apply_event_to_messages(msgs, event)
    assert eff[0] is summary_msg
    assert [m.content for m in eff[1:]] == [f"m{i}" for i in range(7, 10)]


def test_previous_summary_not_reoffloaded():
    """链式压缩不会把上一次的摘要消息再次落盘（避免冗余）。"""
    _, mw = _mk()
    msgs = [
        _human("a"),
        HumanMessage(content="旧摘要", additional_kwargs={"lc_source": "summarization"}),
        _human("b"),
    ]
    out = mw._filter_summary_messages(msgs)
    assert len(out) == 2
    assert "旧摘要" not in [m.content for m in out]


# --- 与项目集成：create_deep_agent 无条件注入 -------------------------------


def test_create_deep_agent_injects_summarization_middleware(monkeypatch):
    """项目 compile_agent 走的 create_deep_agent 会自动装配摘要中间件。

    直接 spy deepagents.graph 的装配函数，验证主 agent 栈确实拿到
    一个配置好的 SummarizationMiddleware（含模型感知的默认阈值）。
    """
    import deepagents.graph as dg

    calls = []
    real = dg.create_summarization_middleware

    def spy(model, backend, **kwargs):
        inst = real(model, backend, **kwargs)
        calls.append(inst)
        return inst

    monkeypatch.setattr(dg, "create_summarization_middleware", spy)
    agent = create_deep_agent(model=FakeModel(), backend=StateBackend())
    assert agent is not None
    # 主 agent（及内联子代理）都自动装配该中间件，且阈值按无 profile 模型默认
    assert len(calls) >= 1
    assert any(m._should_summarize([_human("hi")], 170_000) for m in calls)
    assert any(m._lc_helper.keep == ("messages", 6) for m in calls)
