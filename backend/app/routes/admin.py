"""管理后台路由：员工/技能/工具/知识库/SOP/连接器/用户/组织 CRUD + 分配管理。"""

import io
import json
import os
import re
import shutil
import time
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app import auth, catalog, runtime, traces
from app.models import (UserCreateIn, UserUpdateIn, PasswordIn,
                        OrgCreateIn, OrgUpdateIn)
from app.paths import PROJECT_ROOT

router = APIRouter(prefix="/api/admin", dependencies=[Depends(auth.require_admin)])

SKILLS_CUSTOM_DIR = PROJECT_ROOT / "backend" / "skills-custom"


# ---- 目录 + 默认值 ----

@router.get("/catalog")
async def admin_catalog():
    return catalog.catalog()


@router.get("/defaults")
async def admin_defaults():
    return {"model": os.environ.get("MODEL_NAME", "openai:deepseek-v4-flash")}


# ---- 员工 CRUD ----

@router.get("/employees")
async def admin_list_employees():
    return [catalog.get_full_employee(e["id"]) for e in catalog.list_employees_meta()]


@router.get("/employees/{emp_id}")
async def admin_get_employee(emp_id: str):
    cfg = catalog.get_full_employee(emp_id)
    if not cfg:
        return {"error": "员工不存在"}
    return cfg


@router.post("/employees")
async def admin_create_employee(body: dict):
    if body.get("kbs"):
        catalog.backfill_ragflow_knowledge_bases()
    emp_id = catalog.create_employee(body)
    runtime.invalidate(emp_id)
    return {"id": emp_id}


@router.put("/employees/{emp_id}")
async def admin_update_employee(emp_id: str, body: dict):
    if body.get("kbs"):
        catalog.backfill_ragflow_knowledge_bases()
    ok = catalog.update_employee(emp_id, body)
    if not ok:
        return {"error": "员工不存在"}
    runtime.invalidate(emp_id)
    return {"id": emp_id}


@router.delete("/employees/{emp_id}")
async def admin_delete_employee(emp_id: str):
    catalog.delete_employee(emp_id)
    runtime.invalidate(emp_id)
    return {"ok": True}


# ---- 技能上传/删除 ----

@router.post("/skills/upload")
async def upload_skill(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".zip"):
        return {"error": "只支持 .zip 文件"}
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        return {"error": "zip 过大（>20MB）"}
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return {"error": "无效的 zip 文件"}

    names = [n for n in zf.namelist() if not n.startswith("__MACOSX") and not n.endswith("/")]
    skill_md_name = next((n for n in names if n.endswith("/SKILL.md")), None) \
        or next((n for n in names if n == "SKILL.md"), None)
    if not skill_md_name:
        zf.close()
        return {"error": "zip 内未找到 SKILL.md"}

    skill_md = zf.read(skill_md_name).decode("utf-8", "replace")
    name = description = ""
    for line in skill_md.splitlines():
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("description:"):
            description = line.split(":", 1)[1].strip()
        elif line.strip() == "" and name:
            break

    if not name:
        zf.close()
        return {"error": "SKILL.md frontmatter 缺少 name 字段"}
    if not description:
        zf.close()
        return {"error": "SKILL.md frontmatter 缺少 description 字段"}

    raw = name or Path(file.filename).stem
    skill_id = re.sub(r"[^a-z0-9-]+", "-", raw.lower()).strip("-")
    if not skill_id:
        skill_id = "custom-skill"

    prefix = (skill_md_name.rsplit("/", 1)[0] + "/") if "/" in skill_md_name else ""
    target = SKILLS_CUSTOM_DIR / skill_id
    target.mkdir(parents=True, exist_ok=True)
    for child in target.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    base = str(target.resolve())
    for member in names:
        if prefix and not member.startswith(prefix):
            continue
        rel = member[len(prefix):]
        if not rel or rel.startswith("..") or Path(rel).is_absolute():
            continue
        dest = target / rel
        if not str(dest.resolve()).startswith(base):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(zf.read(member))
    zf.close()

    catalog.upsert_skill(skill_id, name or skill_id, description, f"skills-custom/{skill_id}")
    # 技能文件更新后，只刷新 Store 中的技能内容，不重建已编译 agent。
    affected = catalog.employees_using_skill(skill_id)
    await runtime.refresh_skills_for_employees(affected)
    return {"id": skill_id, "name": name or skill_id, "description": description}


