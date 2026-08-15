"""统一日志配置：结构化（含时间 / 级别 / 模块 / 请求ID），控制台 + 可选文件。

使用方式：
1. 在应用启动早期（lifespan 第一行之后）调用 ``setup_logging()`` 一次；
2. 各模块用 ``get_logger(__name__)`` 取 logger，像平时一样打日志即可；
3. 在 HTTP 中间件里用 ``request_id_var`` 注入请求 ID，让同一次请求的所有
   日志都能被串起来排查。

第三方库（uvicorn.access / langchain / httpx 等）默认降噪到 WARNING，
避免生产环境被无关 INFO 刷屏。
"""
import contextvars
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

# 每个请求一个 ID，供日志串联；默认值 "-" 表示非请求上下文。
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] [rid=%(request_id)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class RequestIdFilter(logging.Filter):
    """给每条日志记录挂上当前请求 ID（来自 contextvars）。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def setup_logging() -> logging.Logger:
    """配置根 logger：控制台 handler +（可选）滚动文件 handler。"""
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    fmt = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
    rid_filter = RequestIdFilter()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    console.addFilter(rid_filter)
    root.addHandler(console)

    log_file = os.environ.get("LOG_FILE")
    if log_file:
        file_handler = RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        file_handler.addFilter(rid_filter)
        root.addHandler(file_handler)

    # 降噪：第三方库的 INFO/DEBUG 对排查帮助不大，且量大。
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("langchain").setLevel(logging.WARNING)
    logging.getLogger("langgraph").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
