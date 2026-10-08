"""应用启动时的生产安全门禁。"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import main


def _set_secure_production_environment(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", "random-test-jwt-secret-that-is-at-least-32-bytes")
    monkeypatch.setenv("DB_BACKEND", "postgres")
    monkeypatch.setenv("POSTGRES_PASSWORD", "A-strong-test-db-password-321")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "1")
    monkeypatch.setenv("SANDBOX_ENABLED", "1")
    monkeypatch.setenv("SANDBOX_DOMAIN", "sandbox.internal:8090")
    monkeypatch.setenv("SANDBOX_API_KEY", "a-test-sandbox-key")
    monkeypatch.setenv("RAGFLOW_API_KEY", "")
    monkeypatch.setenv("RAGFLOW_DATASET_IDS", "")
    monkeypatch.setenv("OIDC_ISSUER", "")
    monkeypatch.setenv("OIDC_CLIENT_ID", "")
    monkeypatch.setenv("OIDC_REDIRECT_URI", "")
    monkeypatch.setenv("LOG_FILE", "")


def _stop_at_catalog_init(monkeypatch):
    def stop():
        raise RuntimeError("catalog initialization reached")

    monkeypatch.setattr(main.catalog, "init", stop)


def test_weak_production_jwt_secret_fails_before_database_initialization(monkeypatch):
    _set_secure_production_environment(monkeypatch)
    monkeypatch.setenv("JWT_SECRET", "change-me-to-a-long-random-secret")

    initialized = []

    def mark_database_initialization():
        initialized.append(True)
        raise RuntimeError("catalog initialization reached")

    monkeypatch.setattr(main.catalog, "init", mark_database_initialization)

    async def start():
        with pytest.raises(RuntimeError, match="JWT_SECRET") as exc_info:
            async with main.lifespan(main.app):
                pass
        return exc_info.value

    error = asyncio.run(start())

    assert "change-me-to-a-long-random-secret" not in str(error)
    assert initialized == []


@pytest.mark.parametrize(("key", "value", "expected"), [
    ("DB_BACKEND", "sqlite", "DB_BACKEND"),
    ("POSTGRES_PASSWORD", "change-me", "POSTGRES_PASSWORD"),
    ("AUTH_COOKIE_SECURE", "0", "AUTH_COOKIE_SECURE"),
    ("SANDBOX_ENABLED", "0", "SANDBOX_ENABLED"),
    ("SANDBOX_API_KEY", "", "SANDBOX_API_KEY"),
    ("RAGFLOW_API_KEY", "configured-test-key", "RAGFLOW_DATASET_IDS"),
])
def test_unsafe_production_configuration_fails_before_database_initialization(
        monkeypatch, key, value, expected):
    _set_secure_production_environment(monkeypatch)
    monkeypatch.setenv(key, value)
    _stop_at_catalog_init(monkeypatch)

    async def start():
        with pytest.raises(RuntimeError, match=expected) as exc_info:
            async with main.lifespan(main.app):
                pass
        return exc_info.value

    error = asyncio.run(start())

    assert not value or value not in str(error)


def test_ragflow_allowlist_must_contain_at_least_one_dataset_id(monkeypatch):
    _set_secure_production_environment(monkeypatch)
    monkeypatch.setenv("RAGFLOW_API_KEY", "configured-test-key")
    monkeypatch.setenv("RAGFLOW_DATASET_IDS", " , , ")
    _stop_at_catalog_init(monkeypatch)

    async def start():
        with pytest.raises(RuntimeError, match="RAGFLOW_DATASET_IDS"):
            async with main.lifespan(main.app):
                pass

    asyncio.run(start())


def test_secure_production_configuration_passes_preflight(monkeypatch, caplog):
    _set_secure_production_environment(monkeypatch)
    _stop_at_catalog_init(monkeypatch)

    async def start():
        with pytest.raises(RuntimeError, match="catalog initialization reached"):
            async with main.lifespan(main.app):
                pass

    asyncio.run(start())
    assert "备份调度及恢复演练" in caplog.text
    assert "HTTPS 反向代理" in caplog.text


def test_production_unwritable_workspace_fails_before_database_initialization(
        monkeypatch, tmp_path):
    from app import paths, startup_preflight

    _set_secure_production_environment(monkeypatch)
    workspace = tmp_path / "workspace-data"
    workspace.mkdir()
    monkeypatch.setattr(paths, "WORKSPACE_DATA", workspace)
    _stop_at_catalog_init(monkeypatch)
    real_access = os.access

    def access(path, mode):
        if Path(path) == workspace:
            return False
        return real_access(path, mode)

    monkeypatch.setattr(startup_preflight.os, "access", access)

    async def start():
        with pytest.raises(RuntimeError, match="WORKSPACE_DATA"):
            async with main.lifespan(main.app):
                pass

    asyncio.run(start())


def test_production_unwritable_log_target_fails_before_logging_setup(monkeypatch, tmp_path):
    from app import startup_preflight

    _set_secure_production_environment(monkeypatch)
    log_dir = tmp_path / "readonly-logs"
    log_dir.mkdir()
    monkeypatch.setenv("LOG_FILE", str(log_dir / "application.log"))
    _stop_at_catalog_init(monkeypatch)
    real_access = os.access

    def access(path, mode):
        if Path(path) == log_dir:
            return False
        return real_access(path, mode)

    monkeypatch.setattr(startup_preflight.os, "access", access)

    async def start():
        with pytest.raises(RuntimeError, match="LOG_FILE"):
            async with main.lifespan(main.app):
                pass

    asyncio.run(start())


def test_production_missing_log_parent_fails_before_logging_setup(monkeypatch, tmp_path):
    _set_secure_production_environment(monkeypatch)
    monkeypatch.setenv("LOG_FILE", str(tmp_path / "missing" / "application.log"))
    _stop_at_catalog_init(monkeypatch)

    async def start():
        with pytest.raises(RuntimeError, match="LOG_FILE"):
            async with main.lifespan(main.app):
                pass

    asyncio.run(start())


def test_development_weak_jwt_secret_warns_without_logging_secret(monkeypatch, caplog):
    secret = "private-development-secret"
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("JWT_SECRET", secret)

    def stop_after_preflight():
        raise RuntimeError("catalog initialization reached")

    monkeypatch.setattr(main.catalog, "init", stop_after_preflight)

    async def start():
        with pytest.raises(RuntimeError, match="catalog initialization reached"):
            async with main.lifespan(main.app):
                pass

    asyncio.run(start())

    assert "JWT_SECRET" in caplog.text
    assert secret not in caplog.text


def test_dotenv_is_loaded_before_data_paths_are_resolved(tmp_path):
    expected = tmp_path / "data-from-env"
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "backend")
    env["UE_TEST_DATA_DIR"] = str(expected)
    env.pop("APP_DATA_DIR", None)
    script = (
        "import os, dotenv\n"
        "dotenv.load_dotenv = lambda path: os.environ.setdefault("
        "'APP_DATA_DIR', os.environ['UE_TEST_DATA_DIR'])\n"
        "from app import paths\n"
        "print(paths.DATA_DIR)\n"
    )

    result = subprocess.run([sys.executable, "-c", script], env=env,
                            capture_output=True, text=True, check=True)

    assert result.stdout.strip() == str(expected.resolve())


def test_existing_production_assets_are_audited_before_seeding(monkeypatch):
    _set_secure_production_environment(monkeypatch)
    events = []

    def record(name):
        def call(*args, **kwargs):
            events.append(name)
        return call

    monkeypatch.setattr(main.catalog, "init", record("catalog.init"))
    catalog_seed_steps = (
        "seed_if_empty", "backfill_connectors", "backfill_ragflow_knowledge_bases",
        "backfill_employee_kb_assignments", "backfill_subagents_if_empty",
        "backfill_ontology_tools", "backfill_employees_if_missing",
        "backfill_analyst_sql_tools", "backfill_xiaoshu_skills",
        "backfill_netops_upgrade", "backfill_sandbox_backend",
        "backfill_ticket_approval", "backfill_market_intel_v2",
        "backfill_workspace_paths", "seed_admin_if_empty",
        "flag_default_admin_password", "seed_assignments_if_empty",
        "seed_default_model_if_empty",
    )
    for name in catalog_seed_steps:
        monkeypatch.setattr(main.catalog, name, record(name))
    monkeypatch.setattr(main.ontology, "init", record("ontology.init"))
    monkeypatch.setattr(main.ontology, "seed_schema_if_empty", record("ontology.seed_schema"))
    monkeypatch.setattr(main.ontology, "backfill_schema_types", record("ontology.backfill"))
    monkeypatch.setattr(main.demo_isolation, "seed_ontology_demo_if_enabled",
                        record("ontology.seed_demo"))

    def stop_after_asset_audit():
        events.append("asset_audit")
        raise RuntimeError("asset audit reached")

    monkeypatch.setattr(main.demo_isolation, "assert_production_data_isolation",
                        stop_after_asset_audit)
    from app import sandbox_mgr
    monkeypatch.setattr(sandbox_mgr, "init_tables", record("sandbox.init"))
    monkeypatch.setattr(sandbox_mgr, "enabled", lambda: True)
    monkeypatch.setattr(sandbox_mgr.manager, "sweep_orphans", lambda: 0)

    async def start():
        with pytest.raises(RuntimeError, match="asset audit reached"):
            async with main.lifespan(main.app):
                pass

    asyncio.run(start())

    assert events.index("catalog.init") < events.index("asset_audit")
    assert events.index("ontology.init") < events.index("asset_audit")
    assert not any(name in events and events.index(name) < events.index("asset_audit")
                   for name in catalog_seed_steps)
    assert "ontology.seed_schema" not in events[:events.index("asset_audit")]


def test_production_rejects_enabled_webhook_without_strong_secret_before_seeding(
        monkeypatch, tmp_path):
    from app import automations, paths

    _set_secure_production_environment(monkeypatch)
    # 环境声明仍为 PostgreSQL 以覆盖生产预检；应用数据库访问留在 tmp_db SQLite。
    monkeypatch.setattr(main.dblayer, "_backend", lambda: "sqlite")
    monkeypatch.setattr(paths, "WORKSPACE_DATA", tmp_path / "workspace")
    monkeypatch.setattr(paths, "WORKSPACE_DATASETS", tmp_path / "datasets")
    automations.create(
        name="weak webhook", trigger_type="event", event_key="test.event",
        employee_id="net-ops", prompt="test", secret="short", enabled=True,
    )

    def stop_if_seeded(*args, **kwargs):
        raise RuntimeError("catalog seed reached")

    monkeypatch.setattr(main.catalog, "seed_if_empty", stop_if_seeded)

    async def start():
        with pytest.raises(RuntimeError, match="Webhook") as exc_info:
            async with main.lifespan(main.app):
                pass
        return exc_info.value

    error = asyncio.run(start())

    assert "short" not in str(error)
    assert "test.event" not in str(error)


def test_production_webhook_secret_length_is_measured_in_utf8_bytes(monkeypatch, tmp_path):
    from app import automations, paths

    _set_secure_production_environment(monkeypatch)
    monkeypatch.setattr(main.dblayer, "_backend", lambda: "sqlite")
    monkeypatch.setattr(paths, "WORKSPACE_DATA", tmp_path / "workspace")
    monkeypatch.setattr(paths, "WORKSPACE_DATASETS", tmp_path / "datasets")
    automations.create(
        name="unicode webhook", trigger_type="event", event_key="test.unicode",
        employee_id="net-ops", prompt="test", secret="密" * 16, enabled=True,
    )

    def stop_after_preflight(*args, **kwargs):
        raise RuntimeError("catalog seed reached")

    monkeypatch.setattr(main.catalog, "seed_if_empty", stop_after_preflight)

    async def start():
        with pytest.raises(RuntimeError, match="catalog seed reached"):
            async with main.lifespan(main.app):
                pass

    asyncio.run(start())
