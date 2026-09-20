"""简报发布工具：publish_briefing —— 市场简报的归档 + 外发闸门（需人工审批）。

V2 自动值守闭环的发布动作：market-daily-brief 生成看板后调用本工具提交发布。
工具在 tools 表登记 needs_approval=["approve","reject"]，编译层据此自动派生
interrupt_on，人工批准前工具不执行、内容不外发；批准后归档为 HTML 文件
（文件卡片可下载），配置了 MARKET_INTEL_PUBLISH_WEBHOOK 时同步推送到外部 IM。
"""
import os
import re
import time
from datetime import datetime
from pathlib import Path

import httpx
from langchain.tools import tool
from langgraph.config import get_config

from app.paths import WORKSPACE_DATA

DATA_DIR = WORKSPACE_DATA  # 归档根目录（与 generate_solution_doc 同源）


def _wrap_html(title: str, content: str) -> str:
    """看板兜底包装：已是完整 HTML 则原样归档，否则包一层可直接打开的最小文档。"""
    if re.search(r"<html[\s>]", content, re.IGNORECASE):
        return content
    return (
        '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="UTF-8">\n'
        f"<title>{title}</title>\n</head>\n<body>\n{content}\n</body>\n</html>\n"
    )


def _safe_name(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", title).strip("_")[:60] or "未命名简报"


def write_briefing(user_id: str, title: str, content_html: str) -> Path:
    """归档简报 HTML 到 workspace/data/<user_id>/briefings/，返回文件路径。"""
    user_dir = DATA_DIR / user_id / "briefings"
    user_dir.mkdir(parents=True, exist_ok=True)
    path = user_dir / f"{_safe_name(title)}_{time.strftime('%Y%m%d_%H%M%S')}.html"
    path.write_text(_wrap_html(title, content_html), encoding="utf-8")
    return path


@tool
def publish_briefing(title: str, content_html: str, summary: str = "") -> str:
    """【发布市场简报】把已生成的简报看板提交发布。调用后会先挂起等待人工审批：
    批准前内容不会外发；批准后归档为 HTML 文件（出现在会话文件卡片里，可下载），
    配置了 MARKET_INTEL_PUBLISH_WEBHOOK 时会同步推送到外部 IM；被拒绝则取消发布。
    参数:
        title: 简报标题，如"市场情报每日简报 · 2026-09-12"
        content_html: 完整看板 HTML（REPORT_HTML 分隔符内的那段，不含分隔符标记本身）
        summary: 一句话摘要（可选，随 webhook 推送）
    返回:
        发布结果说明（归档路径 / 推送状态）
    """
    # 与 generate_solution_doc 同样的上下文纪律：取不到运行时身份宁可拒绝，
    # 也不能静默归档到共享目录。
    try:
        cfg = get_config() or {}
        configurable = cfg.get("configurable") or {}
        user_id = configurable.get("user_id")
        conv_id = configurable.get("thread_id")
    except Exception as e:
        raise RuntimeError(f"无法获取运行时上下文，拒绝发布：{e}")
    if not user_id:
        raise RuntimeError(
            "运行时上下文中缺少 user_id，为避免简报归档到错误目录已拒绝发布。"
        )

    path = write_briefing(user_id, title, content_html)
    published_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"简报已归档：/data/{path.relative_to(WORKSPACE_DATA).as_posix()}（发布时间 {published_at}）",
        "文件已作为产物挂到本会话，可在文件卡片中下载查看。",
    ]

    webhook = os.environ.get("MARKET_INTEL_PUBLISH_WEBHOOK", "").strip()
    if webhook:
        try:
            resp = httpx.post(webhook, timeout=10, json={
                "title": title,
                "summary": summary,
                "published_at": published_at,
                "user_id": user_id,
                "conversation_id": conv_id or "",
                "content_html": _wrap_html(title, content_html),
            })
            lines.append(f"外部推送完成，webhook 返回 {resp.status_code}。")
        except Exception as e:
            lines.append(f"外部推送失败（归档不受影响）：{type(e).__name__}: {e}")
    else:
        lines.append("未配置 MARKET_INTEL_PUBLISH_WEBHOOK，本次仅归档不外发。")
    return "\n".join(lines)
