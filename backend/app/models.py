"""共享 Pydantic 请求/响应模型（集中管理，消除 main.py 里的 inline 定义）。"""

from pydantic import BaseModel, Field


class AttachmentIn(BaseModel):
    """对话附件：name 原始文件名，path 为上传接口返回的 /data/ 虚拟路径。"""
    name: str
    path: str
    size: int = 0
    content_type: str = ""


class MessageIn(BaseModel):
    message: str = ""
    attachments: list[AttachmentIn] = []


class DecisionIn(BaseModel):
    decision: str  # approve / reject


class LoginIn(BaseModel):
    username: str
    password: str


class ChangePwdIn(BaseModel):
    old_password: str
    new_password: str


class UserCreateIn(BaseModel):
    username: str
    password: str
    role: str = "user"
    org_id: str | None = None


class UserUpdateIn(BaseModel):
    role: str | None = None
    status: str | None = None
    # 归属部门：仅在显式传字段时更新（None=移出部门，与「不改动」区分）
    org_id: str | None = None
    set_org: bool = False


class OrgCreateIn(BaseModel):
    name: str
    parent_id: str | None = None
    sort_order: int = 0


class OrgUpdateIn(BaseModel):
    name: str | None = None
    parent_id: str | None = None
    sort_order: int | None = None
    # move=True 才会改动 parent_id（避免改名时误挂到顶级）
    move: bool = False


class PasswordIn(BaseModel):
    password: str


class ImChannelCreate(BaseModel):
    name: str
    description: str = ""
    provider: str = "web"
    config: dict = Field(default_factory=dict)
    enabled: bool = True
    employee_ids: list[str] = []


class ImChannelUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    provider: str | None = None
    config: dict | None = None
    enabled: bool | None = None
    employee_ids: list[str] | None = None


class ImConversationCreate(BaseModel):
    employee_id: str | None = None


class ImIncomingMessage(BaseModel):
    sender_id: str
    message: str
    employee_id: str | None = None
    secret: str | None = None


class AutomationCreate(BaseModel):
    name: str
    trigger_type: str = "cron"          # cron | event
    cron_expr: str = ""                 # cron：分 时 日 月 周（服务器本地时间）
    event_key: str = ""                 # event：事件标识，如 order.refunded
    secret: str = ""                    # event：可选 secret 校验
    employee_id: str = ""               # 执行员工
    prompt: str = ""                    # 任务指令（支持 {{now}} / {{payload}}）
    run_as: str = ""                    # 以哪个用户身份运行（记忆/可见归属）
    channel_id: str = ""                # 可选：结果推送频道（outbound_webhook）
    enabled: bool = True


class AutomationUpdate(BaseModel):
    name: str | None = None
    trigger_type: str | None = None
    cron_expr: str | None = None
    event_key: str | None = None
    secret: str | None = None
    employee_id: str | None = None
    prompt: str | None = None
    run_as: str | None = None
    channel_id: str | None = None
    enabled: bool | None = None


class AutomationEventIn(BaseModel):
    payload: object = None              # 事件数据（注入 {{payload}}）
    secret: str | None = None
