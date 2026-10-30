# How agentlink works

Everything here is read-only with respect to the three clients. The only writes are inside the
project's `.agentlink/` directory (and `AGENTS.md` / `CLAUDE.md` when you ask for the pointer).

## Where the transcripts live

| Tool | Location | Format | Cursor |
| --- | --- | --- | --- |
| DSH | `~/.dsh/sessions/<munged project>/session-*/session.v4.jsonl.zstd` | zstd, one JSON record per line, several frames | record `seq` (the file is rewritten each turn) |
| Codex (ChatGPT) | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | JSONL, append-only | byte offset + line index |
| Claude Code | `~/.claude/projects/<munged project>/*.jsonl` | JSONL, append-only | byte offset + line index |

`$DSH_HOME`, `$CODEX_HOME` and `$CLAUDE_CONFIG_DIR` are honoured when set.

## How a session is claimed by a project

A session belongs to the project when the `cwd` it recorded is inside the project root,
subdirectories included. Paths are normalised with `realpath`, which also resolves Windows 8.3
short names (`RUNNER~1`) — CI caught that one.

If a project is moved or renamed, add the old absolute path to `roots` in
`.agentlink/config.json`; sessions recorded under any listed root count as this project.

## Incremental reads

Codex and Claude files only grow, so the reader remembers a byte offset and a line index and
reads from there. A file that shrank (rotated, replaced) resets to zero.

DSH rewrites its session file on every turn, compressed in multiple frames, so a byte offset is
useless. The reader decompresses the stream, parses records, and remembers the highest `seq`
already ingested.

Reads are tolerant on purpose: a line that is not JSON is skipped, a line larger than 8 MB is
skipped, and an unreadable file produces a warning in `--debug` output rather than an exception.

## Noise filtering

Runtime context blocks, system reminders, tool-result dumps, UI control tags and reviewer
sub-threads are dropped. What remains is normalised into a record with `agent`, `session`,
`role`, `text`, `ts` and `seq`, appended to `.agentlink/journal.jsonl`.

Because everything is merged by timestamp rather than by tool, a task that bounced
Codex → DSH → Claude reads as one story instead of three unrelated logs.

## What the rules layer extracts

- **Current asks** — the last few user messages, verbatim but truncated.
- **Decisions** — lines matching decision language in either Chinese or English.
- **TODOs** — the same for pending work, plus anything added with `agentlink note`.
- **Session cards** — per session: first ask, last conclusion, files touched, commands run.
- **Timeline** — the last N events across tools, labelled by agent.
- **Snapshot** — git branch, last commits, dirty files (skippable with `--no-git`).

Extraction is regex-based and bilingual. It reads text, not meaning: a decision nobody wrote
down cannot be found. That is what `agentlink note` is for.

## Token math

`estimate_tokens(text) = display_width / 1.8`, where CJK characters count as width 2 and
everything else as 1. It is an estimate for budgeting, not a billing figure.

Budgets are enforced by dropping whole sections in priority order rather than truncating
mid-sentence: AI summary and current asks go last, git snapshot and replay go first. A brief
that was cut says so in its footer.

## State layout

```
.agentlink/
├── config.json      agents, extra roots, budgets, git toggle
├── state.json       cursors, session titles, seen record keys
├── journal.jsonl    normalised events (rebuildable)
├── notes.jsonl      entries from `agentlink note`
├── context.md       last brief
├── summary.json     cached handoff
└── HANDOFF.md       output of `agentlink handoff`
```

Delete the directory and the next `brief` rebuilds it from transcripts. `AGENTLINK_STATE_DIR`
moves it elsewhere, for projects on slow or read-only mounts.

## Design choices

**Facts free, meaning cached.** A step you run on every switch cannot cost money. Extraction is
deterministic and instant; an agent-written summary is paid for once and merged thereafter.

**A schema instead of prose.** Prose summaries drift, duplicate and contradict each other. A
fixed schema merges, diffs and renders predictably, and is cheap to validate.

**State inside the project.** The unit of context is the project, so the state travels with it
through backups. It is git-ignored by default, and per-project state keeps two interleaved
projects from producing a brief that is technically true and practically useless.

**Read-only on transcripts.** Nothing under `~/.dsh`, `~/.codex` or `~/.claude` is modified, so
removing this tool cannot damage the clients' own history.

## Adding a fourth agent

Create `src/agentlink/sources/<name>.py` with a `Source` subclass implementing:

```python
name = "newtool"
label = "New Tool"

def root_dir(self) -> Path: ...          # where transcripts live
def discover(self, project_root: str) -> list[Session]: ...
def ingest(self, session: Session, store: Store) -> list[Event]: ...
```

Register it in `SOURCES` and `AGENTS` in `sources/__init__.py`, add a label in
`digest.AGENT_LABELS`, and the brief builder will pick it up without further changes. The base
class provides `read_new_lines` (offset + line index) and `finalize` (cursor bookkeeping) for
append-only formats.