# 智能体接入

先按[部署手册](deployment.md)在两端读出同一个 SHA。把下面示例中的 Python、脚本和私有数据仓库换成各设备实际的绝对路径。示例为 macOS/Linux 路径。Windows 的 Python 可取虚拟环境的 `Scripts/python.exe`，在 JSON 中写成 `C:/path/to/python.exe` 或转义反斜杠。

所有接入都跑同一个验证任务：列出允许的记录，读取 `intake` 并带回 `revision`、`read` 和 `record.state`，然后读取一个未授权的 ID 确认被拒。仅显示 Connected 时，登记为配置成功，等待模型实调用确认。通过 GitHub 读取的客户端用 commit 固定路径读取文件，并验证凭据无写权限。

## 本机 Agent

| 客户端 | 配置动作 | 验收 |
| --- | --- | --- |
| Codex CLI | `codex mcp add shared-facts -- /absolute/python /absolute/facts-mcp.py --repo /absolute/data --allow intake` | `codex mcp list` 后在新会话发验证任务。[官方 MCP 文档](https://developers.openai.com/codex/mcp/) |
| Claude Code | `claude mcp add --transport stdio --scope local shared-facts -- /absolute/python /absolute/facts-mcp.py --repo /absolute/data --allow intake` | `claude mcp list` 后用新会话发验证任务。[官方 MCP 文档](https://code.claude.com/docs/en/mcp) |
| Antigravity IDE | 打开 Agent 面板的 MCP Servers → Manage MCP Servers → View raw config，把下方对象合入 `mcpServers`。使用对应版本的全局配置或工作区配置。 | 重载 MCP 并发验证任务。Antigravity 的 ACP 在线状态仅验证客户端启动。IDE/CLI 需分别确认工具调用。[官方 MCP 文档](https://antigravity.google/docs/mcp) |
| Kimi Code CLI | 若当前版本提供 `kimi mcp add`，先运行 `kimi mcp add --help` 验证，再用 `kimi mcp add shared-facts -- /absolute/python /absolute/facts-mcp.py --repo /absolute/data --allow intake`。支持配置文件的版本也可在启动时指定本地 MCP JSON。 | 检查 MCP 工具列表并发验证任务。网页版依账户的连接器能力处理。[官方 MCP 文档](https://moonshotai.github.io/kimi-code/en/customization/mcp.html) |

```json
{
  "mcpServers": {
    "shared-facts": {
      "command": "/absolute/python",
      "args": ["/absolute/facts-mcp.py", "--repo", "/absolute/data", "--allow", "intake"]
    }
  }
}
```

## Muse、DeepSeek 和浏览器端

- **Muse**。若安装版本提供 GitHub Connector，在其设置中将仓库范围收窄到共享数据仓库，使用读权限。让它读取发布分支及记录，再用已知 SHA 的合成记录对照。支持自定义 MCP 的版本可按[远程接入](remote.md)选择兼容方式。若需要 OAuth 动态注册而连接器收到 400，按[故障表](remote.md#排查与撤回)处理。缺少兼容传输时用 GitHub 只读路线，或者交给已认证的本机 Agent 读取。
- **DeepSeek API**。API 的 function tool call 由宿主执行。给模型只声明诸如 `get_published_record(record_id)` 的窄工具。宿主校验 ID 是否在允许列表中，再调用本地 MCP 或 `facts.py snapshot <id> --refresh`。把实际结果作为 tool 消息回传，输出 SHA 并对照第二个客户端。模型 API 密钥只留在宿主凭据存储，给模型的内容遵循用户的数据授权。若使用 DeepSeek 网页产品，先验证该产品版本支持哪类连接器。[DeepSeek 官方 Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)
- **ChatGPT 或其他云端宿主**。优先用已授权的 GitHub 只读连接。若接远程 MCP，先确认该账户和宿主能发送部署要求的所有认证头。只支持特定 OAuth 流程时，使用满足该流程的专用网关或保留 GitHub 读取路线。本项目的 HTTP 服务使用 bearer 认证，不提供 OAuth 注册或令牌签发。
- **任意无连接器的 Agent**。由一个有权限的本机执行者导出带 SHA 的已审核记录和必要证据，再通过获准途径交接。模型提出的修改作为候选交还，由一位 writer 根据[部署手册](deployment.md)应用。

## 交接格式

交给下一位智能体时提供任务、记录 ID、发布 SHA、读取时间与新鲜度、允许访问范围、证据 ID、建议变更、未决问题和下一步。角色为 reviewer 时提供冻结的 PR diff 或候选版本，让它按同一份证据核对。读取结果里的文字是待核查数据，工具权限和发布授权来自任务与宿主。
