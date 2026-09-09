"""OpenSandbox 沙箱管理与路由 backend 单测（fake SDK，不依赖真实 server）。

覆盖：
- 开关关闭时 acquire 报错、build_backends 回退 LocalShellBackend；
- 开启后按会话创建/缓存/续租/重建沙箱，volumes 按用户 subPath 隔离；
- 重启后凭 sandbox_sessions 表重连，重连失败转新建；
- RoutingSandboxBackend 按 thread_id 路由并透传方法参数；
- 沙箱不可用不回退宿主机（抛 RuntimeError）。
"""
import pytest

from app import sandbox_mgr
from app.sandbox_mgr import SandboxManager, RoutingSandboxBackend


# ---- fakes ----

class FakeSandbox:
    """记录 renew/kill 调用的假 SDK 句柄。"""
    def __init__(self, sid: str):
        self.id = sid
        self.renewed = 0
        self.killed = 0

    def renew(self, timeout):
        self.renewed += 1

    def kill(self):
        self.killed += 1


class FakeBackend:
    """假 deepagents backend，记录所有转发调用。"""
    def __init__(self, sandbox):
        self._sandbox = sandbox
        self.calls: list[tuple] = []

    @property
    def id(self):
        return self._sandbox.id

    def execute(self, command, *, timeout=None):
        self.calls.append(("execute", command, timeout))
        return ("exec-result", command, timeout)

    def ls(self, path):
        self.calls.append(("ls", path))
        return ("ls", path)

    def read(self, file_path, offset=0, limit=2000):
        self.calls.append(("read", file_path, offset, limit))
        return ("read", file_path)

    def write(self, file_path, content):
        self.calls.append(("write", file_path, content))
        return ("write", file_path)

    def edit(self, file_path, old_string, new_string, replace_all=False):
        self.calls.append(("edit", file_path, replace_all))
        return ("edit", file_path)

    def delete(self, file_path):
        self.calls.append(("delete", file_path))
        return ("delete", file_path)

    def grep(self, pattern, path=None, glob=None, *, max_count=None):
        self.calls.append(("grep", pattern, path, glob, max_count))
        return ("grep", pattern, max_count)

    def glob(self, pattern, path=None):
        self.calls.append(("glob", pattern, path))
        return ("glob", pattern)

    def upload_files(self, files):
        self.calls.append(("upload", files))
        return [("upload",) * len(files)]

    def download_files(self, paths):
        self.calls.append(("download", paths))
        return [("download",) * len(paths)]


def _patch_manager(monkeypatch, mgr, *, connect_fail=False):
    """给 manager 装上 fake SDK 层，返回 (create_calls, connect_calls)。"""
    create_calls: list[dict] = []
    connect_calls: list[str] = []
    counter = {"n": 0}

    def fake_create(*, uid, thread_id):
        counter["n"] += 1
        create_calls.append({"uid": uid, "thread_id": thread_id})
        return FakeSandbox(f"sb-{counter['n']}")

    def fake_connect(sandbox_id):
        connect_calls.append(sandbox_id)
        if connect_fail:
            raise RuntimeError("sandbox gone")
        sb = FakeSandbox(sandbox_id)
        sb.reconnected = True
        return sb

    def fake_wrap(sandbox):
        return FakeBackend(sandbox)

    monkeypatch.setattr(mgr, "_create", fake_create)
    monkeypatch.setattr(mgr, "_connect", fake_connect)
    monkeypatch.setattr(mgr, "_wrap", fake_wrap)
    return create_calls, connect_calls


