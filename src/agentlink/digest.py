"""Turn the journal into a compact, agent-readable project brief (context.md).

Two layers:
  * rules   — always available, deterministic, free (this module)
  * AI      — optional structured handoff written by the running agent
              (`summary.py`), merged in when present.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from . import summary as summary_mod
from .activity import extract_activity, short_path
from .gitinfo import snapshot
from .i18n import t
from .model import AGENT_LABELS, Event
from .store import Store
from .util import iso_to_dt, now_iso, read_json, rel_time, truncate_width, width

DECISION_HINT = re.compile(
    r"(决定|结论|约定|决策|已确认|方案定|采用|不要再|必须|禁止|注意[:：]|decided|decision|we'll use|going with|must not|never do|keep in mind)",
)
TODO_HINT = re.compile(
    r"(待办|TODO|todo|未完成|下一步|待实现|还未|尚需|还需要|接着做|剩[下余]|next step|remaining|still need|not yet|left to)",
)
REQUEST_HINT = re.compile(
    r"(要求|需求|目标|请实现|需要实现|任务[:：]|功能[:：]|please implement|need to implement|requirement|task[:：]|feature[:：])",
)
ITEM_LINE = re.compile(r"^\s*(?:\d+[.、)）]|[-*+])\s*(\S.{3,})")
TODO_LINE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s*\[?\s?\]?\s*(.+)$")

SECTION_LIMITS = {
    "sessions": 6,
    "messages_per_session": 6,
    "timeline": 14,
    "todos": 10,
    "decisions": 10,
    "dirty": 8,
}

# 1 token ≈ 1.8 display columns for mixed Chinese/English text
CHARS_PER_TOKEN = 1.8


def tokens_to_width(tokens: int) -> int:
    return int(tokens * CHARS_PER_TOKEN)


class SessionView:
    def __init__(self, agent: str, session: str, events: list[Event], title: str = "",
                 root: str | Path | None = None):
        self.agent = agent
        self.session = session
        self.events = events
        self.title = title
        self.root = root
        self.last_ts = events[-1].ts if events else ""
        self._activity: dict | None = None

    # ------------------------------------------------------------------ info

    @property
    def short_id(self) -> str:
        sid = self.session
        if sid.startswith("session-"):
            sid = sid[len("session-"):]
        return sid[:8]

    @property
    def label(self) -> str:
        name = AGENT_LABELS.get(self.agent, self.agent)
        if self.title:
            return f"{name} · {truncate_width(self.title, 28)}"
        return f"{name} · {self.short_id}"

    @property
    def activity(self) -> dict:
        if self._activity is None:
            self._activity = extract_activity(self.events)
        return self._activity

    def user_events(self) -> list[Event]:
        return [e for e in self.events if e.role == "user"]

    def assistant_events(self) -> list[Event]:
        return [e for e in self.events if e.role == "assistant"]

    def topic(self) -> str:
        for ev in self.user_events():
            text = ev.text.strip()
            if not text:
                continue
            first = text.splitlines()[0]
            if first.startswith(("# Files mentioned", "# Files pasted", "Distinguish instructions")):
                for line in text.splitlines()[1:]:
                    if line.strip() and not line.startswith("#"):
                        first = line.strip()
                        break
                else:
                    continue
            return truncate_width(first, 70)
        return t("empty.no_messages")

    def files(self, limit: int = 5) -> list[str]:
        return [short_path(f["path"], self.root) for f in self.activity["files"][:limit]]

    def commands(self, limit: int = 3) -> list[str]:
        return self.activity["commands"][-limit:]

    # --------------------------------------------------------------- renders

    def render_card(self, per_session: int = 6) -> list[str]:
        """One compact block: asks, outcomes, touched files, commands."""
        heading = f"### {self.label}"
        if not self.title:
            heading += f" — {self.topic()}"
        lines = [t("card.heading", head=heading, t=rel_time(self.last_ts))]
        users = self.user_events()
        assistants = self.assistant_events()

        asks = []
        for ev in users[:2]:
            asks.append(truncate_width(ev.text.replace("\n", " "), 150))
        if len(users) > 2:
            asks.append(truncate_width(users[-1].text.replace("\n", " "), 150))
        if asks:
            lines.append(f"- **{t('card.ask')}**: " + t("sep.semi").join(asks))

        if assistants:
            last = truncate_width(assistants[-1].text.replace("\n", " "), 240)
            lines.append(f"- **{t('card.conclusion')}**: {last}")

        files = self.files()
        if files:
            lines.append(f"- **{t('card.files')}**: " + t("sep.list").join(f"`{f}`" for f in files))

        cmds = self.commands()
        if cmds:
            lines.append(f"- **{t('card.commands')}**: " + t("sep.semi").join(f"`{c}`" for c in cmds))

        if not asks and not assistants:
            lines.append(f"- {t('card.nochat')}")
        return lines

    def render_replay(self, per_session: int = 6) -> list[str]:
        picked: list[Event] = []
        users = self.user_events()
        assistants = self.assistant_events()
        if users:
            picked.append(users[0])
        for ev in users[-2:] + assistants[-2:]:
            if ev not in picked:
                picked.append(ev)
        picked.sort(key=lambda e: e.ts or "")
        picked = picked[-per_session:]
        lines = []
        last_text = ""
        for ev in picked:
            if ev.text.strip() == last_text:
                continue
            last_text = ev.text.strip()
            who = t("role.user") if ev.role == "user" else t("role.assistant")
            lines.append(f"- **{who}**（{rel_time(ev.ts)}）：{truncate_width(ev.text.replace(chr(10), ' '), 220)}")
        return lines

    def digest_card(self) -> dict:
        """Machine-ish card handed to an agent for summarization."""
        return {
            "agent": self.agent,
            "id": self.session,
            "title": self.title,
            "last_active": self.last_ts,
            "messages": len(self.events),
            "user_asks": [truncate_width(e.text.replace("\n", " "), 300) for e in self.user_events()[-4:]],
            "last_answer": (truncate_width(self.assistant_events()[-1].text.replace("\n", " "), 600)
                            if self.assistant_events() else ""),
            "files": self.files(8),
            "commands": self.commands(6),
        }


def group_sessions(events: list[Event], titles: dict[str, str] | None = None,
                   root: str | Path | None = None) -> list[SessionView]:
    titles = titles or {}
    buckets: "OrderedDict[tuple[str, str], list[Event]]" = OrderedDict()
    for ev in sorted(events, key=lambda e: e.ts or ""):
        buckets.setdefault((ev.agent, ev.session), []).append(ev)
    views = [
        SessionView(a, s, evs, titles.get(f"{a}:{s}", ""), root)
        for (a, s), evs in buckets.items()
    ]
    views.sort(key=lambda v: v.last_ts or "", reverse=True)
    return views


def _titles_from_store(store: Store) -> dict[str, str]:
    out = {}
    for key, meta in (store.state.get("sessions") or {}).items():
        title = (meta or {}).get("title")
        if title:
            out[key] = str(title)
    return out


# ----------------------------------------------------------------- extraction


def _scan(events: list[Event], pattern: re.Pattern, limit: int, allow_bullets: bool = True) -> list[str]:
    hits: list[str] = []
    seen: set[str] = set()
    for ev in reversed(events):
        if ev.role == "tool":
            continue
        for raw in ev.text.splitlines():
            line = raw.strip()
            if not line or len(line) < 4:
                continue
            if TODO_LINE.match(line) and not allow_bullets:
                continue
            if pattern.search(line):
                cleaned = re.sub(r"^[-*+\d.\s]+", "", line)
                if cleaned in seen:
                    continue
                seen.add(cleaned)
                hits.append(truncate_width(cleaned, 220))
                if len(hits) >= limit:
                    return hits
    return hits


def _todo_from_requests(events: list[Event], limit: int = 8) -> list[str]:
    out: list[str] = []
    for ev in reversed(events):
        if ev.role != "user" or not REQUEST_HINT.search(ev.text):
            continue
        for line in ev.text.splitlines():
            match = ITEM_LINE.match(line)
            if not match:
                continue
            item = match.group(1).strip()
            if len(item) < 4:
                continue
            out.append(truncate_width(item, 180))
            if len(out) >= limit:
                return out
    return out


def _notes(store: Store, kind: str, limit: int = 10) -> list[str]:
    out: list[str] = []
    for rec in reversed(store.notes()):
        if rec.get("kind") != kind:
            continue
        out.append(truncate_width(str(rec.get("text") or ""), 220))
        if len(out) >= limit:
            break
    return out


def _dedupe(items: list[str]) -> list[str]:
    out, seen = [], set()
    for item in items:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _current_tasks(events: list[Event], limit: int = 3) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for ev in reversed(events):
        if ev.role != "user":
            continue
        text = ev.text.replace("\n", " ").strip()
        if len(text) < 3 or text in seen:
            continue
        seen.add(text)
        lines.append(f"- **{rel_time(ev.ts)}**（{AGENT_LABELS.get(ev.agent, ev.agent)}）："
                     f"{truncate_width(text, 280)}")
        if len(lines) >= limit:
            break
    return lines


def _timeline(events: list[Event], limit: int = 14) -> list[str]:
    talk = [e for e in events if e.role in ("user", "assistant") and e.text.strip()]
    lines = []
    for ev in talk[-limit:]:
        when = iso_to_dt(ev.ts)
        stamp = when.strftime("%m-%d %H:%M") if when else "??"
        who = "用户" if ev.role == "user" else "助手"
        agent = AGENT_LABELS.get(ev.agent, ev.agent).split(" / ")[0]
        lines.append(f"- `{stamp}` [{agent}] {who}：{truncate_width(ev.text.replace(chr(10), ' '), 150)}")
    return lines


# ------------------------------------------------------------------- sections


class Block:
    __slots__ = ("priority", "title", "lines")

    def __init__(self, priority: int, title: str, lines: list[str]):
        self.priority = priority
        self.title = title
        self.lines = lines


def _snapshot_block(store: Store) -> Block:
    info = snapshot(store.root, log_limit=store.config["git"].get("log_limit", 8))
    lines = [f"- {t('snap.root')}: `{store.root}`"]
    if info.get("is_repo"):
        lines.append(f"- Git：`{info.get('branch') or '?'}` @ `{info.get('head') or '?'}`")
        if info.get("commits"):
            lines.append(f"- {t('snap.commits')}:")
            for c in info["commits"][:4]:
                lines.append(f"  - `{c['hash']}` {c['date']} {truncate_width(c['subject'], 90)}")
        dirty = info.get("dirty") or []
        if dirty:
            shown = "、".join(f"`{d[3:] if len(d) > 3 else d}`" for d in dirty[: SECTION_LIMITS["dirty"]])
            lines.append(f"- {t('snap.dirty', n=len(dirty))}: {shown}")
        else:
            lines.append(f"- {t('snap.clean')}")
    else:
        lines.append(f"- {t('snap.nogit')}")
    return Block(3, t("sec.snapshot"), lines)


def _delta_block(store: Store, events: list[Event]) -> Block | None:
    since = store.state.get("last_brief_ts") or ""
    if not since:
        return None
    cutoff = iso_to_dt(since)
    if not cutoff:
        return None
    fresh = [e for e in events if (iso_to_dt(e.ts) or cutoff) > cutoff]
    if not fresh:
        return None
    lines = [t("delta.head", t=rel_time(since), n=len(fresh))]
    for ev in fresh[-8:]:
        who = {"user": t("role.user"), "assistant": t("role.assistant"),
               "tool": t("role.tool")}.get(ev.role, ev.role)
        lines.append(f"- {AGENT_LABELS.get(ev.agent, ev.agent).split(' / ')[0]}｜{who}："
                     f"{truncate_width(ev.text.replace(chr(10), ' '), 160)}")
    return Block(2, t("sec.delta"), lines)


def build_sections(
    store: Store,
    events: list[Event],
    views: list[SessionView],
    include_git: bool = True,
    with_ai: bool = True,
) -> list[Block]:
    blocks: list[Block] = []

    if include_git:
        blocks.append(_snapshot_block(store))

    ai = summary_mod.load(store) if with_ai else None
    if ai:
        ai_lines = summary_mod.render(store, ai)[1:]
        while ai_lines and not ai_lines[0].strip():
            ai_lines.pop(0)
        blocks.append(Block(1, t("sec.ai"), ai_lines))

    tasks = _current_tasks(events)
    blocks.append(Block(1, t("sec.tasks"),
                        tasks or [f"- {t('empty.no_messages')}"]))

    delta = _delta_block(store, events)
    if delta:
        blocks.append(delta)

    timeline = _timeline(events)
    if timeline:
        blocks.append(Block(2, t("sec.timeline"), timeline))

    if views:
        session_lines: list[str] = []
        for view in views[: SECTION_LIMITS["sessions"]]:
            session_lines.extend(view.render_card(store.config["digest"].get("per_session_messages", 6)))
            session_lines.append("")
        blocks.append(Block(1, t("sec.cards"), session_lines))
    else:
        blocks.append(Block(1, t("sec.cards"), [t("empty.no_sessions")]))

    todos = _notes(store, "todo") + _todo_from_requests(events) + _scan(
        events, TODO_HINT, SECTION_LIMITS["todos"])
    todo_lines = [f"- {t}" for t in _dedupe(todos)[: SECTION_LIMITS["todos"]]]
    if not todo_lines:
        todo_lines = [t("empty.no_todos")]
    blocks.append(Block(2, t("sec.todos"), todo_lines))

    decisions = _notes(store, "decision") + _scan(events, DECISION_HINT, SECTION_LIMITS["decisions"])
    dec_lines = [f"- {d}" for d in _dedupe(decisions)[: SECTION_LIMITS["decisions"]]] or [f"- {t('empty.none')}"]
    blocks.append(Block(3, t("sec.decisions"), dec_lines))

    if views:
        replay: list[str] = []
        for view in views[:3]:
            replay.append(f"**{view.label}**")
            replay.extend(view.render_replay())
            replay.append("")
        if replay:
            blocks.append(Block(4, t("sec.replay"), replay))

    return blocks


def _assemble(store: Store, blocks: list[Block], budget: int, events: list[Event],
              views: list[SessionView]) -> str:
    covered_agents = sorted({e.agent for e in events})
    covered = t("sep.list").join(AGENT_LABELS.get(a, a) for a in covered_agents) or t("empty.none")
    if events:
        first = min((e.ts for e in events if e.ts), default="")
        span = f"{rel_time(first)} → {rel_time(events[-1].ts)}" if events[-1].ts else rel_time(first)
    else:
        span = t("span.none")

    header = [
        t("brief.title", name=Path(store.root).name),
        "",
        t("brief.coverage", ts=now_iso(), sessions=len(views), events=len(events),
          agents=covered, span=span),
        t("brief.purpose"),
        t("brief.hint"),
        "",
    ]
    footer = [
        "---",
        t("brief.footer"),
        "",
    ]

    def render(selected: list[Block]) -> str:
        parts = list(header)
        for idx, block in enumerate(selected, start=1):
            parts.append(f"## {idx}. {block.title}")
            parts.append("")
            parts.extend(block.lines)
            parts.append("")
        parts.extend(footer)
        return "\n".join(parts).rstrip() + "\n"

    selected = list(blocks)
    while selected and width(render(selected)) > budget:
        drop_idx = max(range(len(selected)), key=lambda i: selected[i].priority)
        selected.pop(drop_idx)
    return render(selected)


def estimate_tokens(text: str) -> int:
    """Rough token count for mixed Chinese/English text."""
    return max(1, int(round(width(text) / CHARS_PER_TOKEN)))


def build_context(
    store: Store,
    budget: int | None = None,
    include_git: bool = True,
    max_events: int | None = None,
    with_ai: bool = True,
    budget_tokens: int | None = None,
    full: bool = False,
    since=None,
) -> str:
    cfg = store.config["digest"]
    if budget_tokens:
        budget = tokens_to_width(budget_tokens)
    elif full:
        budget = tokens_to_width(int(cfg.get("full_tokens") or 6000))
    elif cfg.get("budget_tokens"):
        budget = tokens_to_width(int(cfg["budget_tokens"]))
    budget = int(budget or cfg.get("budget") or tokens_to_width(1500))
    max_events = int(max_events or cfg.get("max_events") or 400)
    events = store.events(limit=max_events, since=since)
    views = group_sessions(events, _titles_from_store(store), store.root)
    blocks = build_sections(store, events, views, include_git=include_git, with_ai=with_ai)
    return _assemble(store, blocks, budget, events, views)


def build_handoff(store: Store, target: str, budget: int | None = None) -> str:
    label = AGENT_LABELS.get(target, target)
    brief = build_context(store, budget=budget)
    return (
        t("handoff.title", label=label) + "\n\n" + t("handoff.body") + "\n\n"
        "```markdown\n" + brief + "```\n"
    )


def build_digest_payload(
    store: Store,
    max_tokens: int = 6000,
    since_last: bool = True,
    max_events: int = 400,
) -> dict:
    """Structured input for an agent that will write summary.json.

    Incremental by default: if a summary already exists, hand over that summary
    plus only the records that appeared afterwards, so refreshing costs a
    fraction of a full re-read.
    """
    events = store.events(limit=max_events)
    views = group_sessions(events, _titles_from_store(store), store.root)
    prev = summary_mod.load(store) if since_last else None
    notes = store.notes()

    payload: dict = {
        "project_root": str(store.root),
        "generated_at": now_iso(),
        "mode": "incremental" if prev else "full",
        "window": {
            "from": events[0].ts if events else "",
            "to": events[-1].ts if events else "",
            "events": len(events),
        },
        "agents": sorted({v.agent for v in views}),
        "notes": [{"kind": n.get("kind"), "text": truncate_width(str(n.get("text") or ""), 200)}
                  for n in notes[-12:]],
        "schema_hint": {
            "version": summary_mod.SCHEMA_VERSION,
            "fields": ["project.goal", "project.status", "project.stack",
                       "state.done[]", "state.in_progress[]", "state.blocked[]",
                       "state.decisions[]", "state.next[]", "state.risks[]",
                       "sessions[].{agent,id,title,one_line,outcome,open[]}",
                       "notes_for_next_agent[]"],
        },
    }

    if prev:
        fresh = summary_mod.new_events_since(store, prev)
        payload["previous_summary"] = {
            "generated_at": prev.get("generated_at"),
            "project": prev.get("project"),
            "state": prev.get("state"),
            "sessions": prev.get("sessions"),
            "notes_for_next_agent": prev.get("notes_for_next_agent"),
        }
        payload["new_events"] = [
            {"agent": e.agent, "session": e.session[:8], "role": e.role, "ts": e.ts,
             "text": truncate_width(e.text.replace("\n", " "), 280)}
            for e in fresh[-80:]
        ]
        payload["new_event_count"] = len(fresh)
    else:
        payload["sessions"] = [v.digest_card() for v in views[:8]]
        payload["recent_user_asks"] = [
            truncate_width(e.text.replace("\n", " "), 240)
            for e in events if e.role == "user"
        ][-8:]

    import json

    def size() -> int:
        return estimate_tokens(json.dumps(payload, ensure_ascii=False))

    # trim the least important material until the payload fits:
    # raw asks first, then the oldest session cards, then notes
    while size() > max_tokens and payload.get("recent_user_asks"):
        payload["recent_user_asks"].pop(0)
    while size() > max_tokens and payload.get("sessions"):
        payload["sessions"].pop()
    while size() > max_tokens and payload.get("new_events"):
        payload["new_events"].pop(0)
    if size() > max_tokens and payload.get("notes"):
        payload["notes"] = []
    return payload
