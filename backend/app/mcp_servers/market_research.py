"""为外部智能体提供小察研究工作台的 Streamable HTTP MCP。"""

from __future__ import annotations

import hmac
import logging
from typing import Annotated

from fastmcp import FastMCP
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import market_research

log = logging.getLogger("app.mcp.market_research")


class SourceReference(BaseModel):
    """观察记录的可追溯来源。"""

    title: str = Field(default="", max_length=300)
    url: str = Field(default="", max_length=2000)
    published_at: str = Field(default="", max_length=100)
    organization: str = Field(default="", max_length=200)


class BearerTokenASGI:
    """保护入站 MCP 的轻量 Bearer token ASGI 包装。"""

    def __init__(self, app, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        authorization = next(
            (value.decode("latin-1") for key, value in scope.get("headers", [])
             if key.lower() == b"authorization"),
            "",
        )
        scheme, _, supplied = authorization.partition(" ")
        if (scheme.lower() != "bearer" or not supplied
                or not hmac.compare_digest(supplied.strip().encode("utf-8"),
                                           self.token.encode("utf-8"))):
            response = JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "message": "需要有效的 MCP Bearer token"},
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def build_market_research_mcp(tenant_id: str):
    """Build the server and its ASGI app for one configured tenant."""
    mcp = FastMCP("UniEmployee Market Research")

    @mcp.tool
    def list_research_topics() -> list[dict]:
        """列出小察研究工作台主题及当前租户已有观察数量。"""
        workbench = market_research.list_workbench(tenant_id=tenant_id, limit=1)
        return workbench["topics"]

    @mcp.tool
    def list_observations(
        topic_id: str = "",
        category_id: str = "",
        query: str = "",
        published_after: str = "",
        limit: Annotated[int, Field(ge=1, le=100)] = 30,
    ) -> dict:
        """读取最近的行业研究观察，可按主题、关键词和发布时间筛选。

        topic_id 可使用 embodied-intelligence、ai-frontier 或 policy-analysis；
        category_id 必须是该主题下的细分领域 ID。
        published_after 使用 YYYY-MM-DD 格式；最多读取最近 100 条。
        """
        result = market_research.list_workbench(
            tenant_id=tenant_id,
            topic_id=topic_id.strip() or None,
            category_id=category_id.strip() or None,
            limit=100,
        )
        needle = query.strip().casefold()
        items = result["items"]
        if published_after:
            items = [item for item in items
                     if (item.get("published_at") or "") >= published_after]
        if needle:
            items = [item for item in items if needle in "\n".join((
                item.get("title", ""), item.get("summary", ""),
                item.get("content_markdown", ""),
            )).casefold()]
        fields = ("id", "topic_id", "category_id", "title", "summary", "sources",
                  "published_at", "captured_at", "source_name")
        return {
            "count": len(items),
            "truncated": len(result["items"]) == 100,
            "items": [{key: item.get(key) for key in fields} for item in items[:limit]],
        }

    @mcp.tool
    def get_observation(observation_id: str) -> dict:
        """读取单条研究观察详情，包含正文和来源链接。"""
        item = market_research.get_observation(
            tenant_id=tenant_id, observation_id=observation_id.strip())
        if item is None:
            return {"error": "not_found", "message": "没有找到这条研究观察"}
        return item

    @mcp.tool
    def get_judgement(topic_id: str, category_id: str = "") -> dict:
        """读取某个主题或细分领域的最新趋势研判、版本与新增证据状态。

        category_id 留空时读取主题综合研判。细分研判包含所引用的工作台观察。
        """
        try:
            return market_research.get_judgement(
                tenant_id=tenant_id, topic_id=topic_id.strip(),
                category_id=category_id.strip(), include_evidence=bool(category_id))
        except ValueError as exc:
            return {"error": "invalid_scope", "message": str(exc)}

    @mcp.tool
    def get_topic_judgement_overview(topic_id: str) -> dict:
        """读取主题综合研判和全部细分研判的版本、覆盖及待更新状态。

        定时采集结束后可用它判断哪些分类研判已更新、主题报告是否待汇总。
        """
        try:
            return market_research.get_topic_judgement_overview(
                tenant_id=tenant_id, topic_id=topic_id.strip())
        except ValueError as exc:
            return {"error": "invalid_scope", "message": str(exc)}

    @mcp.tool
    def get_judgement_history(topic_id: str, category_id: str = "") -> list[dict]:
        """读取主题或细分领域已保存的研判版本摘要，观察历史判断如何变化。"""
        try:
            return market_research.list_judgement_history(
                tenant_id=tenant_id, topic_id=topic_id.strip(),
                category_id=category_id.strip())
        except ValueError as exc:
            return [{"error": "invalid_scope", "message": str(exc)}]

    @mcp.tool
    def save_judgement(
        topic_id: str,
        category_id: str,
        title: Annotated[str, Field(min_length=1, max_length=300)],
        conclusion: Annotated[str, Field(min_length=1, max_length=4000)],
        content_markdown: Annotated[str, Field(min_length=1, max_length=100_000)],
        sources: Annotated[list[SourceReference], Field(min_length=1, max_length=30)],
        confidence: str = "medium",
        data_cutoff: str = "",
        evidence_ids: Annotated[list[str], Field(max_length=100)] = Field(default_factory=list),
    ) -> dict:
        """保存细分领域或主题综合研判的新版本，并保留来源和观察记录关联。

        主题综合研判（category_id 留空）只能在已有细分领域研判基础上保存。
        """
        try:
            result = market_research.save_judgement(
                tenant_id=tenant_id, topic_id=topic_id, category_id=category_id,
                title=title, conclusion=conclusion,
                content_markdown=content_markdown, confidence=confidence,
                data_cutoff=data_cutoff, evidence_ids=evidence_ids,
                sources=[source.model_dump() for source in sources],
                created_by="mcp:market-intel", created_by_name="外部研究智能体",
            )
            return result
        except ValueError as exc:
            return {"error": "invalid_judgement", "message": str(exc)}

    @mcp.tool
    def get_ingestion_guidelines() -> str:
        """返回定时采集智能体的入库规则与质量要求。"""
        categories = "\n".join(
            f"- {topic['id']}: " + ", ".join(
                f"{item['id']}（{item['name']}）" for item in topic["categories"])
            for topic in market_research.TOPICS)
        return (
            "小察行业研究入库规范：\n"
            "1. 只提交有可访问来源的研究观察；优先原始论文、官方公告、标准或监管文件。\n"
            "2. 每条记录填写 topic_id、category_id、title、summary、content_markdown、sources、source_name、published_at。\n"
            "3. 每条资讯必须且只能归入所属主题下的一个 category_id；无法判断时先核对资料，不要按标题猜测。\n"
            "4. sources 为对象列表，每项含 title、url、published_at、organization。正文区分已核实事实、研究解读和待验证事项。\n"
            "5. 固定数据源的条目应提供稳定 external_id；若没有，则用规范来源 URL 作为去重键。重复运行会返回已有记录，不重复插入。\n"
            "6. 不把供应商自报 benchmark 写成独立验证；不把候选发现写成已证实成果；标明实验、同行评审或复现状态。\n"
            "7. 每轮采集结束后，检查本轮新增记录所涉细分领域的最新研判；如果新增证据会改变趋势判断、指标或风险，追加一版分类研判并写入实际引用的 observation IDs。纯重复、低价值记录不需要机械地产生新版本。\n"
            "8. 主题综合研判只能综合已有的细分领域研判。采集结束可调用 get_topic_judgement_overview(topic_id) 查看各分类版本；细分研判更新后，主题研判显示为待更新。等本轮相关细分研判完成后，再基于这些分类研判形成主题版本，不能跳过分类直接从文章列表生成。\n"
            "9. 历史研判版本会保留，可调用 get_judgement_history(topic_id, category_id) 比较新旧判断，更新时说明哪些结论变化、哪些仍成立。\n"
            "10. 主题和细分领域如下：\n" + categories
        )

    @mcp.tool
    def save_observation(
        topic_id: str,
        category_id: str,
        title: Annotated[str, Field(min_length=1, max_length=300)],
        sources: Annotated[list[SourceReference], Field(max_length=30)],
        summary: Annotated[str, Field(max_length=2000)] = "",
        content_markdown: Annotated[str, Field(max_length=100_000)] = "",
        source_name: Annotated[str, Field(max_length=200)] = "",
        published_at: Annotated[str, Field(max_length=100)] = "",
        external_id: Annotated[str, Field(max_length=500)] = "",
    ) -> dict:
        """写入来源任务的研究观察；按 external_id 或主来源 URL 幂等去重。

        若同一来源条目此前已入库，返回已有观察并标记 created=false。
        """
        clean_sources = [source.model_dump() for source in sources]
        result = market_research.save_source_observation(
            tenant_id=tenant_id,
            topic_id=topic_id,
            category_id=category_id,
            title=title,
            summary=summary,
            content_markdown=content_markdown,
            sources=clean_sources,
            source_name=source_name,
            published_at=published_at,
            external_id=external_id,
            created_by="mcp:market-intel",
            created_by_name="外部研究智能体",
        )
        return result

    http_app = mcp.http_app(
        path="/mcp",
        transport="streamable-http",
        stateless_http=True,
    )
    return mcp, http_app


def mount_market_research_mcp(app, *, token: str, tenant_id: str) -> bool:
    """Mount the protected MCP endpoint when a sufficiently strong token exists."""
    token = (token or "").strip()
    if not token:
        return False
    if len(token.encode("utf-8")) < 32:
        log.error("MARKET_RESEARCH_MCP_TOKEN 至少需要 32 字节；入站 MCP 未启用")
        return False
    server, http_app = build_market_research_mcp(tenant_id)
    app.state.market_research_mcp_server = server
    app.state.market_research_mcp_http_app = http_app
    app.mount("/mcp/market-intel", BearerTokenASGI(http_app, token), name="market-intel-mcp")
    log.info("小察研究 MCP 已启用：/mcp/market-intel/mcp tenant=%s", tenant_id)
    return True
