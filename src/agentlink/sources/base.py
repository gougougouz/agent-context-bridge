"""Shared plumbing for transcript sources (append-only JSONL readers)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from ..model import Event, IngestResult, Session
from ..store import Store
from ..util import debug

MAX_LINE_BYTES = 8 * 1024 * 1024  # never try to JSON-parse a runaway tool output


class Source:
    """Base class: one per agent CLI."""

    name = "base"
    label = "Base"

    def root_dir(self) -> Path:
        raise NotImplementedError

    def available(self) -> bool:
        try:
            return self.root_dir().is_dir()
        except OSError:
            return False

    def discover(self, project_root: str) -> list[Session]:
        raise NotImplementedError

    def ingest(self, session: Session, store: Store) -> list[Event]:
        raise NotImplementedError

    # helpers ---------------------------------------------------------------

    @staticmethod
    def _content_text(content) -> str:
        """Flatten a message content field into text."""
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            return str(content.get("text") or content.get("content") or "")
        parts = []
        if isinstance(content, list):
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    if item.get("type") in ("text", "input_text", "output_text"):
                        parts.append(str(item.get("text") or ""))
        return "\n".join(p for p in parts if p)

    @staticmethod
    def tool_summary(name: str, payload) -> str:
        """One readable line for a tool call: the command, the target path, or a prefix."""
        data = payload
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return f"{name}: {data[:200]}"
        if not isinstance(data, dict):
            return f"{name}: {str(data)[:200]}"
        for key in ("command", "cmd", "script"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                first = next((ln.strip() for ln in value.splitlines() if ln.strip()), "")
                return f"{name}: {first[:220]}"
        for key in ("file_path", "path", "file", "target"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return f"{name}: {value[:220]}"
        for key in ("query", "pattern", "url", "description"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return f"{name}: {value[:200]}"
        return f"{name}: {str(data)[:180]}"

    def read_new_lines(self, session: Session, store: Store) -> tuple[list[tuple[int, dict]], int, int]:
        """Read complete JSON lines appended after the stored cursor.

        Returns (parsed_lines, new_offset, next_line_index).
        """
        path = Path(session.path)
        cursor = store.source_cursor(session.path)
        offset = int(cursor.get("offset") or 0)
        line_index = int(cursor.get("line_index") or 0)
        size = path.stat().st_size if path.exists() else 0
        if size < offset:  # file was rotated or truncated
            offset = 0
            line_index = 0

        out: list[tuple[int, dict]] = []
        if size == offset:
            return out, offset, line_index

        with open(path, "rb") as fh:
            fh.seek(offset)
            buf = fh.read()
        consumed = 0
        start = 0
        while True:
            nl = buf.find(b"\n", start)
            if nl < 0:
                break
            raw = buf[start:nl]
            consumed = nl + 1
            start = nl + 1
            if not raw.strip():
                line_index += 1
                continue
            if len(raw) > MAX_LINE_BYTES:
                debug(f"skip oversized line in {path.name}")
                line_index += 1
                continue
            try:
                rec = json.loads(raw.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                line_index += 1
                continue
            out.append((line_index, rec))
            line_index += 1
        return out, offset + consumed, line_index

    def finalize(self, session: Session, store: Store, offset: int, line_index: int, new_events: int) -> None:
        store.set_source_cursor(
            session.path,
            offset=offset,
            line_index=line_index,
            size=session.size,
            modified=session.modified,
            session=session.session_id,
            agent=self.name,
        )
        store.remember_session(
            session.key,
            agent=self.name,
            path=session.path,
            cwd=session.cwd,
            title=session.title,
            modified=session.modified,
        )


def iter_jsonl_file(path: Path) -> Iterable[dict]:
    with open(path, "rb") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield json.loads(raw.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                continue


def first_record(path: Path, limit: int = 64 * 1024) -> dict:
    try:
        with open(path, "rb") as fh:
            head = fh.read(limit)
    except OSError:
        return {}
    line = head.split(b"\n", 1)[0]
    try:
        return json.loads(line.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return {}


def empty_result(name: str) -> IngestResult:
    return IngestResult(agent=name)