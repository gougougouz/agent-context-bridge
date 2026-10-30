"""Core data structures shared by the sources, the store and the digest."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


AGENTS = ("dsh", "codex", "claude")

AGENT_LABELS = {
    "dsh": "DSH",
    "codex": "Codex / ChatGPT",
    "claude": "Claude Code",
}


@dataclass
class Session:
    """A conversation transcript belonging to this project."""

    agent: str
    path: str
    session_id: str
    cwd: str = ""
    modified: float = 0.0
    size: int = 0
    title: str = ""

    @property
    def key(self) -> str:
        return f"{self.agent}:{self.session_id}"


@dataclass
class Event:
    """One normalized message or tool call taken from a transcript."""

    agent: str
    session: str
    role: str  # user | assistant | tool
    text: str
    ts: str = ""
    kind: str = "message"  # message | command | note
    tool: str = ""
    seq: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        rec = asdict(self)
        rec.pop("meta", None)
        if self.meta:
            rec["meta"] = self.meta
        return rec

    @classmethod
    def from_record(cls, rec: dict[str, Any]) -> "Event":
        known = {k: rec.get(k) for k in (
            "agent", "session", "role", "text", "ts", "kind", "tool", "seq", "meta"
        )}
        known["ts"] = known.get("ts") or ""
        known["kind"] = known.get("kind") or "message"
        known["tool"] = known.get("tool") or ""
        known["meta"] = known.get("meta") or {}
        return cls(**known)

    @property
    def dedupe_key(self) -> str:
        ident = self.seq if self.seq is not None else abs(hash(self.text)) % (10 ** 12)
        return f"{self.agent}|{self.session}|{ident}"


@dataclass
class IngestResult:
    agent: str
    sessions: int = 0
    new_events: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def merge(self, other: "IngestResult") -> "IngestResult":
        self.sessions += other.sessions
        self.new_events += other.new_events
        self.skipped += other.skipped
        self.errors.extend(other.errors)
        return self