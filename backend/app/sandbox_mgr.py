"""OpenSandbox 沙箱执行环境（基础设施层）。

架构（详见 .trae/documents/opensandbox_integration_plan.md）：

- SandboxManager：按**会话**（langgraph thread_id）管理沙箱生命周期。
  内存缓存 + catalog 库 sandbox_sessions 表持久化 thread→sandbox_id 映射
  （服务重启后可 connect 重连），每次取用 best-effort renew 续租 TTL。
- RoutingSandboxBackend：deepagents SandboxBackendProtocol 实现。agent 按
  (员工, 用户) 编译并缓存，backend 实例编译期固定；本代理在每次工具调用时
  从 langgraph config 取 thread_id/user_id，路由到该会话专属的
  OpenSandboxBackend（ls/read_file/write_file/execute 等全部落沙箱容器）。

启用方式：环境变量 SANDBOX_ENABLED=1。未启用时 compiler.build_backends
回退 LocalShellBackend，本模块不发起任何网络请求（opensandbox 包全部延迟
导入）。沙箱创建/连接失败时 acquire 抛 RuntimeError（中文明确提示），
**不回退宿主机执行**——回退等于安全机制失效。

server 侧部署依赖（非本仓库代码）：
- OpenSandbox server config.toml 的 [storage] allowed_host_paths 放行
  SANDBOX_HOST_DATA / SANDBOX_HOST_DATASETS 两个宿主机目录前缀；
- 沙箱镜像需预装 pandas/duckdb/matplotlib/openpyxl/python-docx。
"""
import os
import threading
import time
import urllib.request
from datetime import timedelta

from deepagents.backends.protocol import SandboxBackendProtocol

# ---- 环境变量配置 ----

# 宿主机 workspace/data 的绝对路径（沙箱 server 通过 docker.sock 起容器，
# hostPath 解析在 **docker 宿主机**上，不是 app 容器内路径）。
# 宿主机 workspace/datasets 的绝对路径（共享数据集，只读挂载到 /datasets）。


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def enabled() -> bool:
    """沙箱开关。SANDBOX_ENABLED=1/true/yes 开启。"""
    return _env("SANDBOX_ENABLED", "").lower() in ("1", "true", "yes")


# ---- 持久化表（挂 catalog 库，随 catalog.init 幂等建表）----

