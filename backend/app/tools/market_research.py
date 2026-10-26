"""小察的结构化研究结果写入工具。"""

import json

from langchain.tools import tool

from app.market_research import save_from_agent


@tool
def save_market_observation(topic_id: str, category_id: str, title: str, summary: str,
                            content_markdown: str, sources_json: str = "[]",
                            source_name: str = "", published_at: str = "") -> str:
    """【保存行业观察】把已核实的研究发现写入小察工作台，供后续持续观察和趋势分析。

    参数:
        topic_id: embodied-intelligence / ai-frontier / policy-analysis 之一
        category_id: 该主题下唯一的细分领域 ID。具身智能：vla-embodied-reasoning、world-model-spatial-intelligence、robot-learning-data、dexterous-manipulation-whole-body、simulation-training-toolchain、evaluation-safety-agent-integration、home-service-robots、industrial-robots、commercial-service-robots、robot-platforms、embodied-models、robot-commercialization；AI 前沿观察：foundation-models、multimodal-ai、ai-agents、compute-infrastructure、ai-applications、ai-ecosystem；政策分析：national-strategy、industry-support、regulation-compliance、standards-certification、local-pilots、policy-impact
        title: 观察标题
        summary: 适合工作台列表展示的 1-3 句话摘要
        content_markdown: 研究正文，区分事实、判断和不确定性
        sources_json: 来源列表 JSON，例如 [{"title":"标题","url":"https://...","published_at":"2026-10-21","organization":"机构"}]
        source_name: 采集任务或数据源名称，可选
        published_at: 主要信息发布时间或政策发布日期，可选

    必须先完成来源核验。不要将未经核实的推断写成事实；重要结论应附来源链接。
    """
    return save_from_agent(
        topic_id=topic_id, category_id=category_id, title=title, summary=summary,
        content_markdown=content_markdown, sources_json=sources_json,
        source_name=source_name, published_at=published_at,
    )


@tool
def save_market_judgement(topic_id: str, category_id: str, title: str,
                          conclusion: str, content_markdown: str,
                          confidence: str = "medium", data_cutoff: str = "",
                          evidence_ids_json: str = "[]",
                          sources_json: str = "[]") -> str:
    """【保存趋势研判】把一版有来源、有证据范围的主题/细分领域研判保存为新版本。

    category_id 填某个细分领域 ID；只有生成主题综合研判时才留空。主题研判必须
    以已存在的细分领域研判为基础。每次更新会保留版本记录，并标记所依据的数据截止时间。
    sources_json 为来源对象 JSON 数组；evidence_ids_json 为本轮实际使用的观察记录 ID 数组。
    confidence 仅能是 high、medium 或 low。
    """
    try:
        from langgraph.config import get_config
        from app import market_research
        from app.catalog import get_user

        cfg = get_config() or {}
        configurable = cfg.get("configurable") or {}
        auth_context = configurable.get("auth_context") or {}
        if configurable.get("employee_id") != "market-intel":
            raise RuntimeError("仅小察可以保存行业趋势研判")
        user_id = configurable.get("user_id") or auth_context.get("user_id")
        tenant_id = auth_context.get("tenant_id")
        if not user_id or not tenant_id:
            raise RuntimeError("运行上下文缺少用户或租户信息，未保存研判")
        try:
            evidence_ids = json.loads(evidence_ids_json or "[]")
            sources = json.loads(sources_json or "[]")
        except json.JSONDecodeError as exc:
            raise ValueError("sources_json 和 evidence_ids_json 必须是 JSON 数组") from exc
        if not isinstance(evidence_ids, list) or not isinstance(sources, list):
            raise ValueError("sources_json 和 evidence_ids_json 必须是 JSON 数组")
        user = get_user(user_id) or {}
        result = market_research.save_judgement(
            tenant_id=tenant_id, topic_id=topic_id, category_id=category_id,
            title=title, conclusion=conclusion, content_markdown=content_markdown,
            confidence=confidence, data_cutoff=data_cutoff,
            evidence_ids=evidence_ids, sources=sources,
            created_by=user_id,
            created_by_name=user.get("display_name") or user.get("username") or "",
        )
        report = result.get("report") or {}
        return (f"已保存「{report['title']}」第 {report['version']} 版研判，"
                f"范围={result['category_id'] or '主题综合研判'}。")
    except RuntimeError:
        raise
    except ValueError:
        raise
    except Exception as exc:
        raise RuntimeError("趋势研判保存失败") from exc
