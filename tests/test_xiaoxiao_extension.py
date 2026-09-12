"""xiaoxiao 全生命周期客户经理扩展回归测试。

覆盖：yaml 升级（签后技能 + create_ticket 工具 + persona 审批红线）、
技能文件与触发条件提取、演示数据生成脚本产出与故事线
（临期合同/停滞商机）、create_ticket 审批标记种子与老库 backfill。
"""
import csv
import importlib.util
from datetime import datetime
from pathlib import Path

from app import catalog
from app.compiler import _extract_skill_triggers
from app.spec import load_spec

PROJECT_ROOT = Path(__file__).resolve().parent.parent
XIAOXIAO_YAML = PROJECT_ROOT / "backend" / "employees" / "xiaoxiao.yaml"
SCRIPT = PROJECT_ROOT / "scripts" / "generate_xiaoxiao_data.py"
SKILLS = PROJECT_ROOT / "backend" / "skills"


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_xiaoxiao_data", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------- yaml 升级 ----------

def test_yaml_lifecycle_upgrade():
    spec = load_spec(str(XIAOXIAO_YAML))
    assert spec.kind == "composed"
    assert spec.backend == "local_shell"
    # 签前技能保留 + 两个签后技能
    assert {"enterprise-sales", "customer-360", "renewal-scan"} <= set(spec.skills)
    # 投诉升级需要 create_ticket 工具 + 审批拦截
    assert "create_ticket" in spec.tools
    assert spec.interrupt_on.get("create_ticket") is True
    for kw in ("customer-360", "renewal-scan", "create_ticket", "/memories/AGENTS.md",
               "审批", "workspace/datasets/"):
        assert kw in spec.persona, f"persona 缺少 {kw}"


def test_skill_files_and_triggers():
    for sid in ("customer-360", "renewal-scan"):
        md = (SKILLS / sid / "SKILL.md").read_text(encoding="utf-8")
        assert md.startswith("---"), f"{sid} 缺 frontmatter"
        assert "## 触发条件" in md, f"{sid} 缺触发条件段"
        assert "## 执行步骤" in md, f"{sid} 缺执行步骤段"
        triggers = _extract_skill_triggers(md)
        assert len(triggers) > 10, f"{sid} 触发条件提取失败"
    # enterprise-sales 补了拜访后纪要规程
    ent = (SKILLS / "enterprise-sales" / "SKILL.md").read_text(encoding="utf-8")
    assert "拜访后纪要" in ent
    assert "create_ticket" in ent


# ---------- 演示数据生成脚本 ----------

def test_generator_outputs_and_storylines(tmp_path, monkeypatch):
    gen = _load_generator()
    monkeypatch.setattr(gen, "OUTPUT_DIR", tmp_path)
    gen.gen_contracts()
    gen.gen_opportunities()

    contracts = _rows(tmp_path / "crm_contracts.csv")
    opps = _rows(tmp_path / "crm_opportunities.csv")

    assert contracts and set(contracts[0].keys()) == {
        "contract_id", "customer", "company", "product", "amount_wan",
        "sign_date", "expire_date"}
    assert opps and set(opps[0].keys()) == {
        "opp_id", "customer", "company", "product", "stage",
        "amount_wan", "last_follow_up", "note"}
    # 客户名为演示案例客户（吉利汽车/零跑汽车为浙江联通政企客户背景）
    companies = {c["company"] for c in contracts} | {o["company"] for o in opps}
    assert {"吉利汽车", "零跑汽车"} <= companies

    cutoff = gen.TODAY
    # 故事线 A/B：至少两条临期合同（≤30 天），含大额的吉利汽车 5G 专网
    expiring = [c for c in contracts
                if 0 <= (datetime.strptime(c["expire_date"], "%Y-%m-%d") - cutoff).days <= 30]
    assert len(expiring) >= 2
    assert any(c["company"] == "吉利汽车" for c in expiring)
    # 故事线 C/D：至少两条停滞商机（活跃且 >14 天未跟进）
    stalled = [o for o in opps
               if o["stage"] not in ("赢单", "输单")
               and (cutoff - datetime.strptime(o["last_follow_up"], "%Y-%m-%d")).days > 14]
    assert len(stalled) >= 2
    # 也有活跃商机，避免清单全是风险项
    active = [o for o in opps
              if o["stage"] not in ("赢单", "输单")
              and (cutoff - datetime.strptime(o["last_follow_up"], "%Y-%m-%d")).days <= 14]
    assert active


# ---------- 审批标记种子与老库 backfill ----------

def test_seed_marks_create_ticket_approval():
    catalog.seed_if_empty()
    row = catalog.db._conn().execute(
        "SELECT needs_approval FROM tools WHERE id='create_ticket'").fetchone()
    assert row["needs_approval"] == '["approve", "reject"]'
    # xiaoxiao 配置：工具有 create_ticket，运行时推导出审批中断
    cfg = catalog.get_employee_config("xiaoxiao")
    assert "create_ticket" in cfg["tools"]
    assert cfg["interrupt_on"]["create_ticket"]["allowed_decisions"] == ["approve", "reject"]


def test_backfill_ticket_approval_on_old_db():
    """模拟老库：create_ticket 已登记但无审批标记 → backfill 幂等补齐。"""
    con = catalog.db._conn()
    con.execute(
        "INSERT OR IGNORE INTO tools(id,name,description,source,needs_approval) "
        "VALUES('create_ticket','工单登记','登记客服工单','local',NULL)")
    con.commit()
    catalog.backfill_ticket_approval()
    row = con.execute(
        "SELECT needs_approval FROM tools WHERE id='create_ticket'").fetchone()
    assert row["needs_approval"] == '["approve", "reject"]'
    # 幂等：再跑一次不报错、不覆盖已有策略
    catalog.backfill_ticket_approval()
    assert row["needs_approval"] == '["approve", "reject"]'
