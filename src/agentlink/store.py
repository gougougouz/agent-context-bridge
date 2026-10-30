"""On-disk state for one project: .agentlink/ inside the project root."""

from __future__ import annotations

import os
from pathlib import Path

from .model import Event
from .util import (
    append_jsonl,
    now_iso,
    read_json,
    read_jsonl,
    write_json,
)

STATE_DIRNAME = ".agentlink"
CONFIG_VERSION = 1

DEFAULT_CONFIG = {
    "version": CONFIG_VERSION,
    "agents": ["dsh", "codex", "claude"],
    "digest": {
        "budget": 24000,          # display width of the generated brief
        "max_events": 400,        # journal events considered
        "per_session_messages": 6,
        "recent_days": 60.0,
    },
    "git": {"enabled": True, "log_limit": 8},
}


class Store:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root).resolve()
        override = os.environ.get("AGENTLINK_STATE_DIR")
        self.dir = Path(override).expanduser().resolve() if override else self.root / STATE_DIRNAME
        self.config_path = self.dir / "config.json"
        self.state_path = self.dir / "state.json"
        self.journal_path = self.dir / "journal.jsonl"
        self.notes_path = self.dir / "notes.jsonl"
        self.context_path = self.dir / "context.md"
        self.handoff_path = self.dir / "HANDOFF.md"
        self._config: dict | None = None
        self._state: dict | None = None

    # ---------------------------------------------------------------- layout

    @property
    def exists(self) -> bool:
        return self.config_path.exists()

    def ensure(self) -> "Store":
        self.dir.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            cfg = dict(DEFAULT_CONFIG)
            cfg["created"] = now_iso()
            cfg["project"] = str(self.root)
            write_json(self.config_path, cfg)
            (self.dir / ".gitignore").write_text(
                "# agentlink state: transcripts digests and cursors\n*\n!.gitignore\n",
                encoding="utf-8",
            )
        return self

    # ---------------------------------------------------------------- config

    @property
    def config(self) -> dict:
        if self._config is None:
            cfg = read_json(self.config_path, {}) or {}
            merged = dict(DEFAULT_CONFIG)
            merged.update({k: v for k, v in cfg.items() if k not in ("digest", "git")})
            merged["digest"] = {**DEFAULT_CONFIG["digest"], **(cfg.get("digest") or {})}
            merged["git"] = {**DEFAULT_CONFIG["git"], **(cfg.get("git") or {})}
            merged.setdefault("project", str(self.root))
            self._config = merged
        return self._config

    def save_config(self) -> None:
        write_json(self.config_path, self.config)

    # ----------------------------------------------------------------- state

    @property
    def state(self) -> dict:
        if self._state is None:
            self._state = read_json(self.state_path, {}) or {}
            self._state.setdefault("sources", {})
            self._state.setdefault("seen", [])
            self._state.setdefault("sessions", {})
        return self._state

    def save_state(self) -> None:
        # keep the dedupe ring bounded
        seen = self.state.get("seen") or []
        if len(seen) > 6000:
            self.state["seen"] = seen[-4000:]
        write_json(self.state_path, self.state)

    def session_meta(self, key: str) -> dict:
        return self.state["sessions"].get(key, {})

    def remember_session(self, key: str, **fields) -> None:
        rec = self.state["sessions"].setdefault(key, {})
        rec.update({k: v for k, v in fields.items() if v is not None})

    def is_seen(self, event: Event) -> bool:
        return event.dedupe_key in set(self.state.get("seen") or [])

    def mark_seen(self, events: list[Event]) -> None:
        seen = self.state.setdefault("seen", [])
        seen.extend(e.dedupe_key for e in events)

    def source_cursor(self, path: str) -> dict:
        return self.state["sources"].get(path, {})

    def set_source_cursor(self, path: str, **fields) -> None:
        cur = self.state["sources"].setdefault(path, {})
        cur.update({k: v for k, v in fields.items() if v is not None})

    # --------------------------------------------------------------- journal

    def append_events(self, events: list[Event]) -> None:
        append_jsonl(self.journal_path, [e.to_record() for e in events])

    def events(self, limit: int | None = None, tail: bool = True) -> list[Event]:
        recs = read_jsonl(self.journal_path, limit=limit, tail=tail)
        return [Event.from_record(r) for r in recs]

    # ----------------------------------------------------------------- notes

    def add_note(self, text: str, kind: str = "note", agent: str = "user") -> dict:
        rec = {"ts": now_iso(), "kind": kind, "text": text, "agent": agent}
        append_jsonl(self.notes_path, [rec])
        return rec

    def notes(self) -> list[dict]:
        return read_jsonl(self.notes_path)

    # ----------------------------------------------------------------- stats

    def stats(self) -> dict:
        return {
            "root": str(self.root),
            "events": len(read_jsonl(self.journal_path)),
            "sessions": len(self.state.get("sessions") or {}),
            "sources": len(self.state.get("sources") or {}),
            "last_sync": self.state.get("last_sync", ""),
            "size": sum(
                p.stat().st_size for p in self.dir.glob("*") if p.is_file()
            ) if self.dir.exists() else 0,
        }