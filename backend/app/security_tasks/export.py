"""按会话导出原始解题事件、附件、产物与非敏感配置，并标记缺失记录。"""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import zipfile
from datetime import datetime

from app.paths import DATA_DIR, WORKSPACE_DATA
from .records import encode, record_dir


def _stamp(entry):
    try:
        return datetime.fromisoformat(entry["time"]).timestamp()
    except (KeyError, TypeError, ValueError):
        return None


def timing_summary(records):
    """从完整事件记录算出每题每轮的耗时与调用次数；比赛按耗时排序，必须有数。"""
    runs, unknown = {}, []
    for path in records:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            run = entry.get("run_id") or "?"
            state = runs.setdefault(run, {"started": None, "finished": None, "model_calls": 0,
                                          "model_errors": 0, "tool_calls": 0, "tool_errors": 0,
                                          "open_model": {}, "open_tool": {},
                                          "model_seconds": 0.0, "tool_seconds": 0.0,
                                          "by_tool": {}})
            when, event = _stamp(entry), entry.get("event")
            if event == "run_started" and state["started"] is None:
                state["started"] = when
            elif event == "run_finished":
                state["finished"] = when
            elif event == "model_started":
                state["model_calls"] += 1
                state["open_model"][entry.get("call_id")] = when
            elif event == "model_finished":
                began = state["open_model"].pop(entry.get("call_id"), None)
                if began is not None and when is not None:
                    state["model_seconds"] += when - began
            elif event == "model_error":
                state["model_errors"] += 1
                state["open_model"].pop(entry.get("call_id"), None)
            elif event == "tool_started":
                state["tool_calls"] += 1
                name = entry.get("tool") or "unknown"
                state["by_tool"].setdefault(name, {"count": 0, "seconds": 0.0})["count"] += 1
                state["open_tool"][entry.get("call_id")] = (when, name)
            elif event == "tool_finished":
                began = state["open_tool"].pop(entry.get("call_id"), None)
                if began and when is not None and began[0] is not None:
                    bucket = state["by_tool"].setdefault(began[1], {"count": 0, "seconds": 0.0})
                    bucket["seconds"] += when - began[0]
                    state["tool_seconds"] += when - began[0]
            elif event == "tool_error":
                state["tool_errors"] += 1
                state["open_tool"].pop(entry.get("call_id"), None)
    rows = []
    for run, state in runs.items():
        for call_id, (began, name) in state["open_tool"].items():
            if began is not None:
                unknown.append(f"{run}:{call_id}:{name}:未闭合")
        wall = (state["finished"] - state["started"]) if None not in (state["started"], state["finished"]) else None
        rows.append({"run_id": run, "started": state["started"], "wall_seconds": round(wall, 3) if wall else None,
                     "model_calls": state["model_calls"], "model_errors": state["model_errors"],
                     "model_seconds": round(state["model_seconds"], 3),
                     "tool_calls": state["tool_calls"], "tool_errors": state["tool_errors"],
                     "tool_seconds": round(state["tool_seconds"], 3),
                     "by_tool": {k: {"count": v["count"], "seconds": round(v["seconds"], 3)}
                                 for k, v in sorted(state["by_tool"].items())},
                     "other_seconds": round((wall or 0) - state["model_seconds"] - state["tool_seconds"], 3)
                     if wall else None})
    rows.sort(key=lambda r: r["started"] or 0)
    done = [r for r in rows if r["wall_seconds"]]
    return {"runs": rows, "summary": {
        "runs": len(rows), "completed_runs": len(done),
        "total_wall_seconds": round(sum(r["wall_seconds"] or 0 for r in done), 3),
        "max_wall_seconds": max((r["wall_seconds"] or 0 for r in done), default=None),
        "total_model_seconds": round(sum(r["model_seconds"] for r in rows), 3),
        "total_tool_seconds": round(sum(r["tool_seconds"] for r in rows), 3),
        "total_model_calls": sum(r["model_calls"] for r in rows),
        "total_tool_calls": sum(r["tool_calls"] for r in rows)},
        "unclosed_tool_calls": unknown[:20]}


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
            archive.writestr("timing.json", encode(timing_summary(records)))
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
