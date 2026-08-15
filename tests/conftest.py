"""测试夹具：每个测试用独立的临时数据库，互不污染、不碰真实 catalog.db/conversations.db。"""
import pytest

from app import approvals, catalog, conversations, ontology


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog.db, "DB", tmp_path / "catalog.db")
    monkeypatch.setattr(conversations, "DB", tmp_path / "conversations.db")
    monkeypatch.setattr(approvals, "DB", tmp_path / "approvals.db")
    monkeypatch.setattr(ontology, "DB", tmp_path / "ontology.db")
    catalog.init()  # 建目录库表（conversations._conn 会自动建会话表）
    yield
