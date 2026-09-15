#!/usr/bin/env python3
"""生成比赛版算网运营数据集（CSV）。

与 backend/app/ontology.py 中的星联通信演示实体保持一致，用于小网四类能力演示：
  1. 高新区 1 号基站近一周频繁退服，影响 VIP 客户杭州智造科技
  2. 城东 1 号基站 9 月 3 日发生 P1 板卡故障，指标单日骤降
  3. GPU 训练节点与高新-下沙光缆高水位，支撑扩容测算
  4. 割接 SOP、故障升级上报和 VIP 保障有明确制度依据

输出文件与原字段完全一致，可直接替换 workspace/datasets/ 下旧数据。
"""

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

random.seed(20260914)

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "workspace" / "datasets"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TODAY = datetime(2026, 9, 14)

STATIONS = {
    "城东1号基站": "BS-001",
    "城东2号基站": "BS-002",
    "高新区1号基站": "BS-003",
    "老城1号基站": "BS-004",
}

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


def _write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"生成 {path} — {len(rows)} 行")


def _make_alert(no: int, ds: str, station: str, alarm_type: str,
                severity: str, root_cause: str | None = None,
                status: str | None = None, duration: int | None = None) -> dict:
    hour = random.choices(
        range(24),
        weights=[2, 1, 1, 1, 1, 2, 4, 6, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8,
                 8, 7, 5, 4, 3, 2],
    )[0]
    minute = random.randint(0, 59)
    if duration is None:
        base = {"P1": (720, 2880), "P2": (90, 720), "P3": (15, 180),
                "P4": (1, 10)}[severity]
        duration = random.randint(*base)
    if status is None:
        status = random.choices(["已恢复", "处理中", "待确认"],
                                weights=[86, 8, 6])[0]
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


def gen_alerts() -> list[dict]:
    rows: list[dict] = []
    alert_no = 20000
    start = TODAY - timedelta(days=90)

    for day in range(91):
        date = start + timedelta(days=day)
        ds = date.strftime("%Y-%m-%d")

        # 常规日：全网每天 2~5 条零散告警，以 P3/P4 为主
        for _ in range(random.randint(2, 5)):
            station = random.choice(list(STATIONS))
            severity = random.choices(["P3", "P4", "P2"],
                                      weights=[58, 29, 13])[0]
            alarm_type = random.choice(ALARM_TYPES[2:])
            rows.append(_make_alert(alert_no, ds, station, alarm_type,
                                    severity))
            alert_no += 1

        # 故事线 A：高新区 1 号基站 9/8 起持续劣化
        if ds >= "2026-09-08":
            for _ in range(random.randint(2, 4)):
                rows.append(_make_alert(
                    alert_no, ds, "高新区1号基站",
                    random.choice(["退服", "传输中断", "链路闪断"]),
                    "P2",
                    root_cause=random.choice(["光纤老化", "施工误碰", "负载过高"]),
                    status=random.choice(["处理中", "待确认", "处理中", "已恢复"]),
                ))
                alert_no += 1

        # 故事线 B：城东 1 号基站 9/3 P1 板卡故障
        if ds == "2026-09-03":
            rows.append(_make_alert(
                alert_no, ds, "城东1号基站", "板卡故障", "P1",
                root_cause="设备老化", status="已恢复", duration=2880,
            ))
            alert_no += 1
        elif ds == "2026-09-04":
            rows.append(_make_alert(
                alert_no, ds, "城东1号基站", "光模块故障", "P2",
                root_cause="设备老化", status="已恢复", duration=180,
            ))
            alert_no += 1

    return rows


