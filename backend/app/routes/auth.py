"""认证路由：登录 / 改密 / 当前用户。"""

import time

from fastapi import APIRouter, Depends, HTTPException, Request

from app import auth, catalog
from app.models import LoginIn, ChangePwdIn

router = APIRouter(prefix="/api/auth")

# 登录限流：内存滑动窗口，按 (client_ip, username) 记失败次数。
_LOGIN_FAILS: dict = {}
_LOGIN_WINDOW = 60.0
_LOGIN_MAX_FAILS = 5


def _login_throttled(key: str) -> bool:
    now = time.time()
    fails = [t for t in _LOGIN_FAILS.get(key, []) if now - t < _LOGIN_WINDOW]
    _LOGIN_FAILS[key] = fails
    return len(fails) >= _LOGIN_MAX_FAILS


def _login_record_fail(key: str):
    _LOGIN_FAILS.setdefault(key, []).append(time.time())


@router.post("/login")
async def login(body: LoginIn, request: Request):
    ip = request.client.host if request.client else "?"
    key = f"{ip}|{body.username}"
    if _login_throttled(key):
        raise HTTPException(429, "尝试过于频繁，请 1 分钟后再试")
    u = catalog.get_user_by_username(body.username)
    if not u or not auth.verify_password(body.password, u["password_hash"]):
        _login_record_fail(key)
        raise HTTPException(401, "用户名或密码错误")
    if u.get("status") != "active":
        raise HTTPException(403, "账号已禁用")
    _LOGIN_FAILS.pop(key, None)
    token = auth.create_token(u)
    return {"token": token,
            "must_change_password": bool(u.get("must_change_password")),
            "user": {"id": u["id"], "username": u["username"],
                     "role": u["role"], "tenant_id": u.get("tenant_id", "default")}}


@router.post("/change-password")
async def change_password(body: ChangePwdIn, user: dict = Depends(auth.get_current_user)):
    u = catalog.get_user_by_username(user["username"])
    if not u or not auth.verify_password(body.old_password, u["password_hash"]):
        raise HTTPException(401, "原密码错误")
    if len(body.new_password) < 8:
        raise HTTPException(400, "新密码至少 8 位")
    if body.new_password == body.old_password:
        raise HTTPException(400, "新密码不能与原密码相同")
    catalog.set_password(u["id"], auth.hash_password(body.new_password))
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(auth.get_current_user)):
    return {"id": user["id"], "username": user["username"], "role": user["role"],
            "tenant_id": user.get("tenant_id", "default")}