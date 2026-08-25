"""SSE 流式响应核心逻辑：_stream_run 及其辅助函数。

从 main.py 拆出的独立模块，专注于"把 agent.astream 的事件翻译成 SSE 事件"。
"""

import asyncio
import json
import logging
import os
import re
import sqlite3
import time

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from app import runtime, traces, catalog, approvals, conversations
from app.compiler import _init_model
from app.paths import db_path

logger = logging.getLogger("app.streaming")

# 会话 → 员工 映射（进程内存热路径；持久清单见 conversations.py）。
# 暴露给外部以便 routes 写入新会话映射。
conv_emp_map: dict[str, str] = {}
# 会话 → 属主 映射：新会话先落内存，首条消息时才写入 conversations.db。
# 用于发送消息前校验"该会话属于当前用户"，避免拿着 conv_id 越权操作。
conv_owner_map: dict[str, str] = {}


def sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _classify_error(exc: BaseException) -> tuple[str, str]:
    """把运行时异常映射为稳定的 error_code，避免把内部异常文本直接暴露给前端。"""
    name = type(exc).__name__
    text = str(exc).lower()
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or "timed out" in text:
        return "timeout", "模型响应超时，请稍后重试"
    if "ratelimit" in name.lower() or "rate.li" in text or "429" in text:
        return "rate_limit", "请求过于频繁或触发限额，请稍后重试"
    if ("context_length" in text or "context length" in text or
            "context window" in text or "token limit" in text or "too many tokens" in text):
        return "context_length", "上下文过长，请缩减后重试"
    if ("authentication" in text or "api key" in text or "unauthorized" in text or
            "401" in text or "403" in text or "permission denied" in text or "access denied" in text):
        return "auth", "模型或工具鉴权失败，请联系管理员"
    if ("connection refused" in text or "connection reset" in text or
            "connection aborted" in text or "urlopen error" in text or
            "failed to connect" in text or "network unreachable" in text):
        return "upstream_unavailable", "上游服务连接失败（模型或知识库等服务不可达），请联系管理员检查"
    return "internal_error", "任务执行出错，请稍后重试"


def employee_of(conv_id: str) -> str:
    if conv_id in conv_emp_map:
        return conv_emp_map[conv_id]
    meta = conversations.get(conv_id)
    if meta:
        return meta["employee_id"]
    emps = runtime.discover_employees()
    return emps[0]["id"] if emps else ""


def text_of(msg) -> str:
    c = getattr(msg, "content", "")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
    return str(c)


def reconstruct(messages: list) -> list[dict]:
    """把 LangGraph flatten 消息流重构成前端"轮次"格式。"""
    turns: list[dict] = []
    cur_ai: dict | None = None
    pending: list[dict] = []
    for m in messages:
        tname = type(m).__name__
        if tname == "HumanMessage":
            turns.append({"role": "user", "content": text_of(m)})
            cur_ai, pending = None, []
        elif tname == "AIMessage":
            tcs = [{"name": tc.get("name"), "args": tc.get("args"), "result": None}
                   for tc in (getattr(m, "tool_calls", None) or [])]
            for tc, raw in zip(tcs, (getattr(m, "tool_calls", None) or [])):
                tc["id"] = raw.get("id")
            txt = text_of(m)
            if tcs:
                if cur_ai is None:
                    cur_ai = {"role": "assistant", "content": "", "tool_calls": []}
                    turns.append(cur_ai)
                cur_ai["tool_calls"].extend(tcs)
                pending.extend(tcs)
            if txt.strip():
                if cur_ai is not None and not cur_ai["content"]:
                    cur_ai["content"] = txt
                else:
                    cur_ai = {"role": "assistant", "content": txt, "tool_calls": []}
                    turns.append(cur_ai)
                pending = []
        elif tname == "ToolMessage":
            tool_call_id = getattr(m, "tool_call_id", None)
            matched = False
            if tool_call_id:
                for tc in pending:
                    if tc.get("id") == tool_call_id:
                        tc["result"] = text_of(m)[:2000]
                        matched = True
                        break
            if not matched:
                for tc in pending:
                    if tc["result"] is None:
                        tc["result"] = text_of(m)[:2000]
                        break
    return [t for t in turns
            if t["role"] == "user" or t["content"].strip() or t["tool_calls"]]


