"""会话级工具调用管理器（从 Aix-DB 搬迁，纯逻辑零改动）。

解决 LLM 死循环和重复调用问题，每个会话独立管理工具调用状态。
检测机制：
  - 单工具调用上限（默认 30 次）
  - 总调用次数上限（默认 60 次）
  - 连续同一工具调用上限（默认 15 次）
  - 连续失败上限（默认 5 次）
  - 重复 SQL 查询检测
  - 多工具循环模式检测（A-B-A-B 模式）
"""

import hashlib
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, Optional
from contextvars import ContextVar

logger = logging.getLogger("app.agent.analyst.tools.tool_call_manager")


@dataclass
class ToolCallStats:
    """工具调用统计"""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    last_call_time: float = 0
    consecutive_failures: int = 0
    consecutive_same_tool: int = 0
    last_tool_name: str = ""


@dataclass
class SessionContext:
    """会话上下文，存储每个会话的工具调用状态"""
    session_id: str
    created_at: float = field(default_factory=time.time)
    tool_call_counts: Dict[str, int] = field(default_factory=dict)
    recent_queries: deque = field(default_factory=lambda: deque(maxlen=20))
    recent_tool_calls: deque = field(default_factory=lambda: deque(maxlen=30))
    stats: ToolCallStats = field(default_factory=ToolCallStats)
    detected_pattern_counts: Dict[str, int] = field(default_factory=dict)
    should_terminate: bool = False
    termination_reason: str = ""


