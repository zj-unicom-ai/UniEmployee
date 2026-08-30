#!/usr/bin/env python3
"""生成算网运营模拟数据集（CSV），输出到 workspace/data/。

覆盖三个算网运营分析维度：
  1. netops_alerts.csv     — 告警流水（90 天，含等级/时长/根因/处理人）
  2. netops_kpi.csv        — 运营指标日报（180 天 × 3 片区，含 SLA 达标率）
  3. netops_resources.csv  — 算网资源台账（算力节点/机房/传输链路/带宽）

数据集是"星联通信"的算网运营模拟数据，实体名称与本体种子
（app/ontology.py 的 seed_netops_demo_if_empty）严格对齐：
基站（城东1/2号、高新区1号、老城1号）、装维人员（王强/赵敏/陈涛）。

内嵌三条可分析出的"故事线"：
  A. 高新区1号基站近 7 天频发 P2 退服/传输中断（对应本体 status=退服）
  B. 城东1号基站 8 月上旬一次 P1 板卡故障大障（长历时）
  C. 资源台账中 AI 训练算力节点与高新区光缆利用率超 80% 预警线
所有数字均为通信行业真实水平估算。
"""

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "workspace" / "data"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 数据截止日（与演示叙事对齐的固定日期，不用 datetime.now 保证可复现）
TODAY = datetime(2026, 8, 30)

STATIONS = {
    "城东1号基站": "BS-001",
    "城东2号基站": "BS-002",
    "高新区1号基站": "BS-003",
    "老城1号基站": "BS-004",
}
# 装维人员与本体 maintain 关系对齐：王强→城东1/2号，赵敏→高新区1号，陈涛→老城1号
HANDLER_BY_STATION = {
    "城东1号基站": "王强",
    "城东2号基站": "王强",
    "高新区1号基站": "赵敏",
    "老城1号基站": "陈涛",
}

ALARM_TYPES = ["退服", "传输中断", "光模块故障", "板卡故障", "功率异常",
               "电池告警", "温度告警", "链路闪断"]
ROOT_CAUSES = ["光纤老化", "电源故障", "设备老化", "软件缺陷", "高温",
               "施工误碰", "负载过高", "未知"]


def _write_csv(path: Path, rows: list[dict]):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"生成 {path} — {len(rows)} 行")


# ── 1. 告警流水 ──
def gen_alerts():
    rows = []
    alert_no = 10000
    start = TODAY - timedelta(days=90)

    for day in range(90):
        date = start + timedelta(days=day)
        ds = date.strftime("%Y-%m-%d")
        # 常规日：全网每天 2~6 条零星告警，以 P3/P4 为主
        n_routine = random.randint(2, 6)
        for _ in range(n_routine):
            station = random.choice(list(STATIONS))
            severity = random.choices(["P3", "P4", "P2"],
                                      weights=[55, 30, 15])[0]
            alarm_type = random.choice(ALARM_TYPES[2:])  # 常规以非退服类为主
            rows.append(_make_alert(alert_no, ds, station, alarm_type, severity))
            alert_no += 1

        # 故事线 A：高新区1号基站 近 7 天（8/24 起）频发 P2 退服/传输中断
        if ds >= "2026-08-24":
            for _ in range(random.randint(1, 3)):
                rows.append(_make_alert(
                    alert_no, ds, "高新区1号基站",
                    random.choice(["退服", "传输中断", "链路闪断"]), "P2",
                    root_cause=random.choice(["光纤老化", "施工误碰", "负载过高"])))
                alert_no += 1

        # 故事线 B：城东1号基站 8/08~8/10 P1 板卡故障大障（连续 3 天告警）
        if ds in ("2026-08-08", "2026-08-09", "2026-08-10"):
            rows.append(_make_alert(
                alert_no, ds, "城东1号基站", "板卡故障", "P1",
                root_cause="设备老化", status="已恢复",
                duration=random.choice([1260, 2880, 180])))
            alert_no += 1

    path = OUTPUT_DIR / "netops_alerts.csv"
    _write_csv(path, rows)
    return rows


def _make_alert(no: int, ds: str, station: str, alarm_type: str,
                severity: str, root_cause: str | None = None,
                status: str | None = None, duration: int | None = None) -> dict:
    hour = random.choices(range(24), weights=[2, 1, 1, 1, 1, 2, 4, 6, 8, 8, 8,
                                              8, 8, 8, 8, 8, 8, 8, 8, 7, 5, 4, 3, 2])[0]
    minute = random.randint(0, 59)
    if duration is None:
        # 历时与等级相关：P1 长历时、P4 秒级自愈
        base = {"P1": (300, 1440), "P2": (60, 480), "P3": (15, 120),
                "P4": (1, 10)}[severity]
        duration = random.randint(*base)
    if status is None:
        # 大部分已恢复；近期 P2 有少量处理中/待确认
        status = random.choices(["已恢复", "处理中", "待确认"],
                                weights=[88, 7, 5])[0]
    if root_cause is None:
        root_cause = random.choice(ROOT_CAUSES)
    return {
        "alert_id": f"AL{no}",
        "time": f"{ds} {hour:02d}:{minute:02d}",
        "station": station,
        "station_code": STATIONS[station],
        "alarm_type": alarm_type,
        "severity": severity,
        "status": status,
        "duration_min": duration,
        "root_cause": root_cause,
        "handler": HANDLER_BY_STATION[station],
    }


