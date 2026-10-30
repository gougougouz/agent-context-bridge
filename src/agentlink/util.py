"""Small shared helpers: path munging, text cleanup, time, jsonl IO."""

from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

WINDOWS = os.name == "nt"


def ci(path: str | os.PathLike) -> str:
    """Normalize a path for comparison (case-insensitive on Windows)."""
    p = os.path.normpath(os.path.abspath(str(path)))
    p = os.path.normcase(p)
    return p.replace("\\", "/").rstrip("/")


def project_match(session_cwd: str | None, project_root: str) -> bool:
    """True when a session's working directory belongs to this project."""
    if not session_cwd:
        return False
    a = ci(session_cwd)
    b = ci(project_root)
    if a == b:
        return True
    return a.startswith(b + "/")


def munge(path: str) -> str:
    """Turn a path into the flat token both DSH and Claude use for session dirs."""
    p = os.path.normpath(os.path.abspath(path)).replace("\\", "-").replace("/", "-")
    p = p.replace(":", "")
    return p


def dsh_session_dirname(project_root: str) -> str:
    """DSH stores sessions under --<munge>-- (e.g. --F-development-skills--)."""
    return "--" + munge(project_root) + "--"


def claude_project_dirname(project_root: str) -> str:
    """Claude Code replaces every non-alphanumeric character with a dash."""
    p = os.path.normpath(os.path.abspath(project_root))
    return re.sub(r"[^A-Za-z0-9]", "-", p)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ms_to_iso(ms: float | int | None) -> str:
    if not ms:
        return ""
    try:
        dt = datetime.fromtimestamp(float(ms) / 1000.0, tz=timezone.utc).astimezone()
        return dt.isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return ""


def iso_to_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        txt = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return dt
    except ValueError:
        return None


_WS = re.compile(r"[ \t\u00a0]+")


def clean_text(text: str, limit: int | None = None) -> str:
    """Collapse whitespace nobody needs, keep paragraph structure."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(_WS.sub(" ", line).strip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if limit is not None and len(text) > limit:
        head = text[: limit - 1].rstrip()
        return head + "…"
    return text


def width(text: str) -> int:
    """Approximate display width: CJK counts double, which matters for budgets."""
    total = 0
    for ch in text:
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def truncate_width(text: str, budget: int, ellipsis: str = "…") -> str:
    if budget <= 0:
        return ""
    if width(text) <= budget:
        return text
    out = []
    used = 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if used + w > budget - 1:
            break
        out.append(ch)
        used += w
    return "".join(out).rstrip() + ellipsis


def read_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, OSError):
        return default


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(value, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def append_jsonl(path: Path, records) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_jsonl(path: Path, limit: int | None = None, tail: bool = False):
    if not path.exists():
        return []
    out = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if limit and not tail and len(out) >= limit:
                break
    if limit and tail:
        out = out[-limit:]
    return out


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}GB"


def rel_time(value: str) -> str:
    dt = iso_to_dt(value)
    if not dt:
        return "?"
    delta = datetime.now(dt.tzinfo) - dt
    secs = delta.total_seconds()
    if secs < 60:
        return "刚刚"
    if secs < 3600:
        return f"{int(secs // 60)} 分钟前"
    if secs < 86400:
        return f"{int(secs // 3600)} 小时前"
    if secs < 86400 * 30:
        return f"{int(secs // 86400)} 天前"
    return dt.strftime("%Y-%m-%d")


def debug(msg: str) -> None:
    if os.environ.get("AGENTLINK_DEBUG"):
        print(f"[agentlink] {msg}", file=sys.stderr)