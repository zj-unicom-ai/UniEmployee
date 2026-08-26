-- UniEmployee PostgreSQL 初始化脚本
-- ---------------------------------------------------------------
-- 用途一：挂载到 docker-entrypoint-initdb.d/，容器首次启动（数据目录为空）
--         时自动执行，建出 7 个业务库。
-- 用途二：人工执行：psql -U uniemployee -d postgres -f scripts/init_postgres.sql
--         （注意：CREATE DATABASE 不支持 IF NOT EXISTS，重复执行会报错，
--          幂等场景请用 scripts/init_postgres.sh）
--
-- 库与业务对应关系（一个 SQLite 文件对应一个 database）：
--   catalog        员工/技能/工具/连接器/用户等配置编目
--   conversations  会话清单与 IM 频道
--   checkpoints    LangGraph 对话状态（checkpointer）
--   store          跨会话长期记忆
--   traces         运行追踪
--   approvals      人工审批工单
--   ontology       企业本体（实体/关系）

CREATE DATABASE catalog;
CREATE DATABASE conversations;
CREATE DATABASE checkpoints;
CREATE DATABASE store;
CREATE DATABASE traces;
CREATE DATABASE approvals;
CREATE DATABASE ontology;
