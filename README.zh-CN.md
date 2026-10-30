# agent-context-bridge

**在 DSH、Codex（ChatGPT）与 Claude Code 之间同步项目上下文与进度。**

[![Tests](https://github.com/gougougouz/agent-context-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/gougougouz/agent-context-bridge/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](#)
[![Agent skill](https://img.shields.io/badge/agent%20skill-DSH%20%7C%20Codex%20%7C%20Claude-8b5cf6.svg)](#-安装)

[English](README.md) · 简体中文

---

在 Codex 里用完了 5 小时额度，换到 DSH 继续 —— 结果新 agent 什么都不知道：
方案定在哪、代码改到一半的是哪个文件、当初为什么选 CSV 而不是 XLSX。
三家工具各存各的对话，谁也不认识谁。

`agentlink` 在本地读取三家的会话记录，按项目归并，输出一份能直接塞进上下文的速览。

```text
$ agentlink brief

# 项目上下文速览 · payments-service
> 覆盖 4 个会话 / 812 条记录（DSH、Codex/ChatGPT、Claude Code；2 天前 → 12 分钟前）

## 1. 接手摘要（AI 整理）
- 项目目标：把结算服务从定时批处理迁到事件驱动
- 当前状态：核心链路已迁移，回滚开关未做
- 正在做：幂等键落库；下一步：补对账任务、加回滚开关

## 2. 当前任务（最近的用户请求，新→旧）
- **12 分钟前**（Codex）：对账任务先别动，先把幂等跑通

## 3. 各会话卡片
### Codex · 幂等键设计（最后活动 12 分钟前）
- **诉求**：唯一键用 business_id+date 还是 uuid？
- **最后结论**：定 business_id+date，冲突时以 Redis 锁兜底
- **涉及文件**：`src/ledger/idempotency.py`、`migrations/007_idem.sql`
- **关键命令**：`pytest tests/test_idempotency.py`

## 4. 进行中的任务 / 待办
- 补对账任务的失败重试
- 回滚开关（已确认要做，未开工）
```

## ✨ 为什么需要它

- **一个项目，三个 agent** —— DSH、Codex、Claude Code 的会话格式和存放位置互不兼容，
  不该每次换工具都重新解释一遍项目。
- **默认省 token** —— 一次 `brief` 约 2k tokens，最贵的 AI 摘要是**跨 agent 缓存**的：
  花一次，三家共用。
- **两层设计** —— 规则保证永远有事实（git 状态、待办、时间线、碰过的文件）；
  真正值得花 token 时才让 agent 写一份结构化交接。
- **纯本地** —— 只读会话文件，不上传，不需要任何 API key。
- **增量** —— Codex/Claude 按字节偏移、DSH 按记录序号；第二次同步只读新增部分。

## 📦 安装

需要 Python 3.9+；`zstandard` 只有读 DSH 会话时才需要。

```powershell
# 1) 依赖
python -m pip install zstandard

# 2) 装进三家的技能目录
git clone https://github.com/gougougouz/agent-context-bridge.git
cd agent-context-bridge
python -m agentlink install          # 加 --path 顺带把 agentlink 加进 PATH
```

或者一键脚本：`pwsh -ExecutionPolicy Bypass -File install.ps1`。

| 工具 | 技能目录 |
| --- | --- |
| DSH | `%USERPROFILE%\.dsh\skills\agent-context-bridge\` |
| Codex / ChatGPT | `%USERPROFILE%\.codex\skills\agent-context-bridge\` |
| Claude Code | `%USERPROFILE%\.claude\skills\agent-context-bridge\` |

每份拷贝都带一个启动器和 `LOCAL.md`（写明本机绝对路径），`agentlink` 不在 PATH 上也能跑。
装完重启客户端或新开会话。

## 🚀 快速开始

```powershell
cd F:\你的项目
agentlink init          # 建 .agentlink/，探测已有会话
agentlink brief         # 约 2k tokens，交给 agent 的那份东西
```

之后在任何一家工具里：

```powershell
agentlink brief --stats          # 给 agent 看的内容（附 token 数与摘要新鲜度）
agentlink note "只做 CSV，xlsx 下个迭代" --kind decision
agentlink hook                   # 可选：往 AGENTS.md / CLAUDE.md 埋提示段
```

## 🪙 Token 经济

这个技能是按"日常调用要便宜、贵的部分要复用"设计的。

| 档位 | 命令 | 花费 | 场景 |
| --- | --- | --- | --- |
| L0 | `agentlink status` | ≈50 tokens | 先确认有没有东西可同步 |
| **L1** | `agentlink brief` | ≈2k tokens | 默认：换工具、"之前聊到哪了" |
| L2 | `agentlink brief --full` | ≈6k tokens | 用户要看细节 |
| L3 | `agentlink digest` → agent 写 JSON → `agentlink summary apply` | 3–8k，**只花一次** | 长任务交接、跨天工作 |

缓存机制：AI 摘要存在 `.agentlink/summary.json`，之后每次 `brief` 都免费合并进来。
`digest` 是增量的 —— 交出去的是「旧摘要 + 上次之后的新记录」，刷新成本只有重读的一小部分。

稳态大概是：**每个里程碑做一次 L3，每次切换用 L1。**

## 🧰 命令

| 命令 | 说明 |
| --- | --- |
| `agentlink init` | 建 `.agentlink/`，列出发现的会话 |
| `agentlink sync` | 抽取新记录，刷新规则速览 |
| `agentlink brief` | 打印速览（默认 2200 tokens） |
| `agentlink brief --full` / `--budget-tokens N` | 更大 / 自定义预算 |
| `agentlink brief --stats` | 末尾附 token 数与 AI 摘要新鲜度 |
| `agentlink digest [--full] [--max-tokens N]` | 给 agent 做摘要的紧凑材料 |
| `agentlink summary apply -f x.json` / `show` / `clear` | 保存 / 查看 / 清除 AI 摘要 |
| `agentlink note "..." --kind note\|todo\|decision\|done` | 写一条共享判断 |
| `agentlink status` | 数据源、会话数、摘要是否落后、缓存速览大小 |
| `agentlink show [--session ID] [--role user]` | 查原始记录 |
| `agentlink handoff --to claude` | 生成 `.agentlink/HANDOFF.md` |
| `agentlink hook [--remove]` | 维护 `AGENTS.md` / `CLAUDE.md` 提示段 |
| `agentlink install [--path]` | 装进三家技能目录 |
| `agentlink doctor` | 自检依赖、目录、安装状态 |

通用参数：`--root <目录>`、`--agent dsh,codex,claude`、`--max-events N`。

## 🔍 工作原理

```text
~/.dsh/sessions/<--munge-->/session-*/session.v4.jsonl.zstd   zstd 压缩的 JSONL
~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl                  追加写 JSONL
~/.claude/projects/<munge>/*.jsonl                            追加写 JSONL
        │
        ├─ 用会话里的 cwd 认领项目（含子目录）
        ├─ 增量游标：字节偏移；DSH 用记录序号 seq
        ├─ 归一化成 Event(agent, session, role, text, ts, kind)
        └─ .agentlink/journal.jsonl → digest → context.md（可选 summary.json）
```

几个刻意的取舍：

- **默认路径不调用任何模型**：事实来自规则 —— 最近诉求、关键词抽结论/待办、git 快照、
  碰过的文件与命令。
- **AI 是显式且缓存的层**：当前 agent 写一次交接，另外两家免费读；本工具自身不调任何 API。
- **读取是会话文件的纯函数**：删掉 `.agentlink/` 就能重建。

### 项目状态目录

```
<项目>/.agentlink/
├── config.json      # agent 列表、token 预算、git 开关
├── state.json       # 文件游标、会话标题、已见记录
├── journal.jsonl    # 归一化记录（可重建）
├── notes.jsonl      # `agentlink note` 写入的共享判断
├── summary.json     # 缓存的 AI 交接摘要（三家共用）
├── context.md       # 上次生成的速览
└── HANDOFF.md       # `agentlink handoff` 产物
```

`.agentlink/.gitignore` 会把整个目录挡在仓库之外。

## 🧠 AI 摘要格式

`summary apply` 是宽容的：缺字段会被忽略，字符串会自动转成列表。

```json
{
  "version": 1,
  "generated_at": "2026-01-01T12:00:00+08:00",
  "project": { "goal": "...", "status": "...", "stack": "..." },
  "state": {
    "done": [], "in_progress": [], "blocked": [],
    "decisions": [], "next": [], "risks": []
  },
  "sessions": [
    { "agent": "codex", "id": "...", "title": "...",
      "one_line": "...", "outcome": "...", "open": [] }
  ],
  "notes_for_next_agent": []
}
```

技能给撰写 agent 的纪律：只写材料能证实的内容；每条一行、≤60 字；写结论而不是抄原文。

## 🔒 隐私

- 只读本地会话文件；除 `pip install` 外没有任何网络请求。
- `.agentlink/` 默认被 git 忽略，摘要不会被误提交。
- 想把状态放到别的盘：设置 `AGENTLINK_STATE_DIR`。
- 删掉 `.agentlink/` 即清除所有痕迹，项目外不留任何副本。

## ❓ 常见问题

**提示找不到 `agentlink`。**
读技能目录里的 `LOCAL.md`，那里有本机绝对路径；或 `agentlink install --path`
把启动器目录加进用户 PATH。

**某一家显示"0 个会话"。**
那个项目在该工具里的工作目录和当前目录不一致（打开的是子目录、或项目挪过位置）。
用 `--root <当时的路径>` 跑一次即可。

**报 `zstandard is not installed`。**
只有 DSH 需要它：`python -m pip install zstandard`。Codex / Claude 不装也能读。

**速览太长 / 太短。**
`agentlink brief --budget-tokens 900` 或 `--full`。冲突时以仓库为准 —— 信 `git log` 和文件内容。

**会不会把别的项目混进来？**
不会。只有会话里记录的 `cwd` 落在当前项目内（含子目录）才会被认领。

## 🛠 开发

```bash
python -m unittest discover -s tests -v     # 11 个离线测试，只用临时假数据
PYTHONPATH=src python -m agentlink doctor
```

```
src/agentlink/
├── cli.py         # 命令行入口
├── store.py       # .agentlink 状态、游标、journal、notes
├── sources/       # dsh.py / codex.py / claude.py 三个解析器
├── digest.py      # 速览生成（分节、预算、token 估算）
├── summary.py     # AI 摘要的格式、校验与渲染
├── activity.py    # 碰过的文件 / 跑过的命令
├── gitinfo.py     # git 快照
└── install.py     # 安装技能 + AGENTS.md 提示段
```

## ⚠️ 已知边界

- 三家会话格式都是各自的内部实现；解析器遇到未知记录会跳过而不是崩溃，
  但真遇到破坏性改动时可能暂时读不到新数据。
- 规则层是文本级的，不是语义理解；微妙的东西请用 `note` 写一句。
- 同一项目被复制到两个路径，会被当成两个项目。

## License

MIT © Junwen Zhao