# ── 2. 运营指标日报（3 片区 × 180 天）──
def gen_kpi():
    rows = []
    start = TODAY - timedelta(days=180)
    groups = ["城东片区", "高新区片区", "老城片区"]

    for day in range(181):
        date = start + timedelta(days=day)
        ds = date.strftime("%Y-%m-%d")
        for group in groups:
            # 基线：接通率 99.2~99.8，时延 12~22ms
            connection = random.uniform(99.2, 99.8)
            latency = random.uniform(12, 22)
            drop = random.uniform(0.05, 0.25)
            n_alerts = random.randint(0, 5)
            n_tickets = random.randint(0, 3)

            # 故事线 A 的指标侧写：高新区 8 月中下旬劣化（8/18 起逐周下滑）
            if group == "高新区片区" and ds >= "2026-08-18":
                days_in = (date - datetime(2026, 8, 18)).days
                connection -= 0.08 * (days_in // 5 + 1) * random.uniform(0.6, 1.0)
                latency += 5 * (days_in // 5 + 1) * random.uniform(0.6, 1.0)
                drop += 0.06 * (days_in // 5 + 1)
                n_alerts += random.randint(2, 6)
                n_tickets += random.randint(1, 3)

            # 故事线 B 的指标侧写：城东 8/08~8/10 接通率骤降
            if group == "城东片区" and ds in ("2026-08-08", "2026-08-09",
                                              "2026-08-10"):
                connection -= random.uniform(1.5, 2.5)
                drop += random.uniform(0.8, 1.6)
                n_alerts += random.randint(3, 8)
                n_tickets += random.randint(2, 5)

            sla = 100.0 if connection >= 99.0 and drop <= 0.5 else \
                round(random.uniform(86, 97), 1)
            satisfaction = round(random.uniform(4.5, 4.9), 2)
            if connection < 99.0:
                satisfaction -= random.uniform(0.1, 0.4)

            rows.append({
                "date": ds,
                "station_group": group,
                "connection_rate": round(max(connection, 95.0), 3),
                "drop_rate": round(max(drop, 0.01), 3),
                "avg_latency_ms": round(max(latency, 8), 1),
                "alert_count": n_alerts,
                "ticket_count": n_tickets,
                "sla_met_rate": sla,
                "satisfaction": round(max(satisfaction, 3.8), 2),
            })

    path = OUTPUT_DIR / "netops_kpi.csv"
    _write_csv(path, rows)
    return rows


# ── 3. 算网资源台账 ──
# 资源名称与本体种子（datacenter/compute_node/link 实体）对齐，便于 csv+本体交叉分析
RESOURCES = [
    # (resource_id, category, name, unit, capacity, used, location, status, demand_forecast)
    ("DC-01", "机房", "滨江核心机房", "机柜", 200, 156, "杭州市滨江区", "运行中", "平稳"),
    ("DC-02", "机房", "下沙汇聚机房", "机柜", 120, 74, "杭州市钱塘区", "运行中", "+10% 半年内"),
    ("CP-01", "算力节点", "GPU训练节点01", "卡", 64, 59, "滨江核心机房", "运行中", "+30% 半年内"),
    ("CP-02", "算力节点", "GPU推理节点01", "卡", 48, 27, "滨江核心机房", "运行中", "+20% 半年内"),
    ("CP-03", "算力节点", "CPU核心节点01", "vCPU", 1024, 688, "下沙汇聚机房", "运行中", "平稳"),
    ("CP-04", "算力节点", "CPU边缘节点01", "vCPU", 256, 121, "高新区边缘机房", "运行中", "+15% 半年内"),
    ("LK-01", "传输链路", "城东-滨江光缆", "Gbps", 400, 268, "城东片区", "运行中", "+10% 半年内"),
    ("LK-02", "传输链路", "高新-下沙光缆", "Gbps", 400, 348, "高新区片区", "运行中", "+25% 半年内"),
    ("LK-03", "传输链路", "老城-滨江光缆", "Gbps", 200, 96, "老城片区", "运行中", "平稳"),
    ("BW-01", "带宽", "政企专线池", "Gbps", 100, 61, "全市", "运行中", "+20% 半年内"),
    ("BW-02", "带宽", "家庭宽带池", "Gbps", 300, 171, "全市", "运行中", "+5% 半年内"),
    ("BW-03", "带宽", "移动回传池", "Gbps", 200, 148, "全市", "运行中", "+15% 半年内"),
]


def gen_resources():
    rows = []
    for rid, cat, name, unit, cap, used, loc, status, demand in RESOURCES:
        rows.append({
            "resource_id": rid,
            "category": cat,
            "name": name,
            "unit": unit,
            "capacity": cap,
            "used": used,
            "utilization_pct": round(used / cap * 100, 1),
            "location": loc,
            "status": status,
            "demand_forecast": demand,
        })
    path = OUTPUT_DIR / "netops_resources.csv"
    _write_csv(path, rows)
    return rows


if __name__ == "__main__":
    print("== 生成算网运营模拟数据集 ==\n")
    gen_alerts()
    gen_kpi()
    gen_resources()
    print("\n全部生成完毕，文件位于:", OUTPUT_DIR)
