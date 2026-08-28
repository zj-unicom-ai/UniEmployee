"""安全护栏管理端点：配置读写、敏感词 CRUD、拦截日志查询（仅 admin）。"""
from fastapi import APIRouter, Depends, HTTPException

from app import guard
from app import auth

router = APIRouter(prefix="/api/admin/guard")


def _admin(user: dict = Depends(auth.get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


@router.get("/settings")
async def get_settings(_=Depends(_admin)):
    return guard.get_settings()


@router.put("/settings")
async def save_settings(body: dict, _=Depends(_admin)):
    for key in ("sensitive_enabled", "admin_only_tools"):
        if key in body:
            guard.set_setting(key, str(body[key]))
    return {"ok": True, "settings": guard.get_settings()}


@router.get("/words")
async def list_words(_=Depends(_admin)):
    return {"words": guard.list_words()}


@router.post("/words")
async def add_word(body: dict, _=Depends(_admin)):
    word = (body.get("word") or "").strip()
    if not word:
        return {"error": "敏感词不能为空"}
    row = guard.add_word(word, body.get("category", ""), body.get("level", "block"))
    return {"ok": True, "word": row}


@router.delete("/words/{word_id}")
async def delete_word(word_id: int, _=Depends(_admin)):
    guard.delete_word(word_id)
    return {"ok": True}


@router.get("/logs")
async def list_logs(limit: int = 100, event_type: str = "", _=Depends(_admin)):
    return {"logs": guard.list_logs(min(limit, 500), event_type)}
