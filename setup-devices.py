"""Select and prepare a Shared Facts or device-access deployment."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
DEVSPACE_PACKAGE = "@waishnav/devspace@1.1.1"
DOCS = "docs/devices.md"
NETWORK_DOCS = "docs/remote.md"
HOST = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}")
RECORD_ID = re.compile(r"[a-z][a-z0-9-]{0,47}")
SYSTEMS = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}
GOALS = {"facts": "读取共享事实", "project": "让 Agent 操作指定项目",
         "terminal": "连接远程终端或传文件", "desktop": "操作远程桌面"}
PORTS = {"ssh": 22, "screen-sharing": 5900, "rdp": 3389}
PRIVATE_IPV4 = tuple(ipaddress.ip_network(cidr) for cidr in
                     ("10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
EXTERNAL = {
    "tailscale": "https://tailscale.com/docs/install",
    "node": "https://nodejs.org/en/download",
    "git": "https://git-scm.com/downloads",
}


def command(name):
    if executable := shutil.which(name):
        return executable
    paths = {
        "tailscale": [Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Tailscale/tailscale.exe",
                      Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale")],
    }
    return next((str(path) for path in paths.get(name, []) if path.is_file()), None)


def windows_rdp_host():
    if sys.platform != "win32":
        return "unknown"
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as key:
            edition, _ = winreg.QueryValueEx(key, "EditionID")
    except OSError:
        return "unknown"
    if edition.startswith(("Professional", "Enterprise", "Education", "Server")):
        return "yes"
    if edition.startswith(("Core", "Starter")):
        return "no"
    return "unknown"


def route(args, local_os):
    target = args.target_os
    if args.role == "target" and target == "auto":
        target = local_os
    base = {"goal": args.goal, "role": args.role, "local_os": local_os, "target_os": target}

    def result(name, steps, *, network=None, doc=DOCS, detail=None, blocked=False):
        return {**base, "route": name, "network": network, "doc": doc, "steps": steps,
                "detail": detail, "blocked": blocked}

    if args.goal == "facts":
        if args.origin == "cloud":
            return result("github-read", ["授权云端客户端读取指定私有仓库", "按发布分支和 SHA 核对记录"],
                          doc="docs/agents.md")
        return result("shared-facts", ["创建或克隆私有数据仓库", "准备本地 Python 环境和只读 MCP 配置",
                                      "用合成记录验证两个克隆读到同一 SHA"], doc="docs/deployment.md")
    if args.goal == "project":
        if args.origin == "cloud" and args.oauth != "compatible":
            return result("github-read", ["先用 GitHub 只读方式交接", "查证目标客户端支持 DevSpace OAuth 后重新选型"],
                          doc="docs/agents.md", detail="GitHub 路线可读取共享记录，项目执行等待兼容客户端。")
        if args.origin == "cloud":
            return result("devspace-public", ["在目标机准备 DevSpace 和隔离工作区",
                                              "配置独立域名和 Cloudflare 命名隧道",
                                              "注册 MCP endpoint，验收 OAuth 和工作区范围"],
                          network="cloudflare", doc=DOCS)
        return result("devspace-private", ["在目标机准备 DevSpace 和隔离工作区",
                                           "配置可达的私有 HTTPS 入口",
                                           "由设备上的 MCP 客户端完成 OAuth 与目标验收"],
                      network="tailscale")
    if args.origin == "cloud":
        return result("device-required", ["从受控设备发起终端或桌面会话"], blocked=True)
    if args.goal == "terminal":
        return result("ssh", ["目标机开启受限 SSH，核对主机指纹", "双方加入私网并验证端口", "从发起设备连接"],
                      network="tailscale")
    if target == "macos":
        return result("screen-sharing", ["Mac 启用限定用户的屏幕共享", "在私网中用兼容 VNC 客户端连目标"],
                      network="tailscale")
    if target == "windows":
        capability = args.rdp_host
        if capability == "unknown" and args.role == "target" and local_os == "windows":
            capability = windows_rdp_host()
        if capability == "yes":
            return result("rdp", ["目标机启用 RDP 并限定用户", "在私网中启动远程桌面并核对主机名"],
                          network="tailscale")
        if capability == "no":
            return result("rdp-unavailable", ["如果只需项目操作，选择 project；只需终端，选择 terminal",
                                              "如必须操作桌面，使用组织或设备所有者批准的远控客户端"],
                          detail="目标 Windows 版本无法充当 RDP 主机。", blocked=True)
        return result("check-rdp-host", ["在目标 Windows 的系统信息确认版本",
                                        "确认支持 RDP 主机后以 --rdp-host yes 重跑"],
                      blocked=True)
    return result("choose-target", ["选择受支持的桌面目标 windows 或 macos"],
                  detail="Linux 目标可使用 terminal 或 project。", blocked=True)


def choose(label, options):
    choices = list(options)
    for index, key in enumerate(choices, 1):
        print(f"{index}. {options[key]}")
    while True:
        answer = input(f"{label} [1-{len(choices)}] ").strip()
        if answer in choices:
            return answer
        if answer.isascii() and answer.isdecimal() and 1 <= int(answer) <= len(choices):
            return choices[int(answer) - 1]


def run(args, *, cwd=None):
    subprocess.run(args, cwd=cwd, check=True, stdout=sys.stderr)


def require_program(name):
    if executable := command(name):
        return executable
    raise RuntimeError(f"未找到 {name}。{EXTERNAL.get(name, '请检查本机 PATH。')}")


def require_bash():
    if sys.platform == "win32":
        git_bash = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
        if not git_bash.is_file() and not command("bash"):
            raise RuntimeError("目标 Windows 需要 Git Bash。https://git-scm.com/download/win")
    else:
        require_program("bash")


def prepare_facts(root, args):
    require_program("git")
    if args.data_repo:
        repo = args.data_repo.resolve()
        if not repo.is_dir():
            raise RuntimeError("共享仓库路径不存在，请先克隆私有数据仓库。")
        status = subprocess.run([require_program("git"), "-C", str(repo), "rev-parse", "--git-dir"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if status.returncode:
            raise RuntimeError("--data-repo 必须指向 Git 仓库。")
    venv = root / ".venv"
    interpreter = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not interpreter.is_file():
        run([sys.executable, "-m", "venv", str(venv)])
    run([str(interpreter), "-m", "pip", "install", "-r", str(root / "requirements-mcp.txt")])
    assets = {"python": str(interpreter)}
    if args.data_repo:
        records = [value for key in args.record for value in ("--allow", key)]
        config = {"mcpServers": {"shared-facts": {"command": str(interpreter),
                  "args": [str(root / "facts-mcp.py"), "--repo", str(repo), *records]}}}
        path = root / ".setup" / "shared-facts-mcp.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8") as file:
                file.write(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
        except FileExistsError:
            if json.loads(path.read_text(encoding="utf-8")) != config:
                raise RuntimeError("已有 MCP 配置内容不同。请先保存或移动旧文件再运行。")
        assets["mcp_config"] = str(path)
    return assets


def devspace(root, action, local_os):
    node = require_program("node")
    npm = require_program("npm.cmd" if local_os == "windows" else "npm")
    require_program("git")
    require_bash()
    version = subprocess.check_output([node, "-p", "process.versions.node"], text=True).strip()
    major, minor, *_ = map(int, version.split("."))
    if not (22 <= major < 27 and (major > 22 or minor >= 19)):
        raise RuntimeError("DevSpace 1.1.1 需要 Node.js >=22.19 且 <27。")
    install = root / ".setup" / "devspace"
    executable = install / "node_modules" / "@waishnav" / "devspace" / "bin" / "devspace.js"
    if not executable.is_file():
        if action != "prepare":
            raise RuntimeError("先用 --prepare 安装仓库指定的 DevSpace 版本。")
        install.mkdir(parents=True, exist_ok=True)
        run([npm, "install", "--no-audit", "--no-fund", "--save-exact", DEVSPACE_PACKAGE], cwd=install)
    if not executable.is_file():
        raise RuntimeError("DevSpace 安装后缺少入口，请检查 npm 安装输出。")
    if action == "init" and (Path.home() / ".devspace" / "config.jsonc").exists():
        raise RuntimeError("已发现本机 DevSpace 配置。保留现有配置，先运行 --devspace doctor。")
    if action != "prepare":
        run([node, str(executable), action])
    return {"devspace": str(executable)}


def install_network(local_os):
    if command("tailscale"):
        return "found"
    if local_os == "windows" and command("winget"):
        run([command("winget"), "install", "--id", "Tailscale.Tailscale", "--exact", "--source", "winget"])
        return "installer-completed"
    if local_os == "macos" and command("brew"):
        run([command("brew"), "install", "--cask", "tailscale-app"])
        return "installer-completed"
    raise RuntimeError(f"缺少可用的包管理器，请按官方步骤安装 Tailscale。{EXTERNAL['tailscale']}")


def probe_private_host(host, port):
    addresses = {item[4][0] for item in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)}
    if not addresses or any(not any(ipaddress.ip_address(ip) in network for network in PRIVATE_IPV4)
                            for ip in addresses):
        raise RuntimeError("目标必须解析到私网 IPv4 地址。请检查 MagicDNS 或使用 Tailscale IPv4。")
    last_error = None
    for ip in sorted(addresses):
        try:
            with socket.create_connection((ip, port), timeout=4):
                return {"host": host, "address": ip, "port": port, "reachable": True}
        except OSError as exc:
            last_error = exc
    raise RuntimeError(f"{host}:{port} 无法连接。检查目标在线状态、服务和私网权限。") from last_error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal", choices=GOALS)
    parser.add_argument("--role", choices=("client", "target"), default="client")
    parser.add_argument("--origin", choices=("device", "cloud"), default="device")
    parser.add_argument("--target-os", choices=("auto", *SYSTEMS.values()), default="auto")
    parser.add_argument("--rdp-host", choices=("unknown", "yes", "no"), default="unknown")
    parser.add_argument("--oauth", choices=("unknown", "compatible", "incompatible"), default="unknown")
    parser.add_argument("--prepare", action="store_true", help="Install only the dependencies of the selected route.")
    parser.add_argument("--install-network", action="store_true", help="Run the platform's Tailscale installer.")
    parser.add_argument("--devspace", choices=("init", "doctor", "serve"))
    parser.add_argument("--data-repo", type=Path, help="Local Git clone for Shared Facts MCP.")
    parser.add_argument("--record", action="append", default=[], help="Shareable record ID, repeatable.")
    parser.add_argument("--host", help="Private hostname or IPv4 for a direct route.")
    parser.add_argument("--probe", action="store_true", help="Check TCP reachability only.")
    parser.add_argument("--open", action="store_true", help="Open the selected SSH or Windows RDP client.")
    parser.add_argument("--user", help="SSH login name when opening a terminal.")
    parser.add_argument("--json", action="store_true", help="Print a machine-readable route and result.")
    args = parser.parse_args()
    interactive = not args.goal
    if sys.version_info < (3, 12):
        parser.error("Python 3.12+ required.")
    if not args.goal:
        if args.json or not sys.stdin.isatty():
            parser.error("--goal required when input is not interactive.")
        try:
            args.goal = choose("你希望完成什么", GOALS)
            if args.goal in {"facts", "project"}:
                args.origin = choose("由谁发起", {"device": "设备上的用户或 Agent", "cloud": "云端 Agent"})
                if args.goal == "project":
                    args.role = choose("脚本当前运行在哪里", {"client": "发起端", "target": "要被访问的目标设备"})
                    if args.origin == "cloud":
                        args.oauth = choose("已确认客户端兼容 DevSpace OAuth 吗",
                                            {"unknown": "未确认", "compatible": "已确认兼容"})
            if args.goal == "desktop":
                args.target_os = choose("目标设备系统", {"macos": "macOS", "windows": "Windows"})
                if args.target_os == "windows":
                    args.rdp_host = choose("目标 Windows 支持作为 RDP 主机吗",
                                           {"unknown": "未确认", "yes": "支持", "no": "不支持"})
        except (EOFError, KeyboardInterrupt):
            return 130
    if bool(args.data_repo) != bool(args.record):
        parser.error("--data-repo and --record must be supplied together.")
    if any(not RECORD_ID.fullmatch(key) for key in args.record):
        parser.error("--record requires a lowercase record ID.")
    if args.host and not HOST.fullmatch(args.host):
        parser.error("--host requires a hostname or IPv4 address without a port.")
    if args.json and (args.open or args.devspace == "init" or args.devspace == "serve"):
        parser.error("Interactive operations require terminal output.")
    local = SYSTEMS.get(platform.system(), "unsupported")
    plan = route(args, local)
    selected = plan["route"]
    required = []
    if selected == "shared-facts":
        required.append("git")
    if selected.startswith("devspace-") and args.role == "target":
        required.extend(("git", "node", "npm.cmd" if local == "windows" else "npm"))
    if plan["network"] == "tailscale":
        required.append("tailscale")
    if args.role == "client" and selected == "ssh":
        required.append("ssh")
    if args.role == "client" and selected == "rdp" and local == "windows":
        required.append("mstsc.exe")
    plan["missing_programs"] = [name for name in required if not command(name)]
    if plan["network"]:
        plan["network_doc"] = NETWORK_DOCS
    try:
        if interactive:
            print(f"已选路线: {selected}")
            can_prepare = selected == "shared-facts" or (
                selected.startswith("devspace-") and args.role == "target")
            if can_prepare and not args.prepare:
                args.prepare = choose("现在准备该路线的依赖吗", {"no": "只查看方案", "yes": "安装所需依赖"}) == "yes"
            if "tailscale" in plan["missing_programs"] and not args.install_network:
                args.install_network = choose(
                    "现在启动 Tailscale 安装吗", {"no": "查看安装步骤", "yes": "运行系统包管理器"}) == "yes"
        if plan["blocked"] and (args.prepare or args.install_network or args.probe or args.open or args.devspace):
            raise RuntimeError("先解决选型结果中列出的问题。")
        if args.prepare:
            if selected == "shared-facts":
                plan["prepared"] = prepare_facts(ROOT, args)
            elif not selected.startswith("devspace-"):
                raise RuntimeError("此路线不需要准备本项目依赖。私网安装可用 --install-network。")
        if args.devspace or (args.prepare and selected.startswith("devspace-")):
            if not selected.startswith("devspace-") or args.role != "target" or plan["target_os"] != local:
                raise RuntimeError("请在目标设备上用 --goal project --role target 运行 DevSpace 安装或操作。")
            if args.prepare:
                plan["prepared"] = devspace(ROOT, "prepare", local)
            if args.devspace:
                devspace(ROOT, args.devspace, local)
        if args.install_network:
            if plan["network"] != "tailscale":
                raise RuntimeError("所选路线无需安装 Tailscale。")
            plan["network_install"] = install_network(local)
        if args.probe or args.open:
            if args.role != "client" or selected not in PORTS or not args.host:
                raise RuntimeError("请在发起设备上指定 --host 并选择 SSH、屏幕共享或 RDP。")
            port = PORTS[selected]
            plan["tcp"] = probe_private_host(args.host, port)
            if args.open and selected == "ssh":
                if not args.user or not re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,63}", args.user):
                    raise RuntimeError("SSH 需要有效的 --user。")
                run([require_program("ssh"), "-o", f"HostKeyAlias={args.host}",
                     f"{args.user}@{plan['tcp']['address']}"])
            elif args.open and selected == "rdp" and local == "windows":
                run([require_program("mstsc.exe"), f"/v:{args.host}"])
            elif args.open:
                raise RuntimeError("请用兼容的桌面客户端连接上面给出的地址。")
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        plan["error"] = str(exc)
    if args.json:
        print(json.dumps(plan, ensure_ascii=True))
    else:
        print(f"路线: {selected} · 本机: {local} · 目标: {plan['target_os']}")
        if plan["detail"]:
            print(plan["detail"])
        if plan["missing_programs"]:
            print("初始检查缺少: " + ", ".join(plan["missing_programs"]))
        for index, step in enumerate(plan["steps"], 1):
            print(f"{index}. {step}")
        for key in ("prepared", "network_install", "tcp", "error"):
            if key in plan:
                print(f"{key}: {plan[key]}")
        print(f"手册: {plan['doc']}")
    return 1 if "error" in plan else 2 if plan["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
