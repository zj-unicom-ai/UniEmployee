"""全局异常处理：把未捕获的异常转成干净的 JSON 500，不向客户端泄露堆栈。

原则：
- 正常的 ``HTTPException`` 仍由 Starlette 默认处理器返回 ``{detail: ...}`` 的 JSON，
  保持不变（客户端已能正确解析）。
- 任何漏网的 ``Exception``（bug / 未预期错误）在这里被兜底：完整堆栈只写日志，
  客户端只拿到 ``{"error": "internal_server_error"}``，避免暴露内部实现。
"""
import logging

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("app.errors")


def register_exception_handlers(app) -> None:
    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "未捕获异常: %s %s | %s: %s",
            request.method,
            request.url.path,
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"error": "internal_server_error", "message": "服务器内部错误，请稍后重试"},
        )
