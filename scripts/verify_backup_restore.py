"""在隔离 PostgreSQL 库和临时 workspace 上验证备份及恢复。"""

from __future__ import annotations

import argparse
import os
import subprocess
import tarfile
import tempfile
import time
import uuid
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from psycopg import sql


ROOT = Path(__file__).resolve().parent.parent
DBS = ("catalog", "conversations", "checkpoints", "store", "traces", "approvals", "ontology")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-container", required=True, help="隔离 PostgreSQL 容器名")
    parser.add_argument("--pg-port", type=int, required=True, help="容器映射到宿主机的端口")
    parser.add_argument("--pg-host", default="127.0.0.1")
    parser.add_argument("--env-file", type=Path, required=True, help="含 POSTGRES_USER/PASSWORD 的本地文件")
    args = parser.parse_args()

    credentials = dotenv_values(args.env_file)
    user = credentials.get("POSTGRES_USER")
    password = credentials.get("POSTGRES_PASSWORD")
    if not user or not password:
        raise SystemExit("凭据文件缺少 POSTGRES_USER 或 POSTGRES_PASSWORD")

    suffix = uuid.uuid4().hex[:8]
    source_prefix, target_prefix = f"p0src_{suffix}_", f"p0dst_{suffix}_"
    marker = f"restore-{suffix}"
    created: list[str] = []
    admin = psycopg.connect(
        host=args.pg_host, port=args.pg_port, dbname="postgres",
        user=user, password=password, autocommit=True,
    )

    def connect_db(name: str):
        return psycopg.connect(
            host=args.pg_host, port=args.pg_port, dbname=name,
            user=user, password=password,
        )

    try:
        for prefix in (source_prefix, target_prefix):
            for logical in DBS:
                name = prefix + logical
                admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
                created.append(name)

        for logical in DBS:
            with connect_db(source_prefix + logical) as con:
                con.execute("CREATE TABLE backup_probe(logical_db TEXT PRIMARY KEY, marker TEXT NOT NULL)")
                con.execute("INSERT INTO backup_probe VALUES (%s,%s)", (logical, marker))

        with tempfile.TemporaryDirectory(prefix="uniemployee-backup-verify-") as root_name:
            temp_root = Path(root_name)
            workspace = temp_root / "workspace"
            report = workspace / "data" / "u_verify" / "report.txt"
            report.parent.mkdir(parents=True)
            report.write_text(marker, encoding="utf-8")
            output = temp_root / "backups"
            env = os.environ.copy()
            env.update({
                "BACKUP_ENV_FILE": str(args.env_file),
                "BACKUP_PG_CONTAINER": args.pg_container,
                "BACKUP_DB_PREFIX": source_prefix,
                "BACKUP_WORKSPACE_DIR": str(workspace),
                "BACKUP_QUIESCED": "1",
                "BACKUP_KEEP": "0",
            })
            start = time.perf_counter()
            subprocess.run([str(ROOT / "scripts" / "backup.sh"), str(output)],
                           env=env, cwd=ROOT, check=True, capture_output=True, text=True)
            archives = list(output.glob("uniemployee-*.tar.gz"))
            if len(archives) != 1:
                raise AssertionError(f"预期一份备份，实际 {len(archives)} 份")
            archive = archives[0]

            restore_root = temp_root / "restore"
            with tarfile.open(archive, "r:gz") as bundle:
                members = bundle.getmembers()
                names = {member.name.rstrip("/") for member in members}
                expected = {"manifest.txt", "workspace/data/u_verify/report.txt"}
                expected.update(f"pg/{db}.dump" for db in DBS)
                if not expected.issubset(names):
                    raise AssertionError(f"归档缺少 {sorted(expected - names)}")
                if any(member.name.startswith("/") or ".." in Path(member.name).parts
                       for member in members):
                    raise AssertionError("归档包含不安全路径")
                manifest_file = bundle.extractfile("manifest.txt")
                if manifest_file is None:
                    raise AssertionError("归档缺少 manifest.txt")
                manifest = manifest_file.read().decode("utf-8")
                if "format=uniemployee-backup-v2" not in manifest or \
                        "consistency=writes_paused_by_operator" not in manifest:
                    raise AssertionError("备份清单格式或一致性标记无效")
                bundle.extractall(restore_root, filter="data")

            for logical in DBS:
                dump = (restore_root / "pg" / f"{logical}.dump").read_bytes()
                subprocess.run(
                    ["docker", "exec", "-i", args.pg_container, "pg_restore",
                     "-U", user, "-d", target_prefix + logical],
                    input=dump, check=True, capture_output=True,
                )
                with connect_db(target_prefix + logical) as con:
                    row = con.execute("SELECT logical_db,marker FROM backup_probe").fetchone()
                    if row != (logical, marker):
                        raise AssertionError(f"{logical} 恢复内容不一致：{row}")
            restored_report = restore_root / "workspace" / "data" / "u_verify" / "report.txt"
            if restored_report.read_text(encoding="utf-8") != marker:
                raise AssertionError("workspace 文件恢复内容不一致")
            print(f"backup_restore_passed databases={len(DBS)} workspace_files=1 "
                  f"elapsed_seconds={time.perf_counter() - start:.2f}")
    finally:
        for name in reversed(created):
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.close()
        print(f"temporary_databases_removed={len(created)}")


if __name__ == "__main__":
    main()
