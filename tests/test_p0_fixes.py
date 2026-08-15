"""P0 修复回归测试：审批权限字段、管理员种子、公开案例接口、会话认领。"""

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from app import approvals, auth, catalog, conversations, runtime
from app.compiler import make_kb_search
from app.spec import EmployeeSpec
from app.tools.kb import create_ticket
from app.routes.public import router as public_router
from app.workflows.refund import get_refund_graph


def test_seed_admin_does_not_reset_existing_password(monkeypatch):
    """管理员已存在时，seed_admin_if_empty 绝不把密码打回 ADMIN_PASS。"""
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASS", "admin123")
    catalog.create_user("admin", auth.hash_password("custom-secret"),
                        role="admin", user_id="u_admin")

    catalog.seed_admin_if_empty()

    u = catalog.get_user_by_username("admin")
    assert auth.verify_password("custom-secret", u["password_hash"])
    assert not u.get("must_change_password")


def test_seed_admin_creates_when_empty(monkeypatch):
    """空库时仍会创建初始管理员并标记强制改密。"""
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASS", "admin123")

    catalog.seed_admin_if_empty()

    u = catalog.get_user_by_username("admin")
    assert u is not None
    assert u["role"] == "admin"
    assert u.get("must_change_password")


def test_seed_if_empty_works_with_soft_delete_migration():
    """迁移后的表含 deleted_at，种子 INSERT 必须显式列名（容器首次启动会走这里）。"""
    catalog.seed_if_empty()
    assert len(catalog.list_employees_meta()) == 5
    assert catalog.get_skill("product-faq") is not None


def test_approval_tracks_owner_and_inner_thread():
    """审批单需记录发起用户与退款内层 thread，供 decision 端点校验和恢复。"""
    rec = approvals.create("c1", "xiaosu", "start_refund",
                           {"order_id": "O12345"}, user_id="u_1",
                           inner_thread="refund:O12345:1")
    assert rec["user_id"] == "u_1"
    assert rec["inner_thread"] == "refund:O12345:1"
    assert approvals.get(rec["approval_id"])["status"] == "pending"
    decided = approvals.decide(rec["approval_id"], "approve")
    assert decided is not None and decided["status"] == "approve"
    assert approvals.decide(rec["approval_id"], "reject") is None


def test_public_employees_endpoints_anonymous():
    """案例页使用的公开接口无需登录，且只返回基础元数据。"""
    catalog.create_employee({
        "id": "pub1", "name": "案例员工", "role": "顾问",
        "model": "openai:x", "persona": "内部人设不应暴露",
        "skills": ["product-faq"], "tools": ["kb_search"],
    })
    app = FastAPI()
    app.include_router(public_router)
    client = TestClient(app)

    r = client.get("/api/public/employees")
    assert r.status_code == 200
    assert any(e["id"] == "pub1" for e in r.json())
    detail = client.get("/api/public/employees/pub1")
    assert detail.status_code == 200
    assert "persona" not in detail.json()
    assert client.get("/api/public/employees/nope").status_code == 404


def test_create_ticket_rejects_invalid_urgency_without_asserting():
    """#9：非法 urgency 不再抛 AssertionError，返回友好提示。"""
    r = create_ticket.invoke({
        "category": "售后",
        "urgency": "asap",
        "summary": "测试工单",
    })
    assert "无法登记" in r
    assert "asap" not in r.split("仅")[0] or "urgency" in r


def test_create_ticket_accepts_valid_urgency():
    """合法 urgency 仍能正常建档。"""
    r = create_ticket.invoke({
        "category": "售后",
        "urgency": "urgent",
        "summary": "测试工单2",
    })
    assert r.startswith("工单已登记：")


