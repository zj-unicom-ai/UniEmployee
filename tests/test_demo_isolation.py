"""生产模式下的演示数据与实验连接器隔离。"""

import pytest

from app import catalog, demo_isolation, ontology


def test_fresh_production_database_has_no_demo_data_or_connectors(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEMO_DATA_ENABLED", "1")
    from app import paths
    monkeypatch.setattr(paths, "WORKSPACE_DATA", tmp_path / "data")
    monkeypatch.setattr(paths, "WORKSPACE_DATASETS", tmp_path / "datasets")

    catalog.seed_if_empty()
    catalog.backfill_connectors()
    ontology.init()
    ontology.seed_schema_if_empty()
    assert demo_isolation.seed_ontology_demo_if_enabled() is False
    demo_isolation.assert_production_data_isolation()

    con = catalog.db._conn()
    connector_ids = {row["id"] for row in con.execute("SELECT id FROM connectors").fetchall()}
    con.close()
    assert connector_ids.isdisjoint(demo_isolation.DEMO_CONNECTOR_IDS)
    assert not set(catalog.get_employee_config("xiaoxiao")["connectors"]) & demo_isolation.DEMO_CONNECTOR_IDS
    assert ontology.list_entities("default") == []


def test_existing_demo_database_cannot_silently_switch_to_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    catalog.seed_if_empty()
    catalog.backfill_connectors()
    ontology.init()
    assert demo_isolation.seed_ontology_demo_if_enabled() is True

    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError, match="演示 CRM 连接器指派"):
        demo_isolation.assert_production_data_isolation()

    con = catalog.db._conn()
    con.execute("DELETE FROM employee_connectors WHERE connector_id IN ('crm','crm_lab')")
    con.commit()
    con.close()
    with pytest.raises(RuntimeError, match="seed 来源本体数据"):
        demo_isolation.assert_production_data_isolation()


def test_production_rejects_demo_connector_runtime_and_dev_can_opt_out(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    for connector_id in demo_isolation.DEMO_CONNECTOR_IDS:
        with pytest.raises(RuntimeError, match="生产模式禁止加载演示连接器"):
            demo_isolation.ensure_connector_allowed(connector_id)

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_DATA_ENABLED", "0")
    assert demo_isolation.demo_data_enabled() is False
    demo_isolation.ensure_connector_allowed("crm_lab")


def test_production_rejects_generated_demo_csv(monkeypatch, tmp_path):
    from app import paths

    datasets = tmp_path / "datasets"
    datasets.mkdir()
    (datasets / "crm_contracts.csv").write_text("synthetic", encoding="utf-8")
    monkeypatch.setattr(paths, "WORKSPACE_DATA", tmp_path / "data")
    monkeypatch.setattr(paths, "WORKSPACE_DATASETS", datasets)
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError, match="演示 CSV"):
        demo_isolation.assert_production_workspace_isolation()

    monkeypatch.setenv("APP_ENV", "development")
    demo_isolation.assert_production_workspace_isolation()
