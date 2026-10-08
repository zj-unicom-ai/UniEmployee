"""Fail-closed target validation for the opt-in PostgreSQL test suite."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping


def validate_pg_test_environment(environ: Mapping[str, str]) -> None:
    """Permit only a disposable, prefixed database on localhost or CI service."""
    if environ.get("DB_BACKEND", "").strip().lower() != "postgres":
        raise ValueError("PostgreSQL 集成测试必须显式设置 DB_BACKEND=postgres")
    if not environ.get("POSTGRES_DB_PREFIX", "").startswith("codex_test_"):
        raise ValueError("PostgreSQL 集成测试只允许 POSTGRES_DB_PREFIX=codex_test_*")

    host = environ.get("POSTGRES_HOST", "").strip().lower()
    if host not in {"localhost", "127.0.0.1", "::1", "postgres"}:
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            raise ValueError("PostgreSQL 集成测试只允许本机或 CI postgres 服务地址")
    if environ.get("POSTGRES_PORT", "5432") != "5432":
        raise ValueError("PostgreSQL 集成测试端口必须为 5432")
    if not environ.get("POSTGRES_USER", "").strip() or not environ.get("POSTGRES_PASSWORD", ""):
        raise ValueError("PostgreSQL 集成测试必须提供专用连接凭据")
