"""受控保存会话产物快照的文件存储适配器。"""

import hashlib
import logging
import os
import shutil
import time
from pathlib import Path

logger = logging.getLogger("app.artifact_storage")


def snapshot_root_artifact(workspace_root: Path, user_id: str, conv_id: str,
                           turn_no: int | None, info: dict) -> dict | None:
    """把 workspace 根目录文件复制到隐藏的用户/会话私有目录，返回新的相对路径。

    用户目录内的文件已经按用户隔离，直接保留原路径。根目录文件则必须快照，
    因为 local-shell 员工会在共享工作目录生成同名文件。
    """
    root = Path(workspace_root).resolve()
    rel = Path(str(info.get("path") or ""))
    if not rel.parts or (len(rel.parts) > 1 and rel.parts[0] == user_id):
        return info
    candidate = root / rel
    if candidate.is_symlink():
        logger.warning("产物快照拒绝符号链接: %s", info.get("path"))
        return None
    source = candidate.resolve()
    try:
        source.relative_to(root)
    except ValueError:
        logger.warning("产物快照路径越界，跳过登记: %s", info.get("path"))
        return None
    if not source.is_file():
        return None

    user_key = hashlib.sha256((user_id or "default").encode()).hexdigest()[:24]
    conv_key = hashlib.sha256(conv_id.encode()).hexdigest()[:24]
    source_key = hashlib.sha256(rel.as_posix().encode()).hexdigest()[:10]
    turn_key = str(turn_no) if turn_no is not None else str(time.time_ns())
    name = Path(str(info.get("name") or source.name)).name
    archive_dir = root / ".artifact-store" / user_key / conv_key
    target = archive_dir / f"turn-{turn_key}-{source_key}-{name}"
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        # Refuse a symlinked store path so an agent-created link cannot redirect the copy.
        if archive_dir.resolve() != archive_dir or target.is_symlink():
            logger.warning("产物快照目录异常，跳过登记: %s", info.get("path"))
            return None
        temp = target.with_name(target.name + f".{time.time_ns()}.tmp")
        shutil.copy2(source, temp)
        os.replace(temp, target)
        size = target.stat().st_size
    except OSError as exc:
        try:
            if "temp" in locals():
                temp.unlink(missing_ok=True)
        except OSError:
            pass
        logger.warning("产物快照保存失败，跳过登记: %s (%s)", info.get("path"), exc)
        return None
    return {**info, "path": target.relative_to(root).as_posix(), "size": size}
