"""IM 频道路由：配置不同 IM 频道、平台内 Web 聊天、外部 Webhook 接入。

每个频道可以配置 provider（web / wecom / feishu / dingtalk / generic），
provider 不是 web 时可通过 /channels/{id}/incoming 接收外部 IM 消息，
配置里的 outbound_webhook 可把数字员工回复推回对应 IM。
"""

import json
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app import auth, conversations, runtime
from app.models import (
    ImChannelCreate, ImChannelUpdate, ImConversationCreate, ImIncomingMessage, MessageIn,
)
from app.streaming import _stream_run, reconstruct, conv_emp_map, conv_owner_map

router = APIRouter(prefix="/api/im", tags=["im"])


def _accessible_employee_map(user: dict) -> dict[str, dict]:
    if user.get("role") == "admin":
        rows = runtime.discover_employees()
    else:
        rows = runtime.discover_assigned_employees(user["id"])
    return {e["id"]: e for e in rows}


def _channel_employees(channel_id: str, user: dict) -> list[dict]:
    channel = conversations.get_channel(channel_id)
    if not channel:
        raise HTTPException(404, "频道不存在")
    accessible = _accessible_employee_map(user)
    member_ids = conversations.list_employee_ids_for_channel(channel_id)
    # 频道从未挂载员工时回退到当前用户可访问的全部员工，保证首次使用可聊天。
    if not member_ids:
        return list(accessible.values())
    return [accessible[eid] for eid in member_ids if eid in accessible]


def _channel_item(ch: dict, user: dict) -> dict:
    item = {
        "id": ch["id"],
        "name": ch["name"],
        "description": ch["description"],
        "kind": ch.get("kind") or ch.get("provider") or "web",
        "provider": ch.get("provider") or "web",
        "enabled": bool(ch.get("enabled", True)),
        "employees": _channel_employees(ch["id"], user),
    }
    if ch.get("provider", "web") != "web":
        item["inbound_url"] = f"/api/im/channels/{ch['id']}/incoming"
    if user.get("role") == "admin":
        item["config"] = ch.get("config") or {}
    return item


def _external_user_id(channel_id: str, sender_id: str) -> str:
    return f"im:{channel_id}:{sender_id}"


async def _run_external_reply(conv_id: str, input_, user_id: str) -> str:
    reply_parts: list[str] = []
    async for raw in _stream_run(conv_id, input_, user_id=user_id, role="user"):
        if not raw.startswith("data: "):
            continue
        try:
            ev = json.loads(raw[len("data: "):])
        except Exception:
            continue
        if ev.get("type") == "token":
            reply_parts.append(ev.get("content", ""))
        elif ev.get("type") == "error":
            reply_parts.append(ev.get("message", "任务执行出错"))
    return "".join(reply_parts).strip()


async def _send_outbound(channel: dict, conv_id: str, reply: str) -> None:
    cfg = channel.get("config") or {}
    url = cfg.get("outbound_webhook")
    if not url or not reply:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json={
                "conversation_id": conv_id,
                "channel_id": channel["id"],
                "message": reply,
            })
    except Exception:
        pass


@router.get("/channels")
async def list_channels(user: dict = Depends(auth.get_current_user_or_fallback)):
    out = []
    for ch in conversations.list_channels():
        out.append(_channel_item(ch, user))
    return {"items": out}


@router.post("/channels")
async def create_channel(body: ImChannelCreate,
                         user: dict = Depends(auth.get_current_user_or_fallback)):
    if user.get("role") != "admin":
        raise HTTPException(403, "仅管理员可创建 IM 频道")
    row = conversations.create_channel(
        name=body.name,
        description=body.description,
        kind=body.provider or "web",
        provider=body.provider or "web",
        config=body.config or {},
        enabled=body.enabled,
        created_by=user.get("id", "admin"),
        employee_ids=body.employee_ids,
    )
    return row


@router.put("/channels/{channel_id}")
async def update_channel(channel_id: str, body: ImChannelUpdate,
                         user: dict = Depends(auth.get_current_user_or_fallback)):
    if user.get("role") != "admin":
        raise HTTPException(403, "仅管理员可修改 IM 频道")
    ch = conversations.update_channel(
        channel_id,
        name=body.name,
        description=body.description,
        provider=body.provider,
        kind=body.provider,
        config=body.config,
        enabled=body.enabled,
        employee_ids=body.employee_ids,
    )
    if not ch:
        raise HTTPException(404, "频道不存在")
    return ch


@router.delete("/channels/{channel_id}")
async def delete_channel(channel_id: str,
                         user: dict = Depends(auth.get_current_user_or_fallback)):
    if user.get("role") != "admin":
        raise HTTPException(403, "仅管理员可删除 IM 频道")
    if not conversations.delete_channel(channel_id):
        raise HTTPException(404, "频道不存在")
    return {"ok": True}


