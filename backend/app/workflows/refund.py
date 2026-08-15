"""Workflow 层：退款 SOP（刚性状态机，审批已内化）。

本文件把退款流程实现为 LangGraph StateGraph：
    validate_order → calc_refund → await_approval(interrupt) → execute_refund

设计要点（解决「审批只能在外层 agent 拦截、无法在流程中间插入」的老问题）：
- **审批是流程的一个显式节点** `await_approval`，用 LangGraph 的 `interrupt()`
  原语挂起——状态机明确知道「当前卡在审批」，trace 能看见完整的
  validate → (suspend at approval) → execute 进度。
- 图在编译期注入 checkpointer，且运行在**派生的内层 thread**
  (`refund:{order_id}:{sha1(reason)[:12]}`）上，与外层 agent 的 thread
  (会话 id) 隔离，互不污染。
- 工具 `start_refund` 首次调用跑图 → 在 `await_approval` 处 `interrupt()`
  向上冒泡成外层 agent 的 `__interrupt__` → `_stream_run` 据此建审批单
  （存 `inner_thread`）→ 审批人决策后，`decision` 端点先 `Command(resume=...)`
  恢复内层图执行 `execute_refund` 拿到 summary，再 `Command(resume=summary)`
  恢复外层 agent（把工具调用结果喂回）。整条链路确定性、可恢复。
- 老实现里 `MOCK_ORDERS` 硬编码订单数据（见 README 路线图 Point 3：
  后续应改为经 Connector 取数）。本文件只负责流程编排，不持有数据源。

说明：本模块不再在 import 期编译全局图，而是提供 `get_refund_graph(checkpointer)`
（按 checkpointer 实例缓存）与 `make_start_refund(checkpointer)` 工厂，
由 compiler 在编译期用运行时 checkpointer 注入。
"""
from typing import TypedDict
import hashlib

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command

# ---------------------------------------------------------------------------
# 演示用硬编码订单（后续替换为 Connector 数据源，见 README 路线图）
# ---------------------------------------------------------------------------
MOCK_ORDERS = {
    "O12345": {"product": "X1 智能音箱", "amount": 399.0, "status": "已签收", "days_since_sign": 3},
    "O12346": {"product": "S2 智能台灯", "amount": 199.0, "status": "已签收", "days_since_sign": 10},
    "O12347": {"product": "X1 智能音箱", "amount": 399.0, "status": "运输中", "days_since_sign": 0},
    "O12348": {"product": "W5 智能手表（硅胶版）", "amount": 599.0, "status": "已签收", "days_since_sign": 1},
    "O12349": {"product": "H7 降噪耳机", "amount": 499.0, "status": "已签收", "days_since_sign": 5},
    "O12350": {"product": "P3 智能投影仪", "amount": 2999.0, "status": "运输中", "days_since_sign": 0},
    "O12351": {"product": "S2 Pro 双灯头台灯", "amount": 299.0, "status": "已签收", "days_since_sign": 20},
    "O12352": {"product": "X1 智能音箱（白色）", "amount": 399.0, "status": "已签收", "days_since_sign": 60},
    "O12353": {"product": "H7 Pro 降噪耳机", "amount": 699.0, "status": "已签收", "days_since_sign": 2},
    "O12354": {"product": "W5 Pro eSIM 手表", "amount": 899.0, "status": "已签收", "days_since_sign": 14},
}


class RefundState(TypedDict, total=False):
    order_id: str
    reason: str
    inner_thread: str        # 本次退款运行的内层 thread id（供 interrupt 回传）
    order: dict
    refund_amount: float
    refund_no: str
    approval: dict           # {"approved": bool} —— await_approval 节点的 resume 值
    summary: str


def validate_order(state: RefundState) -> RefundState:
    """校验订单：存在 + 已签收 + 7 天内。不通过则终止（无副作用）。"""
    order = MOCK_ORDERS.get(state["order_id"])
    if not order:
        return {"summary": f"流程终止：订单 {state['order_id']} 不存在。"}
    if order["status"] != "已签收":
        return {"summary": f"流程终止：订单 {state['order_id']} 当前状态「{order['status']}」，仅已签收订单可退款。"}
    if order["days_since_sign"] > 7:
        return {"summary": f"流程终止：订单签收已 {order['days_since_sign']} 天，超出 7 天无理由退货期。"}
    return {"order": order}


def calc_refund(state: RefundState) -> RefundState:
    if "order" not in state:
        return {}
    return {"refund_amount": state["order"]["amount"]}


def await_approval(state: RefundState) -> RefundState:
    """审批节点：用 interrupt() 挂起，等待人工决策。

    挂起时把订单/金额/内层 thread 回传给外层，便于审批 UI 展示与恢复。
    resume 值形如 {"approved": bool}。"""
    amount = state.get("refund_amount", 0.0)
    payload = {
        "type": "refund_approval",
        "inner_thread": state.get("inner_thread"),
        "order_id": state.get("order_id"),
        "amount": amount,
        "summary": (
            f"订单 {state.get('order_id')} 申请退款 ¥{amount:.2f}"
            f"（{state.get('order', {}).get('product', '')}）；"
            f"原因：{state.get('reason', '')}。是否批准？"
        ),
    }
    decision = interrupt(payload)            # 挂起，等待 Command(resume=...)
    return {"approval": decision}


