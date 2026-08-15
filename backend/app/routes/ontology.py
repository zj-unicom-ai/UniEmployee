"""业务本体管理 API：schema（实体/关系类型）与 data（实例）的 CRUD。

仅管理员可访问，数据按登录用户的 tenant_id 隔离。
"""

from fastapi import APIRouter, Depends, HTTPException

from app import auth, ontology

router = APIRouter(prefix="/api/admin/ontology", dependencies=[Depends(auth.require_admin)])


def _tenant(admin: dict) -> str:
    return admin.get("tenant_id", "default")


def _ok(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---- Schema ----

@router.get("/schema")
async def get_schema(admin: dict = Depends(auth.require_admin)):
    return ontology.list_schema(_tenant(admin))


@router.post("/entity-types")
async def create_entity_type(body: dict, admin: dict = Depends(auth.require_admin)):
    return {"id": _ok(ontology.create_entity_type, _tenant(admin), body)}


@router.put("/entity-types/{type_id}")
async def update_entity_type(type_id: int, body: dict, admin: dict = Depends(auth.require_admin)):
    _ok(ontology.update_entity_type, _tenant(admin), type_id, body)
    return {"ok": True}


@router.delete("/entity-types/{type_id}")
async def delete_entity_type(type_id: int, admin: dict = Depends(auth.require_admin)):
    _ok(ontology.delete_entity_type, _tenant(admin), type_id)
    return {"ok": True}


@router.post("/relation-types")
async def create_relation_type(body: dict, admin: dict = Depends(auth.require_admin)):
    return {"id": _ok(ontology.create_relation_type, _tenant(admin), body)}


@router.put("/relation-types/{type_id}")
async def update_relation_type(type_id: int, body: dict, admin: dict = Depends(auth.require_admin)):
    _ok(ontology.update_relation_type, _tenant(admin), type_id, body)
    return {"ok": True}


@router.delete("/relation-types/{type_id}")
async def delete_relation_type(type_id: int, admin: dict = Depends(auth.require_admin)):
    _ok(ontology.delete_relation_type, _tenant(admin), type_id)
    return {"ok": True}


# ---- Data ----

@router.get("/entities")
async def list_entities(entity_type: str | None = None, keyword: str | None = None,
                        admin: dict = Depends(auth.require_admin)):
    return {"items": ontology.list_entities(
        _tenant(admin), entity_type=entity_type, keyword=keyword, limit=500)}


@router.post("/entities")
async def create_entity(body: dict, admin: dict = Depends(auth.require_admin)):
    return {"id": _ok(ontology.create_entity, _tenant(admin), body)}


@router.get("/entities/{entity_id}")
async def get_entity(entity_id: int, admin: dict = Depends(auth.require_admin)):
    e = ontology.get_entity(_tenant(admin), entity_id)
    if not e:
        raise HTTPException(status_code=404, detail="实体不存在")
    e["relations"] = ontology.list_relations(_tenant(admin), entity_id)
    return e


@router.put("/entities/{entity_id}")
async def update_entity(entity_id: int, body: dict, admin: dict = Depends(auth.require_admin)):
    _ok(ontology.update_entity, _tenant(admin), entity_id, body)
    return {"ok": True}


@router.delete("/entities/{entity_id}")
async def delete_entity(entity_id: int, admin: dict = Depends(auth.require_admin)):
    _ok(ontology.delete_entity, _tenant(admin), entity_id)
    return {"ok": True}


@router.get("/relations")
async def list_relations(entity_id: int | None = None,
                         admin: dict = Depends(auth.require_admin)):
    return {"items": ontology.list_relations(_tenant(admin), entity_id)}


@router.post("/relations")
async def create_relation(body: dict, admin: dict = Depends(auth.require_admin)):
    return {"id": _ok(ontology.create_relation, _tenant(admin), body)}


@router.delete("/relations/{relation_id}")
async def delete_relation(relation_id: int, admin: dict = Depends(auth.require_admin)):
    _ok(ontology.delete_relation, _tenant(admin), relation_id)
    return {"ok": True}


@router.get("/stats")
async def get_stats(admin: dict = Depends(auth.require_admin)):
    return ontology.stats(_tenant(admin))
