"""Connector 层：CRM 连接器（FastMCP stdio server，mock 数据）。"""
from fastmcp import FastMCP

mcp = FastMCP("crm")

ORDERS = {
    "O12345": {"order_id": "O12345", "product": "X1 智能音箱", "amount": 399.0,
               "status": "已签收", "sign_date": "2026-07-22", "customer": "张总", "company": "华强电子", "phone": "138****5678"},
    "O12346": {"order_id": "O12346", "product": "S2 智能台灯", "amount": 199.0,
               "status": "已签收", "sign_date": "2026-07-15", "customer": "李经理", "company": "鼎新科技", "phone": "139****9012"},
    "O12347": {"order_id": "O12347", "product": "X1 智能音箱", "amount": 399.0,
               "status": "运输中", "sign_date": None, "customer": "张总", "company": "华强电子", "phone": "138****5678"},
    "O12348": {"order_id": "O12348", "product": "W5 智能手表（硅胶版）", "amount": 599.0,
               "status": "已签收", "sign_date": "2026-07-24", "customer": "王老师", "company": "阳光中学", "phone": "136****2345"},
    "O12349": {"order_id": "O12349", "product": "H7 降噪耳机", "amount": 499.0,
               "status": "已签收", "sign_date": "2026-07-20", "customer": "陈工", "company": "先锋设计院", "phone": "158****6789"},
    "O12350": {"order_id": "O12350", "product": "P3 智能投影仪", "amount": 2599.0,
               "status": "运输中", "sign_date": None, "customer": "李经理", "company": "鼎新科技", "phone": "139****9012"},
    "O12351": {"order_id": "O12351", "product": "S2 Pro 双灯头台灯", "amount": 299.0,
               "status": "已签收", "sign_date": "2026-07-05", "customer": "赵女士", "company": "瑞和地产", "phone": "137****3456"},
    "O12352": {"order_id": "O12352", "product": "X1 智能音箱（白色）", "amount": 399.0,
               "status": "已签收", "sign_date": "2026-05-26", "customer": "周同学", "company": "星辰科技", "phone": "150****7890"},
    "O12353": {"order_id": "O12353", "product": "H7 Pro 降噪耳机", "amount": 699.0,
               "status": "已签收", "sign_date": "2026-07-23", "customer": "王老师", "company": "阳光中学", "phone": "136****2345"},
    "O12354": {"order_id": "O12354", "product": "W5 Pro eSIM 手表", "amount": 899.0,
               "status": "已签收", "sign_date": "2026-07-11", "customer": "陈工", "company": "先锋设计院", "phone": "158****6789"},
    # ---- 新增企业客户订单 ----
    "O12355": {"order_id": "O12355", "product": "P3 智能投影仪×5 + X1 智能音箱×10", "amount": 16985.0,
               "status": "已签收", "sign_date": "2026-06-20", "customer": "刘总", "company": "天域集团", "phone": "133****6789"},
    "O12356": {"order_id": "O12356", "product": "S2 智能台灯×50（批量采购）", "amount": 8950.0,
               "status": "已签收", "sign_date": "2026-06-15", "customer": "黄主任", "company": "市图书馆", "phone": "135****4321"},
    "O12357": {"order_id": "O12357", "product": "H7 Pro 降噪耳机×20", "amount": 13980.0,
               "status": "运输中", "sign_date": None, "customer": "林总", "company": "云帆互联网", "phone": "136****8888"},
    "O12358": {"order_id": "O12358", "product": "X1 智能音箱×30（企业集采）", "amount": 10770.0,
               "status": "已签收", "sign_date": "2026-06-28", "customer": "杨总", "company": "万通地产", "phone": "137****2222"},
}

