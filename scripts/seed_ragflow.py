#!/usr/bin/env python3
"""把项目内置的模拟知识数据灌入 RAGFlow dataset（幂等，可重复执行）。

数据源 → 目标：
  catalog.db kb_entries kb_product（30 条产品 FAQ）         → 「产品知识库」
  catalog.db kb_entries kb_employee_handbook（34 条员工手册）→ 「智选员工手册」（不存在则自动新建）
  crm_server.py CUSTOMERS/ORDERS（10 位客户档案）           → 「客户档案」

员工手册灌完后，把 hrbp（综合人力专员）的知识库绑定从「综合人力知识库」
切换到「智选员工手册」，与现有制度公文类数据集隔离。

用法：PYTHONPATH=backend .venv/bin/python scripts/seed_ragflow.py
"""

import os
import re
import sqlite3
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.connectors import ragflow_client  # noqa: E402
from app.paths import db_path  # noqa: E402

API_BASE = ragflow_client._base_url()
API_KEY = ragflow_client._api_key()

HEADERS = {"Authorization": f"Bearer {API_KEY}"}

# 数据集（按名称定位，与 catalog 中 backfill 的 name 约定一致）
DS_PRODUCT = "产品知识库"
DS_CUSTOMER = "客户档案"
DS_HANDBOOK = "智选员工手册"

KB_PRODUCT_ID = "kb_product"
KB_HANDBOOK_ID = "kb_employee_handbook"
# hrbp 原绑定的旧版制度数据集名（切换来源）
DS_HANDBOOK_OLD = "综合人力知识库"


def rf(method: str, path: str, **kw) -> dict:
    resp = requests.request(method, f"{API_BASE}{path}", headers=HEADERS, timeout=120, **kw)
    try:
        payload = resp.json()
    except Exception:
        raise RuntimeError(f"{method} {path} 非 JSON 响应: {resp.status_code} {resp.text[:300]}")
    if payload.get("code") not in (0, None):
        raise RuntimeError(payload.get("message") or f"{method} {path} 失败")
    return payload.get("data") or {}


def list_datasets() -> list[dict]:
    data = rf("GET", "/api/v1/datasets")
    rows = data if isinstance(data, list) else (data.get("data") or [])
    return rows


def ensure_dataset(name: str, description: str = "") -> str:
    for d in list_datasets():
        if d.get("name") == name:
            return d["id"]
    data = rf("POST", "/api/v1/datasets", json={"name": name, "description": description})
    did = data.get("id") or data.get("name")
    print(f"  [新建] RAGFlow 数据集「{name}」 id={did}")
    return did


def list_documents(dataset_id: str) -> list[dict]:
    docs: list[dict] = []
    page = 1
    while True:
        data = rf("GET", f"/api/v1/datasets/{dataset_id}/documents?page={page}&page_size=100")
        batch = data.get("docs") if isinstance(data, dict) else data
        batch = batch or []
        docs.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return docs


def upload_documents(dataset_id: str, files: list[tuple[str, bytes]]) -> int:
    if not files:
        return 0
    payload = [("file", (name, content, "text/markdown")) for name, content in files]
    resp = requests.post(
        f"{API_BASE}/api/v1/datasets/{dataset_id}/documents",
        headers=HEADERS, files=payload, timeout=180,
    )
    data = resp.json()
    if data.get("code") not in (0, None):
        raise RuntimeError(data.get("message") or "上传文档失败")
    docs = data.get("data") or []
    return len(docs) if isinstance(docs, list) else 1


def trigger_parse(dataset_id: str, name: str) -> None:
    docs = list_documents(dataset_id)
    ids = [d["id"] for d in docs if d.get("run") in ("UNSTART", "FAIL")]
    if not ids:
        print(f"  [解析] {name}：无需解析")
        return
    data = rf("POST", f"/api/v1/datasets/{dataset_id}/documents/parse",
              json={"document_ids": ids})
    print(f"  [解析] {name}：已触发 {data.get('success_count', len(ids))} 个文档解析")


def wait_parsed(dataset_id: str, name: str, timeout: int = 600) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        docs = list_documents(dataset_id)
        running = [d for d in docs if d.get("run") in ("UNSTART", "RUNNING")]
        failed = [d for d in docs if d.get("run") == "FAIL"]
        done = sum(d.get("chunk_count") or 0 for d in docs if d.get("run") == "DONE")
        if not running:
            if failed:
                print(f"  [警告] {name}：{len(failed)} 个文档解析失败："
                      f"{[d.get('name') for d in failed[:5]]}")
            print(f"  [完成] {name}：共 {len(docs)} 个文档，chunk {done}")
            return
        print(f"  [解析中] {name}：{len(running)} 个文档排队中…")
        time.sleep(5)
    raise RuntimeError(f"{name} 解析超时（>{timeout}s）")


def load_kb_entries(kb_id: str) -> list[dict]:
    con = sqlite3.connect(db_path("catalog.db"))
    con.row_factory = sqlite3.Row
    rows = [
        dict(r) for r in con.execute(
            "SELECT title, content FROM kb_entries WHERE kb_id=? ORDER BY id", (kb_id,)
        )
    ]
    con.close()
    return rows


def safe_name(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "-", title).strip("-") or "untitled"