@router.post("/channels/{channel_id}/incoming")
async def incoming_message(channel_id: str, body: ImIncomingMessage):
    """外部 IM Webhook 入口：接收消息并让对应数字员工回复。"""
    ch = conversations.get_channel(channel_id)
    if not ch:
        raise HTTPException(404, "频道不存在")
    if not ch.get("enabled", True):
        raise HTTPException(403, "频道已停用")
    if ch.get("provider", "web") == "web":
        raise HTTPException(400, "Web 频道请使用平台内置聊天")
    cfg = ch.get("config") or {}
    secret = cfg.get("secret")
    if secret and body.secret != secret:
        raise HTTPException(403, "secret 校验失败")
    employees = conversations.list_employee_ids_for_channel(channel_id)
    if not employees:
        employees = [e["id"] for e in runtime.discover_employees()]
    if not employees:
        raise HTTPException(500, "该频道没有可交互的数字员工")
    emp_id = body.employee_id or employees[0]
    if emp_id not in employees:
        raise HTTPException(403, "该员工未挂载到当前频道")

    user_id = _external_user_id(channel_id, body.sender_id)
    meta = conversations.find_channel_conversation(channel_id, user_id, emp_id)
    if meta:
        conv_id = meta["conv_id"]
        conversations.touch(conv_id, title=body.message[:40], preview=body.message[:60], bump=1)
    else:
        conv_id = "c_im_" + time.strftime("%Y%m%d%H%M%S") + str(time.time()).split(".")[1]
        conversations.create(conv_id, emp_id, user_id=user_id, channel_id=channel_id,
                             title=body.message[:40], preview=body.message[:60], count=1)
        conv_emp_map[conv_id] = emp_id
        conv_owner_map[conv_id] = user_id

    input_ = {"messages": [{"role": "user", "content": body.message}]}
    reply = await _run_external_reply(conv_id, input_, user_id)
    await _send_outbound(ch, conv_id, reply)
    return {"conversation_id": conv_id, "channel_id": channel_id,
            "employee_id": emp_id, "sender_id": body.sender_id, "reply": reply}


@router.get("/channels/{channel_id}/employees")
async def list_channel_employees(channel_id: str,
                                 user: dict = Depends(auth.get_current_user_or_fallback)):
    return {"items": _channel_employees(channel_id, user)}


@router.post("/channels/{channel_id}/conversations")
async def new_channel_conversation(channel_id: str, body: ImConversationCreate,
                                   user: dict = Depends(auth.get_current_user_or_fallback)):
    employees = _channel_employees(channel_id, user)
    if not employees:
        raise HTTPException(403, "当前没有可聊天的数字员工，请联系管理员")
    emp = body.employee_id or employees[0]["id"]
    if emp not in {e["id"] for e in employees}:
        raise HTTPException(403, "该数字员工不在当前频道内或未分配给你")
    conv_id = "c_" + time.strftime("%Y%m%d%H%M%S") + str(time.time()).split(".")[1]
    conversations.create(conv_id, emp, user_id=user["id"], channel_id=channel_id)
    conv_emp_map[conv_id] = emp
    conv_owner_map[conv_id] = user["id"]
    return {"conversation_id": conv_id, "channel_id": channel_id,
            "employee_id": emp, "user_id": user["id"]}


@router.get("/channels/{channel_id}/conversations")
async def list_channel_conversations(channel_id: str,
                                     user: dict = Depends(auth.get_current_user_or_fallback)):
    if not conversations.get_channel(channel_id):
        raise HTTPException(404, "频道不存在")
    uid = None if user.get("role") == "admin" else user["id"]
    return {"items": conversations.list_for_channel(channel_id, uid, limit=50)}


@router.get("/channels/{channel_id}/conversations/{conv_id}")
async def get_channel_conversation(channel_id: str, conv_id: str,
                                   user: dict = Depends(auth.get_current_user_or_fallback)):
    meta = conversations.get(conv_id)
    if not meta:
        raise HTTPException(404, "会话不存在或已清理")
    if meta.get("channel_id") != channel_id:
        raise HTTPException(400, "会话不属于该频道")
    if user.get("role") != "admin" and meta.get("user_id", "default") != user["id"]:
        raise HTTPException(403, "无权访问该会话")
    emp = meta["employee_id"]
    agent, _ = await runtime.get_agent(emp)
    states = [s async for s in agent.aget_state_history(
        {"configurable": {"thread_id": conv_id}}, limit=1)]
    msgs = states[0].values.get("messages", []) if states else []
    return {
        "employee_id": emp,
        "channel_id": channel_id,
        "title": meta["title"],
        "message_count": meta["message_count"],
        "turns": reconstruct(msgs),
    }


@router.post("/channels/{channel_id}/conversations/{conv_id}/messages")
async def send_channel_message(channel_id: str, conv_id: str, body: MessageIn,
                               user: dict = Depends(auth.get_current_user_or_fallback)):
    meta = conversations.get(conv_id)
    owner = conv_owner_map.get(conv_id) or (meta or {}).get("user_id")
    if not meta and conv_id not in conv_emp_map:
        raise HTTPException(404, "会话不存在")
    if meta and meta.get("channel_id") != channel_id:
        raise HTTPException(400, "会话不属于该频道")
    if owner and owner != user["id"] and owner != "default" and user.get("role") != "admin":
        raise HTTPException(403, "无权操作该会话")
    emp = meta["employee_id"] if meta else conv_emp_map.get(conv_id, "")
    if not emp:
        raise HTTPException(500, "会话缺少员工信息")
    text = body.message.strip()
    if not meta:
        conversations.create(conv_id, emp, channel_id=channel_id, title=text[:40],
                             preview=text[:60], count=1, user_id=user["id"])
    else:
        if meta.get("user_id") == "default":
            conversations.claim(conv_id, user["id"])
        conversations.touch(conv_id, title=text[:40], preview=text[:60], bump=1)
    input_ = {"messages": [{"role": "user", "content": body.message}]}
    return StreamingResponse(
        _stream_run(conv_id, input_, user_id=user["id"], role=user.get("role", "user")),
        media_type="text/event-stream")
