"""认证模块：密码哈希(bcrypt) + JWT 签发/校验 + FastAPI 鉴权依赖。

- 用户表在 catalog.db（users），由 catalog.py 管理。
- JWT 载荷 {sub: user_id, username, role, tenant_id}，过期时间 JWT_EXPIRE_HOURS。
- 依赖：get_current_user（任意登录用户）、get_admin_user（要求 admin 角色）。
- 单租户起步：tenant_id 预留字段，默认 "default"，后续多租户可直接用。
"""
import os
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import dotenv
import httpx
import jwt
from fastapi import Cookie, Depends, Header, HTTPException

from app import catalog

# 关键：SECRET 在模块导入时读取，而 main.py 的 load_dotenv 在 lifespan 才执行，
# 若不在此处先加载 .env，JWT 将永远用默认弱密钥签名（可被伪造 token）。
# 注意：真实 .env 位于项目根（backend 的上一级），
# 此处必须向上三级（auth.py → app → backend → 项目根）才能正确加载。
_env_cand = Path(__file__).resolve().parent.parent.parent / ".env"
if not _env_cand.exists():
    _env_cand = Path(__file__).resolve().parent.parent / ".env"  # 兼容旧布局
dotenv.load_dotenv(_env_cand)
SECRET = os.environ.get("JWT_SECRET", "change-me-in-prod")
if SECRET == "change-me-in-prod":
    print("[security] 警告：JWT_SECRET 未配置，正在使用默认弱密钥！请在 .env 设置 JWT_SECRET")
ALGO = "HS256"
EXPIRE_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS", "24"))
SESSION_COOKIE = "ue_session"
CSRF_COOKIE = "ue_csrf"


# ---- 密码 ----

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ---- JWT ----

