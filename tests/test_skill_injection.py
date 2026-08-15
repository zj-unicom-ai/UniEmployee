"""Point1 技能确定性路由测试。

验证 _extract_skill_triggers 从四种 SKILL.md 提取触发条件、
_build_skill_routing 生成确定性路由指令的格式。
"""
from pathlib import Path

from app.compiler import _extract_skill_triggers, _build_skill_routing

SKILLS_DIR = Path(__file__).resolve().parent.parent / "backend" / "skills"


def _read(name: str) -> str:
    return (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")


def test_extract_triggers_complaint_has_trigger_section():
    """complaint-handling 有 ## 触发条件 段落，应优先提取它。"""
    triggers = _extract_skill_triggers(_read("complaint-handling"))
    assert "投诉" in triggers
    assert "负面情绪" in triggers
    # 不应混入 frontmatter 的 description
    assert "客户投诉处理规程" not in triggers


def test_extract_triggers_product_faq_has_scope_section():
    """product-faq 有 ## 适用范围 段落，应提取它（语义等同触发条件）。"""
    triggers = _extract_skill_triggers(_read("product-faq"))
    assert "产品规格" in triggers or "保修" in triggers


def test_extract_triggers_data_analysis_fallback_to_description():
    """data-analysis 无 ## 触发条件/适用范围 段落，兜底用 frontmatter description。"""
    triggers = _extract_skill_triggers(_read("data-analysis"))
    assert "统计" in triggers or "数据" in triggers


def test_extract_triggers_frontend_design_fallback_to_description():
    """frontend-design 无触发条件段落，兜底用英文 description。"""
    triggers = _extract_skill_triggers(_read("frontend-design"))
    assert "design" in triggers.lower() or "UI" in triggers


def test_build_skill_routing_format():
    """_build_skill_routing 生成含技能名、触发条件、规程路径的路由指令。"""
    skills = [
        {"name": "complaint-handling", "description": "投诉处理",
         "triggers": "用户表达负面情绪：投诉、坏了、垃圾"},
        {"name": "data-analysis", "description": "数据分析",
         "triggers": "当用户给出数据问题、要求统计时"},
    ]
    routing = _build_skill_routing(skills)
    assert "技能路由" in routing
    assert "确定性激活" in routing
    assert "complaint-handling" in routing
    assert "data-analysis" in routing
    assert "/skills/complaint-handling/SKILL.md" in routing
    assert "/skills/data-analysis/SKILL.md" in routing
    assert "投诉、坏了、垃圾" in routing
    assert "read_file" in routing  # 明确要求查阅规程


def test_build_skill_routing_empty():
    """无技能时返回空字符串（不污染 system_prompt）。"""
    assert _build_skill_routing([]) == ""


def test_build_skill_routing_uses_description_when_no_triggers():
    """triggers 为空时兜底用 description。"""
    skills = [{"name": "x", "description": "某技能描述", "triggers": ""}]
    routing = _build_skill_routing(skills)
    assert "某技能描述" in routing
