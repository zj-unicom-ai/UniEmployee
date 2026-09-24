"""Persist report HTML emitted inline in assistant messages as workspace artifacts."""

from __future__ import annotations

import hashlib
import html
import logging
import os
import re
import time
from html.parser import HTMLParser
from pathlib import Path

from app import conversations
from app.artifact_storage import MAX_ARTIFACT_SIZE
from app.paths import WORKSPACE_DATA

logger = logging.getLogger("app.report_artifacts")

_REPORT_RE = re.compile(
    r"<!--\s*REPORT_HTML_START\s*-->([\s\S]*?)<!--\s*REPORT_HTML_END\s*-->",
    re.IGNORECASE,
)


class _TitleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.parts.append(data)


def _is_renderable_report(value: str) -> bool:
    source = (value or "").strip()
    if len(source) < 80:
        return False
    return bool(
        re.search(r"<!doctype\s+html", source, re.IGNORECASE)
        or (re.search(r"<html[\s>]", source, re.IGNORECASE)
            and re.search(r"</html\s*>", source, re.IGNORECASE))
        or (re.search(r"<(?:head|body|div|section|main|script|style|canvas|svg)[\s>]",
                      source, re.IGNORECASE)
            and re.search(r"</(?:div|section|main|script|style|canvas|svg)\s*>",
                          source, re.IGNORECASE))
    )


def extract_inline_reports(content: str) -> list[str]:
    """Extract valid REPORT_HTML blocks and de-duplicate identical blocks."""
    if not isinstance(content, str) or not content:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for match in _REPORT_RE.finditer(content):
        report = match.group(1).strip()
        fence = re.fullmatch(r"```(?:html)?\s*\n([\s\S]*?)\n```", report, re.IGNORECASE)
        if fence:
            report = fence.group(1).strip()
        if not _is_renderable_report(report):
            continue
        digest = hashlib.sha256(report.encode("utf-8")).hexdigest()
        if digest not in seen:
            found.append(report)
            seen.add(digest)
    return found


def _report_title(report: str) -> str:
    parser = _TitleParser()
    try:
        parser.feed(report[:200_000])
    except Exception:
        return "数据分析报告"
    title = re.sub(r"\s+", " ", html.unescape("".join(parser.parts))).strip()
    title = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", title).strip(" ._")
    return (title[:72] or "数据分析报告")


def save_inline_report(workspace_root: Path, user_id: str, conv_id: str,
                       turn_no: int | None, report: str) -> dict | None:
    """Write an inline report into the private artifact store using a stable path."""
    if not _is_renderable_report(report):
        return None
    payload = report.encode("utf-8")
    if len(payload) > MAX_ARTIFACT_SIZE:
        logger.warning("内嵌看板超过产物大小限制，跳过归档 conv=%s size=%d", conv_id, len(payload))
        return None

    root = Path(workspace_root).resolve()
    user_key = hashlib.sha256((user_id or "default").encode()).hexdigest()[:24]
    conv_key = hashlib.sha256(conv_id.encode()).hexdigest()[:24]
    digest = hashlib.sha256(payload).hexdigest()
    turn_key = str(turn_no) if turn_no is not None else "unknown"
    name = f"{_report_title(report)}-T{turn_key}-{digest[:10]}.html"
    archive_dir = root / ".artifact-store" / user_key / conv_key / "inline-reports"
    target = archive_dir / name
    try:
        if any(part.is_symlink() for part in (
            root / ".artifact-store", root / ".artifact-store" / user_key,
            root / ".artifact-store" / user_key / conv_key, archive_dir,
        )):
            logger.warning("内嵌看板归档目录包含符号链接，跳过 conv=%s", conv_id)
            return None
        archive_dir.mkdir(parents=True, exist_ok=True)
        resolved_dir = archive_dir.resolve()
        if root not in resolved_dir.parents or target.is_symlink():
            logger.warning("内嵌看板归档路径越界，跳过 conv=%s", conv_id)
            return None
        if not target.is_file() or target.stat().st_size != len(payload):
            temp = archive_dir / f".{digest}.{time.time_ns()}.tmp"
            try:
                with temp.open("xb") as out:
                    out.write(payload)
                os.replace(temp, target)
            finally:
                temp.unlink(missing_ok=True)
        return {"name": name, "path": target.relative_to(root).as_posix(),
                "size": target.stat().st_size, "turn_no": turn_no}
    except OSError as exc:
        logger.warning("内嵌看板归档失败 conv=%s (%s)", conv_id, exc)
        return None


def archive_inline_reports(content: str, user_id: str, conv_id: str,
                           turn_no: int | None) -> list[dict]:
    """Save and index report blocks from one assistant response."""
    saved: list[dict] = []
    for report in extract_inline_reports(content):
        item = save_inline_report(WORKSPACE_DATA, user_id, conv_id, turn_no, report)
        if not item:
            continue
        artifact_id = conversations.add_file(
            conv_id, item["name"], item["path"], item["size"], turn_no,
            artifact_type="inline_report",
        )
        if artifact_id:
            saved.append({**item, "artifact_id": artifact_id,
                          "artifact_type": "inline_report"})
    return saved


def _message_text(message) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content
                       if isinstance(part, dict) and part.get("type") == "text")
    return ""


def archive_assistant_reports(messages: list, user_id: str,
                              conv_id: str) -> list[dict]:
    """Idempotently backfill report blocks from persisted assistant messages only."""
    turn_no = 0
    saved: list[dict] = []
    seen_artifact_ids: set[int] = set()
    for message in messages or []:
        kind = type(message).__name__
        if kind == "HumanMessage":
            turn_no += 1
            continue
        if kind != "AIMessage":
            # ToolMessage bodies can echo a file or a skill template. Only the
            # user-facing assistant answer should become a workspace artifact.
            continue
        for artifact in archive_inline_reports(_message_text(message), user_id,
                                              conv_id, turn_no or None):
            artifact_id = artifact.get("artifact_id")
            if artifact_id not in seen_artifact_ids:
                saved.append(artifact)
                if artifact_id is not None:
                    seen_artifact_ids.add(artifact_id)
    return saved
