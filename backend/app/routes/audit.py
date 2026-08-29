"""管理端审计日志查询端点（仅 admin）。写入在各变更端点内调用 audit.log()。"""
from fastapi import APIRouter, Depends

from app import audit
from app import auth

router = APIRouter(prefix="/api/admin/audit")


@router.get("/logs")
async def list_audit_logs(limit: int = 50, offset: int = 0,
                          obj_type: str = "", actor_id: str = "",
                          action: str = "", _=Depends(auth.require_admin)):
    limit = min(max(limit, 1), 200)
    logs, total = audit.list_logs(limit, offset, obj_type, actor_id, action)
    return {"logs": logs, "total": total}
