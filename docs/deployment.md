# 部署与发布

## 1. 确定事实归属

每个事实选一个有权限修改的权威位置，并记录仓库、分支、记录 ID、维护人和证据类型。共享任务状态可由私有 Git 的 `main:records/<id>.json` 负责。若实验记录、邮件、订单等已经有自己的原始系统，继续在原系统维护明细，Git 记录只表达获准共享的状态。GitHub、MCP 和不同设备应该读同一条记录，设备缓存随读取附带 commit SHA。

建议将公开代码库、私有共享数据仓库和高敏源数据分开。云端客户端和只读服务器仅访问共享数据仓库。每个候选分支用一份独立 checkout 或 worktree，明确一位写入者。需要第二位智能体时，让它根据同一份 diff 和同一组证据审阅。

## 2. 在 Windows、macOS 或 Linux 准备两份克隆

1. 先在公开代码库运行 README 的测试。创建 Python 环境用 `python -m venv .venv`。Windows 用 `.venv/Scripts/python.exe`，macOS/Linux 用 `.venv/bin/python` 运行和安装 MCP 依赖。
2. 在自己的 GitHub 账号创建 **Private** 仓库并初始化 README，指定 `main` 为发布分支。用各设备自己的身份登录。写入设备获得提案权限，读取设备采用最小权限。只读 MCP 服务可使用只读 deploy key 或最小范围的 Git 凭据，凭据通过 SSH agent、系统凭据管理器或受控服务账户提供。
3. 向私有仓库导入一条合成记录。将公开仓库的 `examples/initial.json` 复制成私有仓库的 `records/intake.json`。建议在数据仓库根加入 `.gitattributes` 一行 `records/*.json text eol=lf`，避免换行转换引起误差。提交并合入发布分支。每条记录恰好有 `state`、`summary`、`evidence`，按脚本生成的 UTF-8 单行 JSON 保存。证据是获准共享的短 ID，解析规则由部署者记录。
4. 在 GitHub 的 Settings 中检查 Rulesets 或 Branches 能否限制直接 push、force push 和删除，并要求 PR 与适用的状态检查。先验证账号套餐与仓库可见性支持所需规则。单人库若无法设置独立审批，可由仓库维护者审查冻结 diff 后合并并明确记录流程约束。多人库需要把审批放在远端分支规则里。此模板的 CI 测试代码库，私有数据仓库的分支规则和检查须由部署者另行配置。
5. 在第二台设备克隆私有数据仓库，调用下面的 `snapshot --refresh`。两个设备应读到相同的记录和 SHA。读者使用普通 Git 克隆即可，MCP 是可选的。

GitHub 创建入口见 [创建仓库](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository)，分支要求见 [Protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)。

## 3. 写入、审阅和读回

以下命令从公开代码库根目录运行。`../shared-data` 是私有仓库，`../intake-candidate.json` 在两个仓库外部。替换成真实位置。若用非默认发布分支，在子命令前加 `--remote <name> --branch <branch>`；两者使用小写短名。

```sh
python facts.py --repo ../shared-data snapshot intake --refresh
python facts.py --repo ../shared-data candidate intake examples/reviewed.json --refresh --out ../intake-candidate.json
python facts.py --repo ../shared-data plan ../intake-candidate.json
git -C ../shared-data switch -c proposal/review-intake origin/main
python facts.py --repo ../shared-data apply ../intake-candidate.json
git -C ../shared-data add -- records/intake.json
git -C ../shared-data diff --cached -- records/intake.json
git -C ../shared-data commit -m "Review intake"
git -C ../shared-data push -u origin proposal/review-intake
```

在 GitHub 开 PR，base 选发布分支，compare 选 `proposal/review-intake`。提交记录 ID、原始 base SHA、证据 ID 和验证结果。审阅者核对整份 PR diff，确认每个变化有证据且范围正确。如果目标记录已变化，在最新版本上重新核对三方内容并创建新候选。使用逐条单行记录，使 Git 对同一记录的并发变更也会直接产生合并冲突。真实迁移、归并或废弃记录由审阅者核查后用状态字段表达。

批准并合并后，从第二台设备用相同候选文件运行：

```sh
python facts.py --repo ../shared-data verify ../intake-candidate.json
```

退出码 0 与 `already-published` 代表上游当前记录等于候选内容，且候选 base 仍是上游的祖先。它验证当前内容，PR 链接单独证明由哪次变更发布。退出码 2 表示冲突，3 表示目标内容尚未生效，1 表示运行、验证或连接错误。共享回执写入记录 ID、候选文件名或任务 ID、PR URL、读回 commit SHA、验证时间。用获准途径传递候选，避免把本地 inbox 加入任何仓库。

## 4. 离线和故障

| 现象 | 智能体下一步 |
| --- | --- |
| 设备离线，仍能读缓存 | 用 `snapshot` 读取已抓取 SHA，并标注 `cache-freshness-unknown`。创建候选时省略 `--refresh`，将候选留在本地 inbox。连接恢复后先执行 `plan`。 |
| `plan` 返回 `conflict` | 保留原候选。读取其 base 记录、当前上游记录和拟写内容。核实证据或让负责人选择，再从新 base 创建新候选。避免 force push 和覆盖式合并。 |
| 上游变了，目标记录没变 | `plan` 可继续。用最新 `origin/main` 新建干净提案分支后再 `apply`。旧分支已有修改时先保留并对照 diff。 |
| `apply` 拒绝 | 检查是否在 `proposal/` 分支、HEAD 是否与抓取 SHA 一致、工作区是否有其他改动。用新 worktree 或新克隆隔离，保留用户的改动。 |
| `verify` 失败或原内容已被替换 | 查看 PR 合并状态及上游实际 SHA。内容已经更新就记录当前上游，并用 PR 或历史提交查明之前是否发布过。 |
| 机器重启或睡眠后无法访问 | 本地先验证 Git 拉取和 MCP，再检查服务进程和隧道。恢复前按离线流程工作。使用长期节点时设置受控的任务计划或服务、最小权限账户和重启后验收。 |
| 发现错误已合入 | 从上游创建新提案，将记录修正或用新的 PR revert，再跨设备读回。若泄露凭据，先撤销和轮换，再由维护者按 GitHub 清理敏感历史的流程处理。 |

定期检查读取账号权限、令牌到期、设备休眠和分支规则。升级客户端或服务器时先在合成记录上重新验收。自动化可以定时刷新缓存或提醒待审核队列，写入与发布仍按同一流程执行。