CUSTOMERS = {
    "张总": {"name": "张总", "company": "华强电子", "title": "采购总监", "level": "VIP",
            "industry": "电子制造", "employees": 500, "orders": ["O12345", "O12347"],
            "total_spent": 798.0, "since": "2025-03", "last_visit": "2026-07-10",
            "notes": "对智能办公方案感兴趣，有会议室升级需求"},
    "李经理": {"name": "李经理", "company": "鼎新科技", "title": "行政经理", "level": "VIP",
             "industry": "互联网科技", "employees": 200, "orders": ["O12346", "O12350"],
             "total_spent": 2798.0, "since": "2025-06", "last_visit": "2026-07-18",
             "notes": "公司搬迁新办公室，有整层智能化采购需求"},
    "王老师": {"name": "王老师", "company": "阳光中学", "title": "教务主任", "level": "金卡",
             "industry": "教育", "employees": 150, "orders": ["O12348", "O12353"],
             "total_spent": 1298.0, "since": "2025-09", "last_visit": "2026-07-22",
             "notes": "学校计划建设智慧教室，需要投影和扩声方案"},
    "陈工": {"name": "陈工", "company": "先锋设计院", "title": "设备主管", "level": "普通",
            "industry": "建筑设计", "employees": 80, "orders": ["O12349", "O12354"],
            "total_spent": 1398.0, "since": "2026-01", "last_visit": "2026-07-12",
            "notes": "设计院电脑多，需要降噪耳机改善办公环境"},
    "赵女士": {"name": "赵女士", "company": "瑞和地产", "title": "人力总监", "level": "普通",
              "industry": "房地产", "employees": 300, "orders": ["O12351"],
              "total_spent": 299.0, "since": "2026-07", "last_visit": "2026-07-05",
              "notes": "首次采购试用，潜在企业集采客户"},
    "周同学": {"name": "周同学", "company": "星辰科技", "title": "CEO", "level": "金卡",
              "industry": "人工智能", "employees": 30, "orders": ["O12352"],
              "total_spent": 399.0, "since": "2025-11", "last_visit": "2026-07-20",
              "notes": "创业公司，后续可能有批量采购需求"},
    # ---- 新增企业客户 ----
    "刘总": {"name": "刘总", "company": "天域集团", "title": "副总裁", "level": "VIP",
            "industry": "综合集团", "employees": 2000, "orders": ["O12355"],
            "total_spent": 16985.0, "since": "2025-01", "last_visit": "2026-06-20",
            "notes": "集团采购量大，已采购会议室投影+音箱方案，后续有全国分公司扩展需求"},
    "黄主任": {"name": "黄主任", "company": "市图书馆", "title": "设备科主任", "level": "金卡",
              "industry": "公共事业", "employees": 50, "orders": ["O12356"],
              "total_spent": 8950.0, "since": "2025-08", "last_visit": "2026-06-15",
              "notes": "图书馆照明升级项目已完成，后续可能有阅读区智能音箱需求"},
    "林总": {"name": "林总", "company": "云帆互联网", "title": "技术总监", "level": "金卡",
            "industry": "互联网", "employees": 150, "orders": ["O12357"],
            "total_spent": 13980.0, "since": "2026-04", "last_visit": "2026-07-25",
            "notes": "正在采购员工降噪耳机，对批量折扣敏感"},
    "杨总": {"name": "杨总", "company": "万通地产", "title": "行政总监", "level": "VIP",
            "industry": "房地产", "employees": 800, "orders": ["O12358"],
            "total_spent": 10770.0, "since": "2025-05", "last_visit": "2026-06-28",
            "notes": "已采购智能音箱30台用于售楼处，后续有样板间智能家居方案需求"},
}


@mcp.tool
def order_query(order_id: str) -> dict:
    """按订单号查询订单详情（商品、金额、状态、签收日期）。"""
    return ORDERS.get(order_id, {"error": f"订单 {order_id} 不存在"})


@mcp.tool
def customer_profile(customer_name: str) -> dict:
    """按客户姓名查询客户档案（等级、历史订单）。"""
    return CUSTOMERS.get(customer_name, {"error": f"客户 {customer_name} 不存在"})


if __name__ == "__main__":
    mcp.run()  # stdio transport