def build_product_docs() -> list[tuple[str, bytes]]:
    docs = []
    for e in load_kb_entries(KB_PRODUCT_ID):
        md = f"# {e['title']}\n\n{e['content']}\n".encode("utf-8")
        docs.append((f"{safe_name(e['title'])}.md", md))
    return docs


def build_handbook_docs() -> list[tuple[str, bytes]]:
    docs = []
    for i, e in enumerate(load_kb_entries(KB_HANDBOOK_ID), 1):
        em = f"EM-{i:03d}"
        md = f"# {e['title']}\n\n编号：{em}\n\n{e['content']}\n".encode("utf-8")
        docs.append((f"{em}-{safe_name(e['title'])}.md", md))
    return docs


def build_customer_docs() -> list[tuple[str, bytes]]:
    from app.connectors.crm_server import CUSTOMERS, ORDERS

    docs = []
    for c in CUSTOMERS.values():
        lines = [f"# 客户档案：{c['name']}", ""]
        fields = [
            ("公司", c["company"]), ("职位", c["title"]), ("客户等级", c["level"]),
            ("行业", c["industry"]), ("员工规模", f"{c['employees']} 人"),
            ("合作起始", c["since"]), ("最近拜访", c["last_visit"]),
            ("累计消费", f"{c['total_spent']} 元"), ("备注", c["notes"]),
        ]
        for k, v in fields:
            lines.append(f"- **{k}**：{v}")
        orders = [ORDERS[o] for o in c["orders"] if o in ORDERS]
        if orders:
            lines += ["", "## 历史订单", ""]
            for o in orders:
                lines.append(
                    f"- {o['order_id']}：{o['product']}，金额 {o['amount']} 元，"
                    f"状态「{o['status']}」，签收 {o['sign_date'] or '—'}"
                )
        docs.append((f"客户档案-{safe_name(c['name'])}.md", "\n".join(lines).encode("utf-8")))
    return docs


def upload_into(dataset_id: str, name: str, files: list[tuple[str, bytes]]) -> int:
    existed = {d.get("name") for d in list_documents(dataset_id)}
    new_files = [(fn, data) for fn, data in files if fn not in existed]
    if not new_files:
        print(f"  [跳过] {name}：{len(files)} 个文档已全部存在")
        return 0
    n = upload_documents(dataset_id, new_files)
    print(f"  [上传] {name}：新上传 {n} 个，跳过 {len(files) - n} 个已存在")
    return n


def switch_hrbp_handbook(dataset_id: str) -> None:
    """把 hrbp 的知识库绑定从「综合人力知识库」切换到「智选员工手册」。"""
    con = sqlite3.connect(db_path("catalog.db"))
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO knowledge_bases(id,name,description,ragflow_dataset_id) "
        "VALUES(?,?,?,?)",
        (dataset_id, DS_HANDBOOK, "智选智能硬件有限公司员工手册（模拟数据）", dataset_id),
    )
    old = cur.execute(
        "SELECT id FROM knowledge_bases WHERE name=? AND deleted_at IS NULL", (DS_HANDBOOK_OLD,)
    ).fetchone()
    changed = False
    if old:
        cur.execute(
            "DELETE FROM employee_kbs WHERE employee_id='hrbp' AND kb_id=?", (old["id"],)
        )
        changed = True
    cur.execute(
        "INSERT OR IGNORE INTO employee_kbs(employee_id,kb_id) VALUES('hrbp',?)", (dataset_id,)
    )
    cur.execute(
        "UPDATE employees SET updated_at=? WHERE id='hrbp'",
        (time.strftime("%Y-%m-%d %H:%M:%S"),),
    )
    con.commit()
    con.close()
    print(f"  [绑定] hrbp 知识库已切换到「{DS_HANDBOOK}」（原「{DS_HANDBOOK_OLD}」"
          f"{'解绑' if changed else '未绑定'}）")


def main() -> None:
    if not API_KEY:
        print("错误：未配置 RAGFLOW_API_KEY（.env），请先配置再运行。")
        sys.exit(1)
    print("== 灌入模拟知识数据到 RAGFlow ==\n")
    datasets = {d["name"]: d["id"] for d in list_datasets()}

    for name, build, is_handbook in (
        (DS_PRODUCT, build_product_docs, False),
        (DS_CUSTOMER, build_customer_docs, False),
        (DS_HANDBOOK, build_handbook_docs, True),
    ):
        print(f"--- {name} ---")
        files = build()
        if name in datasets:
            dataset_id = datasets[name]
        elif is_handbook:
            dataset_id = ensure_dataset(name, "智选智能硬件有限公司员工手册（模拟数据）")
        else:
            print(f"  [跳过] RAGFlow 中不存在数据集「{name}」，请先在界面创建或改脚本配置。")
            continue
        if upload_into(dataset_id, name, files) == 0:
            docs = list_documents(dataset_id)
            chunks = sum(d.get("chunk_count") or 0 for d in docs)
            print(f"  [已就绪] {name}：{len(docs)} 个文档，chunk {chunks}")
        trigger_parse(dataset_id, name)
        wait_parsed(dataset_id, name)
        if is_handbook:
            switch_hrbp_handbook(dataset_id)

    print("\n== 完成 ==")


if __name__ == "__main__":
    main()
