---
name: agent-context-bridge
description: 在 DSH / Codex（现统一叫 ChatGPT）/ Claude Code 之间同步同一个项目的对话上下文与进度。当用户切换 agent、五小时额度用完要换工具、上下文丢失、说"接着之前的做"，或询问"之前聊到哪了 / 项目进度如何"时使用。
whenToUse: 用户提到 codex / chatgpt / claude / dsh 之间切换，或提到额度限制、上下文断了、继续之前的任务、查看其他 agent 的记录。
---

# 项目上下文桥（agentlink）

同一个项目里，DSH、Codex（ChatGPT 桌面端）和 Claude Code 各自把对话存在自己的目录里，
换工具时新 agent 看不到之前的讨论和进度。这个技能把三家的会话记录读出来，
生成一份可以塞进上下文的项目速览，让接手的一方几行字内对齐。

## 什么时候必须用

- 用户在 Codex / Claude / DSH 之间切换，并说"继续"、"接着做"、"刚才说到哪"。
- 用户提到 5 小时额度用完、token 用尽、被限流，需要换工具继续。
- 用户问"之前别的 agent 说了什么"、"这个项目现在到哪一步了"。
- 你在新会话里发现 `.agentlink/context.md` 存在（说明这个项目之前用过本技能）。

## 标准流程

1. **确认命令**：先试 `agentlink --version`。若不在 PATH，读技能同目录的 `LOCAL.md`，
   那里写着本机启动器的绝对路径，后面用这个路径替代 `agentlink`。
2. **首次在该项目使用**：`agentlink init`（创建 `.agentlink/`，探测三家历史会话）。
3. **同步并取上下文**：

   ```
   agentlink sync      # 抽取新增记录，刷新 .agentlink/context.md
   agentlink brief     # 打印速览（默认会先 sync）
   ```

4. **读 brief 的输出**，然后用 3–5 行向用户复述：
   - 上次在做什么（当前任务）
   - 已经定下的结论/约束
   - 未完成的待办
   - 你准备接着做什么（等用户确认或直接开工）
5. **需要细节**时再查原始记录，不要一开始就把全部历史读进上下文：

   ```
   agentlink show --session <会话 id 前缀> --role user --limit 20
   agentlink show --role assistant --limit 10
   ```

## 命令一览

| 命令 | 作用 |
| --- | --- |
| `agentlink init` | 初始化 `.agentlink/`，列出发现的历史会话 |
| `agentlink sync` | 增量抽取三家记录，刷新 `context.md` |
| `agentlink brief` | 打印项目速览（默认先 sync） |
| `agentlink brief --budget 8000` | 控制速览长度（按显示宽度算） |
| `agentlink status` | 数据源、会话数、上次同步时间 |
| `agentlink show` | 查看原始记录，可 `--session` / `--agent` / `--role` 过滤 |
| `agentlink note "..." --kind todo\|decision` | 写一条人工进度，三方共享 |
| `agentlink handoff --to codex` | 生成给某个 agent 的交接文件 |
| `agentlink hook` | 在 `AGENTS.md` / `CLAUDE.md` 写入提示段，让新会话自动想起本技能 |
| `agentlink doctor` | 自检依赖、会话目录、技能安装状态 |

## 反向同步：把本轮进展写回去

对话本身会被自动读到，但"我觉得这事定了/还没做完"这类判断不会。
在关键节点写一条，三方都能看到：

```
agentlink note "导出功能决定只做 CSV，xlsx 下个迭代" --kind decision
agentlink note "还差分页和错误提示" --kind todo
```

## 失败与边界

- **某家没有会话目录**：说明本机没装或没用过，跳过即可，`status` 会写明。
- **报 zstandard 缺失**：DSH 的会话是 zstd 压缩的，需要 `python -m pip install zstandard`。
- **路径对不上**：三家按"会话记录里的工作目录"匹配项目。如果项目改过名或换了盘，
  用 `agentlink sync --root <旧路径>` 或把新路径加进配置的 `project` 字段。
- **只读承诺**：本技能只读三家的会话文件，只写项目里的 `.agentlink/`（以及用 `hook`
  时你显式要求写入的 `AGENTS.md` / `CLAUDE.md`）；不联网、不上传任何内容。

## 边界提醒

速览是"对话摘要"，不是事实来源：涉及代码状态时，仍要看仓库本身（`git log`、文件内容），
速览里的 git 快照只是辅助。冲突时以仓库为准。