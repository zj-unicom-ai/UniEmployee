"""表格问答（fileqa）：上传 Excel/CSV 附件自动注册为 DuckDB 表供 SQL 查询。

借鉴 Aix-DB ExcelAgent 思路（DataFrame → DuckDB → LLM 生成 SQL → 执行），
适配 UniEmployee 的差异：
  - 不引入 MinIO/独立服务：文件复用对话附件通道落盘 workspace/data/uploads/
  - 每用户一个 DuckDB 库文件（uploaded_tables.duckdb），跨会话可复用、可跨表 JOIN
  - 表名 = 文件名（含上传时间戳）+ sheet 名，天然去重且对 LLM 可读
  - 查询结果复用 sql_tools 的 SSE 桥接缓冲，前端 SqlViewer 直接渲染
"""
