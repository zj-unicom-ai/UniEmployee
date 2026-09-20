"""请求授权上下文：把已验证身份转换为业务层可消费的最小权限事实。"""
from __future__ import annotations

from dataclasses import dataclass

from app import catalog


ROLE_PERMISSIONS = {
    "admin": frozenset({"*", "trace:read"}),
    "user": frozenset({"employee:use", "conversation:read_own", "approval:decide_own"}),
}


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    username: str
    tenant_id: str
    org_id: str | None
    org_ids: frozenset[str]
    role: str
    permissions: frozenset[str]

    def allows(self, permission: str) -> bool:
        return "*" in self.permissions or permission in self.permissions

    def owns(self, owner_id: str | None) -> bool:
        return bool(owner_id) and owner_id == self.user_id

    def same_tenant(self, tenant_id: str | None) -> bool:
        return bool(tenant_id) and tenant_id == self.tenant_id

    def as_runtime_config(self) -> dict:
        """仅暴露工具执行所需、且不可由浏览器请求伪造的授权事实。"""
        return {
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "org_id": self.org_id or "",
            "org_ids": sorted(self.org_ids),
            "role": self.role,
            "permissions": sorted(self.permissions),
        }


def from_user(user: dict) -> AuthContext:
    org_id = user.get("org_id")
    org_ids = frozenset(catalog.descendant_ids(org_id)) if org_id else frozenset()
    role = user.get("role") or "user"
    return AuthContext(
        user_id=user["id"],
        username=user.get("username") or "",
        tenant_id=user.get("tenant_id") or "default",
        org_id=org_id,
        org_ids=org_ids,
        role=role,
        permissions=ROLE_PERMISSIONS.get(role, ROLE_PERMISSIONS["user"]),
    )
