---
name: agents-mcp
description: Guide Codex to create or reuse a secure MCP tool for on-demand Gemini or Claude review, including academic manuscripts and excessive defensive writing; keeps Codex as the sole implementer and verifies the resulting tool before use.
---

# Agents MCP

**一份独立可复用的 Agent Skill**：让 Codex 在已有工作界面中自行创建或复用 MCP 接入工具，把 Gemini / Claude 作为按需调用的独立审查者。

目标：**Codex 是唯一写作者和修改者；Gemini 是通过 MCP 调用的只读审稿员。** 同样可以按需接入 Claude 复核。此 Skill 提供配置和使用规约，**不是**一个预装好的模型工具或 MCP Server。

## 直接交给 Codex 的指令

> 阅读这个 Skill。先检查现有 Codex/MCP 配置，优先复用已经可用的 Gemini 审稿工具。若没有，请你自己创建一个**最小的本地 MCP 审稿工具**并注册到 Codex，使用低敏虚构文章测试真实调用结果。以后只在文章、论文的重要版本完成时调用 Gemini 独立审查，最后由你根据原文和来源核查、接受或拒绝修改建议。不要让我另开双 Agent 界面。

所谓“让 Codex 自己做插件”，是**Codex 创建、配置并调用外部 MCP 工具**，不是修改 Codex 主程序，也不是仅把 Skill 放进去就有 API 权限。

## 适用范围

本 Skill 以“Codex 撰写初稿 → 通过 MCP 调用 Gemini 审查 → Codex 核实后自动执行修改”为可复现实例；同一个创建/注册/测试步骤也可复用于其他允许的 MCP 任务，但必须按新任务重新检查权限、实际工具能力及数据出站范围。**Skill 不等于 MCP Server**，只有实际创建、注册并成功调用后才能说插件已接入。

## 触发条件

- 学术论文、综述、研究报告写出一个实质版本，需要检查论点、方法、数据与引用。
- 普通文章“防御性写作”太多：冗长免责声明、反复打圆场、无理由的套话、读者看完仍不知道作者的判断。
- 需要对 Codex 写好的版本进行独立反证或反方审稿。

**默认每个重要版本最多一次外部审查**；只有修正了重大论证问题，且确需确认时才补一轮。普通短句润色不触发。

## 第一步：查已有 MCP，不重复安装

1. 在当前设备查看 `codex --version`、`codex mcp list`、`codex mcp --help`；按本机版本操作，不假定所有版本命令相同。
2. 如果已有 `gemini_review` 或其他功能等价的 MCP，读取实际工具 schema 并用虚构段落进行一次测试；优先复用，**不要重复启动两个同职责服务**。
3. 状态 `enabled` 只表示配置存在，**不能代替成功调用**。只有实际拿到审稿响应，才写“可用”。
4. Claude 可选，但不意味着已把 Claude Code 所有编程功能接入：以实际暴露的只读复核工具为准。

## 第二步：如缺失，由 Codex 生成并注册最小 MCP 插件

让 Codex 查阅 [Codex MCP 官方文档](https://developers.openai.com/codex/mcp) 和当前操作系统/版本，创建一个本地 **stdio MCP Server**，只暴露 `review_manuscript`（或现成同用途的只读工具）。注册后检查配置并实调一次。

建议输入：

```json
{
  "draft_excerpt": "仅含本次需要审查的脱敏段落",
  "genre": "scientific_manuscript",
  "revision_id": "draft-v2",
  "criteria": ["logic", "claim_evidence", "unnecessary_hedging", "citations", "clarity"],
  "evidence_summary": "必要证据及可核对的来源 ID"
}
```

建议输出：`status`、`revision_id`、`findings[]`（每项含严重程度、确切位置、证据、修改建议、不确定性）、`limitations`。返回不必是 JSON，但要有这些可核查的内容。

安全条件：

- API Key 由用户在 Google AI Studio 自行取得；保存在受保护的**本机环境/机密存储**。不得写在代码、Skill、GitHub、聊天、截图、终端日志中，也不要求用户发给 Agent。
- 初次接入前明确材料的第三方出站范围；科研未发表原稿、个人数据、保密资料**未经允许不得上传**。不同意时返回 `REVIEW_NOT_SENT`。
- 工具只发送所需段落与证据，不读全盘、不调用任意命令、不编辑用户原稿；设置请求超时、预算和长度限制。
- 不自动无限重试收费 API，不因一个小改动就完整重审长论文。
- 把“已注册”“已连通”“已完成审稿”当成三个独立状态。

## 第三步：文章/论文审查标准

**普通文章：** 找出绕圈、重复立场、过度解释、无意义道歉和缺乏具体结论的文字。指出原句，解释其问题，建议保留原意的短写法。

**学术论文/综述：** 对照真实证据核对研究对象、样本量、单位、统计、方法、表格、图注和引用；检查论点的证据级别、推理跨度、反例、术语和章节逻辑。不能捏造文献、实验、DOI、统计显著性或未经发表的数据。

**关键区别：** 科学的必要限定和不确定性**不是**必须删除的“防御性写作”。不要为了“讲人话”把推论写成确定事实。对于每条含新引用或事实的修改意见，Codex 应回到原始来源核实；无来源则标记 `NEEDS_SOURCE_CHECK`。

## 第四步：Codex 判定并修订

1. Codex 先写出一份可恢复的初稿/实质修订，标注版本。
2. 只将授权范围内的稿件片段和证据摘要交 Gemini 审查。
3. Gemini 只返回意见，不改主稿。Codex 对每条标记**采纳、拒绝、待核实**。
4. Codex 依据源文件和引用完成修改，检查正文、表格、引用的一致性。
5. 若重大问题未解，最多补一轮针对性审查；失败须报告 `REVIEW_UNAVAILABLE`，不要称“通过”。

## 扩展到 Claude

可以让 Codex 以同样流程注册或复用 `claude_review`。先核对是否有可用授权和实际工具返回；两个复核模型不是必须同时调用。**“Claude 复核插件可用”不等于“Claude Code 全部功能已集成”。**

## 最终记录

```text
Draft version: ...
Reviewer tool/model: ...（未知则如实标明）
Review result: PASS / PARTIAL / REVIEW_UNAVAILABLE / REVIEW_NOT_SENT
Accepted: ...   Rejected: ...   Unresolved: ...
Codex source/citation verification: ...
Next action: ...
```

此公共 Skill 不包含个人 MCP 代码、用户 API Key、科研数据或私人仓库路径。
