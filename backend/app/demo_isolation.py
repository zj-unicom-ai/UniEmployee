"""演示数据与实验连接器的部署边界。"""

from __future__ import annotations

import os


DEMO_CONNECTOR_IDS = frozenset({"crm", "crm_lab"})
DEMO_DATASET_FILES = frozenset({
    "crm_contracts.csv", "crm_opportunities.csv",
    "netops_alerts.csv", "netops_kpi.csv", "netops_resources.csv",
})
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


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

    from app.catalog.db import _conn as catalog_conn

    con = catalog_conn()
    assigned = con.execute(
        "SELECT 1 FROM employee_connectors WHERE connector_id IN (?,?) LIMIT 1",
        tuple(sorted(DEMO_CONNECTOR_IDS)),
    ).fetchone()
    con.close()
    if assigned:
        raise RuntimeError(
            "生产模式检测到演示 CRM 连接器指派；请先在资源中心解除 crm/crm_lab 指派"
        )

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
        raise RuntimeError(
            "生产模式检测到 default 租户中尚未审核的 seed 来源本体数据；"
            "请先核对、迁移或隔离演示实体及关系，再启用生产模式"
        )

    assert_production_workspace_isolation()


def assert_production_workspace_isolation() -> None:
    """拒绝将仓库生成的模拟 CSV 共享挂载到生产执行环境。"""
    if not is_production():
        return
    from app.paths import WORKSPACE_DATA, WORKSPACE_DATASETS

    found = sorted(
        str(root / name)
        for root in (WORKSPACE_DATA, WORKSPACE_DATASETS)
        for name in DEMO_DATASET_FILES
        if (root / name).is_file()
    )
    if found:
        raise RuntimeError(
            "生产模式检测到 workspace 内的演示 CSV；请先核对并移出生产挂载目录："
            + ", ".join(found)
        )