def gen_kpi() -> list[dict]:
    rows: list[dict] = []
    start = TODAY - timedelta(days=180)
    groups = ["城东片区", "高新区片区", "老城片区"]

    for day in range(181):
        date = start + timedelta(days=day)
        ds = date.strftime("%Y-%m-%d")
        for group in groups:
            connection = random.uniform(99.30, 99.70)
            latency = random.uniform(12, 20)
            drop = random.uniform(0.04, 0.18)
            n_alerts = random.randint(0, 4)
            n_tickets = random.randint(0, 2)

            if group == "高新区片区" and ds >= "2026-09-08":
                days_in = (date - datetime(2026, 9, 8)).days
                connection -= 0.12 * (days_in + 1) * random.uniform(0.85, 1.05)
                latency += 3.0 * (days_in + 1) * random.uniform(0.8, 1.1)
                drop += 0.08 * (days_in + 1) * random.uniform(0.8, 1.05)
                n_alerts += random.randint(2, 6)
                n_tickets += random.randint(1, 3)

            if group == "城东片区" and ds in ("2026-09-03", "2026-09-04"):
                connection -= random.uniform(1.7, 2.2)
                drop += random.uniform(0.85, 1.20)
                n_alerts += random.randint(4, 8)
                n_tickets += random.randint(2, 5)

            connection = max(connection, 96.5)
            drop = min(max(drop, 0.01), 1.60)
            latency = min(max(latency, 8), 52)

            sla = 100.0 if connection >= 99.0 and drop <= 0.5 else \
                round(random.uniform(86, 96), 1)
            satisfaction = round(random.uniform(4.50, 4.90), 2)
            if connection < 99.0:
                satisfaction -= random.uniform(0.08, 0.30)
            satisfaction = round(min(max(satisfaction, 3.8), 4.95), 2)

            rows.append({
                "date": ds,
                "station_group": group,
                "connection_rate": round(connection, 3),
                "drop_rate": round(drop, 3),
                "avg_latency_ms": round(latency, 1),
                "alert_count": n_alerts,
                "ticket_count": n_tickets,
                "sla_met_rate": sla,
                "satisfaction": satisfaction,
            })

    return rows


RESOURCES = [
    ("DC-01", "机房", "滨江核心机房", "机柜", 200, 156, "杭州市滨江区", "运行中", "平稳"),
    ("DC-02", "机房", "下沙汇聚机房", "机柜", 120, 74, "杭州市钱塘区", "运行中", "+10% 半年内"),
    ("CP-01", "算力节点", "GPU训练节点01", "卡", 64, 59, "滨江核心机房", "运行中", "+30% 半年内"),
    ("CP-02", "算力节点", "GPU推理节点01", "卡", 48, 28, "滨江核心机房", "运行中", "+20% 半年内"),
    ("CP-03", "算力节点", "CPU核心节点01", "vCPU", 1024, 688, "下沙汇聚机房", "运行中", "平稳"),
    ("CP-04", "算力节点", "CPU边缘节点01", "vCPU", 256, 121, "高新区边缘机房", "运行中", "+15% 半年内"),
    ("LK-01", "传输链路", "城东-滨江光缆", "Gbps", 400, 268, "城东片区", "运行中", "+10% 半年内"),
    ("LK-02", "传输链路", "高新-下沙光缆", "Gbps", 400, 348, "高新区片区", "运行中", "+25% 半年内"),
    ("LK-03", "传输链路", "老城-滨江光缆", "Gbps", 200, 96, "老城片区", "运行中", "平稳"),
    ("BW-01", "带宽", "政企专线池", "Gbps", 100, 61, "全市", "运行中", "+20% 半年内"),
    ("BW-02", "带宽", "家庭宽带池", "Gbps", 300, 171, "全市", "运行中", "+5% 半年内"),
    ("BW-03", "带宽", "移动回传池", "Gbps", 200, 148, "全市", "运行中", "+15% 半年内"),
]


def gen_resources() -> list[dict]:
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
    return rows


def main() -> None:
    print("== 生成比赛版算网运营数据集 ==\n")
    _write_csv(OUTPUT_DIR / "netops_alerts.csv", gen_alerts())
    _write_csv(OUTPUT_DIR / "netops_kpi.csv", gen_kpi())
    _write_csv(OUTPUT_DIR / "netops_resources.csv", gen_resources())
    print("\n生成完毕：", OUTPUT_DIR)


if __name__ == "__main__":
    main()
