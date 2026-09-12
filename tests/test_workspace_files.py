"""工作区产物文件服务测试：下载端点路径安全与用户隔离、流内文件探测。

覆盖：路径归一（相对//data//workspace/data 前缀）、穿越与越界拒绝、
<uid>/ 隔离目录权限、_WorkspaceFileWatcher 快照-对比探测。
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import auth, catalog, streaming
import app.paths as app_paths
from app.routes.workspace import router as workspace_router


def _client(monkeypatch, role="admin", uid="u_admin"):
    app = FastAPI()
    app.include_router(workspace_router)
    app.dependency_overrides[auth.get_current_user_or_fallback] = lambda: {
        "id": uid, "username": "tester", "role": role}
    return TestClient(app)


def _make_file(root: Path, rel: str, content: str = "产物内容") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ---------- 下载端点 ----------

def test_download_roundtrip_and_path_forms(monkeypatch, tmp_path):
    monkeypatch.setattr(app_paths, "WORKSPACE_DATA", tmp_path)
    _make_file(tmp_path, "解决方案_测试.docx.txt", "hello 产物")
    client = _client(monkeypatch)

    for form in ("解决方案_测试.docx.txt", "/data/解决方案_测试.docx.txt",
                 "workspace/data/解决方案_测试.docx.txt", str(tmp_path / "解决方案_测试.docx.txt")):
        r = client.get("/api/workspace/file", params={"path": form})
        assert r.status_code == 200, f"形态 {form} 应可下载"
        assert r.text == "hello 产物"


def test_traversal_and_outside_root_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(app_paths, "WORKSPACE_DATA", tmp_path)
    client = _client(monkeypatch)

    for evil in ("../../.env", "../db/catalog.db", "/etc/hosts",
                 str(tmp_path.parent / "elsewhere.txt")):
        r = client.get("/api/workspace/file", params={"path": evil})
        assert r.status_code in (403, 404), f"{evil} 应被拒绝， got {r.status_code}"

    # 越界写到根外再确认即使存在也拿不到
    outside = tmp_path.parent / "outside_secret.txt"
    outside.write_text("x", encoding="utf-8")
    r = client.get("/api/workspace/file", params={"path": str(outside)})
    assert r.status_code == 403
    outside.unlink()


def test_user_isolation_on_uid_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(app_paths, "WORKSPACE_DATA", tmp_path)
    catalog.db.init()
    catalog.create_user("u_other", "x", role="user", user_id="u_other")
    _make_file(tmp_path, "u_other/私有产物.docx", "private")
    _make_file(tmp_path, "共享产物.md", "shared")

    # 他人 uid 目录：普通用户拒绝、本人放行、管理员放行
    r = _client(monkeypatch, role="user", uid="u_me").get(
        "/api/workspace/file", params={"path": "u_other/私有产物.docx"})
    assert r.status_code == 403
    r = _client(monkeypatch, role="user", uid="u_other").get(
        "/api/workspace/file", params={"path": "u_other/私有产物.docx"})
    assert r.status_code == 200
    r = _client(monkeypatch, role="admin", uid="u_admin").get(
        "/api/workspace/file", params={"path": "u_other/私有产物.docx"})
    assert r.status_code == 200
    # 根级共享产物：普通用户可读（本地模式 execute cwd=项目根，产物常落根目录）
    r = _client(monkeypatch, role="user", uid="u_me").get(
        "/api/workspace/file", params={"path": "共享产物.md"})
    assert r.status_code == 200


def test_missing_file_404(monkeypatch, tmp_path):
    monkeypatch.setattr(app_paths, "WORKSPACE_DATA", tmp_path)
    r = _client(monkeypatch).get("/api/workspace/file", params={"path": "不存在.docx"})
    assert r.status_code == 404


# ---------- 流内文件探测 ----------

def test_workspace_file_watcher_diff(monkeypatch, tmp_path):
    monkeypatch.setattr(streaming, "WORKSPACE_DATA", tmp_path)
    w = streaming._WorkspaceFileWatcher()

    assert w.diff() == []  # 初始无产物

    _make_file(tmp_path, "汇报.md", "# hi")
    _make_file(tmp_path, "uploads/c123/x.csv", "uploads 内不计")
    _make_file(tmp_path, ".hidden.tmp", "隐藏文件不计")
    got = w.diff()
    names = [f["name"] for f in got]
    assert names == ["汇报.md"]
    info = got[0]
    assert info["path"] == "汇报.md" and info["size"] == len("# hi".encode())

    # 无新变更不重复推送；同回合内同一文件重复触碰也不重复推送
    assert w.diff() == []
    _make_file(tmp_path, "汇报.md", "# updated")
    assert w.diff() == []


# ---------- 会话产物落库与历史恢复 ----------

def test_conversation_files_persist_and_dedupe():
    from app import conversations
    conversations.create("c_files_demo", "xiaoxiao", title="t", preview="p",
                         count=1, user_id="u_admin")
    conversations.add_file("c_files_demo", "方案.docx", "方案.docx", 100, turn_no=3)
    conversations.add_file("c_files_demo", "方案.docx", "方案.docx", 100, turn_no=3)  # 幂等去重
    conversations.add_file("c_files_demo", "纪要.md", "纪要.md", 50, turn_no=5)

    files = conversations.list_files("c_files_demo")
    assert len(files) == 2  # UNIQUE(conv_id, path) 去重
    assert {f["name"] for f in files} == {"方案.docx", "纪要.md"}
    assert files[0]["name"] == "纪要.md"  # 按登记时间倒序
    by_name = {f["name"]: f for f in files}
    assert by_name["方案.docx"]["turn_no"] == 3
    assert by_name["纪要.md"]["turn_no"] == 5
