# Handoff summary format

The brief has two layers. The cheap one is extracted from transcripts by rules and is always
current. The expensive one is written by an agent, stored in `.agentlink/summary.json`, and
merged into every later brief — in all three tools — without paying for it again.

This file documents that second layer: what an agent receives, what it should write back, and
how the result is validated.

## What the agent receives

`agentlink digest` prints a JSON document:

```json
{
  "mode": "incremental",
  "previous_summary": { "project": {}, "state": {}, "sessions": [] },
  "new_events": [
    { "agent": "codex", "role": "user", "ts": "2026-10-30T09:12:00+08:00",
      "text": "对账任务先别动，先把幂等跑通" }
  ],
  "schema_hint": { "version": 1, "fields": ["project.goal", "state.in_progress[]", "..."] }
}
```

- `mode` is `full` on the first run and `incremental` afterwards. In incremental mode
  `previous_summary` holds the last accepted summary and `new_events` only carries records
  added since it was written, so a refresh costs a fraction of a re-read.
- The payload is trimmed to `--max-tokens` (default 6000) from the least important end:
  old asks go first, then session details, then older new events, then notes.
- `agentlink digest --full` ignores the previous summary and sends the whole window.

## What the agent writes back

```json
{
  "version": 1,
  "generated_at": "2026-10-30T22:31:00+08:00",
  "project": {
    "goal": "one sentence",
    "status": "where it stands right now",
    "stack": "languages, frameworks, runtimes"
  },
  "state": {
    "done": ["finished things"],
    "in_progress": ["actively being worked on"],
    "blocked": ["waiting on someone or something"],
    "decisions": ["chosen, with the reason if short"],
    "next": ["the next concrete step"],
    "risks": ["might bite later"]
  },
  "sessions": [
    { "agent": "codex", "id": "session id", "title": "short title",
      "one_line": "what this session was for",
      "outcome": "what came out of it",
      "open": ["what was left"] }
  ],
  "notes_for_next_agent": ["things the next agent must not learn the hard way"]
}
```

Only `version` is required. Everything else is optional and missing pieces are simply absent
from the brief.

## Rules the skill gives the writing agent

1. Only claim what the material supports. No invented progress, no guessed file names.
2. One line per item, under 60 characters. It is a brief, not minutes.
3. Write conclusions, not transcripts. "Picked CSV, xlsx next iteration" beats a quote.
4. Anything uncertain goes into `blocked` or `risks` rather than being smoothed over.
5. Reuse the previous summary where it is still true; rewrite only what changed.

## Validation

`agentlink summary apply -f summary.json` (or `... | agentlink summary apply`):

- rejects malformed JSON with the parser's message;
- normalises shapes: a bare string becomes a one-item list, `sessions` given as an object
  becomes a one-item list, unknown keys are dropped;
- refuses a document with no usable content (no `project.goal`, no `state`, no `sessions`)
  rather than overwriting a good summary with an empty one;
- prints the resulting coverage window and how many records have arrived since, so the agent
  knows whether a refresh is still worthwhile.

`agentlink summary show` prints the cached summary; `agentlink summary clear` deletes it.
`agentlink status` reports its age and how many records have accumulated since.