# 下载后直接运行

克隆仓库或下载 GitHub 的源代码 ZIP，解压后保留整个目录。启动脚本、选型程序、MCP 服务和示例已经随仓库提供。安装程序按本机和所选路线准备依赖，不需要自己写脚本或创建配置模板。

| 运行环境 | 交互启动 | Python 缺失时 |
| --- | --- | --- |
| Windows | 在 PowerShell 运行 `.\setup.cmd`，也可双击 | `.\setup.cmd --install-python` 使用已有 WinGet。安装后重新打开终端。 |
| macOS | 在终端运行 `sh ./setup.sh` | `sh ./setup.sh --install-python` 使用已有 Homebrew。 |
| Linux | 在终端运行 `sh ./setup.sh` | 通过发行版或 Python 官方渠道安装 Python 3.12+。 |

交互模式按需求选择共享事实、Agent 项目操作、远程终端或桌面。它区分本机和目标机，检查本机 PATH 中的依赖。它可以在同一会话中准备只读 MCP 或目标机 DevSpace，也可在 WinGet 或 Homebrew 可用时启动 Tailscale 安装。电脑重启后或新装依赖后，重新打开终端再检查一次。

## 智能体如何自动选型

先确认用户的目标和哪台设备承担哪种角色。执行 `--json` 获取路线、需要补装的本机程序及下一步。例子中的 `python` 可替换为 `py -3`、`python3` 或上述启动脚本。

```sh
python setup-devices.py --goal facts --origin cloud --json
python setup-devices.py --goal project --role target --json
python setup-devices.py --goal project --origin cloud --oauth compatible --json
python setup-devices.py --goal terminal --target-os macos --json
python setup-devices.py --goal desktop --target-os windows --rdp-host yes --json
```

退出码 0 表示路线已给出，2 表示缺少选型条件，1 表示执行或参数有误。对于云端项目操作，只有已经核实客户端兼容 DevSpace OAuth 才传 `--oauth compatible`。未知或不兼容时，返回 GitHub 只读交接路线，项目操作保持待定。对于 Windows 桌面，能在目标机执行时使用 `--role target`，程序读取本机 Windows 版本；若在另一台电脑上执行，先向用户确认目标版本，再填写 `--rdp-host`。机器可达需要另外验收，选型成功与 TCP 可达都不等于认证或远程操作成功。

## 已经可以自动完成的动作

- **共享事实本地 MCP**。先克隆私有数据仓库，再运行 `python setup-devices.py --goal facts --prepare --data-repo ../shared-data --record intake`。程序建立项目虚拟环境，安装 MCP 依赖，并生成 `.setup/shared-facts-mcp.json`。需要更多记录就重复传 `--record`。将生成的配置合入客户端自己的设置。现有不同内容的配置会保留。
- **目标设备的 DevSpace**。在每台目标机上运行 `python setup-devices.py --goal project --role target --prepare`。安装器先解析依赖锁并运行 npm 审计，只有通过才安装。审计失败、高危或严重告警会暂停此路线。已安装的 DevSpace 在初始化、检查和启动前也会重新审计。通过后按相同选型参数使用 `--devspace init`、`--devspace doctor` 和 `--devspace serve`。已有用户配置直接走检查流程。云端接入另需核实 OAuth 兼容性，并按设备手册准备对应入口。
- **设备私网**。选到 Tailscale 路线后，在需安装的设备上加 `--install-network`。已有客户端会被复用。Windows 使用 WinGet，macOS 使用已有 Homebrew。其它环境按官方安装页操作。安装后由用户登录、批准系统网络权限并验证目标设备。
- **验收 SSH、VNC 或 RDP 端口**。在发起机上给选型命令加 `--host macbook --probe --json`。目标须解析为私网 IPv4。要打开 SSH 客户端，改用 `--host macbook --user mac-operator --open`；在 Windows 发起 RDP 时用 `--host win-laptop --open`。屏幕共享用用户已有的 VNC 客户端打开探测确认的地址。真实会话按[设备远控手册](devices.md)核对账户和目标主机。

域名购买、DNS 和隧道路由的账户变更、DevSpace OAuth 批准、开启 SSH 或桌面共享，都需要该设备或服务的所有者按场景授权。程序给出对应流程，账号凭据留在设备或服务的授权界面。Python、Git、Node.js、Tailscale 属于平台依赖，由安装入口调用本机工具或引导至官方来源，源码 ZIP 适用于不同系统。

来源：[Windows Python](https://learn.microsoft.com/windows/dev-environment/python) · [Tailscale 安装](https://tailscale.com/docs/install) · [Homebrew Tailscale](https://formulae.brew.sh/cask/tailscale-app)。
