"""认证模块：密码哈希(bcrypt) + JWT 签发/校验 + FastAPI 鉴权依赖。

- 用户表在 catalog.db（users），由 catalog.py 管理。
- JWT 载荷 {sub: user_id, username, role, tenant_id}，过期时间 JWT_EXPIRE_HOURS。
- 依赖：get_current_user（任意登录用户）、get_admin_user（要求 admin 角色）。
- 单租户起步：tenant_id 预留字段，默认 "default"，后续多租户可直接用。
"""
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import dotenv
import jwt
from fastapi import Depends, Header, HTTPException

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


# ---- FastAPI 依赖 ----

def _user_from_payload(payload: dict) -> dict:
    """从 JWT 载荷取 user_id，回库查最新用户（确保账号仍有效/未禁用）。"""
    user = catalog.get_user(payload["sub"])
    if not user or user.get("status") != "active":
        raise HTTPException(401, "用户不存在或已禁用")
    return user


async def get_current_user(authorization: str | None = Header(None)) -> dict:
    """要求登录：必须携带有效 Bearer token，否则 401。"""
    if authorization and authorization.lower().startswith("bearer "):
        return _user_from_payload(decode_token(authorization[7:]))
    raise HTTPException(401, "未登录")


async def get_current_user_or_fallback(
        authorization: str | None = Header(None)) -> dict:
    """【安全加固】原"无 token 回落 X-User-Id"的演示口子已封：
    该口子允许任何人用请求头冒充任意 user_id 越权读/删对话。
    现在与 get_current_user 行为一致——必须携带有效 token。
    保留函数名以免改动全部路由签名。"""
    if authorization and authorization.lower().startswith("bearer "):
        return _user_from_payload(decode_token(authorization[7:]))
    raise HTTPException(401, "未登录")


async def get_admin_user(user: dict = None) -> dict:
    """要求 admin 角色。需配合 get_current_user 使用（见 main.py 路由）。"""
    return user


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """要求当前登录用户是 admin，否则 403。用于所有 /api/admin/* 路由。"""
    if user.get("role") != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user
