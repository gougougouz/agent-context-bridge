"""Claude Code sessions: ~/.claude/projects/<munged-project>/*.jsonl

Each line is a transcript entry; message entries look like
``{"type":"user"|"assistant","message":{"role":..,"content":[...]},"cwd":..}``.
Files are append-only, so we read incrementally by byte offset.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..model import Event, Session
from ..store import Store
from ..util import ci, clean_text, claude_project_dirname, debug, project_match
from .base import Source, first_record


class ClaudeSource(Source):
    name = "claude"
    label = "Claude Code"

    def root_dir(self) -> Path:
        home = os.environ.get("CLAUDE_CONFIG_DIR")
        base = Path(home).expanduser() if home else Path(os.path.expanduser("~")) / ".claude"
        return base / "projects"

    def discover(self, project_root: str) -> list[Session]:
        root = self.root_dir()
        if not root.is_dir():
            return []
        folders = []
        exact = root / claude_project_dirname(project_root)
        if exact.is_dir():
            folders.append(exact)
        for entry in root.iterdir():
            if entry.is_dir() and entry != exact:
                folders.append(entry)

        sessions: list[Session] = []
        for folder in folders:
            for path in sorted(folder.glob("*.jsonl")):
                try:
                    head = first_record(path)
                except OSError as exc:
                    debug(f"claude header failed {path}: {exc}")
                    continue
                cwd = str(head.get("cwd") or "")
                by_name = ci(folder.name) == ci(claude_project_dirname(project_root))
                if not (by_name or project_match(cwd, project_root)):
                    continue
                stat = path.stat()
                sessions.append(
                    Session(
                        agent=self.name,
                        path=str(path),
                        session_id=str(head.get("sessionId") or path.stem),
                        cwd=cwd,
                        modified=stat.st_mtime,
                        size=stat.st_size,
                        title=str(head.get("summary") or ""),
                    )
                )
        return sessions

    def ingest(self, session: Session, store: Store) -> list[Event]:
        lines, offset, line_index = self.read_new_lines(session, store)
        events: list[Event] = []
        for idx, rec in lines:
            typ = rec.get("type")
            if typ not in ("user", "assistant"):
                continue
            if rec.get("isMeta") or rec.get("isSidechain"):
                continue
            msg = rec.get("message") or {}
            content = msg.get("content")
            ts = str(rec.get("timestamp") or "")
            seq = idx
            if isinstance(content, str):
                text = clean_text(content, 12000)
                if text and not text.startswith(NOISE):
                    events.append(Event(agent=self.name, session=session.session_id,
                                        role=typ, text=text, ts=ts, seq=seq))
                continue
            if not isinstance(content, list):
                continue
            plain = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                itype = item.get("type")
                if itype == "text":
                    plain.append(str(item.get("text") or ""))
                elif itype == "tool_use":
                    name = str(item.get("name") or "tool")
                    payload = item.get("input") or {}
                    snippet = self.tool_summary(name, payload)
                    if snippet:
                        events.append(Event(agent=self.name, session=session.session_id,
                                            role="tool", text=snippet, ts=ts,
                                            kind="command", tool=name, seq=seq))
                elif itype == "tool_result":
                    continue
            text = clean_text("\n".join(p for p in plain if p), 12000)
            if text and not text.startswith(NOISE):
                events.append(Event(agent=self.name, session=session.session_id,
                                    role=typ, text=text, ts=ts, seq=seq))

        self.finalize(session, store, offset=offset, line_index=line_index,
                      new_events=len(events))
        return events


NOISE = (
    "<permissions instructions>",
    "<environment_context>",
    "<command-name>",
    "Caveat: The messages below were generated",
)