"""统一的项目根、数据目录与数据库路径解析。

本地默认数据目录 = 项目根下的 data/db/，与 .gitignore 对齐。
容器化部署可通过环境变量 ``APP_DATA_DIR`` 覆盖指向挂载卷。"""
import os
from pathlib import Path

# 项目根，用于引用 .venv、workspace 等
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
# 后端根（backend/）
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("APP_DATA_DIR", str(PROJECT_ROOT / "data" / "db"))).resolve()
# 对话/数据分析生成的用户文件统一放这里：项目根/workspace/data/
# 沙箱模式下，本目录会被 hostPath 挂载进沙箱（按 <uid> subPath 隔离用户）。
WORKSPACE_DATA = PROJECT_ROOT / "workspace" / "data"
# 共享数据集目录（只读挂载到沙箱 /datasets）：算网运营 CSV 等跨用户共享数据。
# 沙箱 server 通过 docker.sock 起 hostPath，SANDBOX_HOST_DATASETS 指 docker 宿主机
# 上此目录的绝对路径（开发环境裸跑时与 WORKSPACE_DATASETS 同源）。
WORKSPACE_DATASETS = PROJECT_ROOT / "workspace" / "datasets"

# 全部需要持久化的 SQLite 库文件名（备份脚本也用这一份清单）
DB_FILES = ("catalog.db", "conversations.db", "checkpoints.db", "store.db", "traces.db", "approvals.db", "ontology.db")


def db_path(name: str) -> Path:
    """返回某个数据库文件的绝对路径（受 APP_DATA_DIR 控制）。"""
    return DATA_DIR / name
