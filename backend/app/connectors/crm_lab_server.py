"""本地 CRM Lab 的只读 MCP 桥接；真实数据由独立 HTTP 服务提供。"""

from __future__ import annotations

import os
import re

import httpx
from fastmcp import FastMCP


mcp = FastMCP("crm-lab")
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


def _get(path: str, params: dict | None = None) -> dict:
    base_url = os.environ.get("CRM_LAB_API_URL", "http://127.0.0.1:18780").rstrip("/")
    api_key = os.environ.get("CRM_LAB_READ_KEY", "")
    if not api_key:
        return {"error": "CRM Lab 只读密钥未配置", "source": "crm-lab"}
    try:
        with httpx.Client(timeout=8.0, follow_redirects=False) as client:
            response = client.get(
                f"{base_url}{path}",
                params=params,
                headers={"X-API-Key": api_key},
            )
        if response.status_code == 404:
            return {"error": "记录不存在", "source": "crm-lab", "status_code": 404}
        if response.status_code in (401, 403):
            return {"error": "CRM Lab 鉴权失败或无权访问", "source": "crm-lab", "status_code": response.status_code}
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            return {"error": "CRM Lab 返回格式无效", "source": "crm-lab"}
        return result
    except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
        return {"error": "CRM Lab 暂时不可用", "source": "crm-lab"}
    except (httpx.HTTPStatusError, ValueError):
        return {"error": "CRM Lab 查询失败", "source": "crm-lab"}


@mcp.tool
def crm_lab_search_customers(query: str) -> dict:
    """按客户名称或公司名称搜索本地 CRM Lab 的合成客户，返回记录 ID 和更新时间。"""
    return _get("/customers", {"q": query[:100], "limit": 20})


@mcp.tool
def crm_lab_get_customer(customer_id: str) -> dict:
    """按客户 ID 读取本地 CRM Lab 的合成客户档案。"""
    if not _ID.fullmatch(customer_id):
        return {"error": "客户 ID 格式无效", "source": "crm-lab"}
    return _get(f"/customers/{customer_id}")


@mcp.tool
def crm_lab_customer_cases(customer_id: str) -> dict:
    """读取指定客户的客服 Case，包含状态、优先级和更新时间。"""
    return _get("/cases", {"customer_id": customer_id, "limit": 50})


@mcp.tool
def crm_lab_get_case(case_id: str) -> dict:
    """按 Case ID 读取客服 Case 的当前状态和详情。"""
    if not _ID.fullmatch(case_id):
        return {"error": "Case ID 格式无效", "source": "crm-lab"}
    return _get(f"/cases/{case_id}")


if __name__ == "__main__":
    mcp.run()  # stdio transport
