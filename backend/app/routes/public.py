"""公开只读路由：无需登录（落地页 / 案例页等营销页面使用）。

只暴露数字员工的基础元数据（id/name/role/model/skills/tools），
不暴露人设、SOP、知识库内容等内部配置。
"""

from fastapi import APIRouter, HTTPException

from app import runtime

router = APIRouter(prefix="/api/public")


@router.get("/employees")
async def public_employees():
    return runtime.discover_employees()


@router.get("/employees/{emp_id}")
async def public_employee(emp_id: str):
    emp = next((e for e in runtime.discover_employees() if e["id"] == emp_id), None)
    if not emp:
        raise HTTPException(404, "员工不存在")
    return emp
