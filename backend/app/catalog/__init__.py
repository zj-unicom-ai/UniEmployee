"""
catalog 子包 — 数字员工目录库（catalog.db）的全部操作。

拆分说明（原 catalog.py 1051 行 → 6 文件）：
  db.py         数据库连接、建表、迁移、通用工具
  users.py      用户 CRUD + 用户-员工分配
  employees.py  员工配置读取/写入
  resources.py  技能/工具/知识库/SOP/连接器 CRUD
  seeds.py      种子数据

外部代码 `from app import catalog` 或 `from app.catalog import *` 保持兼容。
"""

# db
from .db import GLOBAL_TOOL_NAMES, ROOT, init, _conn, _unlink, _unlink_view

# users
from .users import (
    create_user, get_user, get_user_by_username,
    list_users, list_users_paged, update_user, set_password,
    set_must_change_password, delete_user,
    assign_employee, unassign_employee, get_assignment,
    list_assignments, set_assignment_overrides,
    assigned_employee_ids, list_user_ids_with_emp,
)

# employees
from .employees import (
    list_employees_meta, get_employee_config, get_effective_config,
    get_full_employee, get_skill_dirs_for_employee, catalog,
    create_employee, update_employee, delete_employee,
)

# resources
from .resources import (
    upsert_skill, get_skill, get_skill_content, update_skill_content,
    employees_using_skill, delete_skill,
    update_tool, employees_using_tool,
    create_kb, update_kb, get_kb, delete_kb, employees_using_kb,
    create_sop, update_sop, get_sop, delete_sop, employees_using_sop,
    create_connector, update_connector, get_connector, delete_connector,
)

# seeds
from .seeds import (
    seed_if_empty, backfill_connectors, backfill_subagents_if_empty,
    backfill_ragflow_knowledge_bases,
    backfill_employee_kb_assignments, backfill_ontology_tools,
    seed_assignments_if_empty, seed_admin_if_empty, flag_default_admin_password,
)

__all__ = [
    # db
    "GLOBAL_TOOL_NAMES", "ROOT", "init", "_unlink", "_unlink_view",
    # users
    "create_user", "get_user", "get_user_by_username",
    "list_users", "list_users_paged", "update_user", "set_password",
    "set_must_change_password", "delete_user",
    "assign_employee", "unassign_employee", "get_assignment",
    "list_assignments", "set_assignment_overrides",
    "assigned_employee_ids", "list_user_ids_with_emp",
    # employees
    "list_employees_meta", "get_employee_config", "get_effective_config",
    "get_full_employee", "get_skill_dirs_for_employee", "catalog", "create_employee", "update_employee",
    "delete_employee",
    # resources
    "upsert_skill", "get_skill", "get_skill_content", "update_skill_content",
    "employees_using_skill", "delete_skill",
    "update_tool", "employees_using_tool",
    "create_kb", "update_kb", "get_kb", "delete_kb", "employees_using_kb",
    "create_sop", "update_sop", "get_sop", "delete_sop", "employees_using_sop",
    "create_connector", "update_connector", "get_connector", "delete_connector",
    # seeds
    "seed_if_empty", "backfill_connectors", "backfill_subagents_if_empty",
    "backfill_ragflow_knowledge_bases",
    "backfill_employee_kb_assignments", "backfill_ontology_tools",
    "seed_assignments_if_empty", "seed_admin_if_empty", "flag_default_admin_password",
]
