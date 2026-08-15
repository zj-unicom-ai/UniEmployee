"""通用时间工具：get_current_time —— 返回当前真实日期/时间（东八区/北京时间）。

为什么需要它：LLM 本身不知道“今天”是什么时候，训练数据有时间截止、
且无法感知系统当前时间。用户问“今天几号”“现在几点”“本周/本月/今年”
“距离某天还有多久”时，必须调用本工具才能给出基于真实时间的回答，
否则会凭记忆乱猜日期。本工具是所有数字员工的通用能力，编译期自动注入，
不依赖某个员工在 tools 字段里显式声明。
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain.tools import tool

# 产品用户群在中国，固定东八区；容器/跨平台靠 tzdata 包提供 IANA 数据库。
try:
    TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # 极端情况下系统缺时区库时回退 UTC，并强制标注
    TZ = ZoneInfo("UTC")

WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]  # weekday() 周一=0


@tool
def get_current_time() -> str:
    """【获取当前时间】返回当前真实的北京时间（东八区）。

    当用户问到\"今天几号\"\"现在几点\"\"本周/本月\"\"距离某天还有多久\"等与时间相关的问题时，
    必须先调用本工具获取真实时间再回答，不可凭训练数据猜测。"""
    now = datetime.now(TZ)
    weekday = WEEKDAYS[now.weekday()]
    iso_year, iso_week, _ = now.isocalendar()
    utc = datetime.now(ZoneInfo("UTC"))
    tz_name = "Asia/Shanghai" if TZ.key == "Asia/Shanghai" else TZ.key
    return (
        f"当前时间（{tz_name}，东八区）："
        f"{now.year}年{now.month:02d}月{now.day:02d}日 星期{weekday} "
        f"{now.hour:02d}:{now.minute:02d}:{now.second:02d}\n"
        f"ISO 日期：{now.date().isoformat()}（第 {iso_week} 周，{iso_year} 年）\n"
        f"Unix 时间戳：{int(now.timestamp())}\n"
        f"UTC 参考：{utc.year}年{utc.month:02d}月{utc.day:02d}日 "
        f"{utc.hour:02d}:{utc.minute:02d}:{utc.second:02d}"
    )
