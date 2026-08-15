"""联网搜索工具：博查搜索（bocha_search）。

统一搜索入口——后续凡是需要联网检索的，一律走这个工具。
通过智算平台 openapi 代理调用博查搜索：
  POST https://maas-api.ai-yuanjing.com/openapi/v1/uniclaw/general/tool/bocha_search
  Authorization: Bearer $BOCHA_API_KEY
  {"query": "搜索词"}
返回 data.webPages.value[]（name / url / snippet）。

API Key 走环境变量 BOCHA_API_KEY（.env），不硬编码。
"""
import json
import os
import urllib.request

from langchain.tools import tool

BOCHA_URL = "https://maas-api.ai-yuanjing.com/openapi/v1/uniclaw/general/tool/bocha_search"


@tool
def bocha_search(query: str) -> str:
    """【联网搜索】搜索网络上的实时信息。

    当用户需要查新闻、政策、竞品动态、最新资讯等知识库之外的内容时调用此工具。
    回答时需标注信息来源链接。"""
    key = os.environ.get("BOCHA_API_KEY", "").strip()
    if not key:
        return "[错误] 未配置 BOCHA_API_KEY，无法联网搜索。"

    body = json.dumps({"query": query}).encode("utf-8")
    req = urllib.request.Request(
        BOCHA_URL, data=body, method="POST",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return f"[搜索失败] {type(e).__name__}: {e}"

    if data.get("code") != 200:
        return f"[搜索失败] 接口返回 code={data.get('code')} msg={data.get('msg')}"

    pages = (data.get("data") or {}).get("webPages", {}).get("value", [])
    if not pages:
        return f"未找到与「{query}」相关的搜索结果。"

    out = []
    for i, p in enumerate(pages[:6], 1):
        out.append(
            f"{i}. {p.get('name', '')}\n"
            f"   摘要：{p.get('snippet', '')}\n"
            f"   链接：{p.get('url', '')}"
        )
    return "\n\n".join(out)