def test_make_kb_search_reads_catalog_at_runtime(monkeypatch):
    """kb_search 运行时读取 catalog，不固化编译期知识库配置快照。"""
    from app.connectors import ragflow_client
    seen = {}
    monkeypatch.setattr(ragflow_client, "is_ragflow_configured", lambda: True)

    def fake_retrieve(question, dataset_ids=None, top_k=5, **kwargs):
        seen["question"] = question
        seen["dataset_ids"] = dataset_ids
        seen["top_k"] = top_k
        return [{"content": "新 RAGFlow 内容", "dataset_id": "ds-new", "similarity": 0.91}]

    monkeypatch.setattr(ragflow_client, "retrieve_ragflow", fake_retrieve)
    spec = EmployeeSpec(
        id="emp_kb", name="知识库测试", role="tester",
        model="openai:deepseek-chat", persona="测试",
        tools=["kb_search"], kbs=["kb1"],
    )
    monkeypatch.setattr(
        catalog,
        "get_employee_config",
        lambda emp: {"id": emp, "kb_ragflow_datasets": {"kb1": "ds-new"}},
    )

    fn = make_kb_search(spec, user_id=None)
    out = fn.invoke({"query": "新品"})
    assert "新 RAGFlow 内容" in out
    assert seen == {"question": "新品", "dataset_ids": ["ds-new"], "top_k": 3}


def test_admin_create_employee_syncs_ragflow_kbs_before_save(monkeypatch):
    """新建员工选择 RAGFlow 数据集时，保存前先把最新数据集回填进 catalog。"""
    from app import auth
    from app.routes.admin import router as admin_router

    calls = []

    def fake_backfill():
        calls.append(1)
        catalog.create_kb("ds-001", "产品库", "", ragflow_dataset_id="ds-001")

    monkeypatch.setattr(catalog, "backfill_ragflow_knowledge_bases", fake_backfill)
    app = FastAPI()
    app.include_router(admin_router)
    app.dependency_overrides[auth.require_admin] = lambda: {"id": "u_admin", "role": "admin"}
    client = TestClient(app)

    r = client.post("/api/admin/employees", json={
        "id": "emp_rf2", "name": "RF2", "model": "openai:m",
        "backend": "state", "persona": "p", "kbs": ["ds-001"],
        "skills": [], "tools": [], "sops": [], "connectors": [],
    })
    assert r.status_code == 200
    assert calls == [1]
    cfg = catalog.get_employee_config("emp_rf2")
    assert cfg["kb_ragflow_datasets"] == {"ds-001": "ds-001"}


def test_admin_save_employee_without_kbs_skips_ragflow_sync(monkeypatch):
    """员工保存未选择知识库时，不触发 RAGFlow 同步（避免无谓网络调用）。"""
    from app import auth
    from app.routes.admin import router as admin_router

    calls = []
    monkeypatch.setattr(
        catalog, "backfill_ragflow_knowledge_bases",
        lambda: calls.append(1),
    )
    app = FastAPI()
    app.include_router(admin_router)
    app.dependency_overrides[auth.require_admin] = lambda: {"id": "u_admin", "role": "admin"}
    client = TestClient(app)

    r = client.post("/api/admin/employees", json={
        "id": "emp_nokb", "name": "无库", "model": "openai:m",
        "backend": "state", "persona": "p", "kbs": [],
        "skills": [], "tools": [], "sops": [], "connectors": [],
    })
    assert r.status_code == 200
    assert calls == []


def test_conversations_claim_legacy_owner():
    """历史 default 归属会话可被首个发送者认领。"""
    conversations.create("legacy_1", "xiaosu", title="旧会话", user_id="default")
    conversations.claim("legacy_1", "u_new")
    assert conversations.get("legacy_1")["user_id"] == "u_new"


def test_runtime_resume_refund_wrapper():
    """decision 端点使用的 runtime.resume_refund 能恢复退款内层图。"""
    cp = MemorySaver()
    old = runtime._checkpointer
    runtime._checkpointer = cp
    try:
        graph = get_refund_graph(cp)
        tid = "runtime-resume-test"
        cfg = {"configurable": {"thread_id": tid}}
        graph.invoke({"order_id": "O12345", "reason": "质量问题", "inner_thread": tid}, config=cfg)
        summary = asyncio.run(runtime.resume_refund(tid, True))
        assert "退款单号" in summary
    finally:
        runtime._checkpointer = old
