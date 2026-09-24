"""数字员工产物工作区：个人归档、部门分享、受 ACL 控制的预览和下载。"""
import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse

from app import audit, auth, conversations
from app import paths as app_paths
from app.artifact_storage import snapshot_artifact
from app.docx_preview import render_docx_html

router = APIRouter(prefix="/api")


def _workspace_root() -> Path:
    return Path(app_paths.WORKSPACE_DATA).resolve()


def _normalize_rel(path: str) -> Path:
    """把各种形态的路径归一为相对 WORKSPACE_DATA 的 Path（含越界校验）。"""
    p = (path or "").strip().replace("\\", "/")
    for prefix in ("/data/", "data/", "workspace/data/", "/workspace/data/"):
        if p.startswith(prefix):
            p = p[len(prefix):]
            break
    raw = Path(p)
    if raw.is_absolute():
        # 绝对路径仅当其位于 WORKSPACE_DATA 内时放行（统一转相对）；
        # 注意绝对路径判定必须在 lstrip("/") 之前，否则会被误判为相对路径。
        try:
            return raw.resolve().relative_to(_workspace_root())
        except ValueError:
            raise HTTPException(403, "路径越界")
    p = p.lstrip("/")
    if not p or p == ".":
        raise HTTPException(400, "缺少有效的文件路径")
    return Path(p)


def _resolve_file(rel: Path) -> Path:
    root = _workspace_root()
    candidate = root
    for part in rel.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise HTTPException(403, "不允许通过符号链接访问产物")
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise HTTPException(403, "路径越界")
    if not target.is_file():
        raise HTTPException(404, "文件不存在")
    return target


async def _ensure_private_snapshot(artifact: dict) -> dict:
    """首次读写旧版产物时迁移为会话私有快照，保持同一产物 ID。"""
    rel = _normalize_rel(artifact["path"])
    if rel.parts and rel.parts[0] == ".artifact-store":
        return artifact
    snapshot = await asyncio.to_thread(snapshot_artifact,
        _workspace_root(), artifact["owner_id"], artifact["conv_id"], artifact.get("turn_no"),
        {"name": artifact["name"], "path": rel.as_posix(), "size": artifact.get("size", 0)},
    )
    if not snapshot:
        raise HTTPException(503, "产物快照暂不可用，请稍后重试")
    conversations.update_artifact_path(
        artifact["artifact_id"], snapshot["path"], snapshot.get("size", 0))
    return conversations.get_artifact(artifact["artifact_id"]) or artifact


@router.get("/workspace/artifacts")
async def list_workspace_artifacts(
    q: str = "", scope: str = "all", page: int = 1, page_size: int = 24,
    show_scripts: bool = False,
    user: dict = Depends(auth.get_current_user),
):
    """列出我创建的产物和共享到我所在部门的产物。"""
    if scope not in {"all", "mine", "shared"}:
        raise HTTPException(422, "scope 仅支持 all、mine、shared")
    result = conversations.list_workspace_artifacts(
        user["id"], user.get("tenant_id", "default"), user.get("org_id"),
        role=user.get("role", "user"), scope=scope, query=q,
        page=page, page_size=page_size, show_scripts=show_scripts,
    )
    # 删除或迁移文件后，索引仍可能存在；工作区仅显示当前可打开的产物。
    visible = []
    for item in result["items"]:
        item["can_share"] = bool(item["is_owner"] and user.get("org_id"))
        if not item["is_owner"]:
            # 分享只暴露文件本身，不顺带泄露原会话标题、数字员工或会话 ID。
            item["conv_id"] = None
            item["employee_id"] = None
            item["conversation_title"] = ""
            item["owner_id"] = None
            item["turn_no"] = None
        try:
            target = _resolve_file(_normalize_rel(item["path"]))
        except HTTPException:
            continue
        item["size"] = target.stat().st_size
        if not item["is_owner"]:
            item["path"] = None
        visible.append(item)
    result["items"] = visible
    return result


