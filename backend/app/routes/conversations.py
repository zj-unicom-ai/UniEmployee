"""对话 / 消息 / 追踪 / 审批 路由。"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langgraph.types import Command

from app import auth, runtime, approvals, conversations, catalog, traces
from app.models import MessageIn, DecisionIn
from app.streaming import _stream_run, employee_of, reconstruct, conv_emp_map, conv_owner_map

router = APIRouter(prefix="/api")


@router.get("/employees")
async def list_employees(user: dict = Depends(auth.get_current_user)):
    if user.get("role") == "admin":
        return runtime.discover_employees()
    return runtime.discover_assigned_employees(user["id"])


@router.get("/catalog")
async def public_catalog(user: dict = Depends(auth.get_current_user)):
    c = catalog.catalog()
    c.pop("connectors", None)
    return c



@router.post("/employees/{emp_id}/conversations")
async def new_conversation(emp_id: str, user: dict = Depends(auth.get_current_user_or_fallback)):
    uid = user["id"]
    if user.get("role") != "admin" and emp_id not in catalog.assigned_employee_ids(uid):
        return {"error": "该数字员工未分配给你，请联系管理员"}
    import time as _time
    conv_id = "c_" + _time.strftime("%Y%m%d%H%M%S") + str(_time.time()).split(".")[1]
    conv_emp_map[conv_id] = emp_id
    conv_owner_map[conv_id] = uid
    return {"conversation_id": conv_id, "employee_id": emp_id, "user_id": uid}


@router.get("/conversations")
async def list_conv(
    employee_id: str = None,
    user: dict = Depends(auth.get_current_user_or_fallback),
    page: int | None = None, page_size: int = 10, limit: int | None = None,
):
    uid = user["id"]
    if page:
        return conversations.list_paged(employee_id, user_id=uid, page=page, page_size=page_size)
    return conversations.list_for(employee_id, user_id=uid, limit=limit)


@router.delete("/conversations/{conv_id}")
async def delete_conv(conv_id: str, user: dict = Depends(auth.get_current_user_or_fallback)):
    meta = conversations.get(conv_id)
    if not meta:
        return {"error": "会话不存在"}
    uid = user["id"]
    if meta.get("user_id", "default") != uid:
        return {"error": "无权删除该会话"}
    conversations.delete(conv_id)
    return {"ok": True}


@router.get("/conversations/{conv_id}")
async def get_conv(conv_id: str, user: dict = Depends(auth.get_current_user_or_fallback)):
    meta = conversations.get(conv_id)
    if not meta:
        return {"error": "会话不存在或已清理"}
    uid = user["id"]
    if meta.get("user_id", "default") != uid:
        return {"error": "无权访问该会话"}
    emp = meta["employee_id"]
    agent, _ = await runtime.get_agent(emp)
    states = [s async for s in agent.aget_state_history(
        {"configurable": {"thread_id": conv_id}}, limit=1)]
    msgs = states[0].values.get("messages", []) if states else []
    return {
        "employee_id": emp,
        "title": meta["title"],
        "message_count": meta["message_count"],
        "turns": reconstruct(msgs),
    }


@router.post("/conversations/{conv_id}/messages")
async def send_message(conv_id: str, body: MessageIn,
                       user: dict = Depends(auth.get_current_user_or_fallback)):
    uid = user["id"]
    meta = conversations.get(conv_id)
    owner = conv_owner_map.get(conv_id) or (meta or {}).get("user_id")
    if not meta and conv_id not in conv_emp_map:
        raise HTTPException(404, "会话不存在")
    if owner and owner != uid and owner != "default":
        raise HTTPException(403, "无权操作该会话")
    emp = employee_of(conv_id)
    text = body.message.strip()
    if not meta:
        conversations.create(conv_id, emp, title=text[:40], preview=text[:60],
                             count=1, user_id=uid)
    else:
        if meta.get("user_id") == "default":
            conversations.claim(conv_id, uid)
        conversations.touch(conv_id, title=text[:40], preview=text[:60], bump=1)
    input_ = {"messages": [{"role": "user", "content": body.message}]}
    return StreamingResponse(
        _stream_run(conv_id, input_, user_id=uid, role=user.get("role", "user")),
        media_type="text/event-stream")


@router.get("/conversations/{conv_id}/traces")
async def list_conv_traces(conv_id: str, user: dict = Depends(auth.get_current_user_or_fallback)):
    meta = conversations.get(conv_id)
    if not meta:
        return {"error": "会话不存在"}
    if user.get("role") != "admin" and meta.get("user_id", "default") != user["id"]:
        return {"error": "无权查看该会话的执行记录"}
    return {"conv_id": conv_id, "title": meta.get("title", ""),
            "employee_id": meta.get("employee_id", ""), "runs": traces.list_runs(conv_id)}


@router.get("/traces/stats")
async def trace_token_stats(user: dict = Depends(auth.get_current_user)):
    return traces.token_stats()


@router.get("/traces/{run_id}")
async def get_trace_detail(run_id: str, user: dict = Depends(auth.get_current_user_or_fallback)):
    run = traces.get_run(run_id)
    if not run:
        return {"error": "执行记录不存在"}
    if user.get("role") != "admin" and run.get("user_id") != user["id"]:
        return {"error": "无权查看该执行记录"}
    return run


@router.post("/approvals/{approval_id}/decision")
async def decide(approval_id: str, body: DecisionIn,
                 user: dict = Depends(auth.get_current_user)):
    record = approvals.get(approval_id)
    if not record or record["status"] != "pending":
        raise HTTPException(404, "审批单不存在或已处理")
    if user.get("role") != "admin" and record.get("user_id") not in (None, user["id"]):
        raise HTTPException(403, "无权处理该审批单")
    record = approvals.decide(approval_id, body.decision)
    if not record:
        raise HTTPException(404, "审批单不存在或已处理")
    uid = record.get("user_id") or "default"
    if record.get("inner_thread"):
        summary = await runtime.resume_refund(record["inner_thread"], body.decision == "approve")
        resume = Command(resume=summary)
    else:
        decisions = [{"type": body.decision}]
        if body.decision == "reject":
            decisions[0]["message"] = "审批人已拒绝该请求"
        resume = Command(resume={"decisions": decisions})
    return StreamingResponse(
        _stream_run(record["conversation_id"], resume, user_id=uid),
        media_type="text/event-stream")
