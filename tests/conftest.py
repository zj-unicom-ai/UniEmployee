"""测试夹具：每个测试用独立的临时数据库，互不污染、不碰真实 catalog.db/conversations.db。"""
import os

# 测试一律跑 sqlite 后端：即使 .env 配了 DB_BACKEND=postgres，
# 也在 import app 之前强制回 sqlite（app.db 惰性读环境变量）。
os.environ["DB_BACKEND"] = "sqlite"

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
