# agent-context-bridge

**Sync project context and progress across DSH, Codex (ChatGPT) and Claude Code.**

[![Tests](https://github.com/gougougouz/agent-context-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/gougougouz/agent-context-bridge/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](#)
[![Agent skill](https://img.shields.io/badge/agent%20skill-DSH%20%7C%20Codex%20%7C%20Claude-8b5cf6.svg)](#-install)

English · [简体中文](README.zh-CN.md)

---

You hit the five-hour limit in Codex, switch to DSH — and the new agent knows nothing:
the plan you settled on, the file you were halfway through, the reason you picked CSV over XLSX.
Every agent keeps its own transcript in its own directory.

`agentlink` reads all three transcripts locally, scopes them to the current project,
and produces one compact brief you can drop straight into any agent's context.

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

## ✨ Why

- **One project, three agents** — DSH, Codex and Claude Code write incompatible formats in
  incompatible places; you shouldn't have to re-explain your project after every switch.
- **Token-frugal by default** — a brief costs ~2k tokens, and the expensive AI summary is
  **cached across agents**. Pay once, reuse everywhere.
- **Two layers** — deterministic facts (git state, tasks, timeline, files touched) always;
  a structured handoff written by an agent when it's actually worth the tokens.
- **Local only** — reads transcript files, never uploads anything, no API keys needed.
- **Incremental** — byte offsets for Codex/Claude, record sequence for DSH; the second sync
  reads only what appeared since the last one.

## 📦 Install

Requires Python 3.9+. `zstandard` is only needed to read DSH transcripts.

```powershell
# 1) dependency
python -m pip install zstandard

# 2) install the skill into all three skill directories
git clone https://github.com/gougougouz/agent-context-bridge.git
cd agent-context-bridge
python -m agentlink install          # add --path to also expose `agentlink` on PATH
```

Or run the one-shot installer: `pwsh -ExecutionPolicy Bypass -File install.ps1`.

`agentlink install` copies `SKILL.md` into:

| Agent | Skills directory |
| --- | --- |
| DSH | `%USERPROFILE%\.dsh\skills\agent-context-bridge\` |
| Codex / ChatGPT | `%USERPROFILE%\.codex\skills\agent-context-bridge\` |
| Claude Code | `%USERPROFILE%\.claude\skills\agent-context-bridge\` |

Each copy gets a launcher and a `LOCAL.md` with absolute paths, so it works even when
`agentlink` is not on `PATH`. Restart the client (or open a new session) afterwards.

## 🚀 Quick start

```powershell
cd F:\path\to\your-project
agentlink init          # create .agentlink/, discover existing sessions
agentlink brief         # ~2k tokens: the thing you paste into an agent
```

From that point on, in **any** of the three tools:

```powershell
agentlink brief --stats          # what to give the agent (+ token count, summary freshness)
agentlink note "只做 CSV，xlsx 下个迭代" --kind decision
agentlink hook                   # optional: write a pointer into AGENTS.md / CLAUDE.md
```

## 🪙 Token economy

The skill is designed so a normal invocation stays cheap, and expensive work is reused.

| Tier | Command | Cost | When |
| --- | --- | --- | --- |
| L0 | `agentlink status` | ~50 tokens | is there anything to sync at all? |
| **L1** | `agentlink brief` | ~2k tokens | default: switching tools, "where were we?" |
| L2 | `agentlink brief --full` | ~6k tokens | the user wants detail |
| L3 | `agentlink digest` → agent writes JSON → `agentlink summary apply` | 3–8k **once**, then cached | long handoffs, cross-day work |

How the cache works: the AI summary lives in `.agentlink/summary.json` and is merged into
every later brief for free. `digest` is incremental — it hands over the previous summary
plus only the records that arrived afterwards, so refreshing costs a fraction of a re-read.

Typical steady state: **one L3 pass per milestone, L1 on every switch.**

## 🧰 Commands

| Command | Description |
| --- | --- |
| `agentlink init` | Create `.agentlink/` and list discovered sessions |
| `agentlink sync` | Pull new records; refresh the rules-based brief |
| `agentlink brief` | Print the brief (default 2200 tokens) |
| `agentlink brief --full` / `--budget-tokens N` | Bigger / custom budget |
| `agentlink brief --stats` | Append token count and AI-summary freshness |
| `agentlink digest [--full] [--max-tokens N]` | Compact material for an agent to summarize |
| `agentlink summary apply -f x.json` / `show` / `clear` | Store / inspect / drop the AI summary |
| `agentlink note "..." --kind note\|todo\|decision\|done` | Write a shared judgement |
| `agentlink status` | Data sources, sessions, staleness, cached brief size |
| `agentlink show [--session ID] [--role user]` | Inspect raw records |
| `agentlink handoff --to claude` | Write `.agentlink/HANDOFF.md` |
| `agentlink hook [--remove]` | Maintain the `AGENTS.md` / `CLAUDE.md` pointer |
| `agentlink install [--path]` | Install into the three skill directories |
| `agentlink doctor` | Self-check dependencies, directories, installs |

Global flags: `--root <dir>`, `--agent dsh,codex,claude`, `--max-events N`.

## 🔍 How it works

```text
~/.dsh/sessions/<--munge-->/session-*/session.v4.jsonl.zstd   zstd-compressed JSONL
~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl                  append-only JSONL
~/.claude/projects/<munge>/*.jsonl                            append-only JSONL
        │
        ├─ claim a project by the session's cwd (subdirectories included)
        ├─ incremental cursors: byte offset, or record `seq` for DSH
        ├─ normalize → Event(agent, session, role, text, ts, kind)
        └─ .agentlink/journal.jsonl → digest → context.md (+ optional summary.json)
```

Deliberate choices:

- **No model calls in the default path.** Facts come from rules: recent asks, keyword
  extraction for decisions/todos, git snapshot, files and commands touched.
- **AI is an explicit, cached layer.** The running agent writes the handoff once; the other
  two read it for free. Nothing is sent to any API by this tool.
- **Reading is a pure function of the transcripts** — delete `.agentlink/` and it rebuilds.

### Project state

```
<project>/.agentlink/
├── config.json      # agents, token budgets, git toggle
├── state.json       # per-file cursors, session titles, seen records
├── journal.jsonl    # normalized events (rebuildable)
├── notes.jsonl      # shared judgements from `agentlink note`
├── summary.json     # cached AI handoff (shared by all three agents)
├── context.md       # last generated brief
└── HANDOFF.md       # `agentlink handoff` output
```

`.agentlink/.gitignore` keeps all of it out of your repository.

## 🧠 AI summary schema

`summary apply` is tolerant — missing fields are ignored, strings are coerced to lists.

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

Rules the skill gives the writing agent: only claims supported by the material, one line per
item, ≤ 60 characters, and conclusions rather than transcripts.

## 🔒 Privacy

- Reads local transcript files only; no network calls except `pip install`.
- `.agentlink/` is git-ignored by default — summaries never get committed by accident.
- Want the state somewhere else? Set `AGENTLINK_STATE_DIR`.
- Deleting `.agentlink/` removes every trace; nothing is stored outside the project.

## ❓ FAQ

**`agentlink` is not on PATH.**
Read `LOCAL.md` inside the installed skill folder — it has absolute paths for this machine.
`agentlink install --path` adds the launcher directory to your user PATH.

**A tool shows "0 sessions".**
That project's working directory differs from the one recorded in its transcripts (opened a
subdirectory, or the project moved). Run once with `--root <old path>`.

**`zstandard is not installed`.**
Only DSH needs it: `python -m pip install zstandard`. Codex and Claude work without it.

**The brief is too long / too short.**
`agentlink brief --budget-tokens 900` or `--full`. Facts always beat summaries on conflict:
trust `git log` and the files over the brief.

**Will it mix in other projects?**
No — a session is claimed only when its recorded `cwd` is inside the current project.

## 🛠 Development

```bash
python -m unittest discover -s tests -v     # 11 offline tests, temp fixtures only
PYTHONPATH=src python -m agentlink doctor
```

```
src/agentlink/
├── cli.py         # command line entry point
├── store.py       # .agentlink state, cursors, journal, notes
├── sources/       # dsh.py / codex.py / claude.py parsers
├── digest.py      # brief builder (sections, budgets, token estimate)
├── summary.py     # AI handoff schema, validation, rendering
├── activity.py    # files/commands touched
├── gitinfo.py     # git snapshot
└── install.py     # skill installation + AGENTS.md pointer
```

## ⚠️ Known limits

- Transcript formats are each vendor's internal business — the parsers skip unknown record
  types instead of failing, but a breaking change may hide data until updated.
- The rules-based layer is text-level, not semantic; write a `note` for anything subtle.
- Two copies of the same project at different paths are treated as two projects.

## License

MIT © Junwen Zhao
