"""环境护栏必须先于 PostgreSQL 测试连接阻止非测试目标。"""

import pytest

from test_support.pg_database_safety import validate_pg_test_environment


_SAFE_ENV = {
    "DB_BACKEND": "postgres",
    "POSTGRES_DB_PREFIX": "codex_test_",
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_PORT": "5432",
    "POSTGRES_USER": "postgres",
    "POSTGRES_PASSWORD": "ci-only-password",
}


@pytest.mark.parametrize("overrides", [
    {"DB_BACKEND": "sqlite"},
    {"POSTGRES_DB_PREFIX": ""},
    {"POSTGRES_DB_PREFIX": "production_"},
    {"POSTGRES_HOST": "db.company.example"},
    {"POSTGRES_PORT": "5433"},
    {"POSTGRES_PASSWORD": ""},
])
def test_pg_test_environment_rejects_non_isolated_targets(overrides):
    with pytest.raises(ValueError):
        validate_pg_test_environment({**_SAFE_ENV, **overrides})


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "postgres"])
def test_pg_test_environment_allows_local_or_ci_service_hosts(host):
    validate_pg_test_environment({**_SAFE_ENV, "POSTGRES_HOST": host})
