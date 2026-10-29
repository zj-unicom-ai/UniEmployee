"""统一知识检索模块：运行时知识只来自 RAGFlow。"""

import logging

from app.connectors import ragflow_client

logger = logging.getLogger("app.knowledge")


def configured() -> bool:
    """RAGFlow 是否已配置。"""
    return ragflow_client.is_ragflow_configured()


def dataset_ids_from_config(cfg: dict | None) -> list[str] | None:
    """从员工有效配置中提取 RAGFlow dataset id。

    返回 None 表示使用 RAGFLOW_DATASET_IDS 或 RAGFlow 当前可见的全部数据集。
    """
    mapped = (cfg or {}).get("kb_ragflow_datasets") or {}
    ids = [x for x in mapped.values() if x]
    return ids or None


def search(query: str, cfg: dict | None = None, top_k: int = 3) -> str:
    """检索知识库并返回适合模型引用的文本。

    cfg 可传员工有效配置；未传时使用全局 RAGFlow 数据集配置。
    """
    if not configured():
        return "【知识库未配置】系统未启用 RAGFlow 知识库，无法检索。请管理员配置 RAGFLOW_API_KEY 后重试。"
    try:
        chunks = ragflow_client.retrieve_ragflow(
            query,
            dataset_ids=dataset_ids_from_config(cfg),
            top_k=top_k,
        )
    except Exception:
        # RAGFlow / embedding outages should not fail an otherwise usable agent
        # run. The model can still answer from the provided context and other
        # available sources, while this result makes the missing evidence clear.
        logger.warning("RAGFlow retrieval unavailable", exc_info=True)
        return (
            "【知识库检索暂不可用】RAGFlow 或其向量嵌入服务当前不可达，本次没有取得知识库内容。"
            "请继续使用本轮已提供的资料和其他可用来源回答，并明确说明未能访问知识库；不要假设知识库命中内容。"
        )
    if chunks:
        return ragflow_client.format_chunks(chunks)
    return "未在知识库中检索到相关条目。请换关键词重试；若仍无结果，告知用户需要核实并建议转人工。"
