# OAuth MCP 连接器

UniEmployee 支持对远程 MCP 的 OAuth 2.0 Authorization Code + PKCE 授权。OAuth discovery、受保护资源 metadata、动态客户端注册和 token refresh 的流程参考了 Octop 的实现；授权状态、连接记录和运行时凭据注入由 UniEmployee 自己管理。

## 部署配置

在 `.env` 中配置：

```dotenv
CONNECTOR_OAUTH_REDIRECT_URI=https://your-host.example/api/connectors/oauth/callback
CONNECTOR_OAUTH_ENCRYPTION_KEY=  # Fernet key，生成命令见 .env.example
```

加密密钥必须跨重启保持不变。更换密钥前需要迁移已保存的连接器凭据，否则旧 token 无法解密。OAuth callback URI 必须与 OAuth 服务端注册的 URI 完全一致。仅本机开发允许使用 `http://localhost` 回调。

## 创建连接器

管理员在资源中心创建 HTTP MCP 连接器，例如：

```json
{
  "transport": "http",
  "url": "https://mcp.example.com/mcp",
  "auth_type": "oauth2",
  "oauth_scopes": "documents.read documents.write"
}
```

`oauth_issuer` 和 `oauth_resource` 可选。未配置 `oauth_issuer` 时，服务会从 MCP protected-resource metadata 发现授权服务器；如服务端不提供 resource metadata，则必须配置 issuer。未配置 `oauth_client_id` 时，OAuth 服务端必须支持动态客户端注册。

对于不支持动态注册的授权服务器，可在连接器 JSON 中配置公开的 client ID，并把 client secret 留在服务器环境变量：

```json
{
  "transport": "http",
  "url": "https://mcp.example.com/mcp",
  "auth_type": "oauth2",
  "oauth_issuer": "https://login.example.com",
  "oauth_client_id": "public-client-id",
  "oauth_client_secret_env": "CONNECTOR_OAUTH_CLIENT_SECRET_EXAMPLE",
  "oauth_token_endpoint_auth_method": "client_secret_post"
}
```

环境变量名必须以 `CONNECTOR_OAUTH_CLIENT_SECRET_` 开头。支持 `none`、`client_secret_post` 和 `client_secret_basic` 三种 token endpoint client auth method。服务端若位于私有网络，管理员可在连接器 JSON 中显式设置 `oauth_allow_private_hosts: true`；授权相关请求仍要求 HTTPS。

若授权服务的 metadata 把授权、令牌或注册端点放在 issuer 域名以外，可用 `oauth_allowed_hosts` 显式列出这些主机名，例如 `"oauth_allowed_hosts": ["oauth2.example.com"]`。

## 用户授权

把连接器指派给员工后，用户在 **我的连接器** 页面发起授权。一个账号对同一连接器保存一份授权，可被该账号已分配且绑定该连接器的员工复用。用户可在同一页面重新授权或移除 UniEmployee 本地保存的凭据。移除本地凭据不会调用 OAuth 服务商的撤销接口；如需撤销服务商侧授权，需在服务商处操作。

OAuth state 在数据库中仅保存哈希，PKCE verifier 和动态客户端 secret 加密后保存；state 10 分钟后失效且只能使用一次。用户 token 以 Fernet 加密并按 tenant、user 和 connector 隔离。MCP HTTP 请求时按需刷新 token；断开或重新授权会使该用户的对应员工运行缓存失效。

OAuth 连接器目前仅支持 HTTPS 的远程 MCP HTTP、Streamable HTTP 或 SSE transport；stdio 连接器继续使用现有配置方式。
