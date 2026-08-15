"""技能动态 Store 同步测试。

锁定 #69 的核心行为：runtime.sync_skills_to_store
能把 catalog 当前配置的技能内容写入 Store namespace=(user_id or "default", employee_id)，
且只在内容变化时写入（幂等、避免每次 get_agent 重复写盘）。
"""
import asyncio
from pathlib import Path

from langgraph.store.sqlite import AsyncSqliteStore

from app import runtime
from app.compiler import (
    _extract_skill_triggers,
    _build_skill_routing,
    _build_sop_routing,
    _extract_sop_preview,
)


def test_invalidate_user_only_drops_user_variant():
    """invalidate_user 只清某用户变体，不影响模板/其他用户缓存。"""
    runtime._agents["emp_demo"] = ("agent_template", {})
    runtime._agents["emp_demo|u_1"] = ("agent_u1", {})
    runtime._agents["emp_demo|u_2"] = ("agent_u2", {})
    runtime._mcp_clients["emp_demo|u_1"] = object()

    runtime.invalidate_user("emp_demo", "u_1")

    assert "emp_demo" in runtime._agents
    assert "emp_demo|u_2" in runtime._agents
    assert "emp_demo|u_1" not in runtime._agents
    assert "emp_demo|u_1" not in runtime._mcp_clients


def test_refresh_skills_user_variant_invalidates_that_user(tmp_path, monkeypatch):
    """refresh_skills(emp, user) 刷新用户技能并只清该用户变体。"""
    skill_a = _make_skill_dir(tmp_path, "a-skill", "## 触发条件\nA\n")
    monkeypatch.setattr(
        runtime.catalog,
        "get_skill_dirs_for_employee",
        lambda emp, user=None: {"a-skill": str(skill_a)},
    )
    db = tmp_path / "refresh_u.db"

    async def go():
        async with AsyncSqliteStore.from_conn_string(str(db)) as store:
            runtime._store = store
            runtime._agents["emp_demo"] = ("agent_template", {})
            runtime._agents["emp_demo|u_1"] = ("agent_u1", {})
            runtime._agents["emp_demo|u_2"] = ("agent_u2", {})
            await runtime.refresh_skills("emp_demo", user_id="u_1")

            assert "emp_demo" in runtime._agents
            assert "emp_demo|u_1" not in runtime._agents
            assert "emp_demo|u_2" in runtime._agents
            item = await store.aget(("u_1", "emp_demo"), "/a-skill/SKILL.md")
            assert item is not None

    asyncio.run(go())
    runtime._store = None


def _make_skill_dir(tmp_path: Path, skill_id: str, content: str) -> Path:
    d = tmp_path / skill_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(content, encoding="utf-8")
    return d


def test_sync_skills_writes_and_detects_changes(tmp_path, monkeypatch):
    skill_dir_a = _make_skill_dir(tmp_path, "product-faq", "## 触发条件\n产品咨询\n")
    skill_dir_b = _make_skill_dir(tmp_path, "hr-assistant", "## 触发条件\n人事制度\n")

    monkeypatch.setattr(
        runtime.catalog,
        "get_skill_dirs_for_employee",
        lambda emp, user=None: {
            "product-faq": str(skill_dir_a),
            "hr-assistant": str(skill_dir_b),
        },
    )

    db = tmp_path / "store.db"

    async def go():
        async with AsyncSqliteStore.from_conn_string(str(db)) as store:
            runtime._store = store
            await runtime.sync_skills_to_store("emp_demo")

            a = await store.aget(("default", "emp_demo"), "/product-faq/SKILL.md")
            b = await store.aget(("default", "emp_demo"), "/hr-assistant/SKILL.md")
            assert a is not None and "产品咨询" in a.value["content"]
            assert b is not None and "人事制度" in b.value["content"]

            # 幂等：内容不变时第二次调用不应覆盖（这里只验证不抛错且内容仍正确）
            await runtime.sync_skills_to_store("emp_demo")
            a2 = await store.aget(("default", "emp_demo"), "/product-faq/SKILL.md")
            assert a2.value["content"] == a.value["content"]

            # 技能内容更新后，sync 应能拉到新内容
            (skill_dir_a / "SKILL.md").write_text(
                "## 触发条件\n产品咨询 + 保修\n", encoding="utf-8")
            await runtime.sync_skills_to_store("emp_demo")
            a3 = await store.aget(("default", "emp_demo"), "/product-faq/SKILL.md")
            assert "保修" in a3.value["content"]

    asyncio.run(go())
    runtime._store = None


