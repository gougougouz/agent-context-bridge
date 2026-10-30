"""Turn the journal into a compact, agent-readable project brief (context.md)."""

from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path

from .gitinfo import snapshot
from .model import AGENT_LABELS, Event
from .store import Store
from .util import iso_to_dt, now_iso, rel_time, truncate_width, width

DECISION_HINT = re.compile(
    r"(决定|结论|约定|决策|已确认|方案定|采用|不要再|必须|禁止|注意[:：])",
)
TODO_HINT = re.compile(
    r"(待办|TODO|todo|未完成|下一步|待实现|还未|尚需|还需要|接着做|剩[下余])",
)
TODO_LINE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s*\[?\s?\]?\s*(.+)$")
REQUEST_HINT = re.compile(r"(要求|需求|目标|请实现|需要实现|任务[:：]|功能[:：])")
ITEM_LINE = re.compile(r"^\s*(?:\d+[.、)）]|[-*+])\s*(\S.{3,})")

SECTION_LIMITS = {
    "sessions": 5,
    "messages_per_session": 6,
    "todos": 10,
    "decisions": 10,
    "dirty": 8,
}


class SessionView:
    def __init__(self, agent: str, session: str, events: list[Event], title: str = ""):
        self.agent = agent
        self.session = session
        self.events = events
        self.title = title
        self.last_ts = events[-1].ts if events else ""

    @property
    def short_id(self) -> str:
        sid = self.session
        if sid.startswith("session-"):
            sid = sid[len("session-"):]
        return sid[:8]

    @property
    def label(self) -> str:
        name = AGENT_LABELS.get(self.agent, self.agent)
        if self.title:
            return f"{name} · {truncate_width(self.title, 28)}"
        return f"{name} · {self.short_id}"

    def user_events(self) -> list[Event]:
        return [e for e in self.events if e.role == "user"]

    def assistant_events(self) -> list[Event]:
        return [e for e in self.events if e.role == "assistant"]

    def topic(self) -> str:
        for ev in self.user_events():
            text = ev.text.strip()
            if not text:
                continue
            first = text.splitlines()[0]
            if first.startswith(("# Files mentioned", "# Files pasted", "Distinguish instructions")):
                for line in text.splitlines()[1:]:
                    if line.strip() and not line.startswith("#"):
                        first = line.strip()
                        break
                else:
                    continue
            return truncate_width(first, 60)
        return "（无用户消息）"

    def render(self, per_session: int = 6) -> list[str]:
        picked: list[Event] = []
        users = self.user_events()
        assistants = self.assistant_events()
        if users:
            picked.append(users[0])
        tail_users = users[-2:] if len(users) > 1 else []
        tail_assist = assistants[-2:]
        for ev in tail_users + tail_assist:
            if ev not in picked:
                picked.append(ev)
        picked.sort(key=lambda e: e.ts or "")
        picked = picked[-per_session:]
        lines = []
        last_text = ""
        for ev in picked:
            if ev.text.strip() == last_text:
                continue
            last_text = ev.text.strip()
            who = "用户" if ev.role == "user" else "助手"
            text = truncate_width(ev.text.replace("\n", " "), 260)
            lines.append(f"- **{who}**（{rel_time(ev.ts)}）：{text}")
        if not lines:
            tools = [e for e in self.events if e.role == "tool"]
            for ev in tools[-3:]:
                lines.append(f"- **命令**：`{truncate_width(ev.text.replace(chr(10), ' '), 160)}`")
        return lines


def group_sessions(events: list[Event], titles: dict[str, str] | None = None) -> list[SessionView]:
    titles = titles or {}
    buckets: "OrderedDict[tuple[str, str], list[Event]]" = OrderedDict()
    for ev in sorted(events, key=lambda e: e.ts or ""):
        buckets.setdefault((ev.agent, ev.session), []).append(ev)
    views = [
        SessionView(a, s, evs, titles.get(f"{a}:{s}", ""))
        for (a, s), evs in buckets.items()
    ]
    views.sort(key=lambda v: v.last_ts or "", reverse=True)
    return views


def _titles_from_store(store: Store) -> dict[str, str]:
    out = {}
    for key, meta in (store.state.get("sessions") or {}).items():
        title = (meta or {}).get("title")
        if title:
            out[key] = str(title)
    return out


