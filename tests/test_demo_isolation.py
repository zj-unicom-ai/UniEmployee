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
    assert (datasets / "crm_contracts.csv").is_file()

    monkeypatch.setenv("APP_ENV", "development")
    demo_isolation.assert_production_workspace_isolation()


def test_production_asset_report_aggregates_sources_without_deleting(monkeypatch, tmp_path):
    from app import paths

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("RAGFLOW_API_KEY", "")
    monkeypatch.setenv("RAGFLOW_DATASET_IDS", "")
    data = tmp_path / "data"
    datasets = tmp_path / "datasets"
    data.mkdir()
    datasets.mkdir()
    demo_csv = datasets / "crm_contracts.csv"
    demo_csv.write_text("synthetic", encoding="utf-8")
    nested_demo_csv = data / "user-1" / "uploads" / "netops_kpi.csv"
    nested_demo_csv.parent.mkdir(parents=True)
    nested_demo_csv.write_text("synthetic", encoding="utf-8")
    monkeypatch.setattr(paths, "WORKSPACE_DATA", data)
    monkeypatch.setattr(paths, "WORKSPACE_DATASETS", datasets)

    catalog.seed_if_empty()
    catalog.backfill_connectors()
    ontology.init()
    demo_isolation.seed_ontology_demo_if_enabled()

    monkeypatch.setenv("APP_ENV", "production")
    report = demo_isolation.inspect_production_assets()

    assert any("crm" in finding for finding in report["findings"])
    assert any("本体" in finding for finding in report["findings"])
    assert any(str(demo_csv) in finding for finding in report["findings"])
    assert any(str(nested_demo_csv) in finding for finding in report["findings"])
    entity_count_before = len(ontology.list_entities("default"))
    with pytest.raises(RuntimeError, match="未自动删除"):
        demo_isolation.assert_production_data_isolation()
    assert len(ontology.list_entities("default")) == entity_count_before
    assert demo_csv.is_file() and nested_demo_csv.is_file()


def test_ragflow_dataset_sources_are_reported_for_manual_review(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("RAGFLOW_API_KEY", "do-not-log-this-key")
    monkeypatch.setenv("RAGFLOW_DATASET_IDS", "dataset-1,dataset-2")
    ontology.init()

    report = demo_isolation.inspect_production_assets()

    assert any("RAGFlow" in item for item in report["manual_review"])
    assert "do-not-log-this-key" not in str(report)