async def recover_conversations(limit: int | None = None):
    """启动恢复：扫描 checkpointer 里 c_ 开头的历史线程，重建会话清单。

    默认只处理 ``CONV_RECOVER_LIMIT``（默认 2000）条，避免启动时全表扫描。
    """
    if limit is None:
        try:
            limit = int(os.environ.get("CONV_RECOVER_LIMIT", "2000"))
        except ValueError:
            limit = 2000
    limit = max(0, limit)
    con = sqlite3.connect(str(db_path("checkpoints.db")))
    threads = [r[0] for r in con.execute(
        "SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE 'c_%' LIMIT ?",
        (limit,)).fetchall()]
    con.close()

    emps = runtime.discover_employees()
    skill_index: dict[str, str] = {}
    for e in emps:
        for sk in e["skills"]:
            skill_index.setdefault(sk, e["id"])
    default_emp = emps[0]["id"] if emps else ""
    known = set(conversations.all_conv_ids())

    for tid in threads:
        if tid in known:
            continue
        emp = ""
        con = sqlite3.connect(str(db_path("checkpoints.db")))
        try:
            row = con.execute(
                "SELECT checkpoint, metadata FROM checkpoints WHERE thread_id=? ORDER BY rowid DESC LIMIT 1",
                (tid,)).fetchone()
        except sqlite3.OperationalError:
            row = con.execute(
                "SELECT checkpoint, NULL FROM checkpoints WHERE thread_id=? ORDER BY rowid DESC LIMIT 1",
                (tid,)).fetchone()
        con.close()

        # 优先读线程元数据：_stream_run 现在会把 employee_id 写进 configurable，
        # 这是最可靠的员工归属来源，不再从序列化 blob 里猜。
        if row and row[1]:
            try:
                meta_bytes = row[1] if isinstance(row[1], bytes) else str(row[1]).encode("utf-8", "replace")
                meta_emp = json.loads(meta_bytes.decode("utf-8", "replace")).get("employee_id")
                if meta_emp:
                    emp = meta_emp
            except Exception:
                emp = ""
        if not emp:
            try:
                emp = traces.employee_of_conv(tid) or ""
            except Exception:
                emp = ""
        if not emp and row and row[0]:
            # 遗留线程最后兜底：用技能名做近似匹配，只对老数据生效，不用于新会话。
            blob = row[0] if isinstance(row[0], bytes) else row[0].encode("utf-8", "replace")
            for skill, eid in skill_index.items():
                if skill.encode("utf-8") in blob:
                    emp = eid
                    break
        emp = emp or default_emp
        first = ""
        try:
            agent, _ = await runtime.get_agent(emp)
            states = [s async for s in agent.aget_state_history(
                {"configurable": {"thread_id": tid}}, limit=1)]
            msgs = states[0].values.get("messages", []) if states else []
            first = next((text_of(m) for m in msgs if type(m).__name__ == "HumanMessage"), "")
        except Exception:
            pass
        conversations.create(tid, emp, title=(first[:40] or "历史对话"), preview=first[:60])


async def _gen_title(conv_id: str, user_text: str, bot_text: str):
    """用模型把首轮对话提炼成 ≤16 字标题。失败静默。"""
    try:
        m = _init_model(os.environ.get("MODEL_NAME", ""))
        prompt = ("请根据以下对话生成一个不超过16个字的中文标题，"
                  "直接输出标题文字，不要引号、不要解释、不要句号。\n"
                  f"用户：{user_text[:200]}\n助手：{bot_text[:200]}")
        r = await m.ainvoke([HumanMessage(content=prompt)])
        title = r.content.strip().strip('"').strip("“”").strip("《》")[:24]
        if title:
            conversations.set_title(conv_id, title)
    except Exception:
        pass


def _extract_interrupt(payload) -> tuple[str, dict, str | None]:
    it = payload[0] if isinstance(payload, (list, tuple)) else payload
    value = getattr(it, "value", it)
    if isinstance(value, dict):
        inner_thread = value.get("inner_thread") if isinstance(value.get("inner_thread"), str) else None
        reqs = value.get("action_requests") or []
        if reqs:
            return reqs[0].get("name", "unknown"), reqs[0].get("args", {}), inner_thread
        # refund_approval 新格式
        if value.get("type") == "refund_approval":
            return "start_refund", {"order_id": value.get("order_id"), "amount": value.get("amount")}, inner_thread
        return "unknown", {"raw": str(value)[:300]}, inner_thread
    return "unknown", {"raw": str(value)[:300]}, None


