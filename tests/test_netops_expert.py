"""net-ops「算网运营专家」四能力架构回归测试。

覆盖：数据生成脚本产出与故事线、yaml 升级（local_shell + 4 技能）、
技能触发条件提取、SOP 种子与老库 backfill（persona 同步/保留双路径）、
本体算网资源实体幂等播种。
"""
import csv
import importlib.util
from pathlib import Path

from app import catalog, ontology
from app.compiler import _extract_skill_triggers
from app.spec import load_spec

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NETOPS_YAML = PROJECT_ROOT / "backend" / "employees" / "net-ops.yaml"
SCRIPT = PROJECT_ROOT / "scripts" / "generate_netops_data.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_netops_data", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------- 数据生成脚本 ----------

def test_generator_outputs_three_datasets(tmp_path, monkeypatch):
    gen = _load_generator()
    monkeypatch.setattr(gen, "OUTPUT_DIR", tmp_path)
    gen.gen_alerts()
    gen.gen_kpi()
    gen.gen_resources()

    alerts = _rows(tmp_path / "netops_alerts.csv")
    kpi = _rows(tmp_path / "netops_kpi.csv")
    resources = _rows(tmp_path / "netops_resources.csv")

    assert len(alerts) > 300
    assert set(alerts[0].keys()) == {
        "alert_id", "time", "station", "station_code", "alarm_type",
        "severity", "status", "duration_min", "root_cause", "handler"}
    assert {a["severity"] for a in alerts} == {"P1", "P2", "P3", "P4"}
    assert len(kpi) == 181 * 3  # 180 天 + 截止日 × 3 片区
    assert set(kpi[0].keys()) == {
        "date", "station_group", "connection_rate", "drop_rate",
        "avg_latency_ms", "alert_count", "ticket_count", "sla_met_rate",
        "satisfaction"}
    assert len(resources) == 12
    assert {r["category"] for r in resources} == {"机房", "算力节点", "传输链路", "带宽"}


def test_generator_storylines_consistent(tmp_path, monkeypatch):
    """三条故事线：高新区近 7 天频发 P2、城东 8 月上旬 P1 大障、资源有高水位。"""
    gen = _load_generator()
    monkeypatch.setattr(gen, "OUTPUT_DIR", tmp_path)
    gen.gen_alerts()
    gen.gen_resources()

    alerts = _rows(tmp_path / "netops_alerts.csv")
    gx = [a for a in alerts if a["station"] == "高新区1号基站"
          and a["time"] >= "2026-08-24" and a["severity"] in ("P1", "P2")]
    assert len(gx) >= 7

    p1 = [a for a in alerts if a["station"] == "城东1号基站" and a["severity"] == "P1"]
    assert {a["time"][:10] for a in p1} == {"2026-08-08", "2026-08-09", "2026-08-10"}

    resources = _rows(tmp_path / "netops_resources.csv")
    high = [r for r in resources if float(r["utilization_pct"]) >= 80]
    assert {"GPU训练节点01", "高新-下沙光缆"} <= {r["name"] for r in high}


# ---------- yaml 与技能 ----------

def test_netops_yaml_upgraded():
    spec = load_spec(str(NETOPS_YAML))
    assert spec.backend == "local_shell"
    assert spec.role == "算网运营专家"
    assert spec.skills == ["fault-impact-analysis", "ops-metrics-analysis",
                           "resource-capacity-analysis", "sop-execution"]
    assert "kb_search" in spec.tools and "create_ticket" in spec.tools
    # persona 引用三个数据集与能力路由
    for kw in ("netops_alerts.csv", "netops_kpi.csv", "netops_resources.csv",
               "能力路由", "算网运营专家"):
        assert kw in spec.persona


def test_netops_skills_have_triggers():
    for skill in ("fault-impact-analysis", "ops-metrics-analysis",
                  "resource-capacity-analysis", "sop-execution"):
        md = (PROJECT_ROOT / "backend" / "skills" / skill / "SKILL.md").read_text("utf-8")
        triggers = _extract_skill_triggers(md)
        assert triggers, f"{skill} 缺少触发条件（确定性路由依赖它）"
    assert "告警" in _extract_skill_triggers(
        (PROJECT_ROOT / "backend" / "skills" / "ops-metrics-analysis" / "SKILL.md")
        .read_text("utf-8")) or "指标" in _extract_skill_triggers(
        (PROJECT_ROOT / "backend" / "skills" / "ops-metrics-analysis" / "SKILL.md")
        .read_text("utf-8"))


# ---------- SOP 种子与老库升级 ----------

def test_seed_if_empty_seeds_netops_sops_and_bindings():
    catalog.seed_if_empty()
    con = catalog._conn()
    cur = con.cursor()
    sops = {r["id"] for r in cur.execute("SELECT id FROM sops")}
    assert {"sop_netops_emergency", "sop_netops_cutover",
            "sop_netops_escalation"} <= sops
    skills = {r["skill_id"] for r in cur.execute(
        "SELECT skill_id FROM employee_skills WHERE employee_id='net-ops'")}
    assert {"ops-metrics-analysis", "resource-capacity-analysis",
            "sop-execution"} <= skills
    bound = {r["sop_id"] for r in cur.execute(
        "SELECT sop_id FROM employee_sops WHERE employee_id='net-ops'")}
    assert bound == {"sop_netops_emergency", "sop_netops_cutover",
                     "sop_netops_escalation"}
    con.close()


