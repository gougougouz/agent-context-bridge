"""Minimal git snapshot: branch, recent commits, dirty files."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

CANDIDATE_GIT = [
    "git",
    r"F:\app\tools\git\cmd\git.exe",
    r"C:\Program Files\Git\cmd\git.exe",
]


def find_git() -> str | None:
    env = os.environ.get("AGENTLINK_GIT")
    if env and Path(env).exists():
        return env
    for cand in CANDIDATE_GIT:
        found = shutil.which(cand)
        if found:
            return found
        if Path(cand).exists():
            return cand
    return None


def _run(git: str, cwd: Path, *args: str) -> str:
    try:
        out = subprocess.run(
            [git, *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return (out.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def snapshot(root: Path, log_limit: int = 8) -> dict:
    git = find_git()
    info = {
        "available": bool(git),
        "is_repo": False,
        "branch": "",
        "commits": [],
        "dirty": [],
        "head": "",
    }
    if not git:
        return info
    if _run(git, root, "rev-parse", "--is-inside-work-tree") != "true":
        return info
    info["is_repo"] = True
    info["branch"] = _run(git, root, "rev-parse", "--abbrev-ref", "HEAD")
    info["head"] = _run(git, root, "rev-parse", "--short", "HEAD")
    log = _run(git, root, "log", f"-{log_limit}", "--pretty=format:%h|%ad|%s", "--date=short")
    for line in log.splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            info["commits"].append({"hash": parts[0], "date": parts[1], "subject": parts[2]})
    status = _run(git, root, "status", "--porcelain")
    info["dirty"] = [ln for ln in status.splitlines() if ln.strip()][:40]
    return info