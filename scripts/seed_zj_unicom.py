#!/usr/bin/env python3
"""把 workspace/zj_unicom_kb/ 下的浙江联通知识文档灌入 RAGFlow「浙江联通业务知识库」。

幂等：数据集按名称复用，同名文档跳过，可重复执行。

用法：PYTHONPATH=backend .venv/bin/python scripts/seed_zj_unicom.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

from seed_ragflow import (  # noqa: E402
    ensure_dataset,
    list_documents,
    trigger_parse,
    upload_into,
    wait_parsed,
)

KB_DIR = ROOT / "workspace" / "zj_unicom_kb"
DS_NAME = "浙江联通业务知识库"


def main() -> None:
    files = [(p.name, p.read_bytes()) for p in sorted(KB_DIR.glob("*.md"))]
    if not files:
        print(f"错误：{KB_DIR} 下没有 md 文件")
        sys.exit(1)
    print(f"共发现 {len(files)} 个知识文档")
    did = ensure_dataset(DS_NAME, "浙江联通业务政策、套餐规则、办理流程知识库（售前客服）")
    print(f"  数据集 id={did}")
    upload_into(did, DS_NAME, files)
    trigger_parse(did, DS_NAME)
    wait_parsed(did, DS_NAME, timeout=900)
    docs = list_documents(did)
    print("\n文档清单：")
    for d in docs:
        print(f"  {d.get('name')}  run={d.get('run')}  chunks={d.get('chunk_count')}")


if __name__ == "__main__":
    main()