def test_backfill_upgrades_untouched_persona():
    """老库：persona 还是旧版 → 自动同步为新版，并补齐技能/SOP 绑定。"""
    catalog.create_employee({
        "id": "net-ops", "name": "小网", "role": "网络运营专家",
        "model": "dummy-model",
        "persona": "你是小网，星联通信的网络运营专家，负责基站运维、装维调度与客户网络保障。\n"
                   "语气干练，结论先行，处置建议可执行。",
        "skills": ["fault-impact-analysis"], "tools": ["kb_search"]})
    catalog.backfill_netops_upgrade()

    con = catalog._conn()
    cur = con.cursor()
    row = cur.execute(
        "SELECT role, persona FROM employees WHERE id='net-ops'").fetchone()
    assert row["role"] == "算网运营专家"
    assert "围绕四项核心能力开展工作" in row["persona"]
    skills = {r["skill_id"] for r in cur.execute(
        "SELECT skill_id FROM employee_skills WHERE employee_id='net-ops'")}
    assert "sop-execution" in skills
    sops = {r["sop_id"] for r in cur.execute(
        "SELECT sop_id FROM employee_sops WHERE employee_id='net-ops'")}
    assert "sop_netops_emergency" in sops
    con.close()


def test_backfill_preserves_modified_persona():
    """老库：persona 被管理员改过 → 保留，但绑定仍补齐。"""
    custom = "自定义的网络运维助手人设，管理员手写内容。"
    catalog.create_employee({
        "id": "net-ops", "name": "小网", "role": "网络运营专家",
        "model": "dummy-model", "persona": custom,
        "skills": [], "tools": []})
    catalog.backfill_netops_upgrade()

    con = catalog._conn()
    cur = con.cursor()
    row = cur.execute("SELECT persona FROM employees WHERE id='net-ops'").fetchone()
    assert row["persona"] == custom
    skills = {r["skill_id"] for r in cur.execute(
        "SELECT skill_id FROM employee_skills WHERE employee_id='net-ops'")}
    assert "ops-metrics-analysis" in skills
    con.close()


def test_backfill_idempotent():
    catalog.create_employee({
        "id": "net-ops", "name": "小网", "role": "网络运营专家",
        "model": "dummy-model",
        "persona": "你是小网，星联通信的网络运营专家，负责基站运维、装维调度与客户网络保障。",
        "skills": [], "tools": []})
    catalog.backfill_netops_upgrade()
    catalog.backfill_netops_upgrade()

    con = catalog._conn()
    cur = con.cursor()
    n = cur.execute(
        "SELECT COUNT(*) c FROM employee_sops WHERE employee_id='net-ops'"
    ).fetchone()["c"]
    assert n == 3
    n = cur.execute(
        "SELECT COUNT(*) c FROM sops WHERE id LIKE 'sop_netops%'"
    ).fetchone()["c"]
    assert n == 3
    con.close()


# ---------- 本体算网资源 ----------

def test_ontology_resources_seed_and_backhaul_chain():
    ontology.init()
    ontology.seed_schema_if_empty()
    ontology.seed_netops_demo_if_empty()
    ontology.seed_netops_resources_if_empty()
    # 幂等：再跑一次不重复
    ontology.seed_netops_resources_if_empty()

    dcs = ontology.find_entities("default", entity_type="datacenter")
    assert len(dcs) == 2
    nodes = ontology.find_entities("default", entity_type="compute_node")
    assert len(nodes) == 4
    links = ontology.find_entities("default", entity_type="link")
    assert len(links) == 3

    # 多跳：高新区1号基站 → backhaul → 高新-下沙光缆
    st = ontology.find_entities("default", entity_type="station", keyword="高新区1号")
    assert len(st) == 1
    rels = ontology.query_relations("default", st[0]["id"])
    backhauls = [r["target"]["name"] for r in rels
                 if r["relation_type"] == "backhaul"]
    assert backhauls == ["高新-下沙光缆"]

    # 节点 → deploy_in → 机房
    node_id = ontology.find_entities("default", entity_type="compute_node",
                                     keyword="GPU训练")[0]["id"]
    rels = ontology.query_relations("default", node_id)
    deploys = [r["target"]["name"] for r in rels
               if r["relation_type"] == "deploy_in"]
    assert deploys == ["滨江核心机房"]


def test_ontology_schema_backfill_adds_resource_types():
    """老库升级路径：backfill_schema_types 幂等补齐新增的 3 实体类型/2 关系类型。"""
    ontology.init()
    ontology.seed_schema_if_empty()
    ontology.backfill_schema_types()
    schema = ontology.list_schema("default")
    codes = {t["code"] for t in schema["entity_types"]}
    rels = {t["code"] for t in schema["relation_types"]}
    assert {"datacenter", "compute_node", "link"} <= codes
    assert {"deploy_in", "backhaul"} <= rels
