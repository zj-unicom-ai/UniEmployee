from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import require_admin
from app.routes.ai_models import router


def test_model_admission_stats_endpoint_is_admin_only():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_admin] = lambda: {
        "id": "u_admin", "username": "admin", "role": "admin",
    }
    assert TestClient(app).get("/api/admin/ai-models/admission").status_code == 200

    app2 = FastAPI()
    app2.include_router(router)
    denied = TestClient(app2).get("/api/admin/ai-models/admission")
    assert denied.status_code in (401, 403)
