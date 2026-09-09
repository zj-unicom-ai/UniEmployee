# UniEmployee 沙箱镜像：基于 python:3.12-slim 预装数据分析栈。
#
# 用途：OpenSandbox 沙箱里跑 net-ops / biz-analyzer 等员工的 execute/run_python，
# 预装 pandas / duckdb / matplotlib / openpyxl / python-docx / numpy，
# 与 LocalShellBackend 宿主环境能力对齐（数据分析报告 + 表格问答所需依赖）。
#
# 构建与打标签：
#   docker build -t uniemployee/sandbox:py312-data sandbox/image
#   # 推到私有仓库或本机 docker 即可，OpenSandbox server 按 SANDBOX_IMAGE 拉取
#
# 不要覆盖 ENTRYPOINT / CMD —— OpenSandbox SDK 默认 entrypoint 是 `tail -f /dev/null`，
# 沙箱起容器后通过 exec 注入命令，覆盖 entrypoint 会导致 SDK 健康检查失败。
FROM python:3.12-slim

# 国内镜像加速（如不需要可删）；保留下层 pip 默认源
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    && pip install --no-cache-dir \
        pandas==2.2.3 \
        numpy==1.26.4 \
        duckdb==1.1.3 \
        matplotlib==3.9.2 \
        openpyxl==3.1.5 \
        python-docx==1.1.2 \
        pyarrow==17.0.0 \
        seaborn==0.13.2

# 工作目录设为 /data（与沙箱挂载点对齐：hostPath workspace/data subPath=<uid>）
# 容器内文件按用户隔离落盘；execute 默认 cwd 即 /data
RUN mkdir -p /data /datasets
WORKDIR /data

# 仅声明 sandbox 元数据（不影响 entrypoint）
LABEL org.opencontainers.image.title="uniemployee-sandbox"
LABEL org.opencontainers.image.description="UniEmployee 数据分析沙箱镜像（pandas/duckdb/matplotlib）"
LABEL org.opencontainers.image.source="https://github.com/zj-unicom-ai/UniEmployee"
