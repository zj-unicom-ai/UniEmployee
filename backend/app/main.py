"""FastAPI 网关：应用生命周期 + 中间件 + 健康检查 + 前端静态文件。

路由按职责拆分到 routes/ 子包：
  routes/auth.py          认证（登录、改密、当前用户）
  routes/conversations.py 对话 CRUD + SSE 消息流 + 追踪 + 审批
  routes/admin.py         管理后台 CRUD
  routes/user.py          用户自助 / 看板 / 调试
"""

import datetime
import os
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import auth, catalog, conversations, ontology, runtime
from app.paths import db_path, DB_FILES, PROJECT_ROOT
from app.logging_setup import setup_logging, request_id_var, get_logger
from app.errors import register_exception_handlers
from app.streaming import recover_conversations
from app.routes import router as app_router
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite import AsyncSqliteStore

APP_VERSION = os.environ.get("APP_VERSION", "0.3.0")
log = get_logger("app.main")

# 用户被标记 must_change_password 时仍可访问的接口：登录、改密、当前用户信息。
_PASSWORD_CHANGE_ALLOWED = {"/api/auth/login", "/api/auth/change-password", "/api/auth/me"}


@asynccontextmanager
async def lifespan(app):
    dotenv.load_dotenv(PROJECT_ROOT / ".env")
    setup_logging()
    log.info("启动 myagents v%s | 数据目录=%s", APP_VERSION, db_path("catalog.db").parent)
    catalog.init()
    catalog.seed_if_empty()
    catalog.backfill_connectors()
    catalog.backfill_ragflow_knowledge_bases()
    catalog.backfill_employee_kb_assignments()
    catalog.backfill_subagents_if_empty()
    catalog.backfill_ontology_tools()
    catalog.seed_admin_if_empty()
    catalog.flag_default_admin_password()
    catalog.seed_assignments_if_empty()
    ontology.init()
    ontology.seed_schema_if_empty()
    ontology.seed_demo_if_empty()
    conversations.ensure_default_channel(
        [e["id"] for e in runtime.discover_employees()]
    )
    async with AsyncSqliteSaver.from_conn_string(str(db_path("checkpoints.db"))) as cp:
        runtime.set_checkpointer(cp)
        async with AsyncSqliteStore.from_conn_string(str(db_path("store.db"))) as store:
            runtime.set_store(store)
            await runtime.warmup_all()
            await recover_conversations()
            log.info("启动完成，开始接收请求")
            yield
            await runtime.shutdown_mcp()
            log.info("服务关闭")


app = FastAPI(lifespan=lifespan)
register_exception_handlers(app)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    rid = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:12]
    token = request_id_var.set(rid)
    start = time.time()
    try:
        if request.url.path.startswith("/api/") and request.url.path not in _PASSWORD_CHANGE_ALLOWED:
            try:
                current = await auth.get_current_user(request.headers.get("Authorization"))
            except HTTPException:
                current = None
            if current and current.get("must_change_password"):
                response = JSONResponse(
                    status_code=403,
                    content={"error": "must_change_password",
                             "message": "请先修改默认密码后再使用系统"},
                )
                response.headers["X-Request-Id"] = rid
                return response
        response = await call_next(request)
    except Exception:
        raise
    finally:
        request_id_var.reset(token)
    dur_ms = (time.time() - start) * 1000
    rl = get_logger("app.request")
    rl.info("%s %s -> %d (%.1fms)", request.method, request.url.path,
            response.status_code, dur_ms)
    response.headers["X-Request-Id"] = rid
    return response


@app.get("/health")
async def health():
    """健康检查（无需登录）：供容器探针 / 监控使用。"""
    import sqlite3
    dbs: dict[str, str] = {}
    for name in DB_FILES:
        try:
            con = sqlite3.connect(str(db_path(name)))
            con.execute("SELECT 1")
            con.close()
            dbs[name] = "ok"
        except Exception as e:
            dbs[name] = f"error: {e}"
    all_ok = all(v == "ok" for v in dbs.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "version": APP_VERSION,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "databases": dbs,
    }


# 挂载 API 路由
app.include_router(app_router)


# ---- 前端静态文件 ----
_FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="assets")


@app.get("/")
async def index():
    return FileResponse(_FRONTEND_DIST / "index.html")


# SPA 回落：Vue Router 管理的路径也返回 index.html
@app.get("/{path:path}")
async def spa_fallback(path: str):
    if path.startswith(("assets/",)):
        return FileResponse(path)
    return FileResponse(_FRONTEND_DIST / "index.html")
