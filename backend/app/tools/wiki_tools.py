"""产品知识查询兼容工具。

历史上这里读取本地 markdown Wiki；知识库重构后，运行时统一走 RAGFlow。
保留旧工具名是为了兼容已存在的员工配置。
"""
from langchain.tools import tool

from app import knowledge


@tool
def query_product_wiki(category: str = "", keyword: str = "") -> str:
    """【产品知识库查询】按分类和关键词检索 RAGFlow 中的产品资料。

    客户经理拜访客户前或方案中用此工具获取产品详情、解决方案、行业案例。

    参数:
        category: 分类筛选。products=产品介绍, concepts=行业方案/政策/客户画像, comparisons=竞品分析, 空=全部
        keyword: 搜索关键词，如"云犀"、"智慧园区"、"火焰卫士"、"AI政策"、"安全专线"等
    返回:
        匹配的产品资料文本（最长4000字符）
    """
    if not keyword and not category:
        return "请提供搜索关键词或分类。"
    query = " ".join(x for x in (category, keyword) if x)
    return knowledge.search(query, top_k=5)


@tool
def list_product_catalog() -> str:
    """【产品目录总览】从 RAGFlow 检索自研产品完整目录和简要说明。

    客户经理拜访客户前快速了解公司有哪些产品线可推荐时使用。

    返回: 产品分类列表（约3000字符），含产品名称和简要说明。
    """
    return knowledge.search("自研产品目录 产品线 完整目录 简要说明", top_k=5)