@router.put("/skills/{skill_id}/content")
async def update_skill_content(skill_id: str, body: dict):
    """直接更新自定义技能 SKILL.md 内容，并只刷新 Store 中受影响的员工。"""
    content = body.get("content", "")
    if not isinstance(content, str) or not content.strip():
        return {"error": "SKILL.md 内容不能为空"}
    try:
        ok = catalog.update_skill_content(skill_id, content)
    except PermissionError:
        return {"error": "内置技能不允许直接修改内容"}
    if not ok:
        return {"error": "技能不存在"}
    affected = catalog.employees_using_skill(skill_id)
    await runtime.refresh_skills_for_employees(affected)
    return {"ok": True, "invalidated": False, "refreshed_employees": affected}


@router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str):
    info = catalog.get_skill(skill_id)
    if not info:
        return {"error": "技能不存在"}
    dir_ = info["dir"] or ""
    if not dir_.startswith("skills-custom/"):
        return {"error": "内置技能不允许删除"}
    affected = catalog.employees_using_skill(skill_id)
    catalog.delete_skill(skill_id)
    for emp_id in affected:
        runtime.invalidate(emp_id)
    return {"ok": True, "invalidated": affected}


@router.get("/skills/{skill_id}/content")
async def skill_content(skill_id: str):
    content = catalog.get_skill_content(skill_id)
    if content is None:
        return {"error": "技能不存在"}
    return {"content": content}


# ---- 资源中心 CRUD ----

@router.put("/tools/{tool_id}")
async def edit_tool(tool_id: str, body: dict):
    ok = catalog.update_tool(tool_id, body.get("description", ""), body.get("needs_approval"))
    if not ok:
        return {"error": "工具不存在"}
    for e in catalog.employees_using_tool(tool_id):
        runtime.invalidate(e)
    return {"ok": True}


@router.post("/knowledge-bases")
async def create_kb(body: dict):
    kid = body.get("id") or ("kb_" + time.strftime("%Y%m%d%H%M%S"))
    catalog.create_kb(kid, body.get("name", kid), body.get("description", ""),
                      body.get("ragflow_dataset_id", ""))
    return {"id": kid}


@router.get("/ragflow/datasets")
async def admin_ragflow_datasets():
    from app.connectors import ragflow_client
    if not ragflow_client.is_ragflow_configured():
        return {"datasets": [], "configured": False, "error": "RAGFLOW_API_KEY 未配置"}
    try:
        return {"datasets": ragflow_client.list_datasets(), "configured": True}
    except Exception as e:
        return {"datasets": [], "configured": True,
                "error": f"{type(e).__name__}: {e}"}


@router.put("/knowledge-bases/{kb_id}")
async def edit_kb(kb_id: str, body: dict):
    ok = catalog.update_kb(kb_id, body.get("name", ""), body.get("description", ""),
                           body.get("ragflow_dataset_id", ""))
    if ok:
        for e in catalog.employees_using_kb(kb_id):
            runtime.invalidate(e)
    return {"ok": ok}


@router.delete("/knowledge-bases/{kb_id}")
async def del_kb(kb_id: str):
    affected = catalog.delete_kb(kb_id)
    for e in affected:
        runtime.invalidate(e)
    return {"ok": True, "invalidated": affected}


