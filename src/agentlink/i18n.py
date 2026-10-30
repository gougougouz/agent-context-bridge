"""Tiny message catalog: Chinese and English, chosen once per process.

Language: AGENTLINK_LANG=zh|en, otherwise the system locale decides
(Chinese locale → zh, anything else → en).
"""

from __future__ import annotations

import locale
import os

_ZH, _EN = "zh", "en"

_STRINGS = {
    # agents
    "agent.dsh": ("DSH", "DSH"),
    "agent.codex": ("Codex / ChatGPT", "Codex (ChatGPT)"),
    "agent.claude": ("Claude Code", "Claude Code"),
    # relative time
    "time.now": ("刚刚", "just now"),
    "time.min": ("{n} 分钟前", "{n} min ago"),
    "time.hour": ("{n} 小时前", "{n} h ago"),
    "time.day": ("{n} 天前", "{n} d ago"),
    # brief frame
    "brief.title": ("# 项目上下文速览 · {name}", "# Project context · {name}"),
    "brief.coverage": (
        "> 生成于 {ts}；覆盖 {sessions} 个会话 / {events} 条记录（{agents}；{span}）。",
        "> Generated {ts}; {sessions} sessions / {events} records ({agents}; {span}).",
    ),
    "brief.purpose": (
        "> 供接手者对齐：当前任务、AI 摘要、时间线、会话卡片、待办与决定。",
        "> What a new agent needs: current asks, the handoff summary, timeline, "
        "session cards, TODOs and decisions.",
    ),
    "brief.hint": (
        "> 细节：`agentlink show --session <id>`；刷新：`agentlink sync`。",
        "> Details: `agentlink show --session <id>`; refresh: `agentlink sync`.",
    ),
    "brief.footer": (
        '写进度：`agentlink note "..." --kind todo|decision`　'
        "整理摘要：`agentlink digest` → 写 JSON → `agentlink summary apply`。",
        'Record progress: `agentlink note "..." --kind todo|decision`　'
        "Summarize: `agentlink digest` → write JSON → `agentlink summary apply`.",
    ),
    # sections
    "sec.snapshot": ("项目快照", "Project snapshot"),
    "sec.ai": ("接手摘要（AI 整理）", "Handoff summary (written by an agent)"),
    "sec.tasks": ("当前任务（最近的用户请求，新→旧）", "Current asks (newest first)"),
    "sec.delta": ("上次速览之后的新进展", "Since the last brief"),
    "sec.timeline": ("统一时间线（三家合并，最近的在后）", "Timeline (all agents, oldest first)"),
    "sec.cards": ("各会话卡片", "Session cards"),
    "sec.todos": ("进行中的任务 / 待办", "Open work / TODOs"),
    "sec.decisions": ("已确认的决定与约束", "Decisions & constraints"),
    "sec.replay": ("对话回放（节选）", "Replay (excerpts)"),
    # separators and misc
    "sep.semi": ("；", "; "),
    "sep.list": ("、", ", "),
    "span.none": ("无记录", "no records"),
    "card.heading": ("{head}（最后活动 {t}）", "{head} (last active {t})"),
    "handoff.title": ("# 交接说明（目标：{label}）", "# Handoff for {label}"),
    "handoff.body": (
        "本项目在 DSH / Codex / Claude 之间切换过。继续之前请先读下面的项目速览，"
        "它汇总了其他 agent 的对话结论、待办与最近改动。",
        "This project has moved between DSH, Codex and Claude. Read the brief below "
        "before continuing: it collects the other agents' conclusions, the TODOs and "
        "the latest changes.",
    ),
    # cards
    "card.ask": ("诉求", "Ask"),
    "card.conclusion": ("最后结论", "Last conclusion"),
    "card.files": ("涉及文件", "Files"),
    "card.commands": ("关键命令", "Commands"),
    "card.nochat": ("（该会话只有工具调用，没有对话内容）", "(tool calls only, no conversation)"),
    "card.last_active": ("最后活动 {t}", "last active {t}"),
    # roles and placeholders
    "role.user": ("用户", "user"),
    "role.assistant": ("助手", "assistant"),
    "role.tool": ("工具", "tool"),
    "empty.no_messages": ("（暂无可用的用户消息）", "(no user messages yet)"),
    "empty.no_sessions": (
        "- 还没有读到任何会话记录。先运行 `agentlink sync`。",
        "- No transcripts yet. Run `agentlink sync`.",
    ),
    "empty.no_todos": (
        '- （未识别到明确待办；可写入 `agentlink note "..." --kind todo`）',
        '- (no clear TODO found; add one with `agentlink note "..." --kind todo`)',
    ),
    "empty.none": ("（暂无）", "(none)"),
    "delta.head": (
        "- 上次速览（{t}）之后新增 {n} 条记录",
        "- {n} new records since the last brief ({t})",
    ),
    # snapshot
    "snap.root": ("项目根目录", "Project root"),
    "snap.git": ("Git", "Git"),
    "snap.commits": ("最近提交", "Recent commits"),
    "snap.dirty": ("未提交改动 {n} 项", "{n} uncommitted changes"),
    "snap.clean": ("工作区干净", "working tree clean"),
    "snap.nogit": ("不是 Git 仓库（进度以会话与 note 为准）", "not a git repo (progress lives in transcripts and notes)"),
    # ai summary
    "ai.generated": ("生成于 {t}", "Generated {t}"),
    "ai.source": ("来源：{g}", "by {g}"),
    "ai.stale": ("；**此后有新对话，建议重新整理**", "; **newer records exist — refresh when convenient**"),
    "ai.unknown_time": ("生成时间未知", "generation time unknown"),
    "ai.goal": ("项目目标", "Goal"),
    "ai.status": ("当前状态", "Status"),
    "ai.stack": ("技术栈", "Stack"),
    "ai.in_progress": ("正在做", "In progress"),
    "ai.next": ("下一步", "Next"),
    "ai.blocked": ("卡住/待确认", "Blocked / open questions"),
    "ai.done": ("已完成", "Done"),
    "ai.decisions": ("已定决策", "Decisions"),
    "ai.risks": ("风险", "Risks"),
    "ai.sessions": ("各会话结论", "Session outcomes"),
    "ai.open": ("未完成", "open"),
    "ai.notes": ("给接手者的提醒", "Notes for the next agent"),
    "ai.empty": (
        "- （摘要为空：重新运行 `agentlink digest` 后由 agent 生成）",
        "- (empty summary — run `agentlink digest` and let an agent write it)",
    ),
    # cli
    "cli.stats": (
        "[agentlink] 约 {tokens} tokens；AI 摘要 {ai}；文件 {path}",
        "[agentlink] ~{tokens} tokens; AI summary {ai}; file {path}",
    ),
    "cli.stats.ai_fresh": ("有，落后 {n} 条", "present, {n} records behind"),
    "cli.stats.ai_ok": ("有，已是最新", "present and up to date"),
    "cli.stats.ai_none": ("无", "none"),
    "cli.status.project": ("项目：{root}", "Project: {root}"),
    "cli.status.state": ("状态目录：{dir}", "State dir: {dir}"),
    "cli.status.records": (
        "记录：{events} 条；已知会话 {sessions} 个；上次同步 {sync}",
        "Records: {events}; sessions known: {sessions}; last sync: {sync}",
    ),
    "cli.status.never": ("从未", "never"),
    "cli.status.ai": (
        "AI 摘要：{when} 生成；累计 {n} 条新记录{verdict}",
        "AI summary: generated {when}; {n} new records{verdict}",
    ),
    "cli.status.ai.none": (
        "AI 摘要：无（`agentlink digest` → agent 整理 → `agentlink summary apply`）",
        "AI summary: none (`agentlink digest` → agent writes JSON → `agentlink summary apply`)",
    ),
    "cli.status.suggest": ("，建议重新整理", " — worth refreshing"),
    "cli.status.enough": ("，仍够用", " — still good"),
    "cli.status.brief": (
        "缓存的速览：约 {tokens} tokens（{name}）",
        "Cached brief: ~{tokens} tokens ({name})",
    ),
    # install / doctor
    "install.header": ("已把 {name} 安装到：", "Installed {name} into:"),
    "install.path": ("PATH：{state} {path}", "PATH: {state} {path}"),
    "install.path.added": ("已追加", "added"),
    "install.path.exists": ("已存在或跳过", "already there"),
    "install.restart": (
        "重启对应客户端（或新开会话）后，技能目录里会出现 {name}。",
        "Restart the tools (or open a new session) and {name} will be available.",
    ),
    "doctor.ready": ("结论：环境就绪", "Result: ready"),
    "doctor.missing": ("结论：还有依赖缺失，见上面标记", "Result: some dependencies are missing (see above)"),
    "show.empty": (
        "没有匹配的记录。先运行 `agentlink sync`。",
        "No matching records. Run `agentlink sync` first.",
    ),
}

_LANG = ""


def lang() -> str:
    global _LANG
    if _LANG:
        return _LANG
    explicit = (os.environ.get("AGENTLINK_LANG") or "").strip().lower()
    if explicit.startswith("en"):
        _LANG = _EN
    elif explicit.startswith("zh"):
        _LANG = _ZH
    else:
        try:
            name = (locale.getlocale()[0] or os.environ.get("LANG") or "").lower()
        except (ValueError, TypeError):
            name = ""
        _LANG = _ZH if ("zh" in name or "chinese" in name) else _EN
    return _LANG


def set_lang(value: str | None) -> None:
    global _LANG
    if not value:
        return
    value = value.strip().lower()
    _LANG = _ZH if value.startswith("zh") else _EN


def t(key: str, **kwargs) -> str:
    zh, en = _STRINGS.get(key, (key, key))
    text = zh if lang() == _ZH else en
    if not kwargs:
        return text
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError):
        return text