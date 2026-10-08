"""演示数据与实验连接器的部署边界。"""

from __future__ import annotations

import logging
import os
from pathlib import Path


DEMO_CONNECTOR_IDS = frozenset({"crm", "crm_lab"})
DEMO_DATASET_FILES = frozenset({
    "crm_contracts.csv", "crm_opportunities.csv",
    "netops_alerts.csv", "netops_kpi.csv", "netops_resources.csv",
})
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
log = logging.getLogger("app.demo_isolation")


def is_production() -> bool:
    return os.environ.get("APP_ENV", "").strip().lower() in {"prod", "production"}


def demo_data_enabled() -> bool:
    """开发环境默认展示演示数据；生产环境始终禁止。"""
    if is_production():
        return False
    value = os.environ.get("DEMO_DATA_ENABLED")
    return value is None or value.strip().lower() in _TRUE_VALUES


def ensure_connector_allowed(connector_id: str) -> None:
    if is_production() and connector_id in DEMO_CONNECTOR_IDS:
        raise RuntimeError(f"生产模式禁止加载演示连接器 {connector_id}")


def seed_ontology_demo_if_enabled() -> bool:
    if not demo_data_enabled():
        return False
    from app import ontology

    ontology.seed_demo_if_empty()
    ontology.seed_netops_demo_if_empty()
    ontology.seed_netops_resources_if_empty()
    ontology.seed_crm_demo_if_empty()
    return True


def assert_production_data_isolation() -> None:
    """旧库切换生产模式时拒绝继续使用未审核的演示数据。绝不自动删除。"""
    if not is_production():
        return

    report = inspect_production_assets()
    for item in report["manual_review"]:
        log.warning("生产数据来源需人工确认：%s", item)
    if report["findings"]:
        raise RuntimeError(
            "生产模式发现需人工核对、迁移或隔离的演示资产；未自动删除任何数据："
            + "；".join(report["findings"])
        )


def inspect_production_assets() -> dict[str, list[str]]:
    """汇总已知演示资产与需人工核验的外部数据来源，不修改或删除任何数据。"""
    report: dict[str, list[str]] = {"findings": [], "manual_review": []}
    if not is_production():
        return report

    findings = report["findings"]
    from app.catalog.db import _conn as catalog_conn

    con = catalog_conn()
    assigned = con.execute(
        "SELECT 1 FROM employee_connectors WHERE connector_id IN (?,?) LIMIT 1",
        tuple(sorted(DEMO_CONNECTOR_IDS)),
    ).fetchone()
    con.close()
    if assigned:
        findings.append("检测到演示 CRM 连接器指派；请先在资源中心解除 crm/crm_lab 指派")

    from app import ontology

    con = ontology._conn()
    seeded_entities = con.execute(
        "SELECT 1 FROM entities WHERE tenant_id='default' AND source='seed' "
        "AND deleted_at IS NULL LIMIT 1"
    ).fetchone()
    seeded_relations = con.execute(
        "SELECT 1 FROM relations WHERE tenant_id='default' AND source='seed' "
        "AND deleted_at IS NULL LIMIT 1"
    ).fetchone()
    con.close()
    if seeded_entities or seeded_relations:
        findings.append("检测到 default 租户中尚未审核的 seed 来源本体数据；"
                        "请先核对、迁移或隔离演示实体及关系")

    found = _demo_workspace_files()
    if found:
        findings.append("检测到 workspace 内的演示 CSV；请先核对并移出生产挂载目录："
                        + ", ".join(found))

    if (os.environ.get("RAGFLOW_API_KEY", "").strip()
            and os.environ.get("RAGFLOW_DATASET_IDS", "").strip()):
        report["manual_review"].append(
            "RAGFlow 数据集在外部服务中，应用无法判断其是否含演示数据；请逐项确认数据来源与授权"
        )
    return report


def _demo_workspace_files() -> list[str]:
    from app.paths import WORKSPACE_DATA, WORKSPACE_DATASETS

    return sorted({
        str(path)
        for root in (WORKSPACE_DATA, WORKSPACE_DATASETS)
        if root.exists()
        for name in DEMO_DATASET_FILES
        for path in root.rglob(name)
        if path.is_file()
    })


def assert_production_workspace_isolation() -> None:
    """拒绝将仓库生成的模拟 CSV 共享挂载到生产执行环境。"""
    if not is_production():
        return
    found = _demo_workspace_files()
    if found:
        raise RuntimeError(
            "生产模式检测到 workspace 内的演示 CSV；请先核对并移出生产挂载目录："
            + ", ".join(found)
        )
