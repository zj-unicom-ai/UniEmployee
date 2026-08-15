"""Tool 层：工单登记工具。"""
import time
from langchain.tools import tool


@tool
def create_ticket(category: str, urgency: str, summary: str) -> str:
    """【登记工单】登记客服工单，提交给售后团队处理。

    投诉处理或需要人工跟进时调用。urgency 取 urgent（2小时响应）/ high（24小时）/ normal（48小时）。"""
    if urgency not in ("urgent", "high", "normal"):
        return "工单无法登记：urgency 必须是 urgent/high/normal，请修正后重试。"
    ticket_id = "T" + time.strftime("%m%d%H%M%S")
    sla = {"urgent": "2 小时", "high": "24 小时", "normal": "48 小时"}[urgency]
    return f"工单已登记：{ticket_id}（类别：{category}，紧急度：{urgency}）。预计响应时间：{sla}。"