def _current_tasks(events: list[Event], limit: int = 3) -> list[str]:
    """The newest user requests, which is what the next agent usually needs."""
    lines: list[str] = []
    seen: set[str] = set()
    for ev in reversed(events):
        if ev.role != "user":
            continue
        text = ev.text.replace("\n", " ").strip()
        if len(text) < 3 or text in seen:
            continue
        seen.add(text)
        label = AGENT_LABELS.get(ev.agent, ev.agent)
        lines.append(
            f"- **{rel_time(ev.ts)}**（{label}）：{truncate_width(text, 300)}"
        )
        if len(lines) >= limit:
            break
    return lines


def _scan(events: list[Event], pattern: re.Pattern, limit: int, allow_bullets: bool = True) -> list[str]:
    hits: list[str] = []
    seen: set[str] = set()
    for ev in reversed(events):
        if ev.role == "tool":
            continue
        for raw in ev.text.splitlines():
            line = raw.strip()
            if not line or len(line) < 4:
                continue
            if TODO_LINE.match(line) and not allow_bullets:
                continue
            if pattern.search(line):
                cleaned = re.sub(r"^[-*+\d.\s]+", "", line)
                if cleaned in seen:
                    continue
                seen.add(cleaned)
                hits.append(truncate_width(cleaned, 240))
                if len(hits) >= limit:
                    return hits
    return hits


def _todo_from_requests(events: list[Event], limit: int = 8) -> list[str]:
    """Numbered or bulleted items inside a message that states requirements."""
    out: list[str] = []
    for ev in reversed(events):
        if ev.role != "user" or not REQUEST_HINT.search(ev.text):
            continue
        for line in ev.text.splitlines():
            match = ITEM_LINE.match(line)
            if not match:
                continue
            item = match.group(1).strip()
            if len(item) < 4:
                continue
            out.append(truncate_width(item, 200))
            if len(out) >= limit:
                return out
    return out


def _notes(store: Store, kind: str, limit: int = 10) -> list[str]:
    out: list[str] = []
    for rec in reversed(store.notes()):
        if rec.get("kind") != kind:
            continue
        out.append(truncate_width(str(rec.get("text") or ""), 240))
        if len(out) >= limit:
            break
    return out


def _snapshot_lines(store: Store, info: dict, cfg: dict) -> list[str]:
    root = store.root
    lines = [f"- 项目根目录：`{root}`"]
    if info.get("is_repo"):
        branch = info.get("branch") or "?"
        lines.append(f"- Git 分支：`{branch}`（HEAD `{info.get('head')}`）")
        if info.get("commits"):
            lines.append("- 最近提交：")
            for c in info["commits"][:4]:
                lines.append(f"  - `{c['hash']}` {c['date']} {truncate_width(c['subject'], 90)}")
        dirty = info.get("dirty") or []
        if dirty:
            lines.append(f"- 未提交改动：{len(dirty)} 项，例如 " + "、".join(
                f"`{d[3:] if len(d) > 3 else d}`" for d in dirty[:SECTION_LIMITS["dirty"]]
            ))
        else:
            lines.append("- 工作区干净（无未提交改动）")
    else:
        lines.append("- 不是 Git 仓库（进度以会话记录与 note 为准）")
    return lines


