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


class UserUpdateIn(BaseModel):
    role: str | None = None
    status: str | None = None


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
