"""认证路由：登录 / 改密 / 当前用户。登录成功、登录失败、自助改密均落审计日志。"""

import os
import time
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response

from app import audit, auth, catalog
from app.models import LoginIn, ChangePwdIn

router = APIRouter(prefix="/api/auth")
_OIDC_TXN_COOKIE = "ue_oidc_txn"

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
        # 限流拒绝不写审计：底层失败已留痕，避免爆破流量放大审计表写入
        raise HTTPException(429, "尝试过于频繁，请 1 分钟后再试")
    u = catalog.get_user_by_username(body.username)
    if not u or not auth.verify_password(body.password, u["password_hash"]):
        # 记录尝试的用户名（用户不存在时并无真实账号可归属）
        audit.log("login_failed", "auth", body.username,
                  admin={"id": "", "username": body.username}, request=request,
                  after={"reason": "用户名或密码错误"})
        _login_record_fail(key)
        raise HTTPException(401, "用户名或密码错误")
    if u.get("status") != "active":
        audit.log("login_failed", "auth", body.username,
                  admin={"id": u["id"], "username": body.username}, request=request,
                  after={"reason": "账号已禁用"})
        raise HTTPException(403, "账号已禁用")
    if not auth.local_login_allowed(u):
        audit.log("login_failed", "auth", u["id"],
                  admin={"id": u["id"], "username": u["username"]}, request=request,
                  after={"reason": "SSO 已启用，仅紧急管理员可使用本地密码"})
        raise HTTPException(403, "企业单点登录已启用，请使用企业登录")
    _LOGIN_FAILS.pop(key, None)
    token = auth.create_token(u)
    audit.log("login", "auth", u["id"],
              admin={"id": u["id"], "username": u["username"]}, request=request)
    return {"token": token,
            "must_change_password": bool(u.get("must_change_password")),
            "user": {"id": u["id"], "username": u["username"],
                     "role": u["role"], "tenant_id": u.get("tenant_id", "default")}}


def _safe_next(value: str) -> str:
    return value if value.startswith("/") and not value.startswith("//") else "/app/home"


@router.get("/sso/config")
async def sso_config():
    """仅返回前端展示所需的开关，不暴露 IdP 地址和客户端配置。"""
    return {"enabled": auth.oidc_enabled()}


@router.get("/sso/login")
async def sso_login(next: str = Query("/app/home")):
    """跳转企业 IdP。state 与 nonce 仅在短时、HTTP-only cookie 中保存。"""
    if not auth.oidc_enabled():
        raise HTTPException(404, "企业单点登录尚未配置")
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    response = RedirectResponse(await auth.oidc_authorization_url(state, nonce), status_code=302)
    response.set_cookie(_OIDC_TXN_COOKIE, auth.oidc_transaction(state, nonce, _safe_next(next)),
                        httponly=True, secure=auth._cookie_secure(), samesite="lax", path="/api/auth/sso",
                        max_age=600)
    return response


@router.get("/sso/callback")
async def sso_callback(code: str, state: str, request: Request,
                       oidc_txn: str | None = Cookie(None, alias=_OIDC_TXN_COOKIE)):
    """验证 OIDC 凭证，绑定外部身份后签发平台 HTTP-only 会话。"""
    if not auth.oidc_enabled():
        raise HTTPException(404, "企业单点登录尚未配置")
    txn = auth.decode_oidc_transaction(oidc_txn, state)
    cfg, tokens = await auth.exchange_oidc_code(code)
    claims = await auth.verify_oidc_id_token(cfg, tokens["id_token"], txn["nonce"])
    role, org_id = auth.oidc_role_and_org(claims)
    if org_id and not catalog.get_org(org_id):
        raise HTTPException(503, "OIDC 部门映射指向不存在的组织")
    user = catalog.find_or_create_oidc_user(
        provider=os.environ.get("OIDC_PROVIDER", "enterprise-oidc"),
        issuer=os.environ["OIDC_ISSUER"].rstrip("/"), claims=claims,
        tenant_id=auth.enterprise_tenant_id(), org_id=org_id, role=role)
    if user.get("status") != "active":
        raise HTTPException(403, "账号已禁用")
    audit.log("sso_login", "auth", user["id"],
              admin={"id": user["id"], "username": user["username"]}, request=request,
              after={"provider": os.environ.get("OIDC_PROVIDER", "enterprise-oidc")})
    response = RedirectResponse("/login?" + urlencode({"sso": "1", "next": _safe_next(txn["next"])}),
                                status_code=302)
    response.set_cookie(auth.SESSION_COOKIE, auth.create_token(user), **auth.session_cookie_options())
    response.set_cookie(auth.CSRF_COOKIE, secrets.token_urlsafe(32), **auth.csrf_cookie_options())
    response.delete_cookie(_OIDC_TXN_COOKIE, path="/api/auth/sso")
    return response


@router.post("/logout")
async def logout():
    """清除 SSO 平台会话；不试图登出企业 IdP。"""
    response = Response(status_code=204)
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    response.delete_cookie(auth.CSRF_COOKIE, path="/")
    return response


@router.post("/change-password")
async def change_password(body: ChangePwdIn, request: Request,
                          user: dict = Depends(auth.get_current_user)):
    u = catalog.get_user_by_username(user["username"])
    if not u or not auth.verify_password(body.old_password, u["password_hash"]):
        raise HTTPException(401, "原密码错误")
    if len(body.new_password) < 8:
        raise HTTPException(400, "新密码至少 8 位")
    if body.new_password == body.old_password:
        raise HTTPException(400, "新密码不能与原密码相同")
    catalog.set_password(u["id"], auth.hash_password(body.new_password))
    # 自助改密留痕（不记密码内容），obj_type 与 admin 重置密码一致
    audit.log("update", "user_password", u["id"],
              admin={"id": u["id"], "username": u["username"]}, request=request)
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(auth.get_current_user)):
    return {"id": user["id"], "username": user["username"], "role": user["role"],
            "tenant_id": user.get("tenant_id", "default")}
