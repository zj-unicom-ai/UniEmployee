"""受控保存会话产物快照的文件存储适配器。"""

import hashlib
import logging
import os
import shutil
import time
from pathlib import Path

logger = logging.getLogger("app.artifact_storage")
MAX_ARTIFACT_SIZE = 100 * 1024 * 1024


def snapshot_artifact(workspace_root: Path, user_id: str, conv_id: str,
                      turn_no: int | None, info: dict) -> dict | None:
    """把产物复制到隐藏的用户/会话私有目录，返回新的相对路径。

    根目录文件和用户目录文件都做快照：前者可能被其他用户会话覆盖，后者
    可能被同一用户的另一个会话覆盖。已归档路径直接返回，避免重复复制。
    """
    root = Path(workspace_root).resolve()
    rel = Path(str(info.get("path") or ""))
    if not rel.parts or rel.parts[0] == ".artifact-store":
        return info
    candidate = root
    for part in rel.parts:
        candidate = candidate / part
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