def init_tables(con=None):
    """sandbox_sessions：thread_id → sandbox_id 映射。

    服务重启后凭此重连仍存活的沙箱；沙箱 TTL 过期被 server 回收后，
    重连失败即删除映射并新建。
    """
    own = con is None
    if own:
        from .catalog.db import _conn
        con = _conn()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS sandbox_sessions(
      thread_id TEXT PRIMARY KEY,
      sandbox_id TEXT NOT NULL,
      user_id TEXT,
      created_at TEXT,
      updated_at TEXT);
    """)
    con.commit()
    if own:
        con.close()


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _load_session(thread_id: str) -> str | None:
    from .catalog.db import _conn
    con = _conn()
    try:
        row = con.execute(
            "SELECT sandbox_id FROM sandbox_sessions WHERE thread_id=?",
            (thread_id,)).fetchone()
        return row["sandbox_id"] if row else None
    finally:
        con.close()


def _save_session(thread_id: str, sandbox_id: str, user_id: str) -> None:
    from .catalog.db import _conn
    con = _conn()
    try:
        con.execute(
            "INSERT INTO sandbox_sessions(thread_id,sandbox_id,user_id,created_at,updated_at) "
            "VALUES(?,?,?,?,?) "
            "ON CONFLICT(thread_id) DO UPDATE SET sandbox_id=excluded.sandbox_id, "
            "user_id=excluded.user_id, updated_at=excluded.updated_at",
            (thread_id, sandbox_id, user_id, _now(), _now()))
        con.commit()
    finally:
        con.close()


def _drop_session(thread_id: str) -> None:
    from .catalog.db import _conn
    con = _conn()
    try:
        con.execute("DELETE FROM sandbox_sessions WHERE thread_id=?", (thread_id,))
        con.commit()
    finally:
        con.close()


def _connection_config():
    """构造 OpenSandbox 连接配置（延迟导入 opensandbox）。"""
    from opensandbox.config.connection_sync import ConnectionConfigSync
    return ConnectionConfigSync(
        domain=_env("SANDBOX_DOMAIN", "localhost:8090"),
        protocol=_env("SANDBOX_PROTOCOL", "http"),
        api_key=_env("SANDBOX_API_KEY") or None,
    )


class _Entry:
    """一个会话对应的沙箱句柄缓存。"""

    def __init__(self, backend, sandbox):
        self.backend = backend   # OpenSandboxBackend（deepagents backend）
        self.sandbox = sandbox   # SandboxSync（SDK 句柄）


class SandboxManager:
    """按会话获取/复用/回收沙箱（单例，线程安全）。"""

    def __init__(self):
        self._cache: dict[str, _Entry] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # -- 配置（读环境变量，可被测试 monkeypatch）--

    @property
    def ttl_minutes(self) -> int:
        return int(_env("SANDBOX_TTL_MINUTES", "30") or "30")

    @property
    def cmd_timeout(self) -> int:
        """沙箱内单条命令默认超时（秒），传给 OpenSandboxBackend。"""
        return int(_env("SANDBOX_CMD_TIMEOUT", "1800") or "1800")

    @property
    def image(self) -> str:
        return _env("SANDBOX_IMAGE", "uniemployee/sandbox:py312-data")

    # -- 对外接口 --

    def acquire(self, *, thread_id: str, user_id: str | None):
        """获取会话专属沙箱 backend（OpenSandboxBackend）。

        命中缓存 → renew 续租；沙箱已死（TTL 过期/被回收）→ 丢弃重建。
        未命中 → 先按库中 sandbox_id 尝试 connect 重连，失败再 create。
        任何创建/连接失败抛 RuntimeError，不回退宿主机。
        """
        if not enabled():
            raise RuntimeError(
                "沙箱执行环境未启用（SANDBOX_ENABLED 未置 1），无法执行沙箱操作。"
                "请联系管理员启用 OpenSandbox 集成。")
        if not thread_id:
            raise RuntimeError("沙箱后端只能在会话运行时调用：运行时上下文缺少 thread_id。")
        uid = user_id or "default"

        entry = self._cache.get(thread_id)
        if entry is not None:
            try:
                self._renew(entry.sandbox)
                return entry.backend
            except Exception as e:
                # 沙箱已死（TTL 过期/server 重启被回收）→ 丢弃走重建
                print(f"[sandbox] 会话 {thread_id} 沙箱续租失败，丢弃重建："
                      f"{type(e).__name__}: {e}")
                self._discard(thread_id)

        with self._lock_for(thread_id):
            # 双检：等锁期间可能已被其他线程创建
            entry = self._cache.get(thread_id)
            if entry is not None:
                return entry.backend

            sandbox = None
            sid = _load_session(thread_id)
            if sid:
                try:
                    sandbox = self._connect(sid)
                except Exception as e:
                    print(f"[sandbox] 会话 {thread_id} 重连沙箱 {sid} 失败，将新建："
                          f"{type(e).__name__}: {e}")
                    _drop_session(thread_id)
            if sandbox is None:
                sandbox = self._create(uid=uid, thread_id=thread_id)
                _save_session(thread_id, sandbox.id, uid)
                print(f"[sandbox] 会话 {thread_id} 新建沙箱 {sandbox.id}（uid={uid}）")
            else:
                print(f"[sandbox] 会话 {thread_id} 重连沙箱 {sandbox.id} 成功")

            backend = self._wrap(sandbox)
            self._cache[thread_id] = _Entry(backend, sandbox)
            return backend

    def kill_thread(self, thread_id: str) -> None:
        """best-effort 销毁会话沙箱（会话删除/管理钩子用；TTL 兜底也会自动回收）。"""
        entry = self._cache.pop(thread_id, None)
        if entry is not None:
            try:
                self._kill(entry.sandbox)
            except Exception as e:
                print(f"[sandbox] kill {thread_id} 失败（忽略，TTL 兜底）："
                      f"{type(e).__name__}: {e}")
        _drop_session(thread_id)

    def ping(self) -> bool:
        """探活 OpenSandbox server（短超时，供 /health）。未启用返回 False。"""
        if not enabled():
            return False
        url = f"{_env('SANDBOX_PROTOCOL', 'http')}://{_env('SANDBOX_DOMAIN', 'localhost:8090')}/health"
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                return 200 <= resp.status < 300
        except Exception:
            return False

    # -- SDK 薄封装（测试可 monkeypatch）--

    def _create(self, *, uid: str, thread_id: str):
        """新建沙箱：/data 按用户 subPath 读写挂载，/datasets 只读挂载。"""
        from opensandbox import SandboxSync
        from opensandbox.models.sandboxes import Host, Volume

        host_data = _env("SANDBOX_HOST_DATA")
        if not host_data:
            raise RuntimeError(
                "沙箱已启用但未配置 SANDBOX_HOST_DATA"
                "（docker 宿主机上 workspace/data 目录的绝对路径）。")
        volumes = [
            Volume(
                name="data",
                host=Host(path=host_data),
                mount_path="/data",
                read_only=False,
                # subPath 限定沙箱只能看到本用户目录（多租户隔离）
                sub_path=uid,
            ),
        ]
        host_datasets = _env("SANDBOX_HOST_DATASETS")
        if host_datasets:
            volumes.append(Volume(
                name="datasets",
                host=Host(path=host_datasets),
                mount_path="/datasets",
                read_only=True,
            ))
        return SandboxSync.create(
            self.image,
            timeout=timedelta(minutes=self.ttl_minutes),
            ready_timeout=timedelta(seconds=60),
            volumes=volumes,
            resource={"cpu": _env("SANDBOX_CPU", "1"),
                      "memory": _env("SANDBOX_MEMORY", "2Gi")},
            metadata={"app": "uniemployee", "thread": thread_id, "uid": uid},
            connection_config=_connection_config(),
        )

    def _connect(self, sandbox_id: str):
        """按 sandbox_id 重连已存在的沙箱（带健康检查，失败抛异常）。"""
        from opensandbox import SandboxSync
        return SandboxSync.connect(
            sandbox_id,
            connection_config=_connection_config(),
            connect_timeout=timedelta(seconds=10),
        )

    def _wrap(self, sandbox):
        """把 SDK 句箱包装为 deepagents backend。"""
        from langchain_opensandbox import OpenSandboxBackend
        return OpenSandboxBackend(sandbox=sandbox, timeout=self.cmd_timeout)

    def _renew(self, sandbox) -> None:
        sandbox.renew(timedelta(minutes=self.ttl_minutes))

    def _kill(self, sandbox) -> None:
        sandbox.kill()

    # -- 内部 --

    def _lock_for(self, thread_id: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.get(thread_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[thread_id] = lock
            return lock

    def _discard(self, thread_id: str) -> None:
        """丢弃失效缓存条目（不 kill，沙箱交给 TTL 回收）。"""
        self._cache.pop(thread_id, None)


# 进程级单例
manager = SandboxManager()


def _runtime_ids() -> tuple[str, str | None]:
    """从 langgraph 运行时 config 取 (thread_id, user_id)。

    deepagents 经 asyncio.to_thread 调用 backend 同步方法，contextvars 会
    复制到工作线程，故同步方法内 get_config() 可取到会话上下文。
    """
    try:
        from langgraph.config import get_config
        cfg = get_config() or {}
    except Exception as e:
        raise RuntimeError(
            f"沙箱后端只能在会话运行时调用（无法获取运行时上下文）：{e}")
    conf = cfg.get("configurable") or {}
    thread_id = conf.get("thread_id")
    if not thread_id:
        raise RuntimeError("沙箱后端只能在会话运行时调用：config 缺少 thread_id。")
    return thread_id, conf.get("user_id")


class RoutingSandboxBackend(SandboxBackendProtocol):
    """按会话路由的 deepagents backend（编译期固定一个实例，运行时分发）。

    每次方法调用解析当前会话的沙箱 backend 并委托；沙箱不存在时由
    SandboxManager.acquire 惰性创建。方法集合与转发签名严格对齐
    SandboxBackendProtocol（execute 必须带 timeout 关键字——deepagents
    用 execute_accepts_timeout 内省；grep 带 max_count）。
    """

    def __init__(self, mgr: SandboxManager | None = None):
        self._mgr = mgr or manager

    def _backend(self):
        thread_id, user_id = _runtime_ids()
        return self._mgr.acquire(thread_id=thread_id, user_id=user_id)

    @property
    def id(self) -> str:
        try:
            return self._backend().id
        except Exception:
            return "routing-sandbox"

    def execute(self, command: str, *, timeout: int | None = None):
        return self._backend().execute(command, timeout=timeout)

    def ls(self, path: str):
        return self._backend().ls(path)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000):
        return self._backend().read(file_path, offset, limit)

    def write(self, file_path: str, content: str):
        return self._backend().write(file_path, content)

    def edit(self, file_path: str, old_string: str, new_string: str,
             replace_all: bool = False):
        return self._backend().edit(file_path, old_string, new_string, replace_all)

    def delete(self, file_path: str):
        return self._backend().delete(file_path)

    def grep(self, pattern: str, path: str | None = None, glob: str | None = None,
             *, max_count: int | None = None):
        return self._backend().grep(pattern, path, glob, max_count=max_count)

    def glob(self, pattern: str, path: str | None = None):
        return self._backend().glob(pattern, path)

    def upload_files(self, files: list[tuple[str, bytes]]):
        return self._backend().upload_files(files)

    def download_files(self, paths: list[str]):
        return self._backend().download_files(paths)
