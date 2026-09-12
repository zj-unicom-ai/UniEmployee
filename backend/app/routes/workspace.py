"""工作区文件服务：数字员工产物（Word 方案/投诉记录/拜访纪要等）的下载与预览。

数字员工经 execute/write_file 落在 workspace/data/ 下的产物，此前只以文本路径
出现在回答里，前端无法下载或预览（本地演示与服务器部署均不可用）。本路由把
workspace/data 作为受控根目录对外提供只读访问：

  GET /api/workspace/file?path=<相对 workspace/data 的文件路径>

路径归一：接受相对路径（解决方案_x.docx、u_admin/xx.docx）、/data/ 虚拟路径、
workspace/data/ 前缀路径，以及 WORKSPACE_DATA 内的绝对路径。

安全与权限：
  - 路径穿越防护：resolve() 后必须仍在 WORKSPACE_DATA 内，否则 403。
  - 用户隔离：本地模式 execute cwd=项目根，产物常落在 workspace/data 根，
    根级产物视为共享产物（登录用户可读）；<uid>/ 前缀目录按用户隔离，
    仅本人与管理员可读（与沙箱按 <uid> subPath 隔离的语义一致）。
"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app import auth
from app import paths as app_paths
from app.catalog import db as catalog_db

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


def _is_user_id(name: str) -> bool:
    """判断目录名是否是真实存在的用户 id（用于 <uid>/ 隔离目录判定）。"""
    con = None
    try:
        con = catalog_db._conn()
        row = con.execute("SELECT 1 FROM users WHERE id=?", (name,)).fetchone()
        return bool(row)
    except Exception:
        return False
    finally:
        if con is not None:
            con.close()


@router.get("/workspace/file")
async def download_workspace_file(
    path: str = Query(..., description="相对 workspace/data 的文件路径"),
    user: dict = Depends(auth.get_current_user_or_fallback),
):
    root = _workspace_root()
    rel = _normalize_rel(path)
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise HTTPException(403, "路径越界")
    if not target.is_file():
        raise HTTPException(404, "文件不存在")
    if user.get("role") != "admin":
        first = rel.parts[0] if rel.parts else ""
        # 首段目录若是其他用户的 id（如 u_xxx/），按用户隔离拒绝；根级产物共享可读。
        if first and first != user.get("id") and _is_user_id(first):
            raise HTTPException(403, "无权访问其他用户的文件")
    return FileResponse(target, filename=target.name)
