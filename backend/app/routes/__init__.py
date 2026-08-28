"""
routes 子包 — 全部 API 路由。

由 main.py 中的 lifespan / middleware / health / index / static mounts 之外的
所有路由拆分而来。每个子文件对应一组职责：
  auth.py          认证（登录、改密、当前用户）
  conversations.py 对话 CRUD + SSE 消息流 + 追踪 + 审批决策
  admin.py         管理后台 CRUD（员工/技能/工具/知识库/SOP/连接器/用户/分配）
  ontology.py      业务本体管理 CRUD（实体/关系类型与实例）
  user.py          普通用户自助（员工覆盖、看板）
"""

from fastapi import APIRouter

from .auth import router as auth_router
from .conversations import router as conv_router
from .admin import router as admin_router
from .ontology import router as ontology_router
from .user import router as user_router, debug_router, dash_router
from .public import router as public_router
from .im import router as im_router
from .guard import router as guard_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(conv_router)
router.include_router(admin_router)
router.include_router(ontology_router)
router.include_router(user_router)
router.include_router(debug_router)
router.include_router(dash_router)
router.include_router(public_router)
router.include_router(im_router)
router.include_router(guard_router)
