# Agents MCP

**Agents MCP** 是一个独立的 Skill，不是新的可执行编辑器，也不是需要同时启动的第二套 Agent 运行时。

这个 Skill 让 **Codex 留在原工作界面**，在写完文章或论文后按需调用 Gemini 进行独立复核；也可扩展到 Claude。

**直接打开 [SKILL.md](SKILL.md)**，把内容交给 Codex，或复制到当前项目的 `.agents/skills/agents-mcp/SKILL.md`，再告诉 Codex：

> 请根据这个 Skill 检查我现有的 MCP。没有就自行编写、注册最小的文章审稿工具；用虚构段落实调一次。以后重大稿件版本才触发复核，所有修改仍由你对照原文证据判断。

**注意**：Skill 是操作规范，不是“安装即可使用”的 MCP Server。实际使用仍需相应服务、个人 API 权限及数据出站授权；不要把未发表的论文直接送往第三方模型。
