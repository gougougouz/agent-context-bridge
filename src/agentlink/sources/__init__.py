"""Transcript sources: discovery, incremental ingest, and the sync entry point."""

from __future__ import annotations

from ..model import AGENTS, Event, IngestResult, Session
from ..store import Store
from ..util import debug, now_iso
from .base import Source
from .claude import ClaudeSource
from .codex import CodexSource
from .dsh import DshSource

__all__ = [
    "SOURCES",
    "get_source",
    "discover_sessions",
    "sync",
    "DshSource",
    "CodexSource",
    "ClaudeSource",
]

SOURCES: dict[str, Source] = {
    src.name: src for src in (DshSource(), CodexSource(), ClaudeSource())
}

MAX_EVENTS_PER_SESSION = 3000


def get_source(name: str) -> Source:
    try:
        return SOURCES[name]
    except KeyError:
        raise SystemExit(f"未知 agent: {name}（可选: {', '.join(SOURCES)}）") from None


def discover_sessions(store: Store, agents: list[str] | None = None) -> list[Session]:
    names = agents or list(store.config.get("agents") or AGENTS)
    out: list[Session] = []
    for name in names:
        src = SOURCES.get(name)
        if not src:
            continue
        if not src.available():
            debug(f"{name}: no transcript directory at {src.root_dir()}")
            continue
        try:
            found = src.discover(str(store.root))
        except Exception as exc:
            debug(f"{name}: discovery failed: {exc}")
            continue
        out.extend(found)
    out.sort(key=lambda s: s.modified, reverse=True)
    return out


def sync(store: Store, agents: list[str] | None = None) -> list[IngestResult]:
    """Read new transcript lines from every configured agent into the journal."""
    names = agents or list(store.config.get("agents") or AGENTS)
    results: list[IngestResult] = []
    seen = set(store.state.get("seen") or [])

    for name in names:
        src = SOURCES.get(name)
        result = IngestResult(agent=name)
        if src is None:
            result.errors.append(f"未知 agent: {name}")
            results.append(result)
            continue
        if not src.available():
            result.errors.append(f"未找到 {src.label} 的会话目录: {src.root_dir()}")
            results.append(result)
            continue
        try:
            sessions = src.discover(str(store.root))
        except Exception as exc:
            result.errors.append(str(exc))
            results.append(result)
            continue

        result.sessions = len(sessions)
        for session in sessions:
            try:
                events = src.ingest(session, store)
            except Exception as exc:
                result.errors.append(f"{session.path}: {exc}")
                continue
            fresh = [e for e in events if e.dedupe_key not in seen]
            if len(fresh) > MAX_EVENTS_PER_SESSION:
                result.skipped += len(fresh) - MAX_EVENTS_PER_SESSION
                fresh = fresh[-MAX_EVENTS_PER_SESSION:]
            if fresh:
                store.append_events(fresh)
                seen.update(e.dedupe_key for e in fresh)
                result.new_events += len(fresh)
        results.append(result)

    store.state["seen"] = list(seen)
    store.state["last_sync"] = now_iso()
    store.save_state()
    return results