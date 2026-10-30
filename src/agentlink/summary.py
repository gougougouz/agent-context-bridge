"""The optional AI layer: a validated, structured handoff summary.

The deterministic digest says *what happened*; this summary says *what it meant*.
Any capable agent can write it (see `agentlink digest` for the input contract and
SKILL.md for the prompts), then `agentlink summary apply` stores and validates it.
"""

from __future__ import annotations

import json
from pathlib import Path

from .i18n import t
from .model import AGENT_LABELS
from .store import Store
from .util import iso_to_dt, now_iso, read_json, rel_time, truncate_width, write_json

SCHEMA_VERSION = 1

LIST_FIELDS = ("done", "in_progress", "blocked", "decisions", "next", "risks")


def empty() -> dict:
    return {
        "version": SCHEMA_VERSION,
        "generated_at": "",
        "generator": "",
        "window": {"from": "", "to": "", "events": 0},
        "project": {"goal": "", "status": "", "stack": ""},
        "state": {field: [] for field in LIST_FIELDS},
        "sessions": [],
        "notes_for_next_agent": [],
    }


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            if isinstance(item, dict):
                text = "；".join(f"{k}: {v}" for k, v in item.items() if v not in (None, ""))
            else:
                text = str(item)
            text = text.strip()
            if text:
                out.append(text)
        return out
    return [str(value)]


def normalize(payload: dict) -> dict:
    """Tolerant schema: accept partial output from an LLM without exploding."""
    base = empty()
    if not isinstance(payload, dict):
        return base
    base["generated_at"] = str(payload.get("generated_at") or now_iso())
    base["generator"] = str(payload.get("generator") or "")
    window = payload.get("window") or {}
    if isinstance(window, dict):
        base["window"] = {
            "from": str(window.get("from") or ""),
            "to": str(window.get("to") or ""),
            "events": int(window.get("events") or 0),
        }
    project = payload.get("project") or {}
    if isinstance(project, dict):
        for key in ("goal", "status", "stack"):
            base["project"][key] = str(project.get(key) or "").strip()
    state = payload.get("state") or {}
    if isinstance(state, dict):
        for field in LIST_FIELDS:
            base["state"][field] = _as_list(state.get(field))[:20]
    sessions = []
    for item in payload.get("sessions") or []:
        if not isinstance(item, dict):
            continue
        sessions.append({
            "agent": str(item.get("agent") or ""),
            "id": str(item.get("id") or ""),
            "title": str(item.get("title") or ""),
            "one_line": str(item.get("one_line") or ""),
            "outcome": str(item.get("outcome") or ""),
            "open": _as_list(item.get("open"))[:8],
        })
    base["sessions"] = sessions[:20]
    base["notes_for_next_agent"] = _as_list(payload.get("notes_for_next_agent"))[:12]
    return base


def path_for(store: Store) -> Path:
    return store.dir / "summary.json"


def load(store: Store) -> dict | None:
    raw = read_json(path_for(store), None)
    if not raw:
        return None
    data = normalize(raw)
    if not any(data["state"].values()) and not data["project"]["goal"] and not data["sessions"]:
        return None
    return data


def save(store: Store, payload: dict) -> dict:
    data = normalize(payload)
    write_json(path_for(store), data)
    return data


def is_stale(store: Store, data: dict) -> bool:
    last_sync = store.state.get("last_sync") or ""
    if not last_sync:
        return False
    a = iso_to_dt(data.get("generated_at") or "")
    b = iso_to_dt(last_sync)
    if not a or not b:
        return False
    return b > a


def coverage_end(data: dict) -> str:
    """Timestamp up to which this summary has read the transcripts."""
    window = data.get("window") or {}
    return str(window.get("to") or data.get("generated_at") or "")


def new_events_since(store: Store, data: dict) -> list:
    """Journal events that appeared after the summary was written."""
    cutoff = iso_to_dt(coverage_end(data))
    if not cutoff:
        return store.events()
    out = []
    for ev in store.events():
        stamp = iso_to_dt(ev.ts)
        if stamp and stamp > cutoff:
            out.append(ev)
    return out


def needs_refresh(store: Store, data: dict | None, min_new_events: int = 6) -> tuple[bool, int]:
    """(should the AI summary be regenerated, how many new events pile up)."""
    if not data:
        return True, len(store.events())
    fresh = new_events_since(store, data)
    return len(fresh) >= min_new_events, len(fresh)


def render(store: Store, data: dict, budget: int = 6000) -> list[str]:
    """Markdown block placed near the top of the brief."""
    stale = is_stale(store, data)
    when = data.get("generated_at") or ""
    title = f"# {t('sec.ai')}"
    lines = [title, ""]
    meta = f"> {t('ai.generated', t=rel_time(when))}" if when else f"> {t('ai.unknown_time')}"
    if data.get("generator"):
        meta += t("ai.source", g=data["generator"])
    if stale:
        meta += t("ai.stale")
    lines.append(meta)
    lines.append("")

    project = data.get("project") or {}
    if project.get("goal"):
        lines.append(f"- **{t('ai.goal')}**{t('sep.colon')}{project['goal']}")
    if project.get("status"):
        lines.append(f"- **{t('ai.status')}**{t('sep.colon')}{project['status']}")
    if project.get("stack"):
        lines.append(f"- **{t('ai.stack')}**{t('sep.colon')}{project['stack']}")
    if any(project.values()):
        lines.append("")

    state = data.get("state") or {}
    labels = {
        "in_progress": t("ai.in_progress"),
        "next": t("ai.next"),
        "blocked": t("ai.blocked"),
        "done": t("ai.done"),
        "decisions": t("ai.decisions"),
        "risks": t("ai.risks"),
    }
    for field in ("in_progress", "next", "blocked", "decisions", "done", "risks"):
        items = state.get(field) or []
        if not items:
            continue
        lines.append(f"**{labels[field]}**")
        for item in items[:3]:
            lines.append(f"- {truncate_width(item, 180)}")
        lines.append("")

    sessions = data.get("sessions") or []
    if sessions:
        lines.append(f"**{t('ai.sessions')}**")
        for item in sessions[:3]:
            agent = AGENT_LABELS.get(item.get("agent", ""), item.get("agent") or "?")
            head = item.get("title") or item.get("id") or ""
            one = item.get("one_line") or ""
            outcome = item.get("outcome") or ""
            text = f"- {agent}｜{truncate_width(head, 40)}：{truncate_width(one, 120)}"
            if outcome:
                text += f" → {truncate_width(outcome, 120)}"
            lines.append(text)
            for open_item in (item.get("open") or [])[:2]:
                lines.append(f"  - {t('ai.open')}{t('sep.colon')}{truncate_width(open_item, 140)}")
        lines.append("")

    notes = data.get("notes_for_next_agent") or []
    if notes:
        lines.append(f"**{t('ai.notes')}**")
        for note in notes[:3]:
            lines.append(f"- {truncate_width(note, 220)}")
        lines.append("")

    if not any([project.get("goal"), sessions, notes, any(state.values())]):
        lines.append(t("ai.empty"))
        lines.append("")

    return lines

