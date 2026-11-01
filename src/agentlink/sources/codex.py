"""Codex / ChatGPT desktop sessions.

Layout: ~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<uuid>.jsonl
The first line is ``session_meta`` (carries ``cwd``), later lines are
``response_item`` / ``event_msg`` records. Files are append-only, so we read
incrementally by byte offset.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from ..model import Event, Session
from ..store import Store
from ..util import clean_text, debug, iso_to_dt, project_match, read_jsonl
from .base import Source, first_record

SKIP_ROLES = {"developer", "system"}

# Codex injects UI plumbing into the transcript; these are not conversation.
CONTROL_TAG = re.compile(r"^\s*<([a-z][a-z0-9_]*)>.*</\1>\s*$", re.S)
SKIP_THREAD_SOURCES = {"guardian_review"}


def _is_control_message(text: str) -> bool:
    return bool(CONTROL_TAG.match(text.strip())) and len(text.strip()) < 4000


class CodexSource(Source):
    name = "codex"
    label = "Codex / ChatGPT"

    def root_dir(self) -> Path:
        return self._codex_home() / "sessions"

    def _codex_home(self) -> Path:
        home = os.environ.get("CODEX_HOME")
        return Path(home).expanduser() if home else Path(os.path.expanduser("~")) / ".codex"

    def root_dirs(self) -> list[Path]:
        """Active sessions plus archived ones, which still belong to the project."""
        home = self._codex_home()
        return [d for d in (home / "sessions", home / "archived_sessions") if d.is_dir()]

    def available(self) -> bool:
        try:
            return bool(self.root_dirs())
        except OSError:
            return False

    def _titles(self) -> dict[str, str]:
        index = self.root_dir().parent / "session_index.jsonl"
        out: dict[str, str] = {}
        for rec in read_jsonl(index):
            sid = rec.get("id")
            name = rec.get("thread_name")
            if sid and name:
                out[str(sid)] = str(name)
        return out

    def discover(self, project_root: str) -> list[Session]:
        roots = self.root_dirs()
        if not roots:
            return []
        titles = self._titles()
        sessions: list[Session] = []
        paths: list[Path] = []
        for root in roots:
            paths.extend(sorted(root.rglob("rollout-*.jsonl")))
        for path in paths:
            try:
                meta = first_record(path)
            except OSError as exc:
                debug(f"codex header failed {path}: {exc}")
                continue
            if meta.get("type") != "session_meta":
                continue
            payload = meta.get("payload") or {}
            if str(payload.get("thread_source") or "") in SKIP_THREAD_SOURCES:
                continue
            cwd = payload.get("cwd") or ""
            roots = payload.get("runtime_workspace_roots") or []
            hit = project_match(cwd, project_root) or any(
                project_match(r, project_root) for r in roots if isinstance(r, str)
            )
            if not hit:
                continue
            sid = str(payload.get("id") or payload.get("session_id") or path.stem)
            stat = path.stat()
            sessions.append(
                Session(
                    agent=self.name,
                    path=str(path),
                    session_id=sid,
                    cwd=cwd,
                    modified=stat.st_mtime,
                    size=stat.st_size,
                    title=titles.get(sid, ""),
                )
            )
        return sessions

    def ingest(self, session: Session, store: Store) -> list[Event]:
        lines, offset, line_index = self.read_new_lines(session, store)
        events: list[Event] = []
        last_ts = ""
        for idx, rec in lines:
            typ = rec.get("type")
            payload = rec.get("payload") or {}
            ts = str(rec.get("timestamp") or "")
            ordinal = rec.get("ordinal")
            seq = ordinal if isinstance(ordinal, int) else idx
            ptype = payload.get("type")

            if typ == "response_item" and ptype == "message":
                role = str(payload.get("role") or "")
                if role in SKIP_ROLES:
                    continue
                text = self._content_text(payload.get("content"))
                text = clean_text(text, 12000)
                if not text or text.startswith(NOISE) or _is_control_message(text):
                    continue
                events.append(
                    Event(agent=self.name, session=session.session_id,
                          role="assistant" if role == "assistant" else "user",
                          text=text, ts=ts or last_ts, seq=seq)
                )
            elif typ == "response_item" and ptype in ("function_call", "custom_tool_call"):
                name = str(payload.get("name") or ptype)
                raw = payload.get("arguments") or payload.get("input") or ""
                text = self.tool_summary(name, raw)
                if text:
                    events.append(
                        Event(agent=self.name, session=session.session_id, role="tool",
                              text=text, ts=ts or last_ts, kind="command",
                              tool=name, seq=seq)
                    )
            elif typ == "compacted":
                # a compaction replaces history; record it as a marker only
                continue
            if ts:
                last_ts = ts

        if events:
            first = events[0].ts or ""
            last = events[-1].ts or ""
            store.remember_session(
                session.key, agent=self.name, path=session.path, cwd=session.cwd,
                title=session.title, modified=session.modified,
                first_seen=first, last_seen=last,
            )
        self.finalize(session, store, offset=offset, line_index=line_index,
                      new_events=len(events))
        return events


NOISE = (
    "<permissions instructions>",
    "<environment_context>",
    "# AGENTS.md instructions",
    "<user_instructions>",
)