def build_context(
    store: Store,
    budget: int | None = None,
    include_git: bool = True,
    max_events: int | None = None,
) -> str:
    cfg = store.config["digest"]
    budget = int(budget or cfg.get("budget") or 24000)
    max_events = int(max_events or cfg.get("max_events") or 400)
    events = store.events(limit=max_events)
    views = group_sessions(events, _titles_from_store(store))

    if events:
        first = min((e.ts for e in events if e.ts), default="")
        last = max((e.ts for e in events if e.ts), default="")
        span = f"{rel_time(first)} → {rel_time(last)}"
    else:
        span = "无记录"

    agents_cover = sorted({e.agent for e in events})
    covered = "、".join(AGENT_LABELS.get(a, a) for a in agents_cover) or "（暂无）"

    header = [
        f"# 项目上下文速览 · {Path(store.root).name}",
        "",
        f"> 由 `agentlink` 生成于 {now_iso()}；覆盖 {len(views)} 个会话 / {len(events)} 条记录"
        f"（{covered}，{span}）。",
        "> 这是同一项目里其他 agent 的对话与改动摘要，供接手者快速对齐；"
        "细节可用 `agentlink show --session <id>` 查看。",
        "",
    ]

    body: list[tuple[int, list[str]]] = []  # (priority, lines) — higher priority drops first

    if include_git:
        info = snapshot(store.root, log_limit=store.config["git"].get("log_limit", 8))
        body.append((1, ["## 1. 项目快照", "", *_snapshot_lines(store, info, cfg), ""]))

    tasks = _current_tasks(events, 3)
    task_lines = ["## 2. 当前任务（最近的用户请求，新→旧）", ""]
    task_lines.extend(tasks if tasks else ["- （暂无可用的用户消息）"])
    task_lines.append("")
    body.append((1, task_lines))

    progress: list[str] = ["## 3. 各 agent 的最近对话（新→旧）", ""]
    if views:
        for view in views[: SECTION_LIMITS["sessions"]]:
            if view.title:
                progress.append(f"### {view.label}（{rel_time(view.last_ts)}）")
            else:
                progress.append(
                    f"### {view.label} — {view.topic()}（{rel_time(view.last_ts)}）"
                )
            progress.extend(view.render(cfg.get("per_session_messages", 6)))
            progress.append("")
    else:
        progress.append("- 还没有读到任何会话记录。先运行 `agentlink sync`。")
        progress.append("")

    todos = _notes(store, "todo") + _todo_from_requests(events) + _scan(
        events, TODO_HINT, SECTION_LIMITS["todos"]
    )
    todo_lines = ["## 4. 进行中的任务 / 待办", ""]
    todo_lines.extend(f"- {t}" for t in _dedupe(todos)[: SECTION_LIMITS["todos"]])
    if len(todo_lines) == 2:
        todo_lines.append("- （未从对话中识别到明确待办，建议核对上面的对话或写入 `agentlink note --kind todo`）")
    todo_lines.append("")

    decisions = _notes(store, "decision") + _scan(events, DECISION_HINT, SECTION_LIMITS["decisions"])
    dec_lines = ["## 5. 已确认的决定与约束", ""]
    dec_lines.extend(f"- {d}" for d in _dedupe(decisions)[: SECTION_LIMITS["decisions"]])
    if len(dec_lines) == 2:
        dec_lines.append("- （暂无）")
    dec_lines.append("")

    body.append((2, progress))
    body.append((2, todo_lines))
    body.append((3, dec_lines))

    recent = events[-6:]
    if recent:
        step = ["## 6. 最近的原始动作（回放用）", ""]
        for ev in recent:
            who = {"user": "用户", "assistant": "助手", "tool": "工具"}.get(ev.role, ev.role)
            step.append(f"- [{who}] {truncate_width(ev.text.replace(chr(10), ' '), 200)}")
        step.append("")
        body.append((4, step))

    footer = [
        "---",
        "生成命令：`agentlink brief`；刷新：`agentlink sync`；"
        "写进度：`agentlink note \"...\" --kind todo|decision|note`。",
        "",
    ]

    def assemble(selected: list[tuple[int, list[str]]]) -> str:
        parts = list(header)
        for _, lines in selected:
            parts.extend(lines)
        parts.extend(footer)
        return "\n".join(parts).rstrip() + "\n"

    selected = [(p, l) for p, l in body]
    while width(assemble(selected)) > budget and selected:
        # drop the lowest-priority (highest number) block, keeping order otherwise
        drop_idx = max(range(len(selected)), key=lambda i: selected[i][0])
        selected.pop(drop_idx)

    if width(assemble(selected)) > budget:
        # last resort: cut every session down to its two newest bullets
        for _, lines in selected:
            for i, line in enumerate(lines):
                if line.startswith("- ") and len(line) > 200:
                    lines[i] = truncate_width(line, 200)

    text = assemble(selected)
    if width(text) > budget:
        text = _hard_trim(text, budget)
    return text


def _dedupe(items: list[str]) -> list[str]:
    out, seen = [], set()
    for item in items:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _hard_trim(text: str, budget: int) -> str:
    lines = text.splitlines()
    while lines and width("\n".join(lines)) > budget:
        # drop the longest remaining content line
        idx = max(range(len(lines)), key=lambda i: width(lines[i]))
        lines.pop(idx)
    return "\n".join(lines).rstrip() + "\n"


def build_handoff(store: Store, target: str, budget: int | None = None) -> str:
    """A short pointer file an agent can read at the start of a fresh session."""
    label = AGENT_LABELS.get(target, target)
    brief = build_context(store, budget=budget)
    return (
        f"# 交接说明（目标：{label}）\n\n"
        "本项目在 DSH / Codex / Claude 之间切换过。继续之前请先读下面的项目速览，"
        "它汇总了其他 agent 的对话结论、待办与最近改动。\n\n"
        "```markdown\n" + brief + "```\n"
    )