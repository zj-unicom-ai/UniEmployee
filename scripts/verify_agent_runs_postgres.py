"""在隔离 PostgreSQL 临时库验证 Agent 运行记录与事件重放。"""

from __future__ import annotations

import argparse
import os
import uuid
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from psycopg import sql


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-port", type=int, required=True)
    parser.add_argument("--pg-host", default="127.0.0.1")
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    values = dotenv_values(args.env_file)
    user, password = values.get("POSTGRES_USER"), values.get("POSTGRES_PASSWORD")
    if not user or not password:
        raise SystemExit("凭据文件缺少 POSTGRES_USER 或 POSTGRES_PASSWORD")

    prefix = f"p1run_{uuid.uuid4().hex[:8]}_"
    database = prefix + "conversations"
    admin = psycopg.connect(host=args.pg_host, port=args.pg_port, dbname="postgres",
                            user=user, password=password, autocommit=True)
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        os.environ.update({
            "DB_BACKEND": "postgres", "POSTGRES_HOST": args.pg_host,
            "POSTGRES_PORT": str(args.pg_port), "POSTGRES_USER": user,
            "POSTGRES_PASSWORD": password, "POSTGRES_DB_PREFIX": prefix,
        })
        from app import agent_runs, conversations, db

        conversations.create("c_pg_run", "xiaoxiao", user_id="u1", tenant_id="t1")
        agent_runs.init_tables()
        run = agent_runs.create(conv_id="c_pg_run", tenant_id="t1",
                                user_id="u1", employee_id="xiaoxiao")
        agent_runs.mark_running(run["id"])
        seq = agent_runs.append_event(run["id"], {"type": "token", "content": "pg"})
        replay = agent_runs.events_after(run["id"], 1)
        if seq != 2 or replay != [{"seq": 2, "payload": {"type": "token", "content": "pg"}}]:
            raise AssertionError(f"事件重放不一致: seq={seq}, replay={replay}")
        agent_runs.finish(run["id"], "done")
        restored = agent_runs.get(run["id"])
        if not restored or restored["status"] != "done" or restored["last_seq"] != 2:
            raise AssertionError(f"运行状态不一致: {restored}")
        print(f"agent_runs_postgres_passed run_id={run['id']} events=2")
        db.close_all_pools()
    finally:
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
            sql.Identifier(database)))
        admin.close()
        print(f"temporary_database_removed={database}")


if __name__ == "__main__":
    main()
