"""给现有小网补齐安全技能和工具，不覆盖管理员修改的人设。"""

from .policy import SKILL_NAME, TOOL_NAMES

SECURITY_TOOL_ROWS = [
    (TOOL_NAMES[0], "安全实操 Python", "隔离执行分析代码并保留完整脚本和结果", "local", None),
    (TOOL_NAMES[1], "保存实操答案", "按题号保存答案及证据的独立版本", "local", None),
]


def upgrade():
    from app import catalog
    con = catalog._conn()
    try:
        for row in SECURITY_TOOL_ROWS:
            con.execute("INSERT OR IGNORE INTO tools(id,name,description,source,needs_approval) "
                        "VALUES(?,?,?,?,?)", row)
        con.execute("INSERT OR IGNORE INTO skills(id,name,description,dir) VALUES(?,?,?,?)",
                    (SKILL_NAME, "安全实操", "网络安全、数据安全、AI 安全题与 CTF 附件分析",
                     f"skills/{SKILL_NAME}"))
        row = con.execute("SELECT deleted_at FROM employees WHERE id='net-ops'").fetchone()
        if row and not row["deleted_at"]:
            con.execute("INSERT OR IGNORE INTO employee_skills VALUES(?,?)", ("net-ops", SKILL_NAME))
            for name in TOOL_NAMES:
                con.execute("INSERT OR IGNORE INTO employee_tools VALUES(?,?)", ("net-ops", name))
        con.commit()
    finally:
        con.close()
