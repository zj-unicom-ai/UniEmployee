from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import auth, market_intake as intake
from app.routes.market_research import router

@pytest.fixture
def client(monkeypatch):
    intake.init_tables()
    monkeypatch.setattr(intake, 'launch', lambda job: None)
    app = FastAPI()
    app.include_router(router)
    ctx = SimpleNamespace(tenant_id='a', user_id='u-a', allows=lambda _:True)
    app.dependency_overrides[auth.get_auth_context] = lambda: ctx
    with TestClient(app) as c:
        yield c, ctx


def test_intake_and_retry_are_scoped_to_authenticated_tenant(client):
    c, ctx = client
    r=c.post('/api/market-research/intake',json={'url':'https://example.com/article'})
    assert r.status_code==202
    job_id=r.json()['id']
    assert 'document_json' not in r.json()
    assert len(c.get('/api/market-research/intake').json()['items'])==1
    ctx.tenant_id='b';ctx.user_id='u-b'
    assert not c.get('/api/market-research/intake').json()['items']
    assert c.post(f'/api/market-research/intake/{job_id}/retry').status_code==404


def test_unassigned_users_cannot_create_observations_or_intake(client,monkeypatch):
    from app import catalog
    c,ctx=client
    ctx.allows=lambda _:False
    monkeypatch.setattr(catalog,'assigned_employee_ids',lambda _:[])
    assert c.post('/api/market-research/intake',json={'url':'https://example.com/a'}).status_code==403
    assert c.post('/api/market-research/observations',json={'topic_id':'embodied-intelligence','category_id':'','title':'绕过分配'}).status_code==403


def test_invalid_topic_and_private_urls_return_validation_error(client):
    c,_=client
    assert c.post('/api/market-research/intake',json={'url':'http://127.0.0.1/a'}).status_code==422
    assert c.post('/api/market-research/intake',json={'url':'https://example.com/a','topic_id':'invalid','category_id':'invalid'}).status_code==422
