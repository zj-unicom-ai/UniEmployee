"""对话 / 消息 / 追踪 / 审批 路由。"""
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from langgraph.types import Command

from app import attachments, auth, runtime, approvals, conversations, catalog, traces
from app.models import MessageIn, DecisionIn
from app.streaming import _stream_run, employee_of, reconstruct, conv_emp_map, conv_owner_map

logger = logging.getLogger("app.routes.conversations")

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
    exclude_auto: bool = False,
):
    uid = user["id"]
    if page:
        return conversations.list_paged(employee_id, user_id=uid, page=page, page_size=page_size)
    return conversations.list_for(employee_id, user_id=uid, limit=limit,
                                   exclude_auto=exclude_auto)


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
        "model": meta.get("model") or "",
        "turns": reconstruct(msgs),
    }


@router.post("/conversations/{conv_id}/attachments")
async def upload_attachment(conv_id: str, file: UploadFile = File(...),
                            user: dict = Depends(auth.get_current_user_or_fallback)):
    """上传对话附件：落盘到 /data/uploads/{uid}/{conv_id}/，返回 agent 可读的虚拟路径。"""
    uid = user["id"]
    meta = conversations.get(conv_id)
    owner = conv_owner_map.get(conv_id) or (meta or {}).get("user_id")
    if not meta and conv_id not in conv_emp_map:
        raise HTTPException(404, "会话不存在")
    if owner and owner != uid and owner != "default":
        raise HTTPException(403, "无权操作该会话")
    return await attachments.save_attachment(conv_id, uid, file)


@router.post("/conversations/{conv_id}/messages")
async def send_message(conv_id: str, body: MessageIn,
                       datasource_id: str = "",
                       data_source: str = "",
                       user: dict = Depends(auth.get_current_user_or_fallback)):
    uid = user["id"]
    meta = conversations.get(conv_id)
    owner = conv_owner_map.get(conv_id) or (meta or {}).get("user_id")
    if not meta and conv_id not in conv_emp_map:
        raise HTTPException(404, "会话不存在")
    if owner and owner != uid and owner != "default":
        raise HTTPException(403, "无权操作该会话")
    emp = employee_of(conv_id)
    # 附件只接受本用户上传目录内的路径，防止伪造 /data/ 任意路径
    atts = [a.model_dump() for a in body.attachments
            if attachments.validate_attachment_path(uid, a.path)]
    if len(atts) > attachments.MAX_ATTACHMENTS_PER_MESSAGE:
        raise HTTPException(400, f"单条消息最多 {attachments.MAX_ATTACHMENTS_PER_MESSAGE} 个附件")
    text = body.message.strip()
    if not text and not atts:
        raise HTTPException(400, "消息内容为空")
    title = text[:40] or f"附件：{atts[0]['name']}"[:40]
    preview = text[:60] or f"[附件] {atts[0]['name']}"
    # 模型选择：请求体 model > 会话绑定 model > 员工默认
    req_model = (body.model or "").strip()
    if not meta:
        conversations.create(conv_id, emp, title=title, preview=preview,
                             count=1, user_id=uid, model=req_model or None)
    else:
        if meta.get("user_id") == "default":
            conversations.claim(conv_id, uid)
        conversations.touch(conv_id, title=title, preview=preview, bump=1)
        if req_model:
            conversations.set_model(conv_id, req_model)
    content = attachments.compose_user_content(body.message, atts)
    # 数据分析员工：CSV/Excel 附件自动注册为 DuckDB 表（表格问答），
    # 注册摘要替换默认处理指引——xiaoshu 是 standard 后端无 run_python。
    if emp == "xiaoshu":
        try:
            from app.agent.analyst.fileqa import manager as fileqa_manager
            reg_summary = fileqa_manager.register_attachments(atts, uid)
        except Exception:
            logger.warning("表格附件注册异常 conv=%s", conv_id, exc_info=True)
            reg_summary = ""
        if reg_summary:
            content = attachments.compose_user_content(
                body.message, atts,
                guidance="csv/xlsx 数据文件已自动注册为可查询数据表，"
                         "用 file_table_list 查看表结构，用 file_table_query "
                         "编写 SQL 查询分析（DuckDB 只读）。" + reg_summary)
    # 最终使用的模型：请求体优先，其次会话绑定
    bound_model = (meta or {}).get("model") or ""
    use_model = req_model or bound_model
    input_ = {"messages": [{"role": "user", "content": content}]}
    return StreamingResponse(
        _stream_run(conv_id, input_, user_id=uid, role=user.get("role", "user"),
                    datasource_id=datasource_id, data_source=data_source,
                    model_override=use_model),
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
