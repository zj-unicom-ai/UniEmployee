"""Point2 退款内化审批测试。

验证 refund StateGraph 的批准/拒绝/校验失败路径、resume_refund 辅助函数、
以及 _extract_interrupt 对新格式 payload（含 inner_thread）的识别。

这些测试用 MemorySaver 离线跑图，不依赖 8787 服务或真实 LLM。
"""
import asyncio

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.workflows.refund import get_refund_graph, resume_refund


def test_refund_graph_approve_path():
    """批准路径：校验 → 计算金额 → 挂起审批 → 恢复批准 → 执行退款。"""
    graph = get_refund_graph(MemorySaver())
    tid = "test-refund-approve"
    cfg = {"configurable": {"thread_id": tid}}
    # 首次调用：应在 await_approval 挂起
    graph.invoke({"order_id": "O12345", "reason": "质量问题", "inner_thread": tid}, config=cfg)
    st = graph.get_state(cfg)
    assert "await_approval" in st.next, f"应在审批节点挂起，实际 next={st.next}"
    # 恢复：批准
    graph.invoke(Command(resume={"approved": True}), config=cfg)
    st = graph.get_state(cfg)
    assert not st.next, "批准后应跑完"
    summary = st.values.get("summary", "")
    assert "退款单号" in summary, f"summary 应含退款单号: {summary}"


def test_refund_graph_reject_path():
    """拒绝路径：校验 → 计算金额 → 挂起审批 → 拒绝 → 终止。"""
    graph = get_refund_graph(MemorySaver())
    tid = "test-refund-reject"
    cfg = {"configurable": {"thread_id": tid}}
    graph.invoke({"order_id": "O12345", "reason": "质量问题", "inner_thread": tid}, config=cfg)
    graph.invoke(Command(resume={"approved": False}), config=cfg)
    st = graph.get_state(cfg)
    assert not st.next, "拒绝后应终止"
    summary = st.values.get("summary", "")
    assert "拒绝" in summary, f"拒绝路径 summary 应含'拒绝': {summary}"


def test_refund_graph_validation_fail():
    """校验失败：订单不存在 → 直接终止，不挂起审批。"""
    graph = get_refund_graph(MemorySaver())
    tid = "test-refund-notfound"
    cfg = {"configurable": {"thread_id": tid}}
    graph.invoke({"order_id": "O99999", "reason": "x", "inner_thread": tid}, config=cfg)
    st = graph.get_state(cfg)
    assert not st.next, "校验失败应直接终止，不挂起"
    summary = st.values.get("summary", "")
    assert "不存在" in summary, f"summary 应含'不存在': {summary}"


def test_refund_graph_validation_not_signed():
    """校验失败：订单未签收（运输中）→ 直接终止。"""
    graph = get_refund_graph(MemorySaver())
    tid = "test-refund-notsigned"
    cfg = {"configurable": {"thread_id": tid}}
    graph.invoke({"order_id": "O12347", "reason": "x", "inner_thread": tid}, config=cfg)
    st = graph.get_state(cfg)
    assert not st.next
    assert "已签收" in st.values.get("summary", "")


def test_resume_refund_helper():
    """resume_refund 辅助函数：恢复挂起的内层图，返回 summary。"""
    cp = MemorySaver()
    graph = get_refund_graph(cp)
    tid = "test-resume-helper"
    cfg = {"configurable": {"thread_id": tid}}
    graph.invoke({"order_id": "O12345", "reason": "质量问题", "inner_thread": tid}, config=cfg)
    # 用辅助函数恢复（批准）
    summary = asyncio.run(resume_refund(tid, True, cp))
    assert "退款单号" in summary, f"resume_refund 应返回含退款单号的 summary: {summary}"


def test_resume_refund_helper_reject():
    """resume_refund 辅助函数：拒绝路径返回含'拒绝'的 summary。"""
    cp = MemorySaver()
    graph = get_refund_graph(cp)
    tid = "test-resume-helper-reject"
    cfg = {"configurable": {"thread_id": tid}}
    graph.invoke({"order_id": "O12345", "reason": "质量问题", "inner_thread": tid}, config=cfg)
    summary = asyncio.run(resume_refund(tid, False, cp))
    assert "拒绝" in summary


def test_extract_interrupt_new_format():
    """_extract_interrupt 识别 refund_approval 新格式 payload（含 inner_thread）。"""
    from app.streaming import _extract_interrupt

    class FakeInterrupt:
        def __init__(self, value):
            self.value = value

    payload = [FakeInterrupt({
        "type": "refund_approval",
        "inner_thread": "refund:O12345:123",
        "order_id": "O12345",
        "amount": 399.0,
        "summary": "订单 O12345 申请退款 ¥399.00",
    })]
    tool_name, tool_args, inner_thread = _extract_interrupt(payload)
    assert tool_name == "start_refund"
    assert inner_thread == "refund:O12345:123"
    assert tool_args["order_id"] == "O12345"
    assert tool_args["amount"] == 399.0


def test_extract_interrupt_old_format():
    """_extract_interrupt 识别老格式 payload（外层 interrupt_on，无 inner_thread）。"""
    from app.streaming import _extract_interrupt

    class FakeInterrupt:
        def __init__(self, value):
            self.value = value

    payload = [FakeInterrupt({
        "action_requests": [{"name": "create_ticket", "args": {"title": "投诉"}}]
    })]
    tool_name, tool_args, inner_thread = _extract_interrupt(payload)
    assert tool_name == "create_ticket"
    assert tool_args == {"title": "投诉"}
    assert inner_thread is None
