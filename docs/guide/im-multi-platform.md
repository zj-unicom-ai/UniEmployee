# 原生 IM 多平台接入

UniEmployee 复用 Octop 的 MIT 许可 `octop-gateway` 通道适配器，并将平台消息桥接到 UniEmployee 的 LangGraph 会话。当前支持：

- 飞书 / Lark、钉钉、企业微信、微信 iLink、QQ、腾讯元宝
- Telegram、Discord、华为小艺、MQTT
- 通用 Webhook（兼容原有 `/api/im/channels/{id}/incoming` 入口）

适配器负责平台连接、消息解析、分片发送、媒体收发和连接生命周期；员工运行、权限护栏、长期记忆、审批、Trace 与会话记录仍由 UniEmployee 处理。

## 配置

1. 在部署环境中设置稳定的 Fernet 密钥 `CONNECTOR_OAUTH_ENCRYPTION_KEY`。原生 IM 凭据和通用 Webhook 密钥加密存入 `conversations` 库；轮换该密钥前必须先迁移已有加密配置。

   ```bash
   python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
   ```

2. 重启 UniEmployee，在「IM 频道」页面新增平台通道并选择“原生长连接 / 轮询”。不需要原生连接的旧机器人，可继续选“通用 Webhook”。
3. 在对应平台的机器人后台创建机器人、开放消息权限并填写凭据。飞书、企业微信、钉钉、微信、QQ、元宝、Telegram 和 Discord 使用平台长连接或轮询；服务器需要能访问对应平台服务。
4. 将通道绑定到一个数字员工，保存后查看连接状态；可用「测试连接」探测凭据。

编辑时凭据会掩码显示，密码留空代表保留原值。微信使用 `accounts` JSON 数组，例如：

```json
[
  {"account_id": "账号ID", "token": "访问令牌"}
]
```

Discord / Telegram 的允许用户或频道 ID 可选，用逗号或空白分隔。通用 Webhook 保留原有 JSON 消息格式和 `outbound_webhook` 回发能力。

## 行为与边界

- 一个原生 IM 通道绑定一个数字员工；同一平台可创建多个通道分别路由到不同员工。
- 私聊按频道和外部用户隔离会话与工作区；群聊按群会话隔离，并保留平台提供的群聊上下文。
- 入站图片、音频、视频和文件会保存到对应外部身份的 `workspace/data/<im-user>/uploads/`，按附件路径交给员工处理；本轮生成的普通文件会尝试作为附件回传。
- 通道管理仍使用现有管理员权限。通道停止或配置变更后会同步更新运行中的平台连接。
- 升级前已有的 `feishu`、`dingtalk`、`wecom` 等 provider 记录默认保留 Webhook 模式；只有显式标记为原生模式的新配置才会启动 Octop 适配器。
- 当前接入覆盖 Octop 的十种内置协议适配器及基础手动配置；Octop 的二维码机器人创建向导、插件通道注册与平台专属交互卡片不在本次迁移范围内。
