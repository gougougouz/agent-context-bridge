---
name: agent-context-bridge
description: 在 DSH / Codex（ChatGPT）/ Claude Code 之间同步同一个项目的对话上下文与进度。当用户切换 agent、额度用完换工具、上下文断了、说"接着之前的做"，或问"之前聊到哪了 / 项目做到哪一步"时使用。
whenToUse: 用户提到 codex / chatgpt / claude / dsh 之间切换，或提到额度、上下文断了、继续之前的任务、查看其他 agent 的记录。
---

# 项目上下文桥（agentlink）

三家工具各自把对话存在自己的目录里。用户换工具时，新 agent 看不到之前的讨论、决定和进度。
本技能在本地读取三家的会话，按项目归并成一份速览，贴给当前 agent 就能接上。

## 什么时候用它

- 用户从别的 agent 过来："接着刚才的做"、"我们之前聊到哪了"、"这个项目做到哪一步了"
- 用户提到额度用完、换工具、上下文丢了
- 你接手一个陌生项目，想先看看历史讨论

## 三步

```bash
agentlink brief          # 第一步，也是绝大多数情况下的唯一步
agentlink brief --copy   # 直接进剪贴板，省得选中复制
```

1. 读输出，用 3–5 行向用户复述：上次在做什么 → 已定结论 → 还没做完的 → 你准备先做哪件。
2. 然后直接开工，或先确认一句。**不要**为了"对齐"再去读 `.agentlink/context.md`（内容一样，白花 token）。
3. 需要某段细节时只取那一段，别拉全量：`agentlink show --session <id前缀> --role user --limit 20`

`brief` 默认约 2–3k tokens，已经包含 AI 摘要（如果之前生成过）、当前任务、时间线、
会话卡片、待办和决定。用户觉得不够细时再加：

```bash
agentlink brief --full          # 约 6–8k，连回放和 git log 一起
agentlink brief --since 3d      # 只看最近三天
```

## 让交接更准（可选，花一次就有缓存）

规则速览是文本摘要，不懂语义。任务长、跨天、或用户明确要"把进度整理清楚"时，
写一份结构化交接，之后三家共用，不用重复花：

```bash
agentlink digest            # 输出材料：上一版摘要 + 之后新增的记录（增量、有上限）
# 你按下面的格式写一份 JSON
agentlink summary apply -f summary.json
```

```json
{
  "version": 1,
  "project": { "goal": "一句话目标", "status": "当前阶段", "stack": "技术栈" },
  "state": {
    "done": [], "in_progress": [], "blocked": [],
    "decisions": [], "next": [], "risks": []
  },
  "sessions": [
    { "agent": "codex", "id": "会话 id", "title": "标题",
      "one_line": "这条会话干了什么", "outcome": "结论", "open": ["未完成的"] }
  ],
  "notes_for_next_agent": ["接手者必须知道的坑"]
}
```

写的时候：只写材料里能证实的；每条一句话、60 字以内；写结论，不要抄原文；
拿不准的放进 `blocked` 或 `risks`。`agentlink status` 会告诉你摘要落后多少条，
落后少于 6 条就不用重做 —— 那份缓存仍然有效。

## 记事情（最便宜的对齐方式）

```bash
agentlink note "只做 CSV，xlsx 下个迭代" --kind decision
agentlink note "对账任务等幂等跑通再动" --kind todo
```

写一句就进速览，三家都能看到。用户的临时决定值得记就记，别指望它出现在对话里。

## 其他命令

| 命令 | 用途 |
| --- | --- |
| `agentlink status` | 有没有数据、摘要新不新鲜（很便宜，先看这个也行） |
| `agentlink sync` | 只抽取新记录 |
| `agentlink handoff --to claude` | 生成交接文件给指定工具 |
| `agentlink init --hook` | 首次初始化并顺手埋提示段，新会话自动想起本技能 |
| `agentlink hook` | 只埋/刷新提示段 |
| `agentlink doctor` | 依赖、会话目录、安装状态自检 |
| `--lang en` / `--lang zh` | 换输出语言 |

## 没装或报错时

先跑 `agentlink doctor`。命令不存在，就装：

```powershell
irm https://raw.githubusercontent.com/gougougouz/agent-context-bridge/main/install.ps1 | iex
```

```bash
curl -fsSL https://raw.githubusercontent.com/gougougouz/agent-context-bridge/main/install.sh | bash
```

也可以读技能目录里的 `LOCAL.md`，那里写着本机启动器和 Python 的绝对路径，
把那个路径当 `agentlink` 用。

- `zstandard` 缺失：只有 DSH 的会话是压缩的，`python -m pip install zstandard`。
- 某一家显示 0 个会话：那个项目在该工具里的工作目录和现在不一致，用 `--root <当时的路径>` 跑一次。
- 项目挪过位置：同上。

## 用户要你在别的机器上装它

如果用户在聊天里说"帮我装这个 skill"并给了仓库链接，或者他换了台机器：

1. 读技能目录里的 `INSTALL.md`（没有的话读仓库里的），按 **Instructions for an agent** 一节做。
2. 顺序是：确认 Python ≥ 3.9 → 跑对应系统的一条命令 → `agentlink --version` 与
   `agentlink doctor` 验证 → 把版本、三个技能路径和"重启客户端"告诉用户。
3. 不要 clone 仓库、不要建虚拟环境、不要改注册表；安装脚本本身已幂等，重跑即升级。
4. 家目录只读或 PATH 不能改时，用 `-Dir` / `AGENTLINK_HOME` 换位置，或加 `-NoPath`，
   技能目录里仍会生成可用的启动器。

## 边界

- 只读三家的会话文件，只写项目内的 `.agentlink/`（以及用户显式要求时的
  `AGENTS.md` / `CLAUDE.md` 提示段）；不联网、不上传。
- 速览是对话线索，不是事实来源。代码状态以仓库为准（`git log`、文件内容）；
  两者冲突时信仓库，并把冲突写进 `agentlink note`。
