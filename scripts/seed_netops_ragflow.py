#!/usr/bin/env python3
"""把 workspace/netops_kb/ 下的算网运营制度文档灌入 RAGFlow 并绑定给小网。

幂等：数据集按名称复用，同名文档跳过，员工知识库绑定使用 INSERT OR IGNORE。

用法：PYTHONPATH=backend .venv/bin/python scripts/seed_netops_ragflow.py
"""

import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

from seed_ragflow import (  # noqa: E402
    ensure_dataset,
    list_documents,
    trigger_parse,
    upload_into,
    wait_parsed,
)
from app.catalog.db import _conn  # noqa: E402
from app.connectors import ragflow_client  # noqa: E402

KB_DIR = ROOT / "workspace" / "netops_kb"
DS_NAME = "算网运营知识库"
DS_DESC = "算网运营 SLA、故障分级、割接规范、升级上报、资源容量和应急制度（小网专用）"


def bind_netops_kb(dataset_id: str) -> None:
    con = _conn()
    cur = con.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO knowledge_bases"
        "(id,name,description,ragflow_dataset_id) VALUES(?,?,?,?)",
        (dataset_id, DS_NAME, DS_DESC, dataset_id),
    )
    cur.execute(
        "INSERT OR IGNORE INTO employee_kbs(employee_id,kb_id) VALUES(?,?)",
        ("net-ops", dataset_id),
    )
    cur.execute(
        "UPDATE employees SET updated_at=? WHERE id='net-ops' AND deleted_at IS NULL",
        (time.strftime("%Y-%m-%d %H:%M:%S"),),
    )
    con.commit()
    con.close()
    print(f"  [绑定] net-ops 已绑定「{DS_NAME}」")


def main() -> None:
    if not ragflow_client.is_ragflow_configured():
        print("错误：未配置 RAGFLOW_API_KEY（.env），请先配置再运行。")
        sys.exit(1)

    print("== 灌入算网运营知识库到 RAGFlow ==\n")
    files = [(p.name, p.read_bytes()) for p in sorted(KB_DIR.glob("*.md"))]
    if not files:
        print(f"错误：{KB_DIR} 下没有 md 文件")
        sys.exit(1)

    print(f"共发现 {len(files)} 个知识文档")
    did = ensure_dataset(DS_NAME, DS_DESC)
    print(f"  数据集 id={did}")

    upload_into(did, DS_NAME, files)
    trigger_parse(did, DS_NAME)
    wait_parsed(did, DS_NAME, timeout=900)

    docs = list_documents(did)
    print("\n文档清单：")
    for d in docs:
        print(f"  {d.get('name')}  run={d.get('run')}  chunks={d.get('chunk_count')}")

    bind_netops_kb(did)
    print("\n== 完成 ==")


if __name__ == "__main__":
    main()
