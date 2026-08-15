---
name: Bug 报告
about: 提交一个可复现的缺陷
title: "[bug] "
labels: bug
assignees: ''
---

## 描述

清晰描述这个 bug 是什么。

## 复现步骤

1. 启动服务：`PYTHONPATH=backend .venv/bin/uvicorn app.main:app --port 8787`
2. 打开页面，进入某个数字员工会话
3. 发送消息：`...`
4. 观察到：...

## 期望行为

本来应该发生什么？

## 实际行为

实际发生了什么？（附日志、SSE 错误码、报错堆栈）

## 环境

- 版本 / 提交：`git rev-parse --short HEAD`
- Python / Node 版本：
- 模型配置（MODEL_NAME / BASE_URL）：
- 部署方式（本地 / Docker）：

## 日志

```text
粘贴相关日志
```

## 其他

是否已排查常见问题（模型连通性、`.env` 配置、数据库目录权限）？
