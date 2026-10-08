"""Fail-closed checks for environment configuration before startup side effects."""

from __future__ import annotations

import logging
import os
from pathlib import Path


log = logging.getLogger("app.startup_preflight")
_SECRET_PLACEHOLDERS = ("change-me", "replace-me", "your-secret", "your-key")
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_DEFAULT_DB_PASSWORDS = frozenset({"", "change-me", "change-me-in-prod", "uniemployee_dev",
                                  "postgres", "password", "admin123"})


def _jwt_secret_problem(value: str) -> bool:
    normalized = value.strip().lower()
    return (len(value.encode("utf-8")) < 32
            or any(marker in normalized for marker in _SECRET_PLACEHOLDERS))


def _has_ragflow_dataset_allowlist() -> bool:
    return any(part.strip() for part in os.environ.get("RAGFLOW_DATASET_IDS", "").split(","))


def _log_file_problem(value: str) -> bool:
    path = Path(value)
    if path.exists():
        return not path.is_file() or not os.access(path, os.W_OK)
    return not path.parent.is_dir() or not os.access(path.parent, os.W_OK | os.X_OK)


def _production_findings() -> list[str]:
    findings: list[str] = []
    if _jwt_secret_problem(os.environ.get("JWT_SECRET", "")):
        findings.append("JWT_SECRET 未配置或仍是弱默认值")

    backend = os.environ.get("DB_BACKEND", "sqlite").strip().lower()
    if backend != "postgres":
        findings.append("生产环境必须使用 PostgreSQL（DB_BACKEND=postgres）")
    else:
        password = os.environ.get("POSTGRES_PASSWORD", "").strip()
        if (password.lower() in _DEFAULT_DB_PASSWORDS or len(password.encode("utf-8")) < 16
                or any(marker in password.lower() for marker in _SECRET_PLACEHOLDERS)):
            findings.append("POSTGRES_PASSWORD 为空、过短或仍是默认值")

    if os.environ.get("AUTH_COOKIE_SECURE", "").strip().lower() not in _TRUE_VALUES:
        findings.append("生产会话 Cookie 必须启用 AUTH_COOKIE_SECURE=1（HTTPS）")

    sandbox_enabled = os.environ.get("SANDBOX_ENABLED", "").strip().lower() in _TRUE_VALUES
    if not sandbox_enabled:
        findings.append("SANDBOX_ENABLED=1 是生产环境要求，避免回退到宿主机执行")
    elif not os.environ.get("SANDBOX_API_KEY", "").strip():
        findings.append("生产 OpenSandbox 必须配置 SANDBOX_API_KEY")

    oidc_keys = ("OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_REDIRECT_URI")
    configured_oidc = [key for key in oidc_keys if os.environ.get(key, "").strip()]
    if configured_oidc and len(configured_oidc) != len(oidc_keys):
        findings.append("OIDC_ISSUER、OIDC_CLIENT_ID、OIDC_REDIRECT_URI 必须成组配置")

    if os.environ.get("RAGFLOW_API_KEY", "").strip() and not _has_ragflow_dataset_allowlist():
        findings.append("配置了 RAGFLOW_API_KEY 时必须显式设置 RAGFLOW_DATASET_IDS 白名单")

    log_file = os.environ.get("LOG_FILE", "").strip()
    if log_file and _log_file_problem(log_file):
        findings.append("LOG_FILE 目标或父目录不存在可写位置")
    return findings


def _development_warnings() -> list[str]:
    warnings = []
    if _jwt_secret_problem(os.environ.get("JWT_SECRET", "")):
        warnings.append("JWT_SECRET 未配置或仍是弱默认值；请设置至少 32 字节随机密钥")

    if os.environ.get("DB_BACKEND", "sqlite").strip().lower() == "postgres":
        password = os.environ.get("POSTGRES_PASSWORD", "").strip()
        if (password.lower() in _DEFAULT_DB_PASSWORDS or len(password.encode("utf-8")) < 16
                or any(marker in password.lower() for marker in _SECRET_PLACEHOLDERS)):
            warnings.append("POSTGRES_PASSWORD 为空、过短或仍是默认值")

    log_file = os.environ.get("LOG_FILE", "").strip()
    if log_file and _log_file_problem(log_file):
        warnings.append("LOG_FILE 目标或父目录不可写；文件日志可能无法启动")

    oidc_keys = ("OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_REDIRECT_URI")
    configured_oidc = [key for key in oidc_keys if os.environ.get(key, "").strip()]
    if configured_oidc and len(configured_oidc) != len(oidc_keys):
        warnings.append("OIDC_ISSUER、OIDC_CLIENT_ID、OIDC_REDIRECT_URI 配置不完整")

    if os.environ.get("RAGFLOW_API_KEY", "").strip() and not _has_ragflow_dataset_allowlist():
        warnings.append("RAGFLOW_DATASET_IDS 未设置，RAGFlow 将查询该密钥可见的全部数据集")
    return warnings


def _writable_directory(path: Path) -> bool:
    candidate = Path(path)
    if candidate.exists() and not candidate.is_dir():
        return False
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK)


def run_startup_preflight() -> None:
    """校验可在数据库初始化前确认的基础配置；日志不输出任何凭据值。"""
    if os.environ.get("APP_ENV", "").strip().lower() in {"prod", "production"}:
        findings = _production_findings()
        from app.paths import WORKSPACE_DATA

        if not _writable_directory(WORKSPACE_DATA):
            findings.append("WORKSPACE_DATA 不存在可写目录或当前进程无写入权限")
        log.warning("生产运维检查需人工确认：外部 HTTPS 反向代理配置、备份调度及恢复演练")
        if not os.environ.get("OIDC_ISSUER", "").strip():
            log.warning("生产环境未配置企业 OIDC；请确认本地账号登录符合组织策略")
        if findings:
            raise RuntimeError("生产启动安全预检失败：" + "；".join(findings))
        return

    for warning in _development_warnings():
        log.warning("开发环境安全预检：%s", warning)


def assert_production_webhook_credentials() -> None:
    """启用中的生产 Webhook 必须已配置至少 32 字节密钥。"""
    if os.environ.get("APP_ENV", "").strip().lower() not in {"prod", "production"}:
        return

    from app import automations

    with automations._conn() as con:
        rows = con.execute(
            "SELECT id, secret FROM automations WHERE enabled=1 AND trigger_type='event' ORDER BY id"
        ).fetchall()
    weak_ids = [row["id"] for row in rows
                if len((row["secret"] or "").encode("utf-8")) < 32]
    if weak_ids:
        raise RuntimeError(
            f"生产启动安全预检失败：{len(weak_ids)} 个启用的 Webhook 自动化未配置至少 32 字节密钥；"
            "请在自动化管理页轮换密钥后重启"
        )
