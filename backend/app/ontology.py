"""ontology.db 企业业务本体：实体/关系类型（schema）与业务实例（data）两层。

设计要点：
- 通用 schema：类型表存元结构（attrs 为 JSON 数组），实例表存 JSON 属性，不预判业务字段。
- 两层隔离：schema 层 system 租户预置 + 各租户可自定义；data 层按 tenant_id 隔离。
- 运行时工具（ontology_find_entities / ontology_query_relations）只做业务事实查询。
"""

import json
import sqlite3
import time
from pathlib import Path

from app import db as dblayer
from app.paths import db_path

ROOT = Path(__file__).resolve().parent.parent.parent  # backend/
DB = db_path("ontology.db")


def _conn():
    if dblayer.is_pg():
        return dblayer.connect("ontology")
    con = sqlite3.connect(str(DB), timeout=10)
    con.execute("PRAGMA busy_timeout=5000")
    con.row_factory = sqlite3.Row
    return con


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ---------------- 建表 ----------------

def init():
    """建表（幂等）。"""
    con = _conn()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS entity_types(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      code TEXT NOT NULL,
      name TEXT NOT NULL,
      description TEXT,
      icon TEXT,
      attrs TEXT DEFAULT '[]',
      tenant_id TEXT NOT NULL DEFAULT 'system',
      created_at TEXT, updated_at TEXT, deleted_at TEXT,
      UNIQUE(code, tenant_id));
    CREATE TABLE IF NOT EXISTS relation_types(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      code TEXT NOT NULL,
      name TEXT NOT NULL,
      from_type TEXT NOT NULL,
      to_type TEXT NOT NULL,
      cardinality TEXT DEFAULT 'm:n',
      description TEXT,
      tenant_id TEXT NOT NULL DEFAULT 'system',
      created_at TEXT, updated_at TEXT, deleted_at TEXT,
      UNIQUE(code, tenant_id));
    CREATE TABLE IF NOT EXISTS entities(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      entity_type TEXT NOT NULL,
      name TEXT NOT NULL,
      props TEXT DEFAULT '{}',
      tenant_id TEXT NOT NULL,
      created_at TEXT, updated_at TEXT, deleted_at TEXT);
    CREATE TABLE IF NOT EXISTS relations(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      from_id INTEGER NOT NULL,
      to_id INTEGER NOT NULL,
      relation_type TEXT NOT NULL,
      props TEXT DEFAULT '{}',
      tenant_id TEXT NOT NULL,
      created_at TEXT, updated_at TEXT, deleted_at TEXT);
    CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
    CREATE INDEX IF NOT EXISTS idx_entities_tenant ON entities(tenant_id);
    CREATE INDEX IF NOT EXISTS idx_relations_from ON relations(from_id);
    CREATE INDEX IF NOT EXISTS idx_relations_to ON relations(to_id);
    """)
    con.commit()
    con.close()


# ---------------- 种子数据 ----------------

# 模式层预置：9 个实体类型（system 租户，全局共享）
SCHEMA_ENTITY_TYPES = [
    ("org", "组织", "企业/公司本体，业务世界的根节点", "🏢", [
        {"key": "industry", "name": "所属行业", "type": "text"},
        {"key": "scale", "name": "规模", "type": "text"},
        {"key": "address", "name": "地址", "type": "text"},
        {"key": "intro", "name": "简介", "type": "textarea"},
    ]),
    ("department", "部门", "企业内设职能部门，隶属于组织", "🗂️", [
        {"key": "function", "name": "职能", "type": "text"},
        {"key": "head", "name": "负责人", "type": "text"},
        {"key": "intro", "name": "简介", "type": "textarea"},
    ]),
    ("position", "岗位", "岗位职级定义，员工在组织内的角色", "🎖️", [
        {"key": "level", "name": "职级", "type": "text"},
        {"key": "duty", "name": "职责", "type": "textarea"},
    ]),
    ("employee", "员工", "企业雇员，与部门/岗位/客户/项目关联", "👤", [
        {"key": "title", "name": "职位", "type": "text"},
        {"key": "phone", "name": "联系电话", "type": "text"},
        {"key": "email", "name": "邮箱", "type": "text"},
        {"key": "joined_at", "name": "入职日期", "type": "text"},
        {"key": "status", "name": "状态", "type": "text"},
    ]),
    ("customer", "客户", "企业对外服务的对象", "🤝", [
        {"key": "industry", "name": "所属行业", "type": "text"},
        {"key": "grade", "name": "客户等级", "type": "text"},
        {"key": "contact", "name": "联系人", "type": "text"},
        {"key": "intro", "name": "简介", "type": "textarea"},
    ]),
    ("product", "产品", "企业提供的产品/服务", "📦", [
        {"key": "category", "name": "品类", "type": "text"},
        {"key": "price", "name": "参考价", "type": "text"},
        {"key": "intro", "name": "简介", "type": "textarea"},
    ]),
    ("project", "项目", "履约中的项目/交付物", "📁", [
        {"key": "status", "name": "状态", "type": "text"},
        {"key": "budget", "name": "预算", "type": "text"},
        {"key": "start_at", "name": "开始日期", "type": "text"},
        {"key": "end_at", "name": "结束日期", "type": "text"},
        {"key": "intro", "name": "简介", "type": "textarea"},
    ]),
    ("contract", "合同", "与客户签署的商务合同", "📄", [
        {"key": "code", "name": "合同编号", "type": "text"},
        {"key": "amount", "name": "金额", "type": "text"},
        {"key": "status", "name": "状态", "type": "text"},
        {"key": "signed_at", "name": "签约日期", "type": "text"},
    ]),
    ("order", "订单", "销售订单/工单", "🧾", [
        {"key": "code", "name": "订单编号", "type": "text"},
        {"key": "amount", "name": "金额", "type": "text"},
        {"key": "status", "name": "状态", "type": "text"},
        {"key": "date", "name": "下单日期", "type": "text"},
        {"key": "detail", "name": "明细", "type": "textarea"},
    ]),
    ("station", "基站", "网络运营的基站/接入网点", "📡", [
        {"key": "code", "name": "基站编号", "type": "text"},
        {"key": "address", "name": "站址", "type": "text"},
        {"key": "status", "name": "运行状态", "type": "text"},
        {"key": "tech", "name": "制式", "type": "text"},
    ]),
    ("area", "片区", "基站覆盖的业务片区", "🗺️", [
        {"key": "households", "name": "覆盖户数", "type": "text"},
        {"key": "priority", "name": "保障等级", "type": "text"},
        {"key": "intro", "name": "简介", "type": "textarea"},
    ]),
    ("datacenter", "机房", "算网基础设施的物理机房/IDC", "🏭", [
        {"key": "code", "name": "机房编号", "type": "text"},
        {"key": "address", "name": "地址", "type": "text"},
        {"key": "tier", "name": "机房等级", "type": "text"},
        {"key": "status", "name": "运行状态", "type": "text"},
    ]),
    ("compute_node", "算力节点", "算力资源节点（GPU/CPU），部署于机房", "🖥️", [
        {"key": "role", "name": "用途", "type": "text"},
        {"key": "spec", "name": "规格", "type": "text"},
        {"key": "status", "name": "运行状态", "type": "text"},
    ]),
    ("link", "传输链路", "基站/机房间的传输光缆与链路", "🔗", [
        {"key": "bandwidth", "name": "带宽", "type": "text"},
        {"key": "status", "name": "运行状态", "type": "text"},
    ]),
]

# 模式层预置：9 个关系类型（system 租户，全局共享）
SCHEMA_RELATION_TYPES = [
    ("belong_to", "隶属于", "org", "department", "1:n", "部门属于组织"),
    ("belongs_to", "属于", "employee", "department", "n:1", "员工属于某部门"),
    ("hold_position", "担任", "employee", "position", "n:1", "员工担任某岗位"),
    ("manage", "负责", "employee", "project", "n:n", "员工负责某项目"),
    ("follow_up", "跟进", "employee", "customer", "n:n", "员工跟进某客户"),
    ("serve", "服务", "project", "customer", "n:1", "项目服务某客户"),
    ("correspond_to", "对应", "project", "contract", "1:1", "项目对应某合同"),
    ("place_order", "下单", "customer", "order", "1:n", "客户下达订单"),
    ("include", "包含", "order", "product", "1:n", "订单包含产品"),
    ("cover", "覆盖", "station", "area", "1:n", "基站覆盖某片区"),
    ("maintain", "维护", "employee", "station", "n:n", "装维人员维护某基站"),
    ("located_in", "居住于", "customer", "area", "n:1", "客户位于某片区"),
    ("deploy_in", "部署于", "compute_node", "datacenter", "n:1", "算力节点部署于某机房"),
    ("backhaul", "回传", "station", "link", "n:1", "基站经某传输链路回传"),
]

# 数据层演示种子：虚拟企业「星云科技」（default 租户）
_DEPARTMENTS = [
    ("研发中心", {"function": "产品研发", "head": "王建国", "intro": "负责产品与技术研发"}),
    ("营销中心", {"function": "市场与销售", "head": "李晓芳", "intro": "负责市场开拓与销售"}),
    ("客户成功部", {"function": "交付与售后", "head": "陈志强", "intro": "负责项目交付与客户服务"}),
    ("财务部", {"function": "财务管理", "head": "赵明远", "intro": "负责财务核算与资金管理"}),
    ("人力资源部", {"function": "人事管理", "head": "张敏", "intro": "负责招聘、绩效与培训"}),
]

_POSITIONS = [
    ("研发工程师", {"level": "P5", "duty": "负责产品功能研发与迭代"}),
    ("销售经理", {"level": "M3", "duty": "负责重点客户开拓与商机管理"}),
    ("客户成功专员", {"level": "P4", "duty": "负责项目交付与客户关系维护"}),
    ("数据分析师", {"level": "P5", "duty": "负责经营数据分析与报表"}),
    ("HRBP", {"level": "P6", "duty": "负责业务线人力资源伙伴工作"}),
    ("财务经理", {"level": "M3", "duty": "负责财务核算与经营分析"}),
]

_EMPLOYEES = [
    ("王建国", {"title": "研发负责人", "phone": "138-0000-0101", "email": "wangjg@nebula-tech.com", "joined_at": "2020-03-15", "status": "在职"}),
    ("李晓芳", {"title": "销售总监", "phone": "138-0000-0102", "email": "lixf@nebula-tech.com", "joined_at": "2019-07-01", "status": "在职"}),
    ("陈志强", {"title": "客户成功经理", "phone": "138-0000-0103", "email": "chenzq@nebula-tech.com", "joined_at": "2021-01-10", "status": "在职"}),
    ("刘思彤", {"title": "数据分析师", "phone": "138-0000-0104", "email": "liusitong@nebula-tech.com", "joined_at": "2022-05-20", "status": "在职"}),
    ("张敏", {"title": "HRBP", "phone": "138-0000-0105", "email": "zhangmin@nebula-tech.com", "joined_at": "2020-09-01", "status": "在职"}),
    ("赵明远", {"title": "财务经理", "phone": "138-0000-0106", "email": "zhaomy@nebula-tech.com", "joined_at": "2018-11-12", "status": "在职"}),
]

_CUSTOMERS = [
    ("华芯半导体", {"industry": "半导体", "grade": "A级", "contact": "林先生", "intro": "国内领先的芯片设计企业，数字工厂建设核心客户"}),
    ("云帆物流", {"industry": "物流", "grade": "B级", "contact": "周女士", "intro": "区域龙头物流企业，关注数字化提效"}),
    ("星辰制造", {"industry": "智能制造", "grade": "B级", "contact": "钱工", "intro": "汽车零部件制造企业，正在推进 MES 建设"}),
    ("绿洲能源", {"industry": "能源", "grade": "A级", "contact": "孙总", "intro": "新能源企业，对智能巡检需求强烈"}),
]

_PRODUCTS = [
    ("智能巡检平台", {"category": "企业版", "price": "¥298,000/套", "intro": "面向工厂设备的智能巡检与预警平台"}),
    ("数据中台", {"category": "基础版", "price": "¥458,000", "intro": "企业级数据汇聚、治理与应用平台"}),
    ("数字员工平台", {"category": "SaaS", "price": "¥99,000/年", "intro": "基于大模型的数字员工自动化运营平台"}),
]

_PROJECTS = [
    ("华芯智慧工厂", {"status": "进行中", "budget": "¥2,600,000", "start_at": "2026-03-01", "intro": "为华芯半导体建设智慧工厂数字化底座"}),
    ("云帆物流数字化", {"status": "已交付", "budget": "¥1,200,000", "start_at": "2025-09-01", "end_at": "2026-01-15", "intro": "云帆物流数字化运营平台交付"}),
    ("星辰 MES 系统", {"status": "进行中", "budget": "¥1,800,000", "start_at": "2026-05-01", "intro": "星辰制造 MES 制造执行系统建设"}),
]

_CONTRACTS = [
    ("HT-2026-001", {"amount": "¥2,600,000", "status": "履约中", "signed_at": "2026-02-28", "detail": "华芯智慧工厂实施合同"}),
    ("HT-2026-002", {"amount": "¥1,200,000", "status": "已完成", "signed_at": "2025-11-15", "detail": "云帆物流数字化平台合同"}),
    ("HT-2026-003", {"amount": "¥1,800,000", "status": "履约中", "signed_at": "2026-04-20", "detail": "星辰 MES 系统合同"}),
]

_ORDERS = [
    ("SO-1001", {"amount": "¥298,000", "status": "已交付", "date": "2026-03-15", "detail": "智能巡检平台 企业版 ×1"}),
    ("SO-1002", {"amount": "¥458,000", "status": "生产中", "date": "2026-04-02", "detail": "数据中台 基础版 ×1"}),
    ("SO-1003", {"amount": "¥298,000", "status": "已发货", "date": "2026-04-10", "detail": "智能巡检平台 企业版 ×1"}),
    ("SO-1004", {"amount": "¥99,000", "status": "已下单", "date": "2026-05-06", "detail": "数字员工平台 年度订阅 ×1"}),
]


def seed_schema_if_empty():
    """模式层种子：仅 system 租户完全为空时播种（幂等，不覆盖管理员自定义）。"""
    con = _conn()
    n_sys = con.execute(
        "SELECT COUNT(*) c FROM entity_types WHERE tenant_id='system' AND deleted_at IS NULL"
    ).fetchone()["c"]
    if n_sys > 0:
        con.close()
        return
    now = _now()
    for code, name, desc, icon, attrs in SCHEMA_ENTITY_TYPES:
        con.execute(
            "INSERT INTO entity_types(code,name,description,icon,attrs,tenant_id,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (code, name, desc, icon, json.dumps(attrs, ensure_ascii=False), "system", now, now))
    for code, name, frm, to, card, desc in SCHEMA_RELATION_TYPES:
        con.execute(
            "INSERT INTO relation_types(code,name,from_type,to_type,cardinality,description,tenant_id,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (code, name, frm, to, card, desc, "system", now, now))
    con.commit()
    con.close()
    print(f"[ontology] 已播种模式层：{len(SCHEMA_ENTITY_TYPES)} 实体类型 / {len(SCHEMA_RELATION_TYPES)} 关系类型")


def backfill_schema_types():
    """幂等补齐预置模式层类型（新库由 seed_schema_if_empty 写入；
    老库新增类型靠这里 INSERT OR IGNORE 补缺，不覆盖管理员自定义）。"""
    con = _conn()
    cur = con.cursor()
    now = _now()
    for code, name, desc, icon, attrs in SCHEMA_ENTITY_TYPES:
        cur.execute(
            "INSERT OR IGNORE INTO entity_types(code,name,description,icon,attrs,tenant_id,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (code, name, desc, icon, json.dumps(attrs, ensure_ascii=False), "system", now, now))
    for code, name, frm, to, card, desc in SCHEMA_RELATION_TYPES:
        cur.execute(
            "INSERT OR IGNORE INTO relation_types(code,name,from_type,to_type,cardinality,description,tenant_id,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (code, name, frm, to, card, desc, "system", now, now))
    con.commit()
    con.close()


def seed_demo_if_empty():
    """数据层演示种子：仅 default 租户无组织实体时播种（幂等）。"""
    con = _conn()
    has_org = con.execute(
        "SELECT 1 FROM entities WHERE entity_type='org' AND tenant_id='default' AND deleted_at IS NULL"
    ).fetchone()
    if has_org:
        con.close()
        return
    now = _now()
    ids: dict[tuple, int] = {}

    def add(type_, name, props):
        ids[(type_, name)] = dblayer.insert_returning_id(
            con,
            "INSERT INTO entities(entity_type,name,props,tenant_id,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?)",
            (type_, name, json.dumps(props, ensure_ascii=False), "default", now, now))

    def link(frm, to, rel):
        con.execute(
            "INSERT INTO relations(from_id,to_id,relation_type,props,tenant_id,created_at,updated_at)"
            " VALUES(?,?,?,'{}',?,?,?)",
            (frm, to, rel, "default", now, now))

    add("org", "星云科技", {
        "industry": "软件和信息技术服务业", "scale": "200-500 人",
        "address": "杭州市余杭区未来科技城",
        "intro": "面向制造与能源行业提供数字化解决方案的科技公司，主营智能巡检、数据中台与数字员工平台。"})

    for name, props in _DEPARTMENTS:
        add("department", name, props)
        link(ids[("org", "星云科技")], ids[("department", name)], "belong_to")
    for name, props in _POSITIONS:
        add("position", name, props)
    for name, props in _EMPLOYEES:
        add("employee", name, props)
    for name, props in _CUSTOMERS:
        add("customer", name, props)
    for name, props in _PRODUCTS:
        add("product", name, props)
    for name, props in _PROJECTS:
        add("project", name, props)
    for code, props in _CONTRACTS:
        add("contract", code, props)
    for code, props in _ORDERS:
        add("order", code, props)

    # 员工-部门 / 岗位
    for emp, dept, pos in [
        ("王建国", "研发中心", "研发工程师"),
        ("李晓芳", "营销中心", "销售经理"),
        ("陈志强", "客户成功部", "客户成功专员"),
        ("刘思彤", "研发中心", "数据分析师"),
        ("张敏", "人力资源部", "HRBP"),
        ("赵明远", "财务部", "财务经理"),
    ]:
        link(ids[("employee", emp)], ids[("department", dept)], "belongs_to")
        link(ids[("employee", emp)], ids[("position", pos)], "hold_position")

    # 员工-客户 / 项目
    for emp, customer in [("李晓芳", "华芯半导体"), ("李晓芳", "云帆物流"), ("陈志强", "星辰制造")]:
        link(ids[("employee", emp)], ids[("customer", customer)], "follow_up")
    for emp, proj in [("李晓芳", "华芯智慧工厂"), ("陈志强", "云帆物流数字化")]:
        link(ids[("employee", emp)], ids[("project", proj)], "manage")

    # 项目-客户 / 合同
    for proj, customer in [("华芯智慧工厂", "华芯半导体"), ("云帆物流数字化", "云帆物流"), ("星辰 MES 系统", "星辰制造")]:
        link(ids[("project", proj)], ids[("customer", customer)], "serve")
    for proj, contract in [("华芯智慧工厂", "HT-2026-001"), ("云帆物流数字化", "HT-2026-002"), ("星辰 MES 系统", "HT-2026-003")]:
        link(ids[("project", proj)], ids[("contract", contract)], "correspond_to")

    # 客户-订单 / 订单-产品
    for customer, order in [
        ("华芯半导体", "SO-1001"), ("华芯半导体", "SO-1002"),
        ("绿洲能源", "SO-1003"), ("云帆物流", "SO-1004"),
    ]:
        link(ids[("customer", customer)], ids[("order", order)], "place_order")
    for order, product in [
        ("SO-1001", "智能巡检平台"), ("SO-1002", "数据中台"),
        ("SO-1003", "智能巡检平台"), ("SO-1004", "数字员工平台"),
    ]:
        link(ids[("order", order)], ids[("product", product)], "include")

    con.commit()
    con.close()
    print("[ontology] 已播种演示数据：星云科技（5 部门 / 6 员工 / 4 客户 / 3 项目 / 3 合同 / 4 订单）")


# 数据层演示种子：网络运营场景「星联通信」（default 租户，与星云科技并存）
_NETOPS_EMPLOYEES = [
    ("李建国", {"title": "网络监控值班长", "phone": "13800001001", "status": "在职"}),
    ("王强", {"title": "装维工程师", "phone": "13800001002", "status": "在职"}),
    ("赵敏", {"title": "装维工程师", "phone": "13800001003", "status": "在职"}),
    ("陈涛", {"title": "装维工程师", "phone": "13800001004", "status": "在职"}),
]
_NETOPS_AREAS = [
    ("城东片区", {"households": "1.2 万", "priority": "普通", "intro": "老城区以东，住宅为主"}),
    ("高新区片区", {"households": "0.8 万", "priority": "重点保障", "intro": "高新技术企业园区，含政企客户"}),
    ("老城片区", {"households": "0.6 万", "priority": "普通", "intro": "老城核心商圈"}),
]
_NETOPS_STATIONS = [
    ("城东1号基站", {"code": "BS-001", "address": "城东街道88号", "status": "正常", "tech": "5G"}),
    ("城东2号基站", {"code": "BS-002", "address": "城东路与纬三路交叉口", "status": "正常", "tech": "5G"}),
    ("高新区1号基站", {"code": "BS-003", "address": "高新大道1号园区北门", "status": "退服", "tech": "5G"}),
    ("老城1号基站", {"code": "BS-004", "address": "老城中路12号", "status": "升级中", "tech": "4G→5G"}),
]
_NETOPS_CUSTOMERS = [
    ("张桂芳", {"grade": "VIP", "contact": "13911112222", "industry": "个人",
                "intro": "城东片区个人VIP客户"}),
    ("刘志远", {"grade": "普通", "contact": "13933334444", "industry": "个人",
                "intro": "城东片区个人客户"}),
    ("杭州智造科技", {"grade": "VIP", "contact": "0571-88990000", "industry": "智能制造",
                       "intro": "高新区政企VIP客户，专线+组网业务"}),
    ("王秀英", {"grade": "普通", "contact": "13955556666", "industry": "个人",
                "intro": "高新区个人客户"}),
    ("周明轩", {"grade": "VIP", "contact": "13977778888", "industry": "个人",
                "intro": "老城片区个人VIP客户"}),
]


def seed_netops_demo_if_empty():
    """网络运营演示种子：default 租户无基站实体时播种（幂等）。

    场景主线：基站退服 → 覆盖片区 → 受影响客户（筛VIP）→ 装维负责人，
    用于展示本体的多跳关系查询能力。
    """
    con = _conn()
    has_station = con.execute(
        "SELECT 1 FROM entities WHERE entity_type='station' AND tenant_id='default' AND deleted_at IS NULL"
    ).fetchone()
    if has_station:
        con.close()
        return
    now = _now()
    ids: dict[tuple, int] = {}

    def add(type_, name, props):
        ids[(type_, name)] = dblayer.insert_returning_id(
            con,
            "INSERT INTO entities(entity_type,name,props,tenant_id,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?)",
            (type_, name, json.dumps(props, ensure_ascii=False), "default", now, now))

    def link(frm, to, rel):
        con.execute(
            "INSERT INTO relations(from_id,to_id,relation_type,props,tenant_id,created_at,updated_at)"
            " VALUES(?,?,?,'{}',?,?,?)",
            (frm, to, rel, "default", now, now))

    add("org", "星联通信", {
        "industry": "通信运营", "scale": "1000+ 人",
        "address": "杭州市滨江区",
        "intro": "演示用虚拟运营商，用于网络运营场景（基站/片区/装维/客户保障）展示。"})
    add("department", "网络运营部", {"function": "网络运营与维护", "head": "李建国",
                                    "intro": "负责基站运维、装维调度与客户网络保障"})
    link(ids[("org", "星联通信")], ids[("department", "网络运营部")], "belong_to")

    for name, props in _NETOPS_EMPLOYEES:
        add("employee", name, props)
        link(ids[("employee", name)], ids[("department", "网络运营部")], "belongs_to")
    link(ids[("employee", "李建国")], ids[("department", "网络运营部")], "manage")

    for name, props in _NETOPS_AREAS:
        add("area", name, props)
    for name, props in _NETOPS_STATIONS:
        add("station", name, props)
    for name, props in _NETOPS_CUSTOMERS:
        add("customer", name, props)

    # 基站-片区（覆盖）
    for station, area in [
        ("城东1号基站", "城东片区"), ("城东2号基站", "城东片区"),
        ("高新区1号基站", "高新区片区"), ("老城1号基站", "老城片区"),
    ]:
        link(ids[("station", station)], ids[("area", area)], "cover")

    # 装维人员-基站（维护）
    for emp, station in [
        ("王强", "城东1号基站"), ("王强", "城东2号基站"),
        ("赵敏", "高新区1号基站"), ("陈涛", "老城1号基站"),
    ]:
        link(ids[("employee", emp)], ids[("station", station)], "maintain")

    # 客户-片区（居住于）
    for customer, area in [
        ("张桂芳", "城东片区"), ("刘志远", "城东片区"),
        ("杭州智造科技", "高新区片区"), ("王秀英", "高新区片区"),
        ("周明轩", "老城片区"),
    ]:
        link(ids[("customer", customer)], ids[("area", area)], "located_in")

    con.commit()
    con.close()
    print("[ontology] 已播种网络运营演示数据：星联通信（4 员工 / 4 基站 / 3 片区 / 5 客户）")


def seed_netops_resources_if_empty():
    """算网资源演示种子：default 租户无机房实体时播种（幂等）。

    实体名称与 workspace/data/netops_resources.csv 台账严格对齐，
    支撑「台账跑数 + 本体查归属」的交叉分析：
      compute_node → deploy_in → datacenter（节点在哪个机房）
      station → backhaul → link（基站走哪条回传链路）
    """
    con = _conn()
    has_dc = con.execute(
        "SELECT 1 FROM entities WHERE entity_type='datacenter' AND tenant_id='default' "
        "AND deleted_at IS NULL"
    ).fetchone()
    if has_dc:
        con.close()
        return
    now = _now()
    ids: dict[tuple, int] = {}

    def add(type_, name, props):
        ids[(type_, name)] = dblayer.insert_returning_id(
            con,
            "INSERT INTO entities(entity_type,name,props,tenant_id,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?)",
            (type_, name, json.dumps(props, ensure_ascii=False), "default", now, now))

    def find_id(type_, name):
        """查已有实体 id（基站等由 seed_netops_demo_if_empty 先行播种）。"""
        row = con.execute(
            "SELECT id FROM entities WHERE entity_type=? AND name=? AND tenant_id='default' "
            "AND deleted_at IS NULL", (type_, name)).fetchone()
        return row["id"] if row else None

    def link(frm, to, rel):
        con.execute(
            "INSERT INTO relations(from_id,to_id,relation_type,props,tenant_id,created_at,updated_at)"
            " VALUES(?,?,?,'{}',?,?,?)",
            (frm, to, rel, "default", now, now))

    for name, props in [
        ("滨江核心机房", {"code": "DC-01", "address": "杭州市滨江区", "tier": "T3+", "status": "运行中"}),
        ("下沙汇聚机房", {"code": "DC-02", "address": "杭州市钱塘区", "tier": "T3", "status": "运行中"}),
    ]:
        add("datacenter", name, props)

    for name, props in [
        ("GPU训练节点01", {"role": "AI 模型训练", "spec": "64 卡", "status": "运行中"}),
        ("GPU推理节点01", {"role": "在线推理服务", "spec": "48 卡", "status": "运行中"}),
        ("CPU核心节点01", {"role": "核心业务系统", "spec": "1024 vCPU", "status": "运行中"}),
        ("CPU边缘节点01", {"role": "边缘计算", "spec": "256 vCPU", "status": "运行中"}),
    ]:
        add("compute_node", name, props)

    for name, props in [
        ("城东-滨江光缆", {"bandwidth": "400 Gbps", "status": "运行中"}),
        ("高新-下沙光缆", {"bandwidth": "400 Gbps", "status": "运行中"}),
        ("老城-滨江光缆", {"bandwidth": "200 Gbps", "status": "运行中"}),
    ]:
        add("link", name, props)

    # 算力节点 → 部署于 → 机房
    for node, dc in [("GPU训练节点01", "滨江核心机房"), ("GPU推理节点01", "滨江核心机房"),
                     ("CPU核心节点01", "下沙汇聚机房"), ("CPU边缘节点01", "下沙汇聚机房")]:
        link(ids[("compute_node", node)], ids[("datacenter", dc)], "deploy_in")

    # 基站 → 回传 → 链路（基站实体由 seed_netops_demo_if_empty 先行播种）
    for station, lk in [("城东1号基站", "城东-滨江光缆"), ("城东2号基站", "城东-滨江光缆"),
                        ("高新区1号基站", "高新-下沙光缆"), ("老城1号基站", "老城-滨江光缆")]:
        sid = find_id("station", station)
        if sid:
            link(sid, ids[("link", lk)], "backhaul")

    con.commit()
    con.close()
    print("[ontology] 已播种算网资源演示数据：2 机房 / 4 算力节点 / 3 传输链路")


# ---------------- Schema CRUD ----------------

def _row_to_dict(r):
    d = dict(r)
    for k in ("attrs", "props"):
        if k in d and d[k]:
            try:
                d[k] = json.loads(d[k])
            except (TypeError, json.JSONDecodeError):
                pass
    return d


def list_schema(tenant_id: str) -> dict:
    """返回某租户可见的完整 schema（system 预置 + 该租户自定义）。"""
    con = _conn()
    ets = [_row_to_dict(r) for r in con.execute(
        "SELECT * FROM entity_types WHERE deleted_at IS NULL AND tenant_id IN ('system', ?) "
        "ORDER BY CASE tenant_id WHEN 'system' THEN 0 ELSE 1 END, id", (tenant_id,))]
    rts = [_row_to_dict(r) for r in con.execute(
        "SELECT * FROM relation_types WHERE deleted_at IS NULL AND tenant_id IN ('system', ?) "
        "ORDER BY CASE tenant_id WHEN 'system' THEN 0 ELSE 1 END, id", (tenant_id,))]
    con.close()
    return {"entity_types": ets, "relation_types": rts}


def create_entity_type(tenant_id: str, data: dict) -> int:
    code, name = (data.get("code") or "").strip(), (data.get("name") or "").strip()
    if not code or not name:
        raise ValueError("code 与 name 必填")
    con = _conn()
    if con.execute(
        "SELECT 1 FROM entity_types WHERE code=? AND tenant_id=? AND deleted_at IS NULL",
        (code, tenant_id)).fetchone():
        con.close()
        raise ValueError(f"实体类型 {code} 已存在")
    attrs = json.dumps(data.get("attrs") or [], ensure_ascii=False)
    now = _now()
    con = _conn()
    try:
        rid = dblayer.insert_returning_id(
            con,
            "INSERT INTO entity_types(code,name,description,icon,attrs,tenant_id,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (code, name, data.get("description"), data.get("icon"), attrs, tenant_id, now, now))
        con.commit()
        return rid
    finally:
        con.close()


def update_entity_type(tenant_id: str, id_: int, data: dict) -> None:
    con = _conn()
    attrs = json.dumps(data.get("attrs") or [], ensure_ascii=False)
    con.execute(
        "UPDATE entity_types SET name=?, description=?, icon=?, attrs=?, updated_at=? WHERE id=?",
        (data.get("name"), data.get("description"), data.get("icon"), attrs, _now(), id_))
    con.commit()
    con.close()


def delete_entity_type(tenant_id: str, id_: int) -> None:
    con = _conn()
    con.execute("UPDATE entity_types SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
                (_now(), id_))
    con.commit()
    con.close()


def create_relation_type(tenant_id: str, data: dict) -> int:
    code, name = (data.get("code") or "").strip(), (data.get("name") or "").strip()
    if not code or not name:
        raise ValueError("code 与 name 必填")
    con = _conn()
    if con.execute(
        "SELECT 1 FROM relation_types WHERE code=? AND tenant_id=? AND deleted_at IS NULL",
        (code, tenant_id)).fetchone():
        con.close()
        raise ValueError(f"关系类型 {code} 已存在")
    now = _now()
    con = _conn()
    try:
        rid = dblayer.insert_returning_id(
            con,
            "INSERT INTO relation_types(code,name,from_type,to_type,cardinality,description,tenant_id,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (code, name, data.get("from_type"), data.get("to_type"), data.get("cardinality") or "m:n",
             data.get("description"), tenant_id, now, now))
        con.commit()
        return rid
    finally:
        con.close()


def update_relation_type(tenant_id: str, id_: int, data: dict) -> None:
    con = _conn()
    # from_type/to_type NOT NULL：未传时保留原值（COALESCE）
    con.execute(
        "UPDATE relation_types SET name=?, from_type=COALESCE(?, from_type), to_type=COALESCE(?, to_type),"
        " cardinality=COALESCE(?, cardinality), description=?, updated_at=? WHERE id=?",
        (data.get("name"), data.get("from_type"), data.get("to_type"),
         data.get("cardinality"), data.get("description"), _now(), id_))
    con.commit()
    con.close()


def delete_relation_type(tenant_id: str, id_: int) -> None:
    con = _conn()
    con.execute("UPDATE relation_types SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
                (_now(), id_))
    con.commit()
    con.close()


# ---------------- 数据层 CRUD / 查询 ----------------

def _entity_where(entity_type=None, keyword=None):
    where, args = ["deleted_at IS NULL"], []
    if entity_type:
        where.append("entity_type=?")
        args.append(entity_type)
    if keyword:
        where.append("(name LIKE ? OR props LIKE ?)")
        like = f"%{keyword}%"
        args += [like, like]
    return " AND ".join(where), args


def _type_visible(con, table: str, code: str, tenant_id: str) -> bool:
    """校验类型在当前租户可见（system 预置 + 本租户自定义）。"""
    return con.execute(
        f"SELECT 1 FROM {table} WHERE code=? AND deleted_at IS NULL AND tenant_id IN ('system', ?)",
        (code, tenant_id)).fetchone() is not None


def list_entities(tenant_id: str, entity_type: str | None = None,
                  keyword: str | None = None, limit: int = 200) -> list[dict]:
    where, args = _entity_where(entity_type, keyword)
    args = [tenant_id] + args
    con = _conn()
    rows = [_row_to_dict(r) for r in con.execute(
        f"SELECT * FROM entities WHERE tenant_id=? AND {where} "
        "ORDER BY entity_type, id LIMIT ?", args + [limit])]
    con.close()
    return rows


def get_entity(tenant_id: str, id_: int) -> dict | None:
    con = _conn()
    row = con.execute(
        "SELECT * FROM entities WHERE id=? AND tenant_id=? AND deleted_at IS NULL",
        (id_, tenant_id)).fetchone()
    con.close()
    return _row_to_dict(row) if row else None


def create_entity(tenant_id: str, data: dict) -> int:
    type_, name = (data.get("entity_type") or "").strip(), (data.get("name") or "").strip()
    if not type_ or not name:
        raise ValueError("entity_type 与 name 必填")
    props = json.dumps(data.get("props") or {}, ensure_ascii=False)
    now = _now()
    con = _conn()
    if not _type_visible(con, "entity_types", type_, tenant_id):
        con.close()
        raise ValueError(f"实体类型 {type_} 不存在")
    try:
        rid = dblayer.insert_returning_id(
            con,
            "INSERT INTO entities(entity_type,name,props,tenant_id,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?)",
            (type_, name, props, tenant_id, now, now))
        con.commit()
        return rid
    finally:
        con.close()


def update_entity(tenant_id: str, id_: int, data: dict) -> None:
    props = json.dumps(data.get("props") or {}, ensure_ascii=False)
    con = _conn()
    if not _type_visible(con, "entity_types", data.get("entity_type") or "", tenant_id):
        con.close()
        raise ValueError(f"实体类型 {data.get('entity_type')} 不存在")
    con.execute(
        "UPDATE entities SET entity_type=?, name=?, props=?, updated_at=? WHERE id=? AND tenant_id=?",
        (data.get("entity_type"), data.get("name"), props, _now(), id_, tenant_id))
    con.commit()
    con.close()


def delete_entity(tenant_id: str, id_: int) -> None:
    now = _now()
    con = _conn()
    con.execute("UPDATE entities SET deleted_at=? WHERE id=? AND tenant_id=? AND deleted_at IS NULL",
                (now, id_, tenant_id))
    con.execute("UPDATE relations SET deleted_at=? WHERE (from_id=? OR to_id=?) AND tenant_id=? AND deleted_at IS NULL",
                (now, id_, id_, tenant_id))
    con.commit()
    con.close()


def list_relations(tenant_id: str, entity_id: int | None = None) -> list[dict]:
    con = _conn()
    if entity_id:
        rows = con.execute(
            "SELECT * FROM relations WHERE tenant_id=? AND deleted_at IS NULL AND (from_id=? OR to_id=?)",
            (tenant_id, entity_id, entity_id)).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM relations WHERE tenant_id=? AND deleted_at IS NULL ORDER BY id", (tenant_id,)).fetchall()
    out = [_row_to_dict(r) for r in rows]
    con.close()
    return out


def create_relation(tenant_id: str, data: dict) -> int:
    from_id, to_id = data.get("from_id"), data.get("to_id")
    rel = (data.get("relation_type") or "").strip()
    if not from_id or not to_id or not rel:
        raise ValueError("from_id / to_id / relation_type 必填")
    con = _conn()
    rt = con.execute(
        "SELECT * FROM relation_types WHERE code=? AND deleted_at IS NULL AND tenant_id IN ('system', ?)",
        (rel, tenant_id)).fetchone()
    if not rt:
        con.close()
        raise ValueError(f"关系类型 {rel} 不存在")
    from_e = con.execute(
        "SELECT entity_type FROM entities WHERE id=? AND tenant_id=? AND deleted_at IS NULL",
        (from_id, tenant_id)).fetchone()
    to_e = con.execute(
        "SELECT entity_type FROM entities WHERE id=? AND tenant_id=? AND deleted_at IS NULL",
        (to_id, tenant_id)).fetchone()
    if not from_e or not to_e:
        con.close()
        raise ValueError("关系端点实体不存在或不属于当前租户")
    if from_e["entity_type"] != rt["from_type"] or to_e["entity_type"] != rt["to_type"]:
        con.close()
        raise ValueError(
            f"关系 {rel} 要求 {rt['from_type']} → {rt['to_type']}，"
            f"实际 {from_e['entity_type']} → {to_e['entity_type']}")
    now = _now()
    con = _conn()
    try:
        rid = dblayer.insert_returning_id(
            con,
            "INSERT INTO relations(from_id,to_id,relation_type,props,tenant_id,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (from_id, to_id, rel, json.dumps(data.get("props") or {}, ensure_ascii=False),
             tenant_id, now, now))
        con.commit()
        return rid
    finally:
        con.close()


def delete_relation(tenant_id: str, id_: int) -> None:
    con = _conn()
    con.execute("UPDATE relations SET deleted_at=? WHERE id=? AND tenant_id=? AND deleted_at IS NULL",
                (_now(), id_, tenant_id))
    con.commit()
    con.close()


# ---------------- 运行时查询（供 ontology_* 闭包工具调用） ----------------

def find_entities(tenant_id: str, entity_type: str | None = None,
                  keyword: str | None = None, limit: int = 20) -> list[dict]:
    """业务事实查询：按类型/关键词查实体，返回含 id/类型/名称/属性。"""
    rows = list_entities(tenant_id, entity_type=entity_type, keyword=keyword, limit=limit)
    out = []
    for r in rows:
        out.append({
            "id": r["id"], "entity_type": r["entity_type"],
            **(r.get("props") or {}), "name": r["name"],
        })
    return out


def query_relations(tenant_id: str, entity_id: int, relation_type: str | None = None,
                    direction: str = "any") -> list[dict]:
    """关系查询：沿边走一跳，返回对端实体与关系信息。direction: any/out/in。"""
    con = _conn()
    rel_filter = ""
    args: list = []
    if relation_type:
        rel_filter = " AND r.relation_type=?"
        args.append(relation_type)
    out = []
    for sql, label in [
        (f"SELECT r.id rid, r.relation_type, r.props rprops, e.id eid, e.entity_type, e.name, e.props"
         f" FROM relations r JOIN entities e ON e.id=r.to_id"
         f" WHERE r.from_id=? AND r.deleted_at IS NULL AND e.deleted_at IS NULL{rel_filter}", "out"),
        (f"SELECT r.id rid, r.relation_type, r.props rprops, e.id eid, e.entity_type, e.name, e.props"
         f" FROM relations r JOIN entities e ON e.id=r.from_id"
         f" WHERE r.to_id=? AND r.deleted_at IS NULL AND e.deleted_at IS NULL{rel_filter}", "in"),
    ]:
        if direction in ("any", label):
            for r in con.execute(sql, [entity_id] + args):
                eprops = json.loads(r["props"]) if r["props"] else {}
                out.append({
                    "relation_id": r["rid"], "relation_type": r["relation_type"],
                    "direction": label,
                    "target": {"id": r["eid"], "entity_type": r["entity_type"],
                               **(eprops or {}), "name": r["name"]},
                })
    con.close()
    return out


def stats(tenant_id: str) -> dict:
    con = _conn()
    total = con.execute(
        "SELECT COUNT(*) c FROM entities WHERE tenant_id=? AND deleted_at IS NULL",
        (tenant_id,)).fetchone()["c"]
    rel = con.execute(
        "SELECT COUNT(*) c FROM relations WHERE tenant_id=? AND deleted_at IS NULL",
        (tenant_id,)).fetchone()["c"]
    by_type = [dict(r) for r in con.execute(
        "SELECT entity_type, COUNT(*) c FROM entities WHERE tenant_id=? AND deleted_at IS NULL "
        "GROUP BY entity_type ORDER BY c DESC", (tenant_id,))]
    con.close()
    return {"total_entities": total, "total_relations": rel, "by_type": by_type}
