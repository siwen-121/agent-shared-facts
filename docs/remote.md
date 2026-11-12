# 远程接入

GitHub 已授权连接器可以跨设备读取时，到部署手册的跨设备验收即可。需要直接访问常在线节点上的 MCP 时，再部署下面一种路线。服务只暴露明确允许的 Git 记录。每位使用者有自己的设备或边缘服务身份，服务进程只读专用数据克隆。

| 场景 | 路线 | 前置条件 |
| --- | --- | --- |
| 自己控制的 Windows、Mac 或常在线节点 | Tailscale Serve | 客户端和主机可加入同一 tailnet，无需购买域名。 |
| 外部宿主不能加入 tailnet | Cloudflare Tunnel + Access | 已激活的自有域名，客户端能发送 Access 和后端认证头。 |
| 云端宿主只支持其 OAuth 流程，或不支持所需头 | GitHub 只读或独立 OAuth 网关 | 先完成连接器验证。只有确认 OAuth 网关与目标客户端兼容后才上线。 |

## 先启动本地服务

安装 `requirements-mcp.txt`。在服务账户的私密环境设置 `SHARED_FACTS_HTTP_TOKEN`，生成随机值可用 `python -c "import secrets; print(secrets.token_urlsafe(32))"`。生成和保存工作在自己的终端或凭据工具中完成，避免进入聊天、Git、命令参数和日志。启动时把 token 注入进程环境；Git 凭据用服务账户的只读身份。

```sh
python facts-mcp.py --repo /absolute/shared-data --allow intake --http --port 8765
python probe-mcp.py http://127.0.0.1:8765/mcp intake
```

后端只监听回环。正式路由的 HTTP Host 如果不是 `127.0.0.1:8765` 或 `localhost:8765`，在启动时增加 `--hostname <exact-dns-name>`，可重复。代理保持 Host 和 Authorization 可验证，避免对 `/mcp` 缓存。探针请求无认证时须被拒，再验证有认证的工具列表和合成记录 SHA。

## Tailscale Serve

1. 在两台设备安装官方 Tailscale，使用各自账户加入同一 tailnet。确认主机已上线并打开 MagicDNS。检查 HTTPS 证书设置；使用服务名申请的公开证书可能在证书透明度日志中留下名称，避免用个人信息命名。
2. 在管理控制台添加精确的 grants，只允许需要的用户或设备身份访问目标主机的 TCP 443。检查原有通配规则，避免新规则与更宽的旧规则叠加。变更共享 tailnet 前由其管理员确认受影响成员。
3. 从服务宿主运行 `tailscale serve --bg http://127.0.0.1:8765`。用 `tailscale serve status` 获取实际 `.ts.net` 域名，在后端 `--hostname` 中加入该域名并重启服务。使用 Serve 的私网地址。
4. 在第二台获准设备设置后端 bearer，再跑 `python probe-mcp.py https://<actual-tailnet-host>/mcp intake`。核对 SHA，并从无权限设备确认访问被拒。回退时用与原路由一致的 Serve 参数和 `off`，检查其他已有 Serve 路由仍可用。

