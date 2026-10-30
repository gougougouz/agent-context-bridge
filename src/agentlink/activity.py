"""Derive what actually happened: files touched, commands run, tools used."""

from __future__ import annotations

import os
import re
from collections import Counter

from .model import Event

_DRIVE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|/)[^\s\"'<>|]*")
_FILEISH = re.compile(r"\.[A-Za-z0-9]{1,8}$")
_TOOL_LINE = re.compile(r"^(?P<tool>[A-Za-z0-9_.\-/ ]{1,40}):\s*(?P<rest>.*)$", re.S)

FILE_TOOLS = {
    "read", "write", "edit", "multiedit", "notebookedit", "apply_patch", "create_file",
    "view", "open", "str_replace_editor", "file_read", "file_write",
}
COMMAND_TOOLS = {
    "pwsh", "bash", "shell", "exec", "cmd", "terminal", "run_command", "execute",
    "local_shell", "container.exec", "task",
}


def _split_tool_line(text: str) -> tuple[str, str]:
    match = _TOOL_LINE.match(text or "")
    if not match:
        return "", (text or "").strip()
    return match.group("tool").strip(), match.group("rest").strip()


def _looks_like_path(value: str) -> bool:
    value = value.strip().strip("`\"'")
    return bool(_DRIVE_PATH.match(value) or (value.startswith(("./", "../")) and _FILEISH.search(value)))


def extract_activity(events: list[Event]) -> dict:
    """Summarize tool traffic into files / commands / tool counts."""
    files: Counter[str] = Counter()
    commands: list[str] = []
    tools: Counter[str] = Counter()

    for ev in events:
        if ev.role != "tool":
            continue
        tool, rest = _split_tool_line(ev.text)
        tool = (ev.tool or tool or "tool").strip()
        tools[tool] += 1
        rest = rest.strip()
        if not rest:
            continue
        if _looks_like_path(rest) or tool.lower() in FILE_TOOLS:
            target = rest.split()[0].strip("`\"',;")
            if target:
                files[target] += 1
            continue
        if tool.lower() in COMMAND_TOOLS or rest.startswith(("$", ">", "cd ", "git ", "npm ", "python", "pip", "pwsh")):
            first = rest.splitlines()[0].strip()
            if first:
                commands.append(first[:180])

    deduped_commands: list[str] = []
    seen = set()
    for cmd in commands:
        key = re.sub(r"\s+", " ", cmd)
        if key in seen:
            continue
        seen.add(key)
        deduped_commands.append(cmd)

    return {
        "files": [{"path": path, "edits": count} for path, count in files.most_common(12)],
        "commands": deduped_commands[-12:],
        "tools": dict(tools.most_common(8)),
    }


def short_path(path: str, root: str | os.PathLike | None = None) -> str:
    """Show a path relative to the project when possible."""
    if not path:
        return ""
    normalized = path.replace("/", "\\")
    if root:
        base = str(root).replace("/", "\\").rstrip("\\")
        if normalized.lower().startswith(base.lower()):
            rel = normalized[len(base):].lstrip("\\")
            if rel:
                return rel
            return "."
    return normalized if len(normalized) <= 60 else "…\\" + normalized[-55:]