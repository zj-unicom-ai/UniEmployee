"""FastAPI 网关：应用生命周期 + 中间件 + 健康检查 + 前端静态文件。

路由按职责拆分到 routes/ 子包：
  routes/auth.py          认证（登录、改密、当前用户）
  routes/conversations.py 对话 CRUD + SSE 消息流 + 追踪 + 审批
  routes/admin.py         管理后台 CRUD
  routes/user.py          用户自助 / 看板 / 调试
"""

import datetime
import os
import time
import uuid
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

import dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import auth, catalog, conversations, ontology, runtime, scheduler, traces
from app import db as dblayer
from app.paths import db_path, DB_FILES, PROJECT_ROOT
from app.logging_setup import setup_logging, request_id_var, get_logger
from app.errors import register_exception_handlers
from app.streaming import recover_conversations
from app.routes import router as app_router

APP_VERSION = os.environ.get("APP_VERSION", "0.20.0")
log = get_logger("app.main")

# 用户被标记 must_change_password 时仍可访问的接口：登录、改密、当前用户信息。
_PASSWORD_CHANGE_ALLOWED = {"/api/auth/login", "/api/auth/change-password", "/api/auth/me"}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@asynccontextmanager
async def lifespan(app):
    dotenv.load_dotenv(PROJECT_ROOT / ".env")
    setup_logging()
    if dblayer.is_pg():
        log.info("启动 UniEmployee v%s | 数据库=PostgreSQL（%s:%s）", APP_VERSION,
                 os.environ.get("POSTGRES_HOST", "127.0.0.1"),
                 os.environ.get("POSTGRES_PORT", "5432"))
    else:
        log.info("启动 UniEmployee v%s | 数据库=SQLite（%s）", APP_VERSION,
                 db_path("catalog.db").parent)
    catalog.init()
    catalog.seed_if_empty()
    catalog.backfill_connectors()
    catalog.backfill_ragflow_knowledge_bases()
    catalog.backfill_employee_kb_assignments()
    catalog.backfill_subagents_if_empty()
    catalog.backfill_ontology_tools()
    catalog.backfill_employees_if_missing()
    catalog.backfill_analyst_sql_tools()
    catalog.backfill_xiaoshu_skills()
    catalog.backfill_netops_upgrade()
    catalog.backfill_sandbox_backend()
    catalog.backfill_ticket_approval()
    catalog.backfill_market_intel_v2()
    # workspace 目录迁移钩子（uploads/<uid> → <uid>/uploads，netops CSV → datasets/）
    # 必须在 sandbox backend 真实启用前完成，否则沙箱内 subPath=<uid> 看不到旧 uploads。
    catalog.backfill_workspace_paths()
    # OpenSandbox 沙箱：建表 + 启动清扫孤儿（enabled 时；不阻塞启动，异常仅日志）
    from app import sandbox_mgr
    sandbox_mgr.init_tables()
    if sandbox_mgr.enabled():
        killed = sandbox_mgr.manager.sweep_orphans()
        log.info("OpenSandbox 已启用，启动清扫孤儿沙箱 %d 个", killed)
    else:
        log.info("OpenSandbox 未启用（SANDBOX_ENABLED 未置 1），沙箱员工回退 LocalShellBackend")
    catalog.seed_admin_if_empty()
    catalog.flag_default_admin_password()
    catalog.seed_assignments_if_empty()
    catalog.seed_default_model_if_empty()
    ontology.init()
    ontology.seed_schema_if_empty()
    ontology.backfill_schema_types()
    ontology.seed_demo_if_empty()
    ontology.seed_netops_demo_if_empty()
    ontology.seed_netops_resources_if_empty()
    ontology.seed_crm_demo_if_empty()
    conversations.ensure_default_channel(
        [e["id"] for e in runtime.discover_employees()]
    )
    # 市场情报员工值守任务模板（默认停用，管理员在自动化任务页开启）
    from app import automations as _automations
    _automations.backfill_seeds()
    # 上次进程意外退出可能留下 status=running 的 Trace；启动时收口为
    # abandoned，避免运维排障时误判为仍在执行。
    stale_runs = traces.finish_stale_running()
    if stale_runs:
        log.warning("已将上次进程遗留的 running Trace 标记为 abandoned：%d 条", stale_runs)
    # checkpointer（对话状态）与 store（长期记忆）按后端选择实现：
    # sqlite  -> AsyncSqliteSaver/AsyncSqliteStore（文件库）
    # postgres -> AsyncPostgresSaver/AsyncPostgresStore（连接由库内部池化管理）
    async with AsyncExitStack() as stack:
        if dblayer.is_pg():
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            from langgraph.store.postgres import AsyncPostgresStore
            log.info("数据库后端：PostgreSQL（DSN 见 POSTGRES_* 环境变量）")
            cp = await stack.enter_async_context(
                AsyncPostgresSaver.from_conn_string(dblayer.pg_dsn("checkpoints")))
            await cp.setup()
            store = await stack.enter_async_context(
                AsyncPostgresStore.from_conn_string(dblayer.pg_dsn("store")))
            await store.setup()
        else:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
            from langgraph.store.sqlite import AsyncSqliteStore
            log.info("数据库后端：SQLite（%s）", db_path("catalog.db").parent)
            cp = await stack.enter_async_context(
                AsyncSqliteSaver.from_conn_string(str(db_path("checkpoints.db"))))
            await cp.setup()  # 全新环境懒建表，先建好避免 recover_conversations 直查失败
            store = await stack.enter_async_context(
                AsyncSqliteStore.from_conn_string(str(db_path("store.db"))))
        runtime.set_checkpointer(cp)
        runtime.set_store(store)
        await runtime.warmup_all()
        await recover_conversations()
        scheduler.start()
        log.info("启动完成，开始接收请求")
        yield
        await scheduler.stop()
        await runtime.shutdown_mcp()
        if dblayer.is_pg():
            dblayer.close_all_pools()
        log.info("服务关闭")