来源：[Tailscale Quickstart](https://tailscale.com/docs/how-to/quickstart) · [Serve](https://tailscale.com/docs/reference/tailscale-cli/serve) · [MagicDNS](https://tailscale.com/docs/features/magicdns) · [Grants](https://tailscale.com/docs/features/access-control/grants)。

## Cloudflare Tunnel + Access

1. **域名。** 优先用已由你管理的活动域名，挑一个未占用的子域，如 `facts.example.com`。确实需要买域名时，Agent 可以比对可用性、首年与续费、后缀和自动续费。由所有者选择并确认预算，在 Registrar 里填写自己真实的注册联系人、邮箱和付款资料，完成必要的邮箱验证。已经在其他注册商的域名可保留注册商，按 Cloudflare DNS 引导操作。变更 nameserver 前核对邮件和其他现有 DNS 记录，确认迁移范围，等 Zone 显示 Active。
2. **先配置 Access。** 在 Cloudflare Zero Trust 的 Access controls → Applications 新建 Self-hosted 应用。给整个专用 hostname 加保护。为机器客户端在 Service credentials 创建各自的短期 service token。应用策略选 **Service Auth**，Include 只选应获准的 token。记录过期日期与撤销人，保留拒绝默认行为。
3. **再发布路由。** 在 Networking → Tunnels 建命名隧道，选择主机 OS，按控制台提供的官方安装步骤注册 `cloudflared`。将隧道 token 视为部署凭据，仅交给运行隧道的主机。确认隧道健康，再添加 Published application，Hostname 用上一步保护的专用子域，Service URL 填 `http://127.0.0.1:8765`，接口路径为 `/mcp`。在后端加入实际 hostname。常驻运行时用专用服务账户和受保护的凭据存储。
4. **接客户端。** HTTP 客户端需要 `CF-Access-Client-Id`、`CF-Access-Client-Secret` 和 `Authorization: Bearer …`。将它们通过账户或进程私密环境提供。确认 Cloudflare 使用独立的 Access 头，让后端保留 Authorization。用第二个网络和相同的合成记录测试：

   ```sh
   python probe-mcp.py https://facts.example.com/mcp intake --cloudflare
   ```

   探针读取 `CF_ACCESS_CLIENT_ID`、`CF_ACCESS_CLIENT_SECRET` 和 `SHARED_FACTS_HTTP_TOKEN` 环境变量。还应在客户端重做允许和拒绝测试，确认未授权请求在边缘层被拒，测试撤销单一客户端凭据后其访问失效。

Codex HTTP 示例配置放在客户端本地私有设置，仓库只保存示例：

```toml
[mcp_servers.shared-facts]
url = "https://facts.example.com/mcp"
bearer_token_env_var = "SHARED_FACTS_HTTP_TOKEN"
env_http_headers = { CF-Access-Client-Id = "CF_ACCESS_CLIENT_ID", CF-Access-Client-Secret = "CF_ACCESS_CLIENT_SECRET" }
```

来源：[域名注册](https://developers.cloudflare.com/registrar/get-started/register-domain/) · [创建 Access 应用](https://developers.cloudflare.com/learning-paths/clientless-access/access-application/create-access-app/) · [命名隧道](https://developers.cloudflare.com/tunnel/get-started/) · [Access 服务令牌](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/) · [Codex MCP](https://developers.openai.com/codex/mcp/)。

## 排查与撤回

| 现象 | 下一步 |
| --- | --- |
| TCP 失败、DNS 或 TLS 报错 | 先在主机用回环探针验证后端，再按主机在线、隧道进程、DNS Zone 和 HTTPS 证书的顺序排查。远端保留证书校验。 |
| Cloudflare 502 | 核对 `cloudflared` 与后端是否在同一台主机、Service URL、监听端口和进程健康。 |
| 401、403 或出现登录页 | 从独立网络检查是边缘策略还是后端拒绝，核对 Access token、服务策略、后端 token 及过期时间。只支持 OAuth 的客户端走受支持的连接器。 |
| HTTP 421 或 403 Origin | 核对代理转发的 Host 与服务的 `--hostname`。后端面向无浏览器 Origin 的 MCP 客户端。需浏览器跨域时使用受控网关，保留原访问边界。 |
| OAuth 注册 HTTP 400 | 核对宿主版本支持的 OAuth 流程、回调 URI、客户端注册方式与 scope。本文的 HTTP 后端无动态注册，选 GitHub 只读或兼容的专用 OAuth 网关。 |
| MCP 已连接但记录为空或陈旧 | 检查合成记录是否在 allowlist，测试 Git 只读凭据及刷新能力，比较权威分支 SHA。 |
| 撤回外部访问 | 禁用发布路由，撤销该客户端的 Access 凭据，轮换后端 bearer，检查被撤销客户端无法调用。若怀疑隧道 token 泄露，按 Cloudflare 流程轮换并重启连接器。 |

这两条线路只适用于本项目的只读 MCP。需要跨设备操作代码或本机文件时，使用各自获准的独立工作区与客户端，并给专门用途单独配置权限。桌面控制和终端执行留在独立的设备侧操作面。
