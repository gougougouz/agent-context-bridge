"""DSH sessions: ~/.dsh/sessions/<--munge-->/session-*/session.v4.jsonl.zstd

Every session file is a zstd stream of JSON lines. It is rewritten as the
conversation grows, so we cannot seek by byte offset; each record carries a
monotonic ``seq`` which we use as the cursor.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

from ..model import Event, Session
from ..store import Store
from ..util import (
    ci,
    debug,
    dsh_session_dirname,
    ms_to_iso,
    project_match,
    read_json,
    clean_text,
)
from .base import Source

try:  # optional dependency, only needed for this source
    import zstandard as _zstd
except Exception:  # pragma: no cover - depends on host
    _zstd = None

NOISE_SOURCES = {"runtime-context", "time-context", "system-reminder", "system", "skill"}
NOISE_PREFIXES = (
    "<system-reminder>",
    "Current runtime context.",
    "Time sampled while preparing",
    "background job ",
    "The approval policy changed",
)


class DshSource(Source):
    name = "dsh"
    label = "DSH"

    def root_dir(self) -> Path:
        home = os.environ.get("DSH_HOME")
        if home:
            return Path(home).expanduser() / "sessions"
        return Path(os.path.expanduser("~")) / ".dsh" / "sessions"

    # ------------------------------------------------------------------ read

    def _decompress_head(self, path: Path, size: int = 16 * 1024) -> bytes:
        if _zstd is None:
            raise RuntimeError("zstandard is not installed (pip install zstandard)")
        with open(path, "rb") as fh:
            raw = fh.read()
        dctx = _zstd.ZstdDecompressor()
        with dctx.stream_reader(io.BytesIO(raw)) as reader:
            return reader.read(size)

    def _records(self, path: Path):
        if _zstd is None:
            raise RuntimeError("zstandard is not installed (pip install zstandard)")
        with open(path, "rb") as fh:
            raw = fh.read()
        dctx = _zstd.ZstdDecompressor()
        with dctx.stream_reader(io.BytesIO(raw)) as reader:
            data = reader.read()
        for line in data.decode("utf-8", "replace").splitlines():
            line = line.strip()
            if not line:
                continue
            import json

            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue

    def _header(self, path: Path) -> dict:
        head = self._decompress_head(path)
        line = head.split(b"\n", 1)[0]
        import json

        try:
            return json.loads(line.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            return {}

    # -------------------------------------------------------------- discover

    def discover(self, project_root: str) -> list[Session]:
        root = self.root_dir()
        if not root.is_dir():
            return []
        if _zstd is None:
            raise RuntimeError(
                "读取 DSH 会话需要 zstandard：D:\\PythonEnv\\python.exe -m pip install zstandard"
            )
        candidates: list[Path] = []
        fast = root / dsh_session_dirname(project_root)
        if fast.is_dir():
            candidates.append(fast)
        for entry in root.iterdir():
            if not entry.is_dir() or entry == fast:
                continue
            candidates.append(entry)

        sessions: list[Session] = []
        for folder in candidates:
            for path in sorted(folder.glob("session-*/session.v4.jsonl*")):
                try:
                    header = self._header(path)
                except Exception as exc:  # corrupt or locked file
                    debug(f"dsh header failed {path}: {exc}")
                    continue
                cwd = header.get("cwd") or ""
                if not project_match(cwd, project_root):
                    continue
                stat = path.stat()
                sessions.append(
                    Session(
                        agent=self.name,
                        path=str(path),
                        session_id=str(header.get("id") or path.parent.name),
                        cwd=cwd,
                        modified=stat.st_mtime,
                        size=stat.st_size,
                        title=str(header.get("title") or ""),
                    )
                )
        return sessions

    # ---------------------------------------------------------------- ingest

    def ingest(self, session: Session, store: Store) -> list[Event]:
        cursor = store.source_cursor(session.path)
        last_seq = int(cursor.get("last_seq") or -1)
        title = session.title
        events: list[Event] = []
        max_seq = last_seq

        for rec in self._records(Path(session.path)):
            typ = rec.get("type")
            seq = rec.get("seq")
            if isinstance(seq, int):
                if seq <= last_seq:
                    if typ == "session/title":
                        title = str((rec.get("data") or {}).get("title") or title)
                    continue
                max_seq = max(max_seq, seq)
            ts = ms_to_iso(rec.get("time"))
            data = rec.get("data") or {}

            if typ == "session/title":
                title = str(data.get("title") or title)
            elif typ == "user/message":
                src = (data.get("source") or {}).get("kind") or "user"
                text = self._content_text(data.get("content"))
                if src in NOISE_SOURCES or text.startswith(NOISE_PREFIXES):
                    continue
                text = clean_text(text, 12000)
                if not text:
                    continue
                events.append(
                    Event(agent=self.name, session=session.session_id, role="user",
                          text=text, ts=ts, seq=seq)
                )
            elif typ == "assistant/message":
                text = self._content_text(data.get("content"))
                text = clean_text(text, 12000)
                if not text:
                    continue
                events.append(
                    Event(agent=self.name, session=session.session_id, role="assistant",
                          text=text, ts=ts, seq=seq)
                )
            elif typ == "tool/call":
                name = str(data.get("name") or data.get("tool") or "tool")
                text = self.tool_summary(name, data.get("input") or data.get("arguments") or "")
                if not text:
                    continue
                events.append(
                    Event(agent=self.name, session=session.session_id, role="tool",
                          text=text, ts=ts, kind="command", tool=name, seq=seq)
                )

        if isinstance(seq, int):
            store.set_source_cursor(session.path, last_seq=max_seq)
        if title:
            session.title = title
        self.finalize(session, store, offset=0, line_index=0, new_events=len(events))
        store.set_source_cursor(session.path, last_seq=max_seq)
        return events