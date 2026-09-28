"""在隔离 PostgreSQL 临时库验证自动化执行账本、幂等与超时恢复。"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from psycopg import sql


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-port", type=int, required=True)
    parser.add_argument("--pg-host", default="127.0.0.1")
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    values = dotenv_values(args.env_file)
    user, password = values.get("POSTGRES_USER"), values.get("POSTGRES_PASSWORD")
    if not user or not password:
        raise SystemExit("凭据文件缺少 POSTGRES_USER 或 POSTGRES_PASSWORD")

    prefix = f"p1auto_{uuid.uuid4().hex[:8]}_"
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
        from app import automations, db

        auto = automations.create("PG ledger check", "event", "xiaoshu",
                                  "验证任务", event_key="pg.check", enabled=False)
        first, created = automations.create_execution(auto["id"], "event", "evt-1")
        duplicate, duplicate_created = automations.create_execution(auto["id"], "event", "evt-1")
        if not created or duplicate_created or duplicate["id"] != first["id"]:
            raise AssertionError("PostgreSQL 幂等唯一键验证失败")
        automations.update_execution(first["id"], "running")
        with automations._conn() as con:
            con.execute("UPDATE automation_executions SET heartbeat_at='2020-01-01T00:00:00' WHERE id=?",
                        (first["id"],))
            con.commit()
        recovered = automations.recover_stale_executions(max_age_seconds=120)
        row = automations.get_execution(first["id"])
        if recovered != 1 or not row or row["status"] != "interrupted":
            raise AssertionError(f"PostgreSQL 超时恢复失败: {row}")
        retry, retry_created = automations.create_execution(auto["id"], "manual_retry", "retry-1", first["id"])
        if not retry_created or retry["retry_of"] != first["id"]:
            raise AssertionError("PostgreSQL 重跑追踪关系验证失败")
        print("automation_executions_postgres_passed idempotency=ok stale_recovery=ok retry_lineage=ok")
        db.close_all_pools()
    finally:
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
            sql.Identifier(database)))
        admin.close()
        print(f"temporary_database_removed={database}")


if __name__ == "__main__":
    main()
