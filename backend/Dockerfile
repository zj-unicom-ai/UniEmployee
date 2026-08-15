# 数字员工平台（UniEmployee）运行镜像
# 构建上下文是项目根目录（docker-compose.yml 里 context: .）。
# 布局约定：后端代码 /app/backend，前端构建产物 /app/frontend/dist，
# 数据目录 /app/data（挂载卷），工作区 /app/workspace（挂载卷）。
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_DATA_DIR=/app/data \
    PORT=8787 \
    LOG_LEVEL=INFO

WORKDIR /app/backend

# 系统依赖：编译 bcrypt/cryptography 等可能用到（纯 SQLite 运行不一定需要，但装上更稳）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖（利用镜像层缓存）：requirements.lock.txt 是 pip freeze 的完整可复现清单
COPY backend/requirements.lock.txt /app/requirements.lock.txt
RUN pip install --upgrade pip --retries 10 --timeout 60 \
    && pip install --retries 10 --timeout 60 -r /app/requirements.lock.txt

# 再拷代码与前端构建产物（frontend/dist 由前端构建生成，运行时挂载为静态文件）
COPY backend/ /app/backend/
COPY frontend/dist/ /app/frontend/dist/

# 创建数据 / 自定义技能 / 工作区目录；.env（含密钥）不要 COPY，运行时用卷或 -e 注入
RUN mkdir -p /app/data /app/backend/skills-custom /app/workspace/data

EXPOSE 8787

# 容器探针：连不上 /health 即视为不健康
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD curl -fsS http://localhost:8787/health || exit 1

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
