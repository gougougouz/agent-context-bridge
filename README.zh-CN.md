<div align="center">

# agentlink

**换工具，不换思路。**

DSH · Codex（ChatGPT）· Claude Code

[![tests](https://github.com/gougougouz/agent-context-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/gougougouz/agent-context-bridge/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.9%2B-3776ab?logo=python&logoColor=white)](https://www.python.org/)
[![license](https://img.shields.io/badge/license-MIT-2ea44f)](LICENSE)

[English](README.md) · 简体中文

</div>

---

Codex 的额度用完了，你打开 DSH 接着干。它问你想做什么。
于是你又讲了一遍项目，又讲了一遍当时为什么选 CSV 而不是 XLSX，
然后回头去找两分钟前还开着的那个文件。

三家工具都存对话，只是存的位置不同、格式不同，彼此也不认识对方。
`agentlink` 把这些记录从磁盘读出来，只留当前项目的部分，合成一份速览 ——
交给现在正在用的那个 agent 就行。

```console
$ agentlink brief

# 项目上下文速览 · payments-service
> 4 个会话 / 812 条记录（DSH、Codex、Claude；2 天前 → 12 分钟前）

## 1. 接手摘要（AI 整理）
- 项目目标：把结算服务从定时批处理迁到事件驱动
- 当前状态：核心链路已迁移，回滚开关还没做
- 正在做：幂等键落库。下一步：对账任务、回滚开关

## 2. 当前任务（最近的用户请求，新→旧）
- **12 分钟前**（Codex）：对账任务先别动，先把幂等跑通

## 3. 各会话卡片
### Codex · 幂等键设计（最后活动 12 分钟前）
- **诉求**：唯一键用 business_id+date 还是 uuid？
- **最后结论**：定 business_id+date，冲突时用 Redis 锁兜底
- **涉及文件**：src/ledger/idempotency.py、migrations/007_idem.sql
- **关键命令**：pytest tests/test_idempotency.py
```

## 思路

两层，故意分开。

**事实要便宜。** git 状态、最近的请求、按关键词抓出来的决定和待办、碰过的文件和命令。
确定性、离线、不调模型。

**结论很贵，所以缓存。** 真正需要交接时，让 agent 读一遍事实、写一份结构化摘要；
之后每次 `brief` 都免费把它合并进来，三家共用。

```mermaid
flowchart LR
    subgraph transcripts["磁盘上的记录"]
        D["DSH · session.v4.jsonl.zstd"]
        C["Codex · rollout-*.jsonl"]
        K["Claude · projects/*.jsonl"]
    end

    subgraph agentlink
        S["sources/<br/>解析 + 归属项目"]
        J[("journal.jsonl")]
        G["digest<br/>规则事实"]
        A["summary.json<br/>缓存的交接摘要"]
        B["brief"]
    end

    D --> S
    C --> S
    K --> S
    S --> J --> G --> B
    G -.->|"agent 写一次"| A
    A -.->|"之后免费合并"| B
    B --> O["贴给任意一个 agent"]
```

不联网、不上传、不需要 API key。整个项目唯一会联网的地方，是安装脚本下载仓库。

## 安装

Windows，PowerShell 一行：

```powershell
irm https://raw.githubusercontent.com/gougougouz/agent-context-bridge/main/install.ps1 | iex
```

macOS / Linux：

```bash
curl -fsSL https://raw.githubusercontent.com/gougougouz/agent-context-bridge/main/install.sh | bash
```

脚本会下载代码、缺依赖就装 `zstandard`、把 `SKILL.md` 复制进三个技能目录，
再往 PATH 放一个 `agentlink`。升级就是再跑一次：代码被替换，你的项目不受影响。

| 装了什么 | 在哪 |
| --- | --- |
| 代码 | Windows `%LOCALAPPDATA%\agentlink`；macOS/Linux `~/.local/share/agentlink` |
| DSH 技能 | `~/.dsh/skills/agent-context-bridge/` |
| Codex 技能 | `~/.codex/skills/agent-context-bridge/` |
| Claude 技能 | `~/.claude/skills/agent-context-bridge/` |
| 启动器 | `~/.../bin/agentlink`，并把该目录加进 PATH |

想放在指定的盘：

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/gougougouz/agent-context-bridge/main/install.ps1))) -Dir D:\app\agentlink
```

```bash
curl -fsSL .../install.sh | AGENTLINK_HOME=/opt/agentlink bash
```

装完重启对应客户端，或者新开一个会话，让它认出这个技能。用 `agentlink doctor` 看它都发现了什么：

```console
$ agentlink doctor
agentlink 0.2.0
Python      : D:\PythonEnv\python.exe (3.12.15)
zstandard   : 0.25.0
git         : F:\app\tools\git\cmd\git.exe

DSH             skill installed  ~/.dsh/skills/agent-context-bridge
                transcripts OK   ~/.dsh/sessions
Codex (ChatGPT) skill installed  ~/.codex/skills/agent-context-bridge
                transcripts OK   ~/.codex/sessions
Claude Code     skill installed  ~/.claude/skills/agent-context-bridge
                transcripts MISSING  ~/.claude/projects
```

## 头五分钟

```console
$ cd ~/code/payments-service
$ agentlink init

已初始化状态目录：~/code/payments-service/.agentlink
  - DSH：1 个会话，137 条记录
  - Codex / ChatGPT：8 个会话，2182 条记录
合计 9 个会话、2319 条记录

下一步：`agentlink brief` 看一眼项目上下文，愿意的话再 `agentlink hook`。
```

```console
$ agentlink brief            # 这份东西就是要贴给 agent 的
$ agentlink note "只做 CSV，xlsx 下个迭代" --kind decision
已记录 [decision]：只做 CSV，xlsx 下个迭代
$ agentlink hook             # 可选：往 AGENTS.md / CLAUDE.md 埋一句提示
```

`init --hook` 把这两步合成一步，适合希望 agent 自己想起来读上下文的用法。

之后的循环短到不用记：

```mermaid
sequenceDiagram
    participant 你
    participant Codex
    participant DSH
    你->>Codex: 一直干到额度用完
    Codex-->>你: 半成品 + 结论
    你->>DSH: 换个工具
    你->>DSH: 贴上 agentlink brief
    DSH-->>你: 接着既定方案继续，不是从零开始
    你->>Codex: 第二天，同一份速览
```

## 按场景用

**额度用完、任务做到一半。** 一句 `agentlink brief`：新 agent 拿到当前诉求、最后结论、
涉及的文件和没做完的事。如果这次交接比较微妙，就让 agent 顺手写一次缓存摘要
（`agentlink digest` → 写 JSON → `summary apply`），下次切换直接复用。

**一个任务做好几天。** `agentlink brief --since 3d` 让速览只看这三天；
想连时间线和 git log 一起看就 `--full`。`agentlink status` 会告诉你缓存摘要还新不新鲜。

**忘了昨天干了什么。** `agentlink show --since yesterday --role user` 列出当时的请求；
`agentlink show --session 4f2a` 完整看一个会话。

**两个人、三个工具、一个仓库。** `.agentlink/` 被 git 忽略，状态留在本地。
同事想看同样的交接，让他自己跑 `agentlink brief`：事实来自他本机的对话记录，
结论来自仓库里共同的历史。

## 命令

| 命令 | 作用 |
| --- | --- |
| `agentlink init [--hook]` | 建 `.agentlink/`、抽取已有会话，可选写入 `AGENTS.md` 提示段 |
| `agentlink sync` | 只抽取新记录（多数命令会隐式做这件事） |
| `agentlink brief` | 打印速览：`--full`、`--budget-tokens N`、`--since 3d`、`--out FILE`、`--copy`、`--stats`、`--no-ai`、`--no-git` |
| `agentlink digest` | 给 agent 做摘要的紧凑材料（`--full`、`--max-tokens`、`--out`） |
| `agentlink summary apply -f x.json` | 保存交接摘要（`show` 查看、`clear` 清除） |
| `agentlink note "..." --kind todo` | 写一条判断，三家都能看到（`note`/`decision`/`done`） |
| `agentlink status` | 数据源、数量、摘要新鲜度、缓存速览大小 |
| `agentlink show` | 原始记录：`--session ID`、`--role user`、`--since 3d`、`--limit N`、`--full` |
| `agentlink handoff --to claude` | 生成 `.agentlink/HANDOFF.md` 给指定工具 |
| `agentlink hook [--remove]` | 维护 `AGENTS.md` / `CLAUDE.md` 里的提示段 |
| `agentlink doctor` | 依赖、会话目录、技能安装状态自检 |
| `agentlink install [--path]` | （重新）把技能装进三个目录 |

通用参数：`--root DIR`、`--agent dsh,codex,claude`、`--lang en|zh`。

## 花多少 token

默认一份速览约 2–3k tokens，相当于一个短 README，也是切换工具时唯一进入上下文的东西。

| 档位 | 命令 | 大致 | 什么时候用 |
| --- | --- | --- | --- |
| L0 | `agentlink status` | 50 tokens | 先确认有没有东西可同步 |
| **L1** | `agentlink brief` | **~3k** | 默认：换工具、问进度 |
| L2 | `agentlink brief --full` | ~8k | 连时间线、决定和回放一起看 |
| L3 | `agentlink digest` → JSON → `summary apply` | 3–8k，**只花一次** | 长任务交接、跨天工作 |

L3 是"既省又准"的关键：

```mermaid
flowchart TD
    A["summary.json（上次写的）"] --> D["agentlink digest"]
    N["上次之后的新记录"] --> D
    D --> M["agent 写一份结构化摘要"]
    M --> S["agentlink summary apply"]
    S --> A
    A -.-> B["之后每次 brief 免费合并"]
    B -.-> B
```

`digest` 交出去的是「上一版摘要 + 之后新增的记录」，所以刷新只需要重读一小部分。
什么时候刷新？`brief --stats` 说它落后了，或者工作确实推进了 —— 不是每次切换都刷。

## 工作原理

```mermaid
flowchart LR
    A["~/.dsh/sessions/.../<br/>session.v4.jsonl.zstd"] --> P1["zstd 帧 → JSONL"]
    B["~/.codex/sessions/YYYY/MM/DD/<br/>rollout-*.jsonl"] --> P2["JSONL，字节游标"]
    C["~/.claude/projects/<br/>*.jsonl"] --> P3["JSONL，字节游标"]
    P1 --> N["归一化成 Event<br/>agent · session · role · text · ts"]
    P2 --> N
    P3 --> N
    N --> J[("journal.jsonl")]
    J --> R["规则：诉求 · 决定<br/>待办 · 文件 · 命令"]
    J --> T["时间线 + 会话卡片"]
    R --> B2["brief"]
    T --> B2
```

**怎么判断"属于这个项目"。** 会话里记录的 `cwd` 落在项目根目录内（含子目录）才算。
路径用 `realpath` 归一化，顺带解决 Windows 的 8.3 短路径 —— CI 上就踩过这个坑。

**增量读取。** Codex 和 Claude 的文件只追加，字节偏移加行号就够；
DSH 每一轮都会重写整个会话文件（压缩、多帧），所以那边用记录序号 `seq` 当游标。

**过滤噪声。** 运行时上下文、系统提醒、工具结果转储、UI 控制标签、reviewer 子线程都会丢掉；
解析器遇到不认识的记录类型就跳过，而不是报错。

**顺序。** 所有记录按时间合并，而不是按工具分块，所以「Codex → DSH → Claude」接力过的任务
读起来是一件事，不是三段。

## 项目状态目录

```
your-project/
├── .agentlink/              # 被 git 忽略，随时可删
│   ├── config.json          # agent 列表、token 预算、git 开关
│   ├── state.json           # 文件游标、会话标题、已见记录
│   ├── journal.jsonl        # 归一化记录（可重建）
│   ├── notes.jsonl          # `agentlink note` 写的内容
│   ├── context.md           # 上次生成的速览
│   ├── summary.json         # 缓存的交接摘要，三家共用
│   └── HANDOFF.md           # `agentlink handoff` 的产物
├── AGENTS.md                # 可选，`agentlink hook` 写入的提示段
└── CLAUDE.md                # 同上
```

删掉 `.agentlink/`，下次 `brief` 会从会话记录重建。不想把状态放在仓库里，
设置 `AGENTLINK_STATE_DIR`（项目在慢盘或只读挂载上时有用）。

## 怎么写一份交接摘要

`agentlink digest` 给出的材料大致是这样（已省略）：

```json
{
  "mode": "incremental",
  "previous_summary": { "project": {}, "state": {}, "sessions": [] },
  "new_events": [
    { "agent": "codex", "role": "user", "ts": "...", "text": "对账任务先别动" }
  ],
  "schema_hint": { "version": 1, "fields": ["project.goal", "state.in_progress[]", "..."] }
}
```

写成这样交回去：

```json
{
  "version": 1,
  "project": { "goal": "一句话目标", "status": "当前阶段", "stack": "技术栈" },
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

技能给撰写 agent 的纪律：只写材料能证实的；每条一行、60 字以内；写结论而不是抄原文；
拿不准的放进 `blocked` 或 `risks`。`summary apply` 是宽容的 —— 缺字段忽略，
字符串自动收成单元素列表，校验通过才会替换缓存。

## 出问题时

| 现象 | 原因与处理 |
| --- | --- |
| 找不到 `agentlink` | 安装脚本加的 PATH 只在新终端生效；或直接用技能目录里的启动器（`LOCAL.md` 里有绝对路径） |
| 某一家显示 `0 个会话` | 那个项目在该工具里的工作目录和记录不一致，用 `--root <当时的路径>` 跑一次 |
| 提示 `zstandard is not installed` | 只有 DSH 需要：`python -m pip install zstandard` |
| 速览是空的 | 记录比 `--since` 更早，或者属于别的路径；`agentlink status` 会说明找到了什么 |
| 摘要被标成"落后" | 新增记录超过阈值；重新走一次 L3，或者直接忽略 —— 规则层仍然是最新的 |

## 几个刻意的取舍

- **默认路径不调模型。** 每次切换都要跑的东西不能花钱：事实必须免费且即时，
  结论可以花一次钱换质量。
- **用 JSON 而不是自由文本。** 散文式摘要会漂移、会重复；固定结构才能稳定合并、
  对比和渲染，也容易校验。
- **状态放在项目里。** 上下文的单位是项目，状态就应该跟着项目走（靠备份，不靠 git），
  所以默认忽略。
- **按项目而不是全局。** 两个项目混在一起，会得到一份"技术上正确、实际上没用"的速览。

## 边界

- 规则层读的是文字，不是语义。没人写下来的决定可能漏掉 —— 这正是 `agentlink note` 的用处。
- 三家会话格式都是各自的内部实现。不认识的记录会跳过而不是崩溃，但上游真改了格式，
  可能暂时读不到新数据。
- 同一个仓库放在两个路径，会被当成两个项目。
- token 数是估算（显示宽度 ÷ 1.8），用来做预算足够，别拿它记账。

## 开发

```bash
python -m unittest discover -s tests -v     # 15 个离线测试，只用临时假数据
PYTHONPATH=src python -m agentlink doctor
```

CI 在 Ubuntu 和 Windows 上跑 Python 3.9 与 3.12。测试不碰真实会话：每个用例把合成数据
写进临时 home 目录，其中一条故意写成坏行，用来证明读取不会因此中断。

```
src/agentlink/
├── cli.py        命令行入口、参数处理
├── store.py      .agentlink 状态、游标、journal、notes
├── sources/
│   ├── base.py   共享的发现、增量读取、工具摘要
│   ├── dsh.py    zstd 多帧、seq 游标、噪声过滤
│   ├── codex.py  rollout JSONL、控制标签清理、会话标题
│   └── claude.py content 块、tool_use、跳过 sidechain
├── digest.py     速览生成：分节、预算、时间线、token 估算
├── summary.py    缓存摘要：格式、校验、渲染
├── activity.py   碰过的文件与命令
├── i18n.py       中英文案
├── gitinfo.py    git 快照
└── install.py    安装技能、生成启动器、写 AGENTS.md 提示段
```

想接第四家工具，只需要在 `sources/` 下加一个文件（`discover` 与 `ingest` 两个方法），
再在 `SOURCES` 里注册；速览生成那边不关心记录来自哪里。

MIT © Junwen Zhao