@router.post("/sops")
async def create_sop(body: dict):
    sid = body.get("id") or ("sop_" + time.strftime("%Y%m%d%H%M%S"))
    catalog.create_sop(sid, body.get("name", sid), body.get("description", ""),
                       body.get("content", ""))
    return {"id": sid}


@router.put("/sops/{sop_id}")
async def edit_sop(sop_id: str, body: dict):
    ok = catalog.update_sop(sop_id, body.get("name", ""), body.get("description", ""),
                            body.get("content", ""))
    if ok:
        affected = catalog.employees_using_sop(sop_id)
        await runtime.refresh_sops_for_employees(affected)
    return {"ok": ok}


@router.delete("/sops/{sop_id}")
async def del_sop(sop_id: str):
    affected = catalog.delete_sop(sop_id)
    for e in affected:
        runtime.invalidate(e)
    return {"ok": True, "invalidated": affected}


@router.post("/connectors")
async def create_connector(body: dict):
    cid = body.get("id") or ("conn_" + time.strftime("%Y%m%d%H%M%S"))
    catalog.create_connector(cid, body.get("name", cid), body.get("description", ""),
                             body.get("config", {}))
    return {"cid": cid}


@router.get("/connectors/{conn_id}")
async def get_connector(conn_id: str):
    c = catalog.get_connector(conn_id)
    if not c:
        return {"error": "连接器不存在"}
    return c


@router.put("/connectors/{conn_id}")
async def edit_connector(conn_id: str, body: dict):
    ok = catalog.update_connector(conn_id, body.get("name", ""), body.get("description", ""),
                                  body.get("config", {}))
    for e in catalog._unlink_view("connector", conn_id):
        runtime.invalidate(e)
    return {"ok": ok}


@router.delete("/connectors/{conn_id}")
async def del_connector(conn_id: str):
    affected = catalog.delete_connector(conn_id)
    for e in affected:
        runtime.invalidate(e)
    return {"ok": True, "invalidated": affected}


# ---- 组织管理 ----

_ORG_ERRORS = {
    "not_found": "部门不存在",
    "cycle": "不能把部门移动到自身或其子部门下",
    "bad_parent": "父部门不存在",
    "has_children": "请先删除该部门的子部门",
    "has_members": "该部门下仍有用户，请先移出",
}


@router.get("/orgs")
async def list_orgs_api():
    return catalog.list_orgs()


@router.post("/orgs")
async def create_org_api(body: OrgCreateIn):
    if not body.name.strip():
        return {"error": "部门名称不能为空"}
    oid = catalog.create_org(body.name.strip(), body.parent_id, body.sort_order)
    if not oid:
        return {"error": "父部门不存在"}
    return {"id": oid, "name": body.name.strip()}


@router.put("/orgs/{oid}")
async def update_org_api(oid: str, body: OrgUpdateIn):
    err = catalog.update_org(oid, name=body.name.strip() if body.name else None,
                             parent_id=body.parent_id, sort_order=body.sort_order,
                             move=body.move)
    if err:
        return {"error": _ORG_ERRORS.get(err, err)}
    return {"ok": True}


@router.delete("/orgs/{oid}")
async def delete_org_api(oid: str):
    err = catalog.delete_org(oid)
    if err:
        return {"error": _ORG_ERRORS.get(err, err)}
    return {"ok": True}


# ---- 用户管理 ----

@router.get("/users")
async def list_users_api(page: int | None = None, page_size: int = 10,
                         org_id: str | None = None):
    if page:
        return catalog.list_users_paged(page, page_size, org_id=org_id)
    return catalog.list_users(org_id=org_id)


@router.post("/users")
async def create_user_api(body: UserCreateIn):
    if catalog.get_user_by_username(body.username):
        return {"error": "用户名已存在"}
    if body.role not in ("admin", "user"):
        return {"error": "role 必须是 admin 或 user"}
    if body.org_id and not catalog.get_org(body.org_id):
        return {"error": "归属部门不存在"}
    uid = catalog.create_user(body.username, auth.hash_password(body.password),
                              role=body.role, org_id=body.org_id)
    return {"id": uid, "username": body.username, "role": body.role}