@router.put("/workspace/artifacts/{artifact_id}/department-share")
async def set_department_share(artifact_id: int, body: dict, request: Request,
                               user: dict = Depends(auth.get_current_user)):
    """把本人产物共享到当前部门，或撤销该部门的访问权。"""
    if not isinstance(body.get("shared"), bool):
        raise HTTPException(422, "shared 必须是布尔值")
    before = conversations.get_artifact(artifact_id)
    tenant_id = user.get("tenant_id", "default")
    if (body["shared"] and user.get("org_id") and before and before["tenant_id"] == tenant_id
            and before["owner_id"] == user["id"]):
        before = await _ensure_private_snapshot(before)
    result = conversations.set_artifact_department_share(
        artifact_id, user["id"], tenant_id,
        user.get("org_id"), body["shared"],
    )
    if result == "not_found":
        raise HTTPException(404, "产物不存在")
    if result == "forbidden":
        raise HTTPException(403, "只有产物创建者可以管理共享")
    if result == "no_department":
        raise HTTPException(400, "账号尚未加入部门，暂不能使用部门共享")
    after = conversations.get_artifact(artifact_id)
    audit.log("update", "artifact_share", str(artifact_id), user, request,
              before={"shared_org_id": (before or {}).get("shared_org_id")},
              after={"shared_org_id": (after or {}).get("shared_org_id")})
    return {"ok": True, "shared_with_department": body["shared"]}


@router.get("/workspace/artifacts/{artifact_id}/file")
async def download_artifact(artifact_id: int,
                            user: dict = Depends(auth.get_current_user)):
    artifact = conversations.get_accessible_artifact(
        artifact_id, user["id"], user.get("tenant_id", "default"),
        user.get("org_id"), user.get("role", "user"),
    )
    if not artifact:
        raise HTTPException(404, "产物不存在")
    artifact = await _ensure_private_snapshot(artifact)
    target = _resolve_file(_normalize_rel(artifact["path"]))
    return FileResponse(target, filename=artifact["name"])


@router.get("/workspace/artifacts/{artifact_id}/preview")
async def preview_artifact(artifact_id: int,
                           user: dict = Depends(auth.get_current_user)):
    """Render a DOCX after the same tenant/department ACL check as downloads."""
    artifact = conversations.get_accessible_artifact(
        artifact_id, user["id"], user.get("tenant_id", "default"),
        user.get("org_id"), user.get("role", "user"),
    )
    if not artifact:
        raise HTTPException(404, "产物不存在")
    if Path(artifact["name"]).suffix.lower() != ".docx":
        raise HTTPException(415, "仅支持预览 DOCX 文档")
    artifact = await _ensure_private_snapshot(artifact)
    target = _resolve_file(_normalize_rel(artifact["path"]))
    try:
        rendered = await asyncio.to_thread(render_docx_html, target)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return HTMLResponse(rendered, headers={"Content-Disposition": "inline"})


@router.get("/workspace/file")
async def download_workspace_file(
    path: str = Query(..., description="相对 workspace/data 的文件路径"),
    user: dict = Depends(auth.get_current_user_or_fallback),
):
    rel = _normalize_rel(path)
    target = _resolve_file(rel)
    registered = conversations.get_accessible_artifact_by_path(
        rel.as_posix(), user["id"], user.get("tenant_id", "default"),
        user.get("org_id"), user.get("role", "user"),
    )
    if registered:
        registered = await _ensure_private_snapshot(registered)
        target = _resolve_file(_normalize_rel(registered["path"]))
    if registered is None:
        first = rel.parts[0] if rel.parts else ""
        # 兼容旧版单企业共享工作区：根级文件是共享文件，本人 UID 目录属于本人。
        # 管理员保留 workspace 范围内的运维访问；普通用户不能访问他人 UID 目录。
        if user.get("role") != "admin" and len(rel.parts) > 1 and first != user.get("id"):
            raise HTTPException(403, "无权访问其他用户的产物目录")
    return FileResponse(target, filename=target.name)


@router.get("/workspace/preview")
async def preview_workspace_file(
    path: str = Query(..., description="相对 workspace/data 的文件路径"),
    user: dict = Depends(auth.get_current_user_or_fallback),
):
    """Compatibility preview route for older chat cards without an artifact ID."""
    rel = _normalize_rel(path)
    target = _resolve_file(rel)
    registered = conversations.get_accessible_artifact_by_path(
        rel.as_posix(), user["id"], user.get("tenant_id", "default"),
        user.get("org_id"), user.get("role", "user"),
    )
    if registered:
        registered = await _ensure_private_snapshot(registered)
        target = _resolve_file(_normalize_rel(registered["path"]))
    else:
        first = rel.parts[0] if rel.parts else ""
        if user.get("role") != "admin" and len(rel.parts) > 1 and first != user.get("id"):
            raise HTTPException(403, "无权访问其他用户的产物目录")
    if target.suffix.lower() != ".docx":
        raise HTTPException(415, "仅支持预览 DOCX 文档")
    try:
        rendered = await asyncio.to_thread(render_docx_html, target)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return HTMLResponse(rendered, headers={"Content-Disposition": "inline"})
