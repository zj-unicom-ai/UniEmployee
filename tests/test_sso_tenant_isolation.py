"""OIDC 身份绑定、统一授权上下文与一期单企业租户边界回归。"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import approvals, auth, catalog, conversations, traces
from app.auth_context import from_user
from app.routes.auth import router as auth_router
from app.routes.conversations import router as conversations_router


def test_external_identity_uses_issuer_subject_not_email():
    first = catalog.find_or_create_oidc_user(
        provider="corp", issuer="https://id.example", tenant_id="enterprise-a", org_id=None,
        claims={"sub": "immutable-1", "email": "before@example.com", "preferred_username": "alice"},
    )
    again = catalog.find_or_create_oidc_user(
        provider="corp", issuer="https://id.example", tenant_id="enterprise-a", org_id=None,
        claims={"sub": "immutable-1", "email": "after@example.com", "preferred_username": "renamed"},
    )
    assert again["id"] == first["id"]
    assert catalog.get_user_by_identity("https://id.example", "immutable-1")["id"] == first["id"]


def test_oidc_enabled_allows_only_emergency_local_login(monkeypatch):
    monkeypatch.setenv("OIDC_ISSUER", "https://id.example")
    monkeypatch.setenv("OIDC_CLIENT_ID", "client")
    monkeypatch.setenv("OIDC_REDIRECT_URI", "https://app.example/api/auth/sso/callback")
    assert auth.local_login_allowed({"is_emergency_admin": 0}) is False
    assert auth.local_login_allowed({"is_emergency_admin": 1}) is True


def test_oidc_raw_role_claim_cannot_promote_without_group_mapping(monkeypatch):
    monkeypatch.setenv("OIDC_GROUP_ROLE_MAP", "{}")
    role, org = auth.oidc_role_and_org({"role": "admin", "groups": ["ordinary"]})
    assert role == "user"
    assert org is None


def test_sso_callback_binds_identity_and_sets_http_only_session(monkeypatch):
    for key, value in {
        "OIDC_ISSUER": "https://id.example",
        "OIDC_CLIENT_ID": "uniemployee",
        "OIDC_REDIRECT_URI": "https://app.example/api/auth/sso/callback",
        "ENTERPRISE_TENANT_ID": "enterprise-a",
    }.items():
        monkeypatch.setenv(key, value)

    async def fake_auth_url(state, nonce):
        return f"https://id.example/authorize?state={state}&nonce={nonce}"

    async def fake_exchange(code):
        assert code == "one-time-code"
        return {"jwks_uri": "https://id.example/keys"}, {"id_token": "unused"}

    async def fake_verify(cfg, token, nonce):
        assert nonce
        return {"sub": "stable-subject", "preferred_username": "oidc-user", "groups": []}

    monkeypatch.setattr(auth, "oidc_authorization_url", fake_auth_url)
    monkeypatch.setattr(auth, "exchange_oidc_code", fake_exchange)
    monkeypatch.setattr(auth, "verify_oidc_id_token", fake_verify)
    app = FastAPI(); app.include_router(auth_router)
    client = TestClient(app)
    start = client.get("/api/auth/sso/login?next=/app/home", follow_redirects=False)
    assert start.status_code == 302
    state = start.headers["location"].split("state=", 1)[1].split("&", 1)[0]
    done = client.get(f"/api/auth/sso/callback?code=one-time-code&state={state}",
                      follow_redirects=False)
    assert done.status_code == 302
    assert done.headers["location"].startswith("/login?sso=1")
    assert auth.SESSION_COOKIE in client.cookies
    assert catalog.get_user_by_identity("https://id.example", "stable-subject")["tenant_id"] == "enterprise-a"


def test_auth_context_uses_fixed_tenant_and_org_descendants():
    org_root = catalog.create_org("总部")
    org_rd = catalog.create_org("研发部", parent_id=org_root)
    user_id = catalog.create_user("context-user", "x", tenant_id="enterprise-a", org_id=org_root)
    context = from_user(catalog.get_user(user_id))
    assert context.tenant_id == "enterprise-a"
    assert context.org_ids == frozenset({org_root, org_rd})
    assert context.allows("employee:use")
    assert not context.allows("connector:invoke")


def _client_for(user):
    app = FastAPI()
    app.include_router(conversations_router)
    app.dependency_overrides[auth.get_current_user] = lambda: user
    app.dependency_overrides[auth.get_current_user_or_fallback] = lambda: user
    return TestClient(app)


def test_conversation_and_approval_reject_cross_tenant_access():
    user_a = catalog.create_user("tenant-a", "x", user_id="u_ta", tenant_id="enterprise-a")
    user_b = catalog.create_user("tenant-b", "x", user_id="u_tb", tenant_id="enterprise-b")
    conversations.create("c_tenant_a", "emp", user_id=user_a, tenant_id="enterprise-a")
    approval = approvals.create("c_tenant_a", "emp", "tool", {}, user_id=user_a,
                                tenant_id="enterprise-a")

    client = _client_for(catalog.get_user(user_b))
    assert client.get("/api/conversations/c_tenant_a").status_code == 404
    assert client.post(f"/api/approvals/{approval['approval_id']}/decision",
                       json={"decision": "reject"}).status_code == 404
    assert approvals.get(approval["approval_id"])["status"] == "pending"


def test_trace_queries_are_tenant_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(traces, "DB", tmp_path / "traces.db")
    run_a = traces.start_run("c_a", "emp", "u_a", tenant_id="enterprise-a")
    run_b = traces.start_run("c_b", "emp", "u_b", tenant_id="enterprise-b")
    assert traces.get_run(run_a, tenant_id="enterprise-a") is not None
    assert traces.get_run(run_a, tenant_id="enterprise-b") is None
    assert traces.list_runs("c_b", tenant_id="enterprise-a") == []
    traces.finish_run(run_a)
    traces.finish_run(run_b)
