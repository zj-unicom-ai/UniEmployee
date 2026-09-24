#!/usr/bin/env python3
"""Idempotently register historical assistant HTML reports as workspace artifacts.

Run a preview first, then pass --apply to write HTML snapshots and
conversation_files rows. The preview does not archive reports, but initializing
the catalog/runtime may perform their normal idempotent setup. ToolMessage output
is intentionally ignored.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from contextlib import AsyncExitStack

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))
# Backfill only reads checkpoint state; no MCP subprocess is needed.
os.environ.setdefault("MCP_DISABLED", "1")

from app import catalog, conversations, db, runtime  # noqa: E402
from app.paths import db_path  # noqa: E402
from app.report_artifacts import archive_assistant_reports, extract_inline_reports  # noqa: E402


async def _open_runtime(stack: AsyncExitStack):
    if db.is_pg():
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from langgraph.store.postgres import AsyncPostgresStore

        checkpointer = await stack.enter_async_context(
            AsyncPostgresSaver.from_conn_string(db.pg_dsn("checkpoints")))
        await checkpointer.setup()
        store = await stack.enter_async_context(
            AsyncPostgresStore.from_conn_string(db.pg_dsn("store")))
        await store.setup()
    else:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        from langgraph.store.sqlite import AsyncSqliteStore

        checkpointer = await stack.enter_async_context(
            AsyncSqliteSaver.from_conn_string(str(db_path("checkpoints.db"))))
        await checkpointer.setup()
        store = await stack.enter_async_context(
            AsyncSqliteStore.from_conn_string(str(db_path("store.db"))))
    runtime.set_checkpointer(checkpointer)
    runtime.set_store(store)


async def backfill(apply: bool) -> tuple[int, int, int]:
    catalog.init()
    with conversations._conn() as con:
        rows = con.execute(
            "SELECT conv_id,employee_id,user_id FROM conversations "
            "WHERE deleted_at IS NULL ORDER BY updated_at DESC"
        ).fetchall()

    conversation_count = 0
    report_count = 0
    failure_count = 0
    async with AsyncExitStack() as stack:
        await _open_runtime(stack)
        agent_cache = {}
        for row in rows:
            conv_id = row["conv_id"]
            employee_id = row["employee_id"]
            try:
                agent = agent_cache.get(employee_id)
                if agent is None:
                    agent, _ = await runtime.get_agent(employee_id)
                    agent_cache[employee_id] = agent
                states = [state async for state in agent.aget_state_history(
                    {"configurable": {"thread_id": conv_id}}, limit=1)]
                messages = states[0].values.get("messages", []) if states else []
                turn_no = 0
                found = 0
                for message in messages:
                    kind = type(message).__name__
                    if kind == "HumanMessage":
                        turn_no += 1
                    elif kind == "AIMessage":
                        content = getattr(message, "content", "")
                        if isinstance(content, list):
                            content = "".join(
                                part.get("text", "") for part in content
                                if isinstance(part, dict) and part.get("type") == "text")
                        found += len(extract_inline_reports(content))
                if found:
                    conversation_count += 1
                    if apply:
                        saved = archive_assistant_reports(
                            messages, row["user_id"] or "default", conv_id)
                        report_count += len(saved)
                    else:
                        report_count += found
            except Exception as exc:
                failure_count += 1
                print(f"跳过会话 {conv_id}（{employee_id}）：{type(exc).__name__}: {exc}")
    return conversation_count, report_count, failure_count


def main():
    parser = argparse.ArgumentParser(description="归档历史对话中的内嵌 HTML 看板")
    parser.add_argument("--apply", action="store_true", help="实际写入产物文件和数据库索引")
    args = parser.parse_args()
    conversations_found, reports_found, failures = asyncio.run(backfill(args.apply))
    mode = "已归档" if args.apply else "预览"
    print(f"{mode}完成：{conversations_found} 个会话，{reports_found} 份报告，{failures} 个会话读取失败。")
    if not args.apply and reports_found:
        print("确认后使用 --apply 执行幂等回填。")


if __name__ == "__main__":
    main()
