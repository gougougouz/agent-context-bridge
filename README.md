<div align="center">

# agentlink

**Switch agents. Keep the plot.**

DSH · Codex (ChatGPT) · Claude Code

[![tests](https://github.com/gougougouz/agent-context-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/gougougouz/agent-context-bridge/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.9%2B-3776ab?logo=python&logoColor=white)](https://www.python.org/)
[![license](https://img.shields.io/badge/license-MIT-2ea44f)](LICENSE)

[English](README.md) · [简体中文](README.zh-CN.md)

</div>

---

You burn through Codex's five-hour window, open DSH to keep going, and it asks what
you're working on. You explain the project again. Then you explain why you chose CSV
over XLSX. Then you go looking for the file you were halfway through editing.

Each tool keeps its own transcript, in its own format, in its own folder. `agentlink`
reads all three from disk, keeps what belongs to the current project, and prints one
brief you can paste into whichever agent you're talking to now.

```console
$ agentlink brief

# Project context · payments-service
> 4 sessions / 812 records (DSH, Codex, Claude; 2 days ago → 12 min ago)

## 1. Handoff summary (written by an agent)
- Goal: move settlement off cron batches onto event-driven consumers
- Status: core path migrated, rollback switch not built yet
- In progress: idempotency key write path. Next: reconciliation job, rollback flag

## 2. Current asks (newest first)
- 12 min ago (Codex): don't touch reconciliation yet, get idempotency passing first

## 3. Session cards
### Codex · idempotency keys (last active 12 min ago)
- Ask: composite key or uuid?
- Last conclusion: business_id+date, Redis lock on conflict
- Files: src/ledger/idempotency.py, migrations/007_idem.sql
- Commands: pytest tests/test_idempotency.py
```

## Install

Windows, PowerShell:

```powershell
irm https://raw.githubusercontent.com/gougougouz/agent-context-bridge/main/install.ps1 | iex
```

macOS / Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/gougougouz/agent-context-bridge/main/install.sh | bash
```

That's the whole thing. It downloads the code, installs `zstandard` if it's missing,
drops `SKILL.md` into `~/.dsh/skills`, `~/.codex/skills` and `~/.claude/skills`, and
puts an `agentlink` launcher on your PATH. Re-run it to upgrade.

No git, no clone, no virtualenv. If you'd rather keep the files somewhere specific:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/gougougouz/agent-context-bridge/main/install.ps1))) -Dir D:\app\agentlink
```

Restart the tools afterwards, or open a new session, so they notice the skill.

## Use

```bash
cd ~/code/your-project
agentlink brief
```

First run creates `.agentlink/`, finds existing sessions for this project, and prints
the brief. From then on, in any of the three tools, this is what you paste when a new
agent needs to know where things stand. That's the whole workflow — no config file to
edit, no flags required.

Two commands worth remembering on top of it:

```bash
agentlink note "CSV only, xlsx next iteration" --kind decision   # shared by all three
agentlink brief --since 3d                                       # just this week
```

When you want the agents to remember this on their own, run `agentlink hook` once in the
project: it drops a short pointer into `AGENTS.md` and `CLAUDE.md`, so a fresh session
opens by reading the brief instead of asking you what you're doing.

## What it costs

A default brief is about 2k tokens — roughly the size of a short README — and it is the
only thing that enters a context window. Usually that's the whole cost of switching.

| | Command | Roughly | When |
|---|---|---|---|
| L0 | `agentlink status` | 50 tokens | is there anything here? |
| **L1** | `agentlink brief` | **~2k** | default; switching tools, "where were we" |
| L2 | `agentlink brief --full` | ~6k | you want the replay and the git log too |
| L3 | `agentlink digest` → agent writes JSON → `agentlink summary apply` | 3–8k, **once** | long handoff, multi-day work |

L3 is the part that keeps things cheap without cutting corners. An agent reads `digest`
(your previous summary plus only the records added since), writes a structured handoff,
and `summary apply` caches it in `.agentlink/summary.json`. Every later `brief` merges it
for free, in all three tools. Pay once, reuse everywhere — and refresh only when there's
something new to say.

Nothing else calls a model. The rest of the brief is rules: git state, recent asks,
keyword-extracted decisions and TODOs, files and commands touched.

## Commands

| | |
|---|---|
| `init` | create `.agentlink/`, list what it found |
| `sync` | pull new records (usually implicit) |
| `brief` | print the brief — `--full`, `--budget-tokens N`, `--since 3d`, `--stats`, `--no-ai`, `--out FILE` |
| `digest` | compact material for an agent to summarize (`--full`, `--max-tokens`) |
| `summary` | `apply -f x.json` / `show` / `clear` |
| `note` | write a decision or TODO, shared across agents |
| `status` | sources, counts, summary freshness |
| `show` | raw records: `--session`, `--role`, `--since`, `--limit` |
| `handoff` | write `.agentlink/HANDOFF.md` for one tool |
| `hook` | put a pointer in `AGENTS.md` / `CLAUDE.md` |
| `doctor` | check dependencies, transcript dirs, installs |

`--lang en|zh` switches the output language; by default it follows your system locale.

## Where the data comes from

```text
~/.dsh/sessions/<path>/session-*/session.v4.jsonl.zstd    zstd-compressed JSONL
~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl              plain JSONL, append-only
~/.claude/projects/<path>/*.jsonl                         plain JSONL, append-only
        │
        ├─ a session belongs to this project if its recorded cwd is inside it
        ├─ incremental: byte offsets, or the record seq for DSH
        └─ .agentlink/journal.jsonl  →  digest  →  context.md (+ summary.json)
```

`.agentlink/` is git-ignored and disposable: delete it and the next `brief` rebuilds
everything from the transcripts. Point `AGENTLINK_STATE_DIR` elsewhere if you don't want
state inside the repo.

## Honest limits

- The rules layer reads text, not meaning. A decision nobody wrote down can slip through —
  that's what `agentlink note` is for.
- Transcript formats are each vendor's private business. Unknown record types are skipped
  rather than fatal, but a big change upstream may hide data until the parser is updated.
- The same project at two paths counts as two projects. Run once with `--root <old path>`
  if you moved it.
- Codex and Claude read fine without `zstandard`; DSH sessions are compressed and need it.

## Development

```bash
python -m unittest discover -s tests -v     # 15 offline tests, temp fixtures only
PYTHONPATH=src python -m agentlink doctor
```

```
src/agentlink/
├── cli.py        entry point and commands
├── store.py      .agentlink state, cursors, journal
├── sources/      dsh.py · codex.py · claude.py
├── digest.py     brief builder, section budgets, token estimate
├── summary.py    the cached handoff: schema, validation, rendering
├── activity.py   files and commands touched
├── i18n.py       zh / en strings
├── gitinfo.py    git snapshot
└── install.py    skill installation, AGENTS.md pointer
```

MIT © Junwen Zhao