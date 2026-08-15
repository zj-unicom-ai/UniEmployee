#!/usr/bin/env python3
"""通过真实数字员工对话，验证 RAGFlow 知识库灌入后的回复效果。

对售前（xiaoxiao）和综合人力（hrbp）各发 2 个知识库问题，
走真实 LLM 对话（含 kb_search 检索），从三个维度评估：
  1. 知识库命中 —— kb_search 工具调用返回了非空检索结果
  2. 来源标注   —— 回复文本带来源（依据/知识库/检索/EM-编号等）
  3. 关键事实   —— 回复包含期望的知识库事实关键词

用法：PYTHONPATH=backend .venv/bin/python scripts/verify_kb_qa.py
"""

import asyncio
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # noqa: E402
from langgraph.store.sqlite import AsyncSqliteStore  # noqa: E402

from app import conversations, runtime  # noqa: E402
from app.paths import db_path  # noqa: E402
from app.streaming import _stream_run, conv_emp_map  # noqa: E402

CASES = [
    {
        "emp": "xiaoxiao", "label": "售前-产品价格",
        "q": "X1 智能音箱官方售价是多少？",
        "expect": ["399"],
    },
    {
        "emp": "xiaoxiao", "label": "售前-客户档案",
        "q": "华强电子的张总是哪个客户等级？他所在的行业是什么？",
        "expect": ["VIP", "电子制造"],
    },
    {
        "emp": "hrbp", "label": "综合人力-年假",
        "q": "员工连续工作满多久可以休带薪年假？年假有几天？",
        "expect": ["满1年", "5天", "5 天"],
    },
    {
        "emp": "hrbp", "label": "综合人力-试用期",
        "q": "新员工试用期多长？转正考核中工作业绩占比多少？",
        "expect": ["6个月", "40%"],
    },
]

SOURCE_HINTS = ("依据", "知识库", "检索", "来源", "手册", "档案", "EM-")
MISS_HINTS = ("未在知识库中检索到", "未检索到", "【知识库未配置】")


def sse_event(line: str) -> dict | None:
    if not line.startswith("data:"):
        return None
    try:
        return json.loads(line[6:].strip())
    except Exception:
        return None


async def ask(emp: str, question: str):
    conv_id = f"verify_{emp}_{int(time.time() * 1000)}_{random.randint(100, 999)}"
    conv_emp_map[conv_id] = emp
    tokens: list[str] = []
    kb_calls: list[dict] = []
    tools: set[str] = set()
    error = None
    try:
        async for line in _stream_run(
            conv_id, {"messages": [{"role": "user", "content": question}]},
            user_id="u_verify",
        ):
            ev = sse_event(line)
            if not ev:
                continue
            t = ev.get("type")
            if t == "token":
                tokens.append(ev.get("content", ""))
            elif t == "tool":
                if ev.get("name") == "kb_search":
                    if ev.get("status") == "start":
                        kb_calls.append({"args": ev.get("args", {})})
                    elif kb_calls:
                        kb_calls[-1]["preview"] = ev.get("preview", "")
                if ev.get("status") == "start" and ev.get("name"):
                    tools.add(ev["name"])
            elif t == "error":
                error = ev.get("message")
    finally:
        conv_emp_map.pop(conv_id, None)
        try:
            conversations.delete(conv_id)
        except Exception:
            pass
    return "".join(tokens).strip(), kb_calls, sorted(tools), error


def kb_hit(kb_calls: list[dict]) -> tuple[bool, str]:
    for c in kb_calls:
        p = c.get("preview", "")
        if p and not any(h in p for h in MISS_HINTS):
            return True, p
    last = kb_calls[-1].get("preview", "") if kb_calls else ""
    return False, last


async def run_case(case: dict) -> dict:
    print(f"[{case['label']}] ({case['emp']}) 提问：{case['q']}")
    t0 = time.time()
    text, kb, tools, error = await ask(case["emp"], case["q"])
    dt = time.time() - t0
    hit, preview = kb_hit(kb)
    hits = [k for k in case["expect"] if k in text]
    sourced = any(h in text for h in SOURCE_HINTS)
    return {**case, "text": text, "tools": tools, "error": error,
            "dt": dt, "kb_hit": hit, "preview": preview,
            "hits": hits, "sourced": sourced}


def verdict_marks(ok: bool) -> str:
    return "OK" if ok else "--"


async def main() -> None:
    async with (
        AsyncSqliteSaver.from_conn_string(str(db_path("checkpoints.db"))) as cp,
        AsyncSqliteStore.from_conn_string(str(db_path("store.db"))) as store,
    ):
        runtime.set_checkpointer(cp)
        runtime.set_store(store)
        print("== 数字员工知识库回复验证（真实 LLM + RAGFlow）==\n")
        results = []
        for case in CASES:
            r = await run_case(case)
            results.append(r)
            print(f"  耗时 {r['dt']:.0f}s | 工具 {r['tools']} | 错误 {r['error'] or '无'}")
            print(f"  知识库命中: {verdict_marks(r['kb_hit'])}"
                  f" | 来源标注: {verdict_marks(r['sourced'])}"
                  f" | 关键事实命中: {r['hits'] or '-'}")
            if r["preview"]:
                print(f"  检索片段: {r['preview'][:90]}…")
            reply = r["text"].replace("\n", " ")
            print(f"  回复: {reply[:140]}{'…' if len(reply) > 140 else ''}\n")

        print("== 汇总 ==")
        kb_hits = sum(1 for r in results if r["kb_hit"])
        for r in results:
            ok = bool(r["hits"]) and r["sourced"]
            kb = "kb_search命中" if r["kb_hit"] else ("走CRM/其他" if r["tools"] else "无工具")
            print(f"  [{verdict_marks(ok)}] {r['label']:<12} 命中关键词 {r['hits']} | {kb}")
        n_ok = sum(1 for r in results if r["hits"] and r["sourced"])
        print(f"\n事实正确率 {n_ok}/{len(results)}（关键事实+来源标注）"
              f" | RAGFlow kb_search 命中率 {kb_hits}/{len(results)}")


if __name__ == "__main__":
    asyncio.run(main())