async def _stream_run(conv_id: str, input_, user_id: str = "default", role: str = "user"):
    """一次执行的统一事件翻译（新消息或审批 resume 都走这里）。"""
    emp_id = employee_of(conv_id)
    if not emp_id:
        yield sse({"type": "error", "error_code": "internal_error",
                   "message": "系统暂未配置数字员工，请管理员先配置员工"})
        return
    await runtime.ensure_user_memory(user_id, emp_id)
    if role == "admin":
        agent, stage_meta = await runtime.get_agent(emp_id)
    else:
        asg = catalog.get_assignment(user_id, emp_id)
        overrides = asg["overrides"] if asg else {}
        agent, stage_meta = await runtime.get_agent(emp_id, user_id, overrides)
    for st in stage_meta:
        yield sse({"type": "stage", **st})

    input_preview, kind = "", "resume"
    try:
        if isinstance(input_, dict) and input_.get("messages"):
            kind = "message"
            m0 = input_["messages"][0]
            input_preview = m0.get("content", "") if isinstance(m0, dict) else str(m0)
    except Exception:
        pass
    trace_run_id = traces.start_run(conv_id, emp_id, user_id,
                                    input_preview=input_preview, kind=kind)
    tracer = traces.TraceHandler(trace_run_id)
    pending_subagents: dict[str, str] = {}  # tool_call_id -> subagent name

    config = {"configurable": {"thread_id": conv_id, "user_id": user_id, "employee_id": emp_id},
              "callbacks": [tracer]}
    skill_stage_on = False
    bot_text = ""

    try:
        async for event in agent.astream(input_, config=config,
                                         stream_mode=["updates", "messages"], version="v2"):
            if isinstance(event, dict):
                mode, chunk = event["type"], event["data"]
            else:
                mode, chunk = event

            if mode == "messages":
                msg, _meta = chunk if isinstance(chunk, tuple) else (chunk, None)
                if isinstance(msg, AIMessageChunk) and isinstance(msg.content, str) and msg.content:
                    bot_text += msg.content
                    yield sse({"type": "token", "content": msg.content})
                continue

            for node, update in chunk.items():
                if node == "__interrupt__":
                    tool_name, tool_args, inner_thread = _extract_interrupt(update)
                    record = approvals.create(conv_id, emp_id, tool_name, tool_args,
                                              user_id=user_id, inner_thread=inner_thread)
                    yield sse({"type": "approval_required", "approval_id": record["approval_id"],
                               "tool": tool_name, "args": tool_args})
                    tracer.flush_pending()
                    traces.finish_run(trace_run_id, status="interrupted")
                    return
                if not isinstance(update, dict):
                    continue

                rc = update.get("reasoning_content") or update.get("thinking")
                if rc and rc.strip():
                    yield sse({"type": "thinking", "content": rc})

                if update.get("todos"):
                    todos = [{"content": t.get("content", ""), "status": t.get("status", "")}
                             for t in update["todos"]]
                    yield sse({"type": "todos", "items": todos})

                for m in update.get("messages", []) or []:
                    if isinstance(m, ToolMessage):
                        name = m.name or "tool"
                        preview = (m.content if isinstance(m.content, str) else str(m.content))[:120]
                        # 透传工具真实执行状态：LangGraph 会把工具异常包装为
                        # status='error' 的 ToolMessage，前端据此显示失败标记。
                        tool_status = "error" if getattr(m, "status", None) == "error" else "end"
                        yield sse({"type": "tool", "name": name, "args": {}, "status": tool_status,
                                   "preview": preview})
                        if name == "task" and getattr(m, "tool_call_id", None) in pending_subagents:
                            sub_name = pending_subagents.pop(m.tool_call_id)
                            yield sse({"type": "subagent", "name": sub_name,
                                       "status": "completed", "output": text_of(m)[:2000]})
                    elif getattr(m, "tool_calls", None):
                        for tc in m.tool_calls:
                            name, args = tc.get("name", ""), tc.get("args", {})
                            yield sse({"type": "tool", "name": name, "args": args, "status": "start"})
                            if name == "task" and isinstance(args, dict) and args.get("subagent_type"):
                                sub_name = args["subagent_type"]
                                pending_subagents[tc.get("id", "")] = sub_name
                                yield sse({"type": "subagent", "name": sub_name, "status": "started"})
                            if not skill_stage_on:
                                skill_stage_on = True
                                yield sse({"type": "stage", "stage": "skill", "status": "active",
                                           "detail_text": f"调用 {name}"})
                            if "SKILL.md" in json.dumps(args, ensure_ascii=False):
                                skill_name = re.search(r"skills/([^/]+)/SKILL\.md", json.dumps(args))
                                yield sse({"type": "stage", "stage": "skill", "status": "active",
                                           "detail_text": f"激活技能：{skill_name.group(1) if skill_name else ''}"})

        tracer.flush_pending()
        traces.finish_run(trace_run_id, status="done")
        yield sse({"type": "stage", "stage": "report", "status": "done"})
        yield sse({"type": "message_end", "message_id": trace_run_id,
                    "run_id": trace_run_id, "employee_id": emp_id,
                    "conversation_id": conv_id})
        meta = conversations.get(conv_id)
        if meta and (meta.get("message_count") or 0) <= 1 and bot_text.strip():
            user_text = ""
            try:
                msgs = input_.get("messages") if isinstance(input_, dict) else None
                if msgs:
                    user_text = msgs[0].get("content", "") if isinstance(msgs[0], dict) else str(msgs[0])
            except Exception:
                pass
            asyncio.create_task(_gen_title(conv_id, user_text, bot_text))
    except Exception as e:
        tracer.flush_pending()
        traces.finish_run(trace_run_id, status="error", error=f"{type(e).__name__}: {e}")
        error_code, user_message = _classify_error(e)
        logger.error("SSE 运行异常 conv=%s emp=%s code=%s: %s: %s",
                     conv_id, emp_id, error_code, type(e).__name__, e, exc_info=True)
        # 把错误提示写入 checkpoint：刷新/回看历史时错误可见，而不是凭空消失。
        try:
            await agent.aupdate_state(
                config, {"messages": [AIMessage(content=f"⚠ {user_message}")]})
        except Exception:
            logger.warning("错误提示写入 checkpoint 失败 conv=%s", conv_id, exc_info=True)
        yield sse({"type": "error", "error_code": error_code, "message": user_message})
