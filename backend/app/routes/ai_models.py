"""AI 模型管理路由：CRUD + 设默认 + 测试连接。

所有接口仅 admin 可访问，变更操作记录审计日志。
"""
from fastapi import APIRouter, Depends, HTTPException, Request

from app import audit, catalog
from app.auth import require_admin, get_current_user

router = APIRouter(prefix="/api/admin/ai-models", dependencies=[Depends(require_admin)])


# 普通用户可访问的模型列表（不含 api_key），供对话页模型选择下拉框用
public_router = APIRouter(prefix="/api/ai-models")


@public_router.get("")
async def list_ai_models_public(user: dict = Depends(get_current_user)):
    models = catalog.list_models(model_type=1)  # 只返回 LLM 类型给对话页
    return [{
        "id": m["id"], "name": m["name"], "base_model": m["base_model"],
        "supplier": m["supplier"], "default_model": m["default_model"],
    } for m in models]


@router.get("")
async def list_ai_models(keyword: str = "", model_type: int = None):
    return catalog.list_models(keyword=keyword, model_type=model_type)


@router.get("/{model_id}")
async def get_ai_model(model_id: int):
    m = catalog.get_model(model_id)
    if not m:
        raise HTTPException(404, "模型不存在")
    return m


@router.post("")
async def create_ai_model(body: dict, request: Request,
                          admin: dict = Depends(require_admin)):
    mid = catalog.create_model(body)
    audit.log("create", "ai_model", str(mid), admin, request,
              after=catalog.get_model(mid))
    return {"id": mid}


@router.put("")
async def update_ai_model(body: dict, request: Request,
                          admin: dict = Depends(require_admin)):
    model_id = body.get("id")
    if not model_id:
        return {"error": "缺少 id"}
    before = catalog.get_model(model_id)
    ok = catalog.update_model(model_id, body)
    audit.log("update", "ai_model", str(model_id), admin, request,
              before=before, after=catalog.get_model(model_id) if ok else None)
    return {"ok": ok}


@router.delete("/{model_id}")
async def delete_ai_model(model_id: int, request: Request,
                          admin: dict = Depends(require_admin)):
    before = catalog.get_model(model_id)
    ok = catalog.delete_model(model_id)
    audit.log("delete", "ai_model", str(model_id), admin, request, before=before)
    return {"ok": ok}


@router.put("/default/{model_id}")
async def set_default_ai_model(model_id: int, request: Request,
                               admin: dict = Depends(require_admin)):
    ok = catalog.set_default_model(model_id)
    if not ok:
        return {"error": "模型不存在"}
    audit.log("update", "ai_model", f"default:{model_id}", admin, request)
    return {"ok": ok}


@router.post("/status")
async def test_ai_model(body: dict):
    """测试模型连接：用提供的 config 发一条简单请求验证可达性。"""
    from langchain.chat_models import init_chat_model
    from langchain_core.messages import HumanMessage
    try:
        base_model = body.get("base_model", "")
        api_key = body.get("api_key", "")
        api_domain = body.get("api_domain", "")
        kwargs = {"use_responses_api": False} if api_domain else {}
        if api_key:
            kwargs["api_key"] = api_key
        if api_domain:
            kwargs["base_url"] = api_domain
        llm = init_chat_model(base_model, **kwargs)
        r = await llm.ainvoke([HumanMessage(content="回复OK")])
        return {"success": True, "message": "连接成功", "reply": str(r.content)[:200]}
    except Exception as e:
        return {"success": False, "message": f"{type(e).__name__}: {e}"}