def execute_refund(state: RefundState) -> RefundState:
    """执行退款（批准路径）或给出拒绝说明（拒绝路径）。"""
    approved = bool(state.get("approval", {}).get("approved"))
    if not approved:
        return {"summary": f"退款申请已被拒绝，流程终止（订单 {state.get('order_id')}）。"}
    if "order" not in state:
        return {"summary": "流程异常终止：缺少订单数据。"}
    no = "R" + str(state["order_id"])[1:]
    return {
        "refund_no": no,
        "summary": (
            f"退款流程已完成（刚性 SOP：校验订单 → 计算金额 → 审批 → 生成退款单）。\n"
            f"退款单号：{no}；金额：¥{state['refund_amount']:.2f}"
            f"（{state['order']['product']}）；原因：{state['reason']}。"
            f"款项将原路返回，3-5 个工作日到账。"
        ),
    }


def route_after_validate(state: RefundState) -> str:
    return "calc_refund" if "order" in state else END


def _build():
    """构建 StateGraph（不含 checkpointer）。"""
    g = StateGraph(RefundState)
    g.add_node("validate_order", validate_order)
    g.add_node("calc_refund", calc_refund)
    g.add_node("await_approval", await_approval)
    g.add_node("execute_refund", execute_refund)
    g.add_edge(START, "validate_order")
    g.add_conditional_edges("validate_order", route_after_validate)
    g.add_edge("calc_refund", "await_approval")
    # 无论批准/拒绝都走 execute_refund（它内部按 approval 标记分流出两种 summary）
    g.add_edge("await_approval", "execute_refund")
    g.add_edge("execute_refund", END)
    return g


# 按 checkpointer 实例缓存编译后的图（避免每次工具调用都重新编译）
_graph_cache: dict = {}


def get_refund_graph(checkpointer) :
    """取（按 checkpointer 缓存的）已编译退款图。"""
    key = id(checkpointer)
    if key not in _graph_cache:
        _graph_cache[key] = _build().compile(checkpointer=checkpointer)
    return _graph_cache[key]


def make_start_refund(checkpointer):
    """工厂：返回 start_refund 工具，把退款流程跑在派生的内层 thread 上。

    Point2 内化审批：工具首次调用跑 refund StateGraph（validate_order → calc_refund
    → await_approval(interrupt) → execute_refund），在 await_approval 处 interrupt()
    挂起，向上冒泡为外层 agent 的 __interrupt__（见 app.main._stream_run），由审批
    中心建单（存 inner_thread）→ 审批人决策后，decision 端点调 resume_refund 恢复
    内层图拿到 summary，再用 Command(resume=summary) 恢复外层 agent。

    - 内层 thread 由 (order_id, reason) 确定性派生，保证 resume 时定位到同一次运行。
    - 外层 interrupt_on 已撤（catalog _migrate_remove_refund_gate），不会双重拦截。
    """
    from langchain.tools import tool

    graph = get_refund_graph(checkpointer)

    @tool
    async def start_refund(order_id: str, reason: str) -> str:
        """发起退款流程（含人工审批节点）。固定流程：校验订单 → 计算金额 → 审批 → 生成退款单。"""
        # 确定性派生 thread id：避免 abs(hash()) 受 PYTHONHASHSEED 影响，
        # 保证进程重启/多实例下审批恢复仍能定位到同一次运行
        inner = f"refund:{order_id}:{hashlib.sha1(reason.encode()).hexdigest()[:12]}"
        await graph.ainvoke(
            {"order_id": order_id, "reason": reason, "inner_thread": inner},
            config={"configurable": {"thread_id": inner}},
        )
        st = graph.get_state({"configurable": {"thread_id": inner}})
        # 若挂起在审批节点，重抛 interrupt() 让其冒泡到外层 agent 的 __interrupt__
        if st.next and "await_approval" in st.next:
            payload = (
                st.tasks[0].interrupts[0].value
                if (st.tasks and st.tasks[0].interrupts)
                else {"type": "refund_approval", "inner_thread": inner}
            )
            from langgraph.types import interrupt as _interrupt
            _interrupt(payload)
        return st.values.get("summary", "流程异常终止")

    return start_refund


async def resume_refund(inner_thread: str, approved: bool, checkpointer) -> str:
    """恢复挂起的退款内层图，返回最终 summary。

    decision 端点调用：先用本函数恢复内层图（执行 execute_refund 或终止），
    再用返回的 summary 作为 Command(resume=summary) 恢复外层 agent 的工具调用结果。
    """
    graph = get_refund_graph(checkpointer)
    await graph.ainvoke(
        Command(resume={"approved": approved}),
        config={"configurable": {"thread_id": inner_thread}},
    )
    st = graph.get_state({"configurable": {"thread_id": inner_thread}})
    return st.values.get("summary", "流程异常终止")