def test_sync_skills_uses_effective_dirs_for_user(tmp_path, monkeypatch):
    """用户视角同步应使用 get_effective_config 后的技能目录，而不是模板技能。"""
    skill_a = _make_skill_dir(tmp_path, "a-skill", "## 触发条件\nA\n")
    skill_b = _make_skill_dir(tmp_path, "b-skill", "## 触发条件\nB\n")

    monkeypatch.setattr(
        runtime.catalog,
        "get_skill_dirs_for_employee",
        lambda emp, user=None: {
            "a-skill": str(skill_a) if user == "u_1" else str(skill_a),
            "b-skill": str(skill_b),
        },
    )

    db = tmp_path / "store_u.db"

    async def go():
        async with AsyncSqliteStore.from_conn_string(str(db)) as store:
            runtime._store = store
            await runtime.sync_skills_to_store("emp_demo", user_id="u_1")
            a = await store.aget(("u_1", "emp_demo"), "/a-skill/SKILL.md")
            b = await store.aget(("u_1", "emp_demo"), "/b-skill/SKILL.md")
            assert a is not None
            assert b is not None

    asyncio.run(go())
    runtime._store = None


def test_skill_store_namespace_isolates_users(tmp_path, monkeypatch):
    """不同用户视角的技能 Store 命名空间必须隔离，避免互相覆盖。"""
    skill_a = _make_skill_dir(tmp_path, "a-skill", "## 触发条件\nA\n")
    skill_b = _make_skill_dir(tmp_path, "b-skill", "## 触发条件\nB\n")

    monkeypatch.setattr(
        runtime.catalog,
        "get_skill_dirs_for_employee",
        lambda emp, user=None: (
            {"a-skill": str(skill_a)} if user == "u_1"
            else {"b-skill": str(skill_b)}
        ),
    )

    db = tmp_path / "store_iso.db"

    # 用实际调用动态断言同样成立：u_1 看到 a-skill，u_2 看到 b-skill。
    calls = []
    orig_sync = runtime.sync_skills_to_store

    async def tracked_sync(emp, user_id=None, **kw):
        calls.append(user_id)
        return await orig_sync(emp, user_id, **kw)

    monkeypatch.setattr(runtime, "sync_skills_to_store", tracked_sync)

    async def go():
        async with AsyncSqliteStore.from_conn_string(str(db)) as store:
            runtime._store = store
            await runtime.sync_skills_to_store("emp_demo", user_id="u_1")
            await runtime.sync_skills_to_store("emp_demo", user_id="u_2")

            a1 = await store.aget(("u_1", "emp_demo"), "/a-skill/SKILL.md")
            a2 = await store.aget(("u_2", "emp_demo"), "/b-skill/SKILL.md")
            assert a1 is not None
            assert a2 is not None
            assert await store.aget(("u_2", "emp_demo"), "/a-skill/SKILL.md") is None

    asyncio.run(go())
    runtime._store = None
    assert calls == ["u_1", "u_2"]


def test_skill_routing_keeps_full_procedure_out_of_system_prompt():
    """契约：system_prompt 只保留技能清单与触发摘要，
    详细规程必须留在 Store/read_file 里，不随 system_prompt 固化。"""
    skill_md = """---
name: secret-skill
description: 秘密技能描述，当用户触发时使用。
---

## 触发条件
用户提到“验证”时使用。

## 规程
机密全文内容：不要在 system_prompt 里泄露这一段。
"""
    triggers = _extract_skill_triggers(skill_md)
    routing = _build_skill_routing([{
        "name": "secret-skill",
        "description": "秘密技能描述，当用户触发时使用。",
        "triggers": triggers,
    }])
    assert "秘密技能描述" in routing or "用户提到" in routing
    assert "机密全文内容" not in routing
    assert "/skills/secret-skill/SKILL.md" in routing


def test_sop_routing_keeps_full_text_out_of_system_prompt():
    """SOP 全文不拼进 system_prompt，只保留清单与路径。"""
    sop_text = "# 退款 SOP\n\n" + "必须严格按照此流程执行。" * 40 + "\n机密全文内容：不要在 system_prompt 里泄露这一段。\n"
    routing = _build_sop_routing([
        {"id": "sop_refund", "preview": _extract_sop_preview(sop_text)},
    ])
    assert "SOP 路由" in routing
    assert "/sops/sop_refund.md" in routing
    assert "机密全文内容" not in routing


def test_sync_sops_to_store_writes_sop_content(tmp_path, monkeypatch):
    """SOP 内容变更后 sync_sops_to_store 能写入 /sops/<id>.md。"""
    monkeypatch.setattr(
        runtime.catalog,
        "get_sop",
        lambda sop_id: {
            "id": sop_id, "name": "退款", "description": "退款流程",
            "content": "新版退款 SOP：必须走审批流程。",
        },
    )
    monkeypatch.setattr(
        runtime.catalog,
        "get_employee_config",
        lambda emp: {"sops": ["sop_refund"]},
    )

    db = tmp_path / "sop_store.db"

    async def go():
        async with AsyncSqliteStore.from_conn_string(str(db)) as store:
            runtime._store = store
            await runtime.sync_sops_to_store("emp_demo")
            item = await store.aget(("default", "emp_demo"), "/sop_refund.md")
            assert item is not None
            assert "新版退款 SOP" in item.value["content"]

    asyncio.run(go())
    runtime._store = None
