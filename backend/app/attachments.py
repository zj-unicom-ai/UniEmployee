"""对话附件处理：上传落盘 + 用户消息附件信息注入。

设计：附件保存到 workspace/data/uploads/{uid}/{conv_id}/ 下。
编译层已把 /data/ 虚拟路由挂到 FilesystemBackend(WORKSPACE_DATA)，
因此所有员工（含 StateBackend 后端）都能 read_file("/data/...") 读取，
数据分析师还可用 run_python + pandas 直接分析上传的数据文件，
无需为附件新增任何 agent 工具。
"""
import os
import re
import time

from fastapi import HTTPException, UploadFile

from app.paths import WORKSPACE_DATA

# 单文件大小上限（字节），默认 20MB
MAX_ATTACHMENT_SIZE = int(os.environ.get("MAX_ATTACHMENT_SIZE", str(20 * 1024 * 1024)))
# 单条消息附件数量上限
MAX_ATTACHMENTS_PER_MESSAGE = 5
CHUNK_SIZE = 1024 * 1024


def _sanitize_name(name: str) -> str:
    """文件名清洗：只保留字母数字/中文/点/横杠/下划线，限长 80。"""
    clean = re.sub(r"[^\w.\-]", "_", name or "file", flags=re.UNICODE).strip("._") or "file"
    return clean[:80]


async def save_attachment(conv_id: str, uid: str, file: UploadFile) -> dict:
    """把上传文件落盘到 uploads/{uid}/{conv_id}/{毫秒时间戳}_{清洗后文件名}。

    返回前端可直接回传 MessageIn.attachments 的条目（name 为原始文件名，
    path 为 agent 可 read_file 的 /data/ 虚拟路径）。
    """
    stored = f"{int(time.time() * 1000)}_{_sanitize_name(file.filename)}"
    target_dir = WORKSPACE_DATA / "uploads" / uid / conv_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / stored

    size = 0
    try:
        with open(target, "wb") as out:
            while chunk := await file.read(CHUNK_SIZE):
                size += len(chunk)
                if size > MAX_ATTACHMENT_SIZE:
                    raise HTTPException(413, f"附件超过大小限制 {MAX_ATTACHMENT_SIZE // 1024 // 1024}MB")
                out.write(chunk)
    finally:
        await file.close()
    if size == 0:
        target.unlink(missing_ok=True)
        raise HTTPException(400, "附件内容为空")
    return {
        "name": file.filename or stored,
        "path": f"/data/uploads/{uid}/{conv_id}/{stored}",
        "size": size,
        "content_type": file.content_type or "",
    }


def validate_attachment_path(uid: str, path: str) -> bool:
    """校验消息里回传的附件路径：必须是本用户上传目录内的 /data/ 虚拟路径。"""
    return (
        isinstance(path, str)
        and path.startswith(f"/data/uploads/{uid}/")
        and ".." not in path
    )


def _human_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f}MB"
    if size >= 1024:
        return f"{size / 1024:.0f}KB"
    return f"{size}B"


def compose_user_content(message: str, attachments: list[dict]) -> str:
    """把附件清单拼进用户消息文本，供 agent 感知并按路径读取。

    附件不作为多模态内容传给模型，而是以结构化文本注入——
    这与现有纯文本消息管线（checkpointer/reconstruct/记忆）完全兼容。
    """
    if not attachments:
        return message
    lines = [message] if message and message.strip() else []
    lines.append("")
    lines.append("[用户上传了以下附件，文件已保存可访问]")
    for a in attachments:
        ctype = a.get("content_type") or "未知类型"
        lines.append(f"- {a.get('name', '未命名')}｜路径 {a.get('path')}｜"
                     f"{_human_size(int(a.get('size', 0)))}｜{ctype}")
    lines.append("处理指引：文本/代码/JSON 等用 read_file(路径) 读取；"
                 "csv/xlsx 等数据文件用 run_python + pandas 按路径分析。")
    return "\n".join(lines)
