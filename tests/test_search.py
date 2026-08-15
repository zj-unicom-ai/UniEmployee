"""联网搜索工具 bocha_search 回归测试（真实调用，需 BOCHA_API_KEY + 网络）。"""
import os

import dotenv
import pytest

dotenv.load_dotenv()

from app.tools.search import bocha_search

pytestmark = pytest.mark.skipif(
    not os.environ.get("BOCHA_API_KEY"), reason="未配置 BOCHA_API_KEY")


def test_bocha_search_returns_results():
    r = bocha_search.invoke({"query": "今天北京天气"})
    # 不应是错误/失败前缀
    assert "[错误]" not in r
    assert "[搜索失败]" not in r
    # 要么有结果（含"链接"），要么明确"未找到"
    assert "链接" in r or "未找到" in r


def test_bocha_search_result_has_url():
    r = bocha_search.invoke({"query": "DeepSeek"})
    assert "http" in r  # 结果里应含链接
