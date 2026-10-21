"""按会话导出原始解题事件、附件、产物与非敏感配置，并标记缺失记录。"""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import zipfile

from app.paths import DATA_DIR, WORKSPACE_DATA
from .records import encode, record_dir


def export_conversation(meta, config, artifacts):
    tenant, user, conv = meta["tenant_id"], meta["user_id"], meta["conv_id"]
    if any(Path(value).name != value or value in {".", ".."} for value in (user, conv)):
        raise ValueError("无效的会话或用户标识")
    records = sorted(record_dir(tenant, user, conv).glob("*.jsonl"))
    if not records:
        raise ValueError("该会话尚无完整实操记录；历史 Trace 预览不能冒充完整记录")
    sources = [(f"records/{path.name}", path, record_dir(tenant, user, conv)) for path in records]
    for subdir in (Path(user) / "uploads" / conv, Path(user) / "security-tasks" / conv):
        sources.extend((path.relative_to(WORKSPACE_DATA).as_posix(), path, WORKSPACE_DATA)
                       for path in (WORKSPACE_DATA / subdir).rglob("*") if path.is_file())
    sources.extend((f"artifacts/{item['artifact_id']}/{Path(item['name']).name}",
                    WORKSPACE_DATA / item["path"], WORKSPACE_DATA) for item in artifacts)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="security-export-", suffix=".zip", dir=DATA_DIR)
    os.close(fd)
    target = Path(name)
    manifest, total = [], 0
    try:
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for arcname, path, boundary in sources:
                if path.absolute() != path.resolve() or not path.resolve().is_relative_to(boundary.resolve()):
                    raise ValueError("导出拒绝符号链接或工作目录之外的文件")
                if total + path.stat().st_size > 200 * 1024 * 1024:
                    raise ValueError("导出超过 200MB，请先整理产物；不会静默丢弃文件")
                payload = path.read_bytes()
                total += len(payload)
                archive.writestr(arcname, payload)
                manifest.append({"path": arcname, "bytes": len(payload),
                                 "sha256": hashlib.sha256(payload).hexdigest()})
            incomplete = []
            for path in records:
                events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
                if not events or events[-1].get("event") != "run_finished":
                    incomplete.append(path.name)
            archive.writestr("manifest.json", encode({
                "conversation_id": conv, "title": meta.get("title", ""), "files": manifest,
                "incomplete_runs": incomplete, "format": "UniEmployee security v1; 待适配官方格式",
                "source_code": "源码需另行提交；本包仅含本题记录、脚本、附件及产物",
            }))
            archive.writestr("employee.json", encode({key: config.get(key) for key in
                              ("id", "name", "role", "model", "persona", "skills", "tools")}))
            from .policy import enabled
            if enabled("net-ops"):
                archive.writestr("competition.json", encode({
                    "model": os.environ.get("COMPETITION_MODEL", ""),
                    "base_url": os.environ.get("COMPETITION_BASE_URL", ""),
                    "note": "赛事模式使用此配置覆盖员工默认模型；不导出认证密钥",
                }))
        return target
    except BaseException:
        target.unlink(missing_ok=True)
        raise
