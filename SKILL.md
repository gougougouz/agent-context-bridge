---
name: agent-context-bridge
description: 在 DSH / Codex（ChatGPT）/ Claude Code 之间同步同一个项目的对话上下文与进度。当用户切换 agent、额度用完换工具、上下文丢失、说"接着之前的做"，或问"之前聊到哪了 / 项目进度如何"时使用。
whenToUse: 用户提到 codex / chatgpt / claude / dsh 之间切换，或提到额度/上下文断了、继续之前的任务、查看其他 agent 的记录。
---

# 项目上下文桥（agentlink）

三家 agent 各自把对话存在自己的目录里，换工具后新 agent 看不到之前的讨论和进度。
本技能把三家的本地会话读出来，合成一份可直接进上下文的项目速览。

**默认走最省 token 的路径；只有用户明确需要"深度接手"时才升级。**

## 一、按需选择档位（重要）

| 档位 | 命令 | 花费 | 什么时候用 |
| --- | --- | --- | --- |
| L0 探路 | `agentlink status` | ≈50 tokens | 不确定有没有历史、先看三家有没有数据 |
| **L1 默认** | `agentlink brief` | ≈2000 tokens | 绝大多数情况：换工具、继续任务、问进度 |
| L2 详细 | `agentlink brief --full` | ≈6000 tokens | 用户要"看得细一点"、或 L1 明显不够 |
| L3 深度 | `agentlink digest` → 写 JSON → `agentlink summary apply` | 一次 3–8k，之后**缓存复用** | 长任务交接、跨多天、L1/L2 反复解释同一件事 |

规则：

1. **先 L1，不要一上来就 L2/L3。** L1 里已经有 AI 摘要（若之前生成过）、当前任务、
   会话卡片、待办、决定。
2. **不要重复读文件**：`brief` 已经把内容打印给你了，不要再 `cat .agentlink/context.md`。
3. **没有新对话时用 `--no-sync`**（或直接 `agentlink summary show`）避免重复扫描。
4. **L3 的摘要会缓存**在 `.agentlink/summary.json`，之后的会话直接读，不必重新花 token。
   只有 `brief --stats` 显示"落后 ≥6 条"或用户要求更新时才重新整理。

## 二、标准动作（L1）

```
agentlink brief --stats
```

读到输出后，用 3–5 行向用户复述：上次在做什么 → 已定结论 → 未完成 → 你准备接着做什么。
然后**直接开工或先确认一句**，不要为了"对齐"再读一遍原始记录。

需要某个细节时，只取那一段，别拉全量：

```
agentlink show --session <id 前缀> --role user --limit 20
```

## 三、L3：让子 agent/你自己写一份交接摘要

只在 L1/L2 不够、或用户要求"把项目状态整理清楚"时做。这一步花 token，但产出会缓存给三家共用。

1. 取材料（**增量**：已有摘要 + 上次之后的新记录，默认封顶 6000 tokens）：

   ```
   agentlink digest
   ```

2. 按 schema 写一份 JSON（字段缺失会被容错，但尽量写全）：

   ```json
   {
     "version": 1,
     "project": { "goal": "一句话目标", "status": "当前阶段", "stack": "技术栈" },
     "state": {
       "done": ["已完成"], "in_progress": ["正在做"], "blocked": ["卡住/待确认"],
       "decisions": ["已拍板的决定"], "next": ["下一步"], "risks": ["风险"]
     },
     "sessions": [
       { "agent": "codex", "id": "会话 id", "title": "标题",
         "one_line": "这条会话干了什么", "outcome": "结论", "open": ["未完成"] }
     ],
     "notes_for_next_agent": ["接手者必须知道的坑"]
   }
   ```

3. 保存并合并：

   ```
   agentlink summary apply -f summary.json     # 或 - 从 stdin 读
   ```

4. 之后的 `brief` 顶部就会出现「接手摘要（AI 整理）」，三家共用，不再重复计费。

写摘要的纪律：只写**材料里能证实**的内容；不确定的写进 `blocked` 或 `risks`；
每项 ≤ 60 字；`sessions` 最多 6 条；不要复述原文，要写"结论"。

## 四、命令一览

| 命令 | 作用 |
| --- | --- |
| `agentlink status` | 数据源、会话数、AI 摘要是否落后（L0） |
| `agentlink brief` | 项目速览，默认 2200 tokens（L1） |
| `agentlink brief --full` | 完整速览，约 6000 tokens（L2） |
| `agentlink brief --budget-tokens N` | 自定义预算 |
| `agentlink digest` | 给 agent 做摘要的增量材料（L3 第 1 步） |
| `agentlink summary apply/show/clear` | 应用 / 查看 / 清除 AI 摘要 |
| `agentlink note "..." --kind todo\|decision` | 写一条判断，三家共享（最便宜的对齐方式） |
| `agentlink show` | 查原始记录，`--session/--agent/--role/--limit` |
| `agentlink handoff --to codex` | 生成交接文件 |
| `agentlink hook` | 在 AGENTS.md / CLAUDE.md 埋提示段，让新会话自动想起本技能 |
| `agentlink sync` | 只做抽取，不生成速览 |
| `agentlink doctor` | 自检依赖、会话目录、技能安装 |

首次在某项目使用需要 `agentlink init`（`brief` 也会自动初始化）。

## 五、找不到命令时

读技能同目录的 `LOCAL.md`，里面写着本机启动器与 Python 的绝对路径，
把它当作 `agentlink` 使用即可。

## 六、失败与边界

- **某家没数据**：本机没装/没用过那个工具，跳过，`status` 会写明。
- **报 zstandard 缺失**：DSH 会话是 zstd 压缩的，`python -m pip install zstandard`。
- **路径对不上**：按会话记录里的 `cwd` 匹配项目；项目挪过位置就用 `--root <当时路径>`。
- **只读承诺**：只读三家会话文件，只写项目内 `.agentlink/`（以及你显式要求的
  `AGENTS.md`/`CLAUDE.md` 提示段）；不联网、不上传。

## 七、事实优先级

速览是**对话线索**，不是事实来源。涉及代码状态时以仓库为准（`git log`、文件内容）；
两者冲突时信仓库，并把冲突写进 `agentlink note`。
