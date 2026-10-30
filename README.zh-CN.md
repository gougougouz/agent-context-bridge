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

Codex 的五小时额度用完了，你打开 DSH 接着干，它问你想做什么。
于是你把项目又讲了一遍，把为什么选 CSV 又讲了一遍，然后回头找那个改到一半的文件。

三家工具各存各的对话，格式不一样，位置也不一样。`agentlink` 把三份记录都读出来，
只留当前项目的部分，合成一份速览 —— 你把它贴给现在正在用的那个 agent 就行。

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

## 安装

Windows，PowerShell 里一行：

```powershell
irm https://raw.githubusercontent.com/gougougouz/agent-context-bridge/main/install.ps1 | iex
```

macOS / Linux：

```bash
curl -fsSL https://raw.githubusercontent.com/gougougouz/agent-context-bridge/main/install.sh | bash
```

就这些。它会下载代码、缺依赖就装 `zstandard`、把 `SKILL.md` 放进
`~/.dsh/skills`、`~/.codex/skills`、`~/.claude/skills`，再往 PATH 里放一个 `agentlink`。
升级就是再跑一次。

不用 git，不用 clone，不用建虚拟环境。想放到指定的盘：

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/gougougouz/agent-context-bridge/main/install.ps1))) -Dir D:\app\agentlink
```

装完重启一下对应客户端，或者新开一个会话，让它认出这个技能。

## 用法

```bash
cd ~/code/你的项目
agentlink brief
```

第一次运行会建 `.agentlink/`，把已有的会话找出来，打印速览。之后在任何一家工具里，
新 agent 需要知道"现在做到哪了"，你就把这份贴过去 —— 不用改配置，不用记参数。

另外两个值得记的：

```bash
agentlink note "只做 CSV，xlsx 下个迭代" --kind decision   # 一句话，三家共享
agentlink brief --since 3d                                # 只看这三天
```

想让 agent 自己想起来，在项目里跑一次 `agentlink hook`：它往 `AGENTS.md` 和
`CLAUDE.md` 各放一句提示，新会话开场就会先读速览，而不是先问你。

## 花多少 token

默认一份速览大约 2k tokens，差不多一个短 README 的量，也是切换工具时唯一进入上下文的
东西 —— 绝大多数情况下这就是全部开销。

| | 命令 | 大致 | 什么时候 |
|---|---|---|---|
| L0 | `agentlink status` | 50 tokens | 先看看有没有东西可同步 |
| **L1** | `agentlink brief` | **~2k** | 默认：换工具、问进度 |
| L2 | `agentlink brief --full` | ~6k | 连回放和 git log 一起看 |
| L3 | `agentlink digest` → agent 写 JSON → `agentlink summary apply` | 3–8k，**只花一次** | 长任务交接、跨天工作 |

L3 是"既省又准"的关键：agent 读 `digest`（上一版摘要 + 之后新增的记录），写一份结构化
交接，`summary apply` 把它缓存进 `.agentlink/summary.json`；之后每次 `brief` 都免费合并，
三家共用。花一次，用到下次真有新进展为止。

除此之外不调任何模型。速览的其余部分是规则抽出来的：git 状态、最近的请求、
关键词抓的决定和待办、碰过的文件和命令。

## 命令

| | |
|---|---|
| `init` | 建 `.agentlink/`，列出发现了什么 |
| `sync` | 抽取新记录（通常自动发生） |
| `brief` | 打印速览：`--full`、`--budget-tokens N`、`--since 3d`、`--stats`、`--no-ai`、`--out FILE` |
| `digest` | 给 agent 做摘要的紧凑材料（`--full`、`--max-tokens`） |
| `summary` | `apply -f x.json` / `show` / `clear` |
| `note` | 写一条决定或待办，三家共享 |
| `status` | 数据源、数量、摘要新不新鲜 |
| `show` | 原始记录：`--session`、`--role`、`--since`、`--limit` |
| `handoff` | 生成 `.agentlink/HANDOFF.md` |
| `hook` | 往 `AGENTS.md` / `CLAUDE.md` 埋提示段 |
| `doctor` | 检查依赖、会话目录、安装状态 |

`--lang en|zh` 切输出语言，默认跟随系统。

## 数据从哪来

```text
~/.dsh/sessions/<路径>/session-*/session.v4.jsonl.zstd    zstd 压缩的 JSONL
~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl              追加写 JSONL
~/.claude/projects/<路径>/*.jsonl                         追加写 JSONL
        │
        ├─ 会话里记的 cwd 落在本项目内，才算这个项目的
        ├─ 增量：字节偏移；DSH 用记录序号 seq
        └─ .agentlink/journal.jsonl  →  digest  →  context.md（+ summary.json）
```

`.agentlink/` 默认被 git 忽略，删掉也不心疼：下次 `brief` 会从会话记录重建。
不想把状态放在仓库里，设置 `AGENTLINK_STATE_DIR` 即可。

## 说清楚边界

- 规则层读的是文字，不是语义。没人写下来的决定，它可能漏 —— 所以留了 `agentlink note`。
- 三家会话格式都是各自的内部实现。遇到不认识的记录会跳过而不是报错，
  但上游真改了格式，可能暂时读不到新数据。
- 同一个项目放在两个路径，会被当成两个项目。搬过家就用 `--root <原路径>` 跑一次。
- Codex 和 Claude 不装 `zstandard` 也能读；DSH 的会话是压缩的，需要它。

## 开发

```bash
python -m unittest discover -s tests -v     # 15 个离线测试，只用临时假数据
PYTHONPATH=src python -m agentlink doctor
```

```
src/agentlink/
├── cli.py        命令行入口
├── store.py      .agentlink 状态、游标、journal
├── sources/      dsh.py · codex.py · claude.py
├── digest.py     速览生成、分段预算、token 估算
├── summary.py    缓存的交接摘要：格式、校验、渲染
├── activity.py   碰过的文件与命令
├── i18n.py       中英文案
├── gitinfo.py    git 快照
└── install.py    安装技能、写 AGENTS.md 提示段
```

MIT © Junwen Zhao