class ToolCallManager:
    """工具调用管理器 - 每个会话独立管理，检测重复调用和死循环。"""

    MAX_CALLS_PER_TOOL = 30
    MAX_TOTAL_CALLS = 60
    MAX_CONSECUTIVE_SAME_TOOL = 15
    MAX_CONSECUTIVE_FAILURES = 5
    PATTERN_DETECTION_WINDOW = 12
    PATTERN_REPEAT_BEFORE_TERMINATE = 3
    SESSION_TIMEOUT = 35 * 60

    def __init__(self):
        self._sessions: Dict[str, SessionContext] = {}
        self._lock = Lock()

    def get_session(self, session_id: str) -> SessionContext:
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = SessionContext(session_id=session_id)
            return self._sessions[session_id]

    def clear_session(self, session_id: str) -> None:
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]

    def cleanup_expired_sessions(self) -> None:
        current_time = time.time()
        with self._lock:
            expired = [
                sid for sid, ctx in self._sessions.items()
                if current_time - ctx.created_at > self.SESSION_TIMEOUT
            ]
            for sid in expired:
                del self._sessions[sid]

    def check_before_call(
        self, session_id: str, tool_name: str, query: Optional[str] = None
    ) -> tuple[bool, str]:
        """工具调用前检查，返回 (是否允许, 原因)。"""
        ctx = self.get_session(session_id)

        if ctx.should_terminate:
            return False, ctx.termination_reason

        if ctx.stats.total_calls >= self.MAX_TOTAL_CALLS:
            reason = self._terminate_session(
                ctx, f"工具调用总次数已达上限 ({self.MAX_TOTAL_CALLS} 次)。"
                "建议简化查询或重新描述需求。")
            return False, reason

        tool_count = ctx.tool_call_counts.get(tool_name, 0)
        if tool_count >= self.MAX_CALLS_PER_TOOL:
            reason = self._terminate_session(
                ctx, f"工具 '{tool_name}' 调用次数已达上限 ({self.MAX_CALLS_PER_TOOL} 次)。"
                "请使用已获取的信息，无需重复查询。")
            return False, reason

        if ctx.stats.last_tool_name == tool_name:
            ctx.stats.consecutive_same_tool += 1
            if ctx.stats.consecutive_same_tool >= self.MAX_CONSECUTIVE_SAME_TOOL:
                reason = self._terminate_session(
                    ctx, f"连续 {self.MAX_CONSECUTIVE_SAME_TOOL} 次调用同一工具 '{tool_name}'，"
                    "可能陷入循环。")
                return False, reason
        else:
            ctx.stats.consecutive_same_tool = 1

        if ctx.stats.consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
            reason = self._terminate_session(
                ctx, f"连续 {self.MAX_CONSECUTIVE_FAILURES} 次工具调用失败。"
                "请检查查询语法或表结构是否正确。")
            return False, reason

        if query and tool_name == "sql_db_query":
            normalized_query = self._normalize_query(query)
            if normalized_query in ctx.recent_queries:
                return False, (
                    "⚠️ **重复查询检测**: 此查询刚刚已执行过。\n\n"
                    "**请停止重复执行相同查询。**\n"
                    "如需分析结果，请直接使用已获取的数据，或提出新的查询需求。"
                )

        pattern_detected, pattern_msg = self._detect_loop_pattern(ctx, tool_name)
        if pattern_detected:
            reason = self._terminate_session(ctx, pattern_msg)
            return False, reason

        return True, ""

    def record_call(
        self, session_id: str, tool_name: str, success: bool,
        query: Optional[str] = None,
    ) -> None:
        """记录工具调用。"""
        ctx = self.get_session(session_id)
        ctx.tool_call_counts[tool_name] = ctx.tool_call_counts.get(tool_name, 0) + 1
        ctx.stats.total_calls += 1
        ctx.stats.last_call_time = time.time()
        ctx.stats.last_tool_name = tool_name

        if success:
            ctx.stats.successful_calls += 1
            ctx.stats.consecutive_failures = 0
        else:
            ctx.stats.failed_calls += 1
            ctx.stats.consecutive_failures += 1

        ctx.recent_tool_calls.append((tool_name, time.time()))

        if query and tool_name == "sql_db_query" and success:
            normalized_query = self._normalize_query(query)
            ctx.recent_queries.append(normalized_query)

    def get_stats(self, session_id: str) -> Dict:
        ctx = self.get_session(session_id)
        return {
            "session_id": session_id,
            "total_calls": ctx.stats.total_calls,
            "successful_calls": ctx.stats.successful_calls,
            "failed_calls": ctx.stats.failed_calls,
            "consecutive_failures": ctx.stats.consecutive_failures,
            "tool_call_counts": dict(ctx.tool_call_counts),
            "should_terminate": ctx.should_terminate,
            "termination_reason": ctx.termination_reason,
        }

    def _normalize_query(self, query: str) -> str:
        normalized = " ".join(query.split()).upper()
        return hashlib.md5(normalized.encode()).hexdigest()

    def _detect_loop_pattern(
        self, ctx: SessionContext, current_tool: str
    ) -> tuple[bool, str]:
        """检测多工具循环模式（如 A-B-A-B），单一工具连续调用不算。"""
        if len(ctx.recent_tool_calls) < self.PATTERN_DETECTION_WINDOW:
            return False, ""

        recent_tools = [
            t[0] for t in list(ctx.recent_tool_calls)[-self.PATTERN_DETECTION_WINDOW:]
        ]
        recent_tools.append(current_tool)

        for pattern_len in range(2, 5):
            if len(recent_tools) >= pattern_len * 2:
                pattern = tuple(recent_tools[-pattern_len:])
                prev_pattern = tuple(recent_tools[-pattern_len * 2:-pattern_len])

                if pattern == prev_pattern:
                    unique_tools_in_pattern = set(pattern)
                    if len(unique_tools_in_pattern) == 1:
                        continue

                    pattern_str = "->".join(pattern)
                    count = ctx.detected_pattern_counts.get(pattern_str, 0) + 1
                    ctx.detected_pattern_counts[pattern_str] = count
                    if count >= self.PATTERN_REPEAT_BEFORE_TERMINATE:
                        return True, (
                            f"⚠️ **检测到重复调用模式**: {pattern_str}\n\n"
                            "Agent 可能陷入循环。请：\n"
                            "1. 检查之前的查询结果\n"
                            "2. 简化查询需求\n"
                            "3. 明确说明想要的分析目标"
                        )
        return False, ""

    def _terminate_session(self, ctx: SessionContext, reason: str) -> str:
        ctx.should_terminate = True
        ctx.termination_reason = reason
        logger.warning(f"会话 {ctx.session_id} 触发终止: {reason}")
        return reason

    def reset_session(self, session_id: str) -> None:
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id] = SessionContext(session_id=session_id)


# 全局管理器实例
_manager: Optional[ToolCallManager] = None
_manager_lock = Lock()

_current_session_var: ContextVar[Optional[str]] = ContextVar(
    "analyst_session", default=None
)


def get_tool_call_manager() -> ToolCallManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = ToolCallManager()
    return _manager


def set_current_session(session_id: str) -> None:
    _current_session_var.set(session_id)


def get_current_session() -> Optional[str]:
    return _current_session_var.get()