app = FastAPI(lifespan=lifespan)
register_exception_handlers(app)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    rid = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:12]
    token = request_id_var.set(rid)
    start = time.time()
    try:
        # OIDC 登录完成后使用 HTTP-only 会话 cookie。对所有有副作用的 API
        # 强制双提交 CSRF token；Bearer JWT 不会被浏览器自动附带，保持兼容。
        if (request.method not in _SAFE_METHODS and request.url.path.startswith("/api/")
                and request.cookies.get(auth.SESSION_COOKIE)
                and not request.headers.get("Authorization")):
            csrf_cookie = request.cookies.get(auth.CSRF_COOKIE, "")
            csrf_header = request.headers.get("X-CSRF-Token", "")
            if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
                response = JSONResponse(status_code=403, content={"error": "csrf_validation_failed"})
                response.headers["X-Request-Id"] = rid
                return response
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


def _dependency_health() -> tuple[dict, bool]:
    """探测依赖状态；返回结构化结果与 readiness 布尔值。"""
    dbs: dict[str, str] = {}
    for name in DB_FILES:
        try:
            dblayer.ping(name)
            dbs[name] = "ok"
        except Exception as e:
            dbs[name] = f"error: {e}"
    # OpenSandbox 沙箱服务探活（未启用时 disabled，不影响整体状态）
    sandbox_status = "disabled"
    try:
        from app import sandbox_mgr
        if sandbox_mgr.enabled():
            sandbox_status = "ok" if sandbox_mgr.manager.ping() else "error: unreachable"
    except Exception as e:
        sandbox_status = f"error: {type(e).__name__}: {e}"
    all_ok = all(v == "ok" for v in dbs.values()) and not sandbox_status.startswith("error")
    payload = {
        "status": "ok" if all_ok else "degraded",
        "version": APP_VERSION,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "databases": dbs,
        "sandbox": sandbox_status,
    }
    return payload, all_ok


@app.get("/livez")
async def livez():
    """进程存活检查：不探测数据库等外部依赖。"""
    return {
        "status": "ok",
        "version": APP_VERSION,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


@app.get("/readyz")
async def readyz():
    """依赖就绪检查：关键依赖不可用时返回 503。"""
    payload, all_ok = _dependency_health()
    return JSONResponse(status_code=200 if all_ok else 503, content=payload)


@app.get("/health")
async def health():
    """兼容旧监控的结构化健康检查；HTTP 状态始终为 200。"""
    payload, _ = _dependency_health()
    return payload


# 挂载 API 路由
app.include_router(app_router)


# ---- 前端静态文件 ----
_FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
# CI 后端测试与前端构建分属不同 job，测试时 dist/assets 尚未生成；
# 延迟检查目录，生产环境正常构建后仍由同一路径提供静态文件。
app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets"), check_dir=False), name="assets")


@app.get("/")
async def index():
    return FileResponse(_FRONTEND_DIST / "index.html")


@app.get("/report-viewer.html")
async def report_viewer():
    """受控报告壳页面：报告内容由页面脚本放入 sandbox iframe。

    主站 token / cookie 不会自动带到这里——壳页面读 localStorage 中的
    报告 HTML 后注入沙箱 iframe，与主窗口隔离；避免报告 HTML 中潜在
    脚本读取主站会话。
    """
    return FileResponse(_FRONTEND_DIST / "report-viewer.html")


# SPA 回落：Vue Router 管理的路径也返回 index.html
@app.get("/{path:path}")
async def spa_fallback(path: str):
    if path.startswith(("assets/",)):
        return FileResponse(path)
    return FileResponse(_FRONTEND_DIST / "index.html")