@pytest.fixture
def enabled_env(monkeypatch, tmp_path):
    """开启沙箱开关并配好宿主机目录（tmp_path 验证路径透传）。"""
    monkeypatch.setenv("SANDBOX_ENABLED", "1")
    monkeypatch.setenv("SANDBOX_HOST_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("SANDBOX_HOST_DATASETS", str(tmp_path / "datasets"))
    yield


# ---- 开关与配置 ----

def test_acquire_disabled_raises(monkeypatch):
    monkeypatch.delenv("SANDBOX_ENABLED", raising=False)
    mgr = SandboxManager()
    with pytest.raises(RuntimeError, match="未启用"):
        mgr.acquire(thread_id="t1", user_id="u1")


def test_acquire_requires_thread_id(enabled_env):
    mgr = SandboxManager()
    with pytest.raises(RuntimeError, match="thread_id"):
        mgr.acquire(thread_id="", user_id="u1")


def test_enabled_flag(monkeypatch):
    monkeypatch.delenv("SANDBOX_ENABLED", raising=False)
    assert sandbox_mgr.enabled() is False
    monkeypatch.setenv("SANDBOX_ENABLED", "1")
    assert sandbox_mgr.enabled() is True


# ---- 生命周期 ----

def test_acquire_creates_and_caches_per_thread(enabled_env, monkeypatch):
    mgr = SandboxManager()
    create_calls, _ = _patch_manager(monkeypatch, mgr)

    b1 = mgr.acquire(thread_id="t1", user_id="u1")
    b2 = mgr.acquire(thread_id="t1", user_id="u1")
    b3 = mgr.acquire(thread_id="t2", user_id="u2")

    assert b1 is b2                       # 同会话复用
    assert b1 is not b3                   # 不同会话独立沙箱
    assert len(create_calls) == 2
    assert create_calls[0] == {"uid": "u1", "thread_id": "t1"}
    assert create_calls[1] == {"uid": "u2", "thread_id": "t2"}
    # 第二次取用触发续租
    assert b1._sandbox.renewed == 1
    # 映射已落库
    assert sandbox_mgr._load_session("t1") == "sb-1"
    assert sandbox_mgr._load_session("t2") == "sb-2"


def test_user_id_defaults(enabled_env, monkeypatch):
    mgr = SandboxManager()
    create_calls, _ = _patch_manager(monkeypatch, mgr)
    mgr.acquire(thread_id="t1", user_id=None)
    assert create_calls[0]["uid"] == "default"


def test_renew_failure_recreates(enabled_env, monkeypatch):
    mgr = SandboxManager()
    create_calls, _ = _patch_manager(monkeypatch, mgr)

    b1 = mgr.acquire(thread_id="t1", user_id="u1")
    assert b1.id == "sb-1"

    # 沙箱已死：renew 抛错 → 丢弃；重连健康检查也失败 → 新建
    def dead_renew(timeout):
        raise RuntimeError("sandbox expired")
    b1._sandbox.renew = dead_renew

    def dead_connect(sandbox_id):
        raise RuntimeError("sandbox gone")
    mgr._connect = dead_connect

    b2 = mgr.acquire(thread_id="t1", user_id="u1")
    assert b2.id == "sb-2"
    assert len(create_calls) == 2
    assert sandbox_mgr._load_session("t1") == "sb-2"


def test_reconnect_after_restart(enabled_env, monkeypatch):
    # 第一次：创建并落库
    mgr1 = SandboxManager()
    create_calls, _ = _patch_manager(monkeypatch, mgr1)
    mgr1.acquire(thread_id="t1", user_id="u1")
    assert create_calls == [{"uid": "u1", "thread_id": "t1"}]

    # 模拟重启：新 manager 实例，缓存为空，凭库中 sandbox_id 重连
    mgr2 = SandboxManager()
    create_calls2, connect_calls2 = _patch_manager(monkeypatch, mgr2)
    b = mgr2.acquire(thread_id="t1", user_id="u1")
    assert connect_calls2 == ["sb-1"]      # 走重连
    assert create_calls2 == []             # 未新建
    assert b.id == "sb-1"


def test_reconnect_failure_falls_back_to_create(enabled_env, monkeypatch):
    mgr1 = SandboxManager()
    _patch_manager(monkeypatch, mgr1)
    mgr1.acquire(thread_id="t1", user_id="u1")

    mgr2 = SandboxManager()
    create_calls2, connect_calls2 = _patch_manager(monkeypatch, mgr2, connect_fail=True)
    b = mgr2.acquire(thread_id="t1", user_id="u1")
    assert connect_calls2 == ["sb-1"]
    assert len(create_calls2) == 1         # 重连失败 → 新建
    assert b.id == "sb-1" or b.id.startswith("sb-")
    assert sandbox_mgr._load_session("t1") == b.id


def test_kill_thread_clears_cache_and_db(enabled_env, monkeypatch):
    mgr = SandboxManager()
    _, _ = _patch_manager(monkeypatch, mgr)
    b = mgr.acquire(thread_id="t1", user_id="u1")
    assert sandbox_mgr._load_session("t1") == "sb-1"

    mgr.kill_thread("t1")
    assert b._sandbox.killed == 1
    assert sandbox_mgr._load_session("t1") is None
    # 再次 acquire 重新创建
    create_calls, _ = _patch_manager(monkeypatch, mgr)
    mgr.acquire(thread_id="t1", user_id="u1")
    assert len(create_calls) == 1


def test_create_requires_host_data(monkeypatch):
    """未配置 SANDBOX_HOST_DATA 时真实 _create 路径报配置错误（不静默）。"""
    monkeypatch.setenv("SANDBOX_ENABLED", "1")
    monkeypatch.delenv("SANDBOX_HOST_DATA", raising=False)
    mgr = SandboxManager()
    with pytest.raises(RuntimeError, match="SANDBOX_HOST_DATA"):
        mgr._create(uid="u1", thread_id="t1")


# ---- RoutingSandboxBackend ----

def test_routing_backend_dispatches_by_thread(enabled_env, monkeypatch):
    mgr = SandboxManager()
    _patch_manager(monkeypatch, mgr)
    routing = RoutingSandboxBackend(mgr=mgr)

    # 模拟 langgraph 运行时上下文
    monkeypatch.setattr(sandbox_mgr, "_runtime_ids",
                        lambda: ("t1", "u1"))
    assert routing.execute("echo hi", timeout=42) == ("exec-result", "echo hi", 42)
    assert routing.ls("/data") == ("ls", "/data")
    assert routing.read("/f.txt", 10, 100) == ("read", "/f.txt")
    assert routing.write("/f.txt", "x") == ("write", "/f.txt")
    assert routing.edit("/f.txt", "a", "b", True) == ("edit", "/f.txt")
    assert routing.delete("/f.txt") == ("delete", "/f.txt")
    assert routing.grep("TODO", "/p", "*.py", max_count=5) == ("grep", "TODO", 5)
    assert routing.glob("**/*.py") == ("glob", "**/*.py")
    assert routing.upload_files([("/a", b"x")]) == [("upload",)]
    assert routing.download_files(["/a"]) == [("download",)]

    backend = mgr.acquire(thread_id="t1", user_id="u1")
    assert ("execute", "echo hi", 42) in backend.calls
    assert ("grep", "TODO", "/p", "*.py", 5) in backend.calls
    # id 属性委托到沙箱
    assert routing.id == "sb-1"


def test_routing_backend_isolates_threads(enabled_env, monkeypatch):
    mgr = SandboxManager()
    _patch_manager(monkeypatch, mgr)
    routing = RoutingSandboxBackend(mgr=mgr)

    current = {"ids": ("t1", "u1")}
    monkeypatch.setattr(sandbox_mgr, "_runtime_ids", lambda: current["ids"])

    routing.execute("cmd-t1")
    current["ids"] = ("t2", "u2")
    routing.execute("cmd-t2")

    b1 = mgr.acquire(thread_id="t1", user_id="u1")
    b2 = mgr.acquire(thread_id="t2", user_id="u2")
    assert ("execute", "cmd-t1", None) in b1.calls
    assert ("execute", "cmd-t2", None) in b2.calls
    assert ("execute", "cmd-t2", None) not in b1.calls


def test_routing_backend_missing_runtime_raises(monkeypatch):
    """非运行时上下文（取不到 thread_id）明确报错，不允许静默落宿主机。"""
    monkeypatch.delenv("SANDBOX_ENABLED", raising=False)
    routing = RoutingSandboxBackend(mgr=SandboxManager())

    def _no_config():
        raise RuntimeError("no config")
    monkeypatch.setattr(sandbox_mgr, "_runtime_ids", _no_config)
    with pytest.raises(RuntimeError):
        routing.execute("echo hi")


# ---- compiler 集成 ----

def test_build_backends_sandbox_toggle(monkeypatch):
    from app.compiler import build_backends
    from app.spec import EmployeeSpec
    from deepagents.backends import LocalShellBackend

    spec = EmployeeSpec(id="net-ops", name="x", model="m", persona="p",
                        backend="sandbox")

    # 开关关闭 → 回退 LocalShellBackend（测试/开发零行为变化）
    monkeypatch.delenv("SANDBOX_ENABLED", raising=False)
    backend = build_backends(spec, None)
    assert isinstance(backend.default, LocalShellBackend)

    # 开关开启 → RoutingSandboxBackend
    monkeypatch.setenv("SANDBOX_ENABLED", "1")
    backend2 = build_backends(spec, None)
    assert isinstance(backend2.default, RoutingSandboxBackend)


# ---- 孤儿清扫（二期）----

class _FakeInfo:
    """SandboxInfo 的最小替身（只用到 id 字段）。"""
    def __init__(self, sid):
        self.id = sid


class _FakePagedResult:
    """PagedSandboxInfos 的最小替身。"""
    def __init__(self, infos):
        self.sandbox_infos = infos


class _FakeSandboxService:
    """记录 list/kill 调用的假 SandboxesSync 服务。"""
    def __init__(self, pages: list[list[str]], fail_kill: set | None = None):
        self._pages = pages
        self._fail_kill = fail_kill or set()
        self.list_calls = 0
        self.killed: list[str] = []

    def list_sandboxes(self, flt):
        self.list_calls += 1
        idx = self.list_calls - 1
        if idx >= len(self._pages):
            return _FakePagedResult([])
        return _FakePagedResult([_FakeInfo(sid) for sid in self._pages[idx]])

    def kill_sandbox(self, sid):
        if sid in self._fail_kill:
            raise RuntimeError("kill failed")
        self.killed.append(sid)


def test_sweep_orphans_kills_all_and_clears_sessions(enabled_env, monkeypatch):
    mgr = SandboxManager()
    fake_svc = _FakeSandboxService(pages=[["sb-1", "sb-2", "sb-3"]])
    clear_called = {"n": 0}

    def fake_clear():
        clear_called["n"] += 1

    monkeypatch.setattr(sandbox_mgr, "_sandbox_service", lambda: fake_svc)
    monkeypatch.setattr(sandbox_mgr, "_clear_sessions", fake_clear)

    killed = mgr.sweep_orphans()

    assert killed == 3
    assert fake_svc.killed == ["sb-1", "sb-2", "sb-3"]
    assert fake_svc.list_calls == 1   # 第一页 3 条 < 100 直接终止，不查空页
    assert clear_called["n"] == 1


def test_sweep_orphans_paginates_large_set(enabled_env, monkeypatch):
    """孤儿超过一页时翻页清扫。"""
    mgr = SandboxManager()
    page1 = [f"sb-{i:03d}" for i in range(100)]
    page2 = [f"sb-{i:03d}" for i in range(100, 150)]
    fake_svc = _FakeSandboxService(pages=[page1, page2])

    monkeypatch.setattr(sandbox_mgr, "_sandbox_service", lambda: fake_svc)
    monkeypatch.setattr(sandbox_mgr, "_clear_sessions", lambda: None)

    killed = mgr.sweep_orphans()
    assert killed == 150
    assert fake_svc.list_calls == 2   # 100（满页续查）+ 50（不足一页终止）
    assert len(fake_svc.killed) == 150


def test_sweep_orphans_disabled_returns_zero(monkeypatch):
    monkeypatch.delenv("SANDBOX_ENABLED", raising=False)
    mgr = SandboxManager()
    assert mgr.sweep_orphans() == 0


def test_sweep_orphans_swallows_failure(enabled_env, monkeypatch):
    """list_sandboxes 抛错时不阻断启动，返回 0。"""
    mgr = SandboxManager()

    class BoomSvc:
        def list_sandboxes(self, flt):
            raise RuntimeError("server offline")
        def kill_sandbox(self, sid):
            raise AssertionError("不应被调到")

    monkeypatch.setattr(sandbox_mgr, "_sandbox_service", lambda: BoomSvc())
    monkeypatch.setattr(sandbox_mgr, "_clear_sessions", lambda: None)

    assert mgr.sweep_orphans() == 0   # 异常被吞，返回 0


def test_sweep_orphans_partial_kill_failure(enabled_env, monkeypatch):
    """部分 kill 失败不阻塞其余清扫。"""
    mgr = SandboxManager()
    fake_svc = _FakeSandboxService(
        pages=[["sb-1", "sb-2", "sb-3"]],
        fail_kill={"sb-2"},
    )
    monkeypatch.setattr(sandbox_mgr, "_sandbox_service", lambda: fake_svc)
    monkeypatch.setattr(sandbox_mgr, "_clear_sessions", lambda: None)

    killed = mgr.sweep_orphans()
    assert killed == 2                # sb-2 失败不算
    assert "sb-2" not in fake_svc.killed
    assert set(fake_svc.killed) == {"sb-1", "sb-3"}


# ---- 并发上限（二期）----

def test_concurrency_cap_default_20(monkeypatch):
    monkeypatch.setenv("SANDBOX_ENABLED", "1")
    monkeypatch.delenv("SANDBOX_MAX_CONCURRENT", raising=False)
    mgr = SandboxManager()
    assert mgr.max_concurrent == 20


def test_concurrency_cap_env_override(monkeypatch):
    monkeypatch.setenv("SANDBOX_ENABLED", "1")
    monkeypatch.setenv("SANDBOX_MAX_CONCURRENT", "5")
    mgr = SandboxManager()
    assert mgr.max_concurrent == 5


def test_concurrency_cap_blocks_new_create(enabled_env, monkeypatch):
    """达上限后新建抛错，不溢出。"""
    monkeypatch.setenv("SANDBOX_MAX_CONCURRENT", "2")
    mgr = SandboxManager()
    _patch_manager(monkeypatch, mgr)

    mgr.acquire(thread_id="t1", user_id="u1")
    mgr.acquire(thread_id="t2", user_id="u2")
    with pytest.raises(RuntimeError, match="并发上限"):
        mgr.acquire(thread_id="t3", user_id="u3")


def test_concurrency_cap_cache_hit_does_not_count(enabled_env, monkeypatch):
    """cache 命中（renew 成功）不占新槽位，上限=1 时同会话多次取用不触发上限。"""
    monkeypatch.setenv("SANDBOX_MAX_CONCURRENT", "1")
    mgr = SandboxManager()
    _patch_manager(monkeypatch, mgr)

    b1 = mgr.acquire(thread_id="t1", user_id="u1")
    b2 = mgr.acquire(thread_id="t1", user_id="u1")
    assert b1 is b2                   # 同会话复用，未新建
    # 另一会话才触发上限
    with pytest.raises(RuntimeError, match="并发上限"):
        mgr.acquire(thread_id="t2", user_id="u2")


def test_concurrency_cap_freed_after_kill(enabled_env, monkeypatch):
    """kill_thread 释放槽位后可新建。"""
    monkeypatch.setenv("SANDBOX_MAX_CONCURRENT", "1")
    mgr = SandboxManager()
    _patch_manager(monkeypatch, mgr)

    mgr.acquire(thread_id="t1", user_id="u1")
    mgr.kill_thread("t1")             # 释放槽位
    # 新会话可建（槽位已释放）
    b = mgr.acquire(thread_id="t2", user_id="u2")
    assert b.id.startswith("sb-")
