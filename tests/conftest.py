"""测试夹具：每个测试用独立的临时数据库，互不污染、不碰真实 catalog.db/conversations.db。"""
import os

import pytest
from test_support.pg_database_safety import validate_pg_test_environment


_PG_INTEGRATION = os.environ.get("UE_RUN_POSTGRES_INTEGRATION") == "1"
if _PG_INTEGRATION:
    # The PG suite is opt-in and confined to a disposable local/CI service plus
    # databases that carry an unmistakable test-only prefix. Validate before
    # importing app modules, whose DB backend is selected from the environment.
    try:
        validate_pg_test_environment(os.environ)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
else:
    # 普通测试一律使用临时 SQLite：即使 .env 配了 PostgreSQL，也绝不连真实库。
    os.environ["DB_BACKEND"] = "sqlite"

from app import approvals, catalog, conversations, ontology


def pytest_collection_finish(session):
    """拒绝在启用 PG 模式时误跑任何 SQLite/外部服务测试。"""
    if not _PG_INTEGRATION:
        return
    unexpected = [item.nodeid for item in session.items
                  if not item.nodeid.startswith("tests/pg_integration/")]
    if unexpected:
        raise pytest.UsageError(
            "PostgreSQL 集成模式只允许收集 tests/pg_integration/；"
            f"发现其他测试，例如：{unexpected[0]}"
        )


@pytest.fixture
def golden_eval_cases():
    """读取经业务 owner 授权的 JSONL；未提供数据时明确跳过，不造业务答案。"""
    path = os.environ.get("UE_GOLDEN_EVAL_PATH", "").strip()
    if not path:
        pytest.skip("未提供业务负责人授权的 UE_GOLDEN_EVAL_PATH")
    from test_support.golden_eval import GoldenEvalFormatError, load_golden_eval_cases
    try:
        return load_golden_eval_cases(path)
    except GoldenEvalFormatError as exc:
        pytest.fail(str(exc), pytrace=False)


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    if _PG_INTEGRATION:
        yield
        return
    monkeypatch.setattr(catalog.db, "DB", tmp_path / "catalog.db")
    monkeypatch.setattr(conversations, "DB", tmp_path / "conversations.db")
    monkeypatch.setattr(approvals, "DB", tmp_path / "approvals.db")
    monkeypatch.setattr(ontology, "DB", tmp_path / "ontology.db")
    catalog.init()  # 建目录库表（conversations._conn 会自动建会话表）
    yield
