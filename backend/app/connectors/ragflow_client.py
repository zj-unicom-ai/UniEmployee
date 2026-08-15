"""RAGFlow HTTP 客户端：从本地 RAGFlow 检索知识库片段。

当前用于让现有 `kb_search` 闭包直接回调 RAGFlow；后续如果要把知识库
检索拆成独立 MCP connector，可以复用这里的 `retrieve_ragflow`。
"""

import json
import os
import urllib.request
from pathlib import Path

import dotenv

# MCP 子进程/后台进程不一定会继承主应用的 os.environ，模块内自行加载一次根 .env。
_ENV_CAND = Path(__file__).resolve().parents[3] / ".env"
dotenv.load_dotenv(_ENV_CAND)

DEFAULT_BASE_URL = "http://localhost"


def _base_url() -> str:
    return (os.environ.get("RAGFLOW_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")


def _api_key() -> str:
    return os.environ.get("RAGFLOW_API_KEY", "").strip()


def is_ragflow_configured() -> bool:
    return bool(_api_key())


def default_dataset_ids() -> list[str]:
    raw = os.environ.get("RAGFLOW_DATASET_IDS", "")
    return [x.strip() for x in raw.split(",") if x.strip()]


def _request(method: str, path: str, body: dict | None = None) -> dict:
    key = _api_key()
    if not key:
        raise RuntimeError("未配置 RAGFLOW_API_KEY")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{_base_url()}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if payload.get("code") not in (0, None):
        raise RuntimeError(payload.get("message") or json.dumps(payload, ensure_ascii=False))
    return payload.get("data") or {}


def list_datasets() -> list[dict]:
    """获取当前 API key 可见的全部 RAGFlow 知识库（dataset）。"""
    data = _request("GET", "/api/v1/datasets")
    out = []
    rows = data if isinstance(data, list) else (data.get("data") or [])
    for d in rows:
        out.append({
            "id": d.get("id"),
            "name": d.get("name"),
            "description": d.get("description"),
            "document_count": d.get("document_count"),
            "chunk_count": d.get("chunk_count"),
        })
    return out


def _resolve_dataset_ids(dataset_ids: list[str] | None) -> list[str]:
    ids = [x.strip() for x in (dataset_ids or default_dataset_ids()) if x.strip()]
    if ids:
        return ids
    return [d["id"] for d in list_datasets() if d.get("id")]


def retrieve_ragflow(
    question: str,
    dataset_ids: list[str] | None = None,
    top_k: int = 5,
    similarity_threshold: float = 0.1,
    vector_similarity_weight: float = 0.3,
) -> list[dict]:
    """调用 RAGFlow `/api/v1/retrieval`，返回命中的 chunk 列表。"""
    ids = _resolve_dataset_ids(dataset_ids)
    if not ids:
        return []
    data = _request("POST", "/api/v1/retrieval", {
        "question": question,
        "dataset_ids": ids,
        "top_k": top_k,
        "similarity_threshold": similarity_threshold,
        "vector_similarity_weight": vector_similarity_weight,
    })
    return data.get("chunks") or []


def format_chunks(chunks: list[dict], max_chars: int = 4000) -> str:
    """把 RAGFlow chunk 整理成适合大模型直接引用的文本。"""
    lines = []
    for i, c in enumerate(chunks, 1):
        source = (
            c.get("document_keyword")
            or c.get("dataset_id")
            or c.get("id")
            or "RAGFlow"
        )
        sim = round(float(c.get("similarity") or 0), 2)
        content = "\n".join(x.strip() for x in str(c.get("content") or "").splitlines() if x.strip())
        lines.append(f"[{i}] 来源：{source} | 相似度：{sim}\n{content}")
    text = "\n\n".join(lines)
    return text[:max_chars]