def create_token(user: dict) -> str:
    payload = {
        "sub": user["id"],
        "username": user["username"],
        "role": user["role"],
        "tenant_id": user.get("tenant_id", "default"),
        "exp": datetime.now(timezone.utc) + timedelta(hours=EXPIRE_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, SECRET, algorithm=ALGO)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET, algorithms=[ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "token 已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "无效的 token")


# ---- OIDC 单点登录 ----

def oidc_enabled() -> bool:
    """OIDC 是显式启用的可选能力，缺少关键配置时不暴露登录入口。"""
    return bool(os.environ.get("OIDC_ISSUER", "").strip()
                and os.environ.get("OIDC_CLIENT_ID", "").strip()
                and os.environ.get("OIDC_REDIRECT_URI", "").strip())


def enterprise_tenant_id() -> str:
    """一期单企业部署的固定租户边界。"""
    return os.environ.get("ENTERPRISE_TENANT_ID", "default").strip() or "default"


def _cookie_secure() -> bool:
    return os.environ.get("AUTH_COOKIE_SECURE", "0").strip().lower() in {"1", "true", "yes"}


def session_cookie_options() -> dict:
    return {"httponly": True, "secure": _cookie_secure(), "samesite": "lax", "path": "/",
            "max_age": EXPIRE_HOURS * 3600}


def csrf_cookie_options() -> dict:
    return {"httponly": False, "secure": _cookie_secure(), "samesite": "lax", "path": "/",
            "max_age": EXPIRE_HOURS * 3600}


def local_login_allowed(user: dict) -> bool:
    """启用 SSO 后，仅显式标记的紧急管理员可用本地口令兜底。"""
    return not oidc_enabled() or bool(user.get("is_emergency_admin"))


def oidc_transaction(state: str, nonce: str, next_url: str) -> str:
    return jwt.encode({"typ": "oidc_txn", "state": state, "nonce": nonce,
                       "next": next_url, "exp": datetime.now(timezone.utc) + timedelta(minutes=10)},
                      SECRET, algorithm=ALGO)


def decode_oidc_transaction(value: str | None, state: str) -> dict:
    if not value:
        raise HTTPException(400, "SSO 登录状态已失效，请重新登录")
    try:
        payload = jwt.decode(value, SECRET, algorithms=[ALGO])
    except jwt.PyJWTError:
        raise HTTPException(400, "SSO 登录状态无效，请重新登录")
    if payload.get("typ") != "oidc_txn" or not secrets.compare_digest(payload.get("state", ""), state):
        raise HTTPException(400, "SSO state 校验失败，请重新登录")
    return payload


async def oidc_discovery() -> dict:
    issuer = os.environ.get("OIDC_ISSUER", "").rstrip("/")
    url = os.environ.get("OIDC_DISCOVERY_URL", "").strip() or f"{issuer}/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            response.raise_for_status()
        cfg = response.json()
    except Exception as exc:
        raise HTTPException(503, "企业身份服务暂不可用") from exc
    if any(not cfg.get(k) for k in ("authorization_endpoint", "token_endpoint", "jwks_uri")):
        raise HTTPException(503, "企业身份服务的 OIDC 配置不完整")
    return cfg


async def oidc_authorization_url(state: str, nonce: str) -> str:
    cfg = await oidc_discovery()
    args = {"response_type": "code", "client_id": os.environ["OIDC_CLIENT_ID"],
            "redirect_uri": os.environ["OIDC_REDIRECT_URI"],
            "scope": os.environ.get("OIDC_SCOPES", "openid profile email") or "openid",
            "state": state, "nonce": nonce}
    return cfg["authorization_endpoint"] + ("&" if "?" in cfg["authorization_endpoint"] else "?") + urlencode(args)


async def exchange_oidc_code(code: str) -> tuple[dict, dict]:
    cfg = await oidc_discovery()
    form = {"grant_type": "authorization_code", "code": code,
            "redirect_uri": os.environ["OIDC_REDIRECT_URI"], "client_id": os.environ["OIDC_CLIENT_ID"]}
    if secret := os.environ.get("OIDC_CLIENT_SECRET", ""):
        form["client_secret"] = secret
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(cfg["token_endpoint"], data=form)
            response.raise_for_status()
        tokens = response.json()
    except Exception as exc:
        raise HTTPException(401, "企业身份服务未接受登录授权") from exc
    if not tokens.get("id_token"):
        raise HTTPException(401, "企业身份服务未返回 id_token")
    return cfg, tokens


async def verify_oidc_id_token(cfg: dict, id_token: str, nonce: str) -> dict:
    try:
        header = jwt.get_unverified_header(id_token)
        if header.get("alg") in {"none", "HS256", "HS384", "HS512"}:
            raise ValueError("OIDC id_token 必须使用非对称签名")
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(cfg["jwks_uri"])
            response.raise_for_status()
        jwks = jwt.PyJWKSet.from_dict(response.json())
        key = next((k.key for k in jwks.keys if k.key_id == header.get("kid")), None)
        if key is None:
            raise ValueError("未找到匹配的 JWK")
        claims = jwt.decode(id_token, key=key, algorithms=[header["alg"]],
                            audience=os.environ["OIDC_CLIENT_ID"],
                            issuer=os.environ["OIDC_ISSUER"].rstrip("/"))
    except Exception as exc:
        raise HTTPException(401, "企业身份凭证校验失败") from exc
    audiences = claims.get("aud")
    if isinstance(audiences, list) and len(audiences) > 1:
        if not secrets.compare_digest(str(claims.get("azp", "")), os.environ["OIDC_CLIENT_ID"]):
            raise HTTPException(401, "企业身份凭证 azp 校验失败")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise HTTPException(401, "企业身份凭证 nonce 校验失败")
    return claims


def oidc_role_and_org(claims: dict) -> tuple[str, str | None]:
    """IdP 声明只作受控映射输入；任何原始 role claim 都不会直接提权。"""
    try:
        role_map = json.loads(os.environ.get("OIDC_GROUP_ROLE_MAP", "{}"))
        org_map = json.loads(os.environ.get("OIDC_ORG_MAP", "{}"))
    except json.JSONDecodeError as exc:
        raise HTTPException(503, "OIDC 组映射配置不是合法 JSON") from exc
    groups = claims.get(os.environ.get("OIDC_GROUPS_CLAIM", "groups"), [])
    groups = [groups] if isinstance(groups, str) else groups if isinstance(groups, list) else []
    role = "admin" if any(role_map.get(str(g)) == "admin" for g in groups) else "user"
    org_value = claims.get(os.environ.get("OIDC_ORG_CLAIM", "department"), "")
    return role, org_map.get(str(org_value))


# ---- FastAPI 依赖 ----

def _user_from_payload(payload: dict) -> dict:
    """从 JWT 载荷取 user_id，回库查最新用户（确保账号仍有效/未禁用）。"""
    user = catalog.get_user(payload["sub"])
    if not user or user.get("status") != "active":
        raise HTTPException(401, "用户不存在或已禁用")
    return user


async def get_current_user(authorization: str | None = Header(None),
                           ue_session: str | None = Cookie(None)) -> dict:
    """要求登录：必须携带有效 Bearer token，否则 401。"""
    if authorization and authorization.lower().startswith("bearer "):
        return _user_from_payload(decode_token(authorization[7:]))
    if ue_session:
        return _user_from_payload(decode_token(ue_session))
    raise HTTPException(401, "未登录")


async def get_current_user_or_fallback(
        authorization: str | None = Header(None), ue_session: str | None = Cookie(None)) -> dict:
    """【安全加固】原"无 token 回落 X-User-Id"的演示口子已封：
    该口子允许任何人用请求头冒充任意 user_id 越权读/删对话。
    现在与 get_current_user 行为一致——必须携带有效 token。
    保留函数名以免改动全部路由签名。"""
    if authorization and authorization.lower().startswith("bearer "):
        return _user_from_payload(decode_token(authorization[7:]))
    if ue_session:
        return _user_from_payload(decode_token(ue_session))
    raise HTTPException(401, "未登录")


async def get_auth_context(user: dict = Depends(get_current_user)):
    from app.auth_context import from_user
    return from_user(user)


def require_permission(permission: str):
    async def dependency(context=Depends(get_auth_context)):
        if not context.allows(permission):
            raise HTTPException(403, f"缺少权限：{permission}")
        return context
    return dependency


async def get_admin_user(user: dict = None) -> dict:
    """要求 admin 角色。需配合 get_current_user 使用（见 main.py 路由）。"""
    return user


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """要求当前登录用户是 admin，否则 403。用于所有 /api/admin/* 路由。"""
    from app.auth_context import from_user
    if not from_user(user).allows("*"):
        raise HTTPException(403, "需要管理员权限")
    return user