@router.put("/users/{uid}")
async def update_user_api(uid: str, body: UserUpdateIn, admin: dict = Depends(auth.require_admin)):
    if uid == admin["id"] and body.status == "disabled":
        return {"error": "不能禁用当前登录的管理员"}
    if body.set_org and body.org_id and not catalog.get_org(body.org_id):
        return {"error": "归属部门不存在"}
    ok = catalog.update_user(uid, role=body.role, status=body.status,
                             org_id=body.org_id, set_org=body.set_org)
    return {"ok": ok}


@router.put("/users/{uid}/password")
async def reset_password_api(uid: str, body: PasswordIn):
    ok = catalog.set_password(uid, auth.hash_password(body.password))
    return {"ok": ok}


@router.delete("/users/{uid}")
async def delete_user_api(uid: str, admin: dict = Depends(auth.require_admin)):
    if uid == admin["id"]:
        return {"error": "不能删除当前登录的管理员"}
    admins = [u for u in catalog.list_users() if u["role"] == "admin" and u["status"] == "active"]
    target = catalog.get_user(uid)
    if target and target["role"] == "admin" and len(admins) <= 1:
        return {"error": "至少保留一个管理员"}
    return {"ok": catalog.delete_user(uid)}


# ---- 用户-员工分配 ----

@router.get("/users/{uid}/employees")
async def admin_list_user_employees(uid: str):
    if not catalog.get_user(uid):
        return {"error": "用户不存在"}
    assigns = {a["employee_id"]: a["overrides"] for a in catalog.list_assignments(uid)}
    emps = catalog.list_employees_meta()
    return {
        "user_id": uid,
        "employees": [{
            "employee_id": e["id"], "name": e["name"], "role": e["role"],
            "granted": e["id"] in assigns, "overrides": assigns.get(e["id"], {}),
        } for e in emps],
    }


@router.post("/users/{uid}/employees")
async def admin_assign_employee(uid: str, body: dict,
                                admin: dict = Depends(auth.require_admin)):
    if not catalog.get_user(uid):
        return {"error": "用户不存在"}
    emp_id = body.get("employee_id")
    if not catalog.get_employee_config(emp_id):
        return {"error": "员工不存在"}
    catalog.assign_employee(uid, emp_id, body.get("overrides"), granted_by=admin["id"])
    runtime.invalidate(emp_id)
    return {"ok": True, "employee_id": emp_id}


@router.put("/users/{uid}/employees/{emp_id}")
async def admin_update_assignment(uid: str, emp_id: str, body: dict,
                                  admin: dict = Depends(auth.require_admin)):
    if not catalog.get_assignment(uid, emp_id):
        return {"error": "该用户未分配此员工"}
    catalog.set_assignment_overrides(uid, emp_id, body.get("overrides", {}))
    runtime.invalidate(emp_id)
    return {"ok": True}


@router.delete("/users/{uid}/employees/{emp_id}")
async def admin_unassign_employee(uid: str, emp_id: str,
                                   admin: dict = Depends(auth.require_admin)):
    ok = catalog.unassign_employee(uid, emp_id)
    runtime.invalidate(emp_id)
    return {"ok": ok}


# ── 运行评估 ──────────────────────────────────────────────────────

@router.get("/evaluation/stats")
async def admin_evaluation_stats(employee_id: str = "", period: str = "30d",
                                  admin: dict = Depends(auth.require_admin)):
    return traces.get_evaluation_stats(employee_id or None, period)


@router.get("/evaluation/feedback")
async def admin_evaluation_feedback(employee_id: str = "", rating: int = None,
                                     limit: int = 50, offset: int = 0,
                                     admin: dict = Depends(auth.require_admin)):
    return traces.get_feedback_list(employee_id or None, rating, limit, offset)
