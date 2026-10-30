"""Command line interface: agentlink <sync|brief|note|status|show|handoff|install|doctor>."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .digest import build_context, build_handoff, group_sessions
from .gitinfo import find_git
from .install import (
    MARK_BEGIN,
    MARK_END,
    POINTER_FILES,
    SKILL_NAME,
    install as install_skills,
    remove_pointers,
    repo_root,
    skill_home,
    write_pointers,
)
from .model import AGENTS, AGENT_LABELS
from .sources import SOURCES, discover_sessions, sync as sync_sources
from .store import Store
from .util import human_size, rel_time, width


# --------------------------------------------------------------------- helpers


def _out(text: str = "") -> None:
    sys.stdout.write(text + "\n")


def _setup_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def resolve_root(explicit: str | None) -> Path:
    """--root wins; otherwise the nearest .agentlink/ above cwd; finally cwd."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    cwd = Path.cwd().resolve()
    for candidate in [cwd, *cwd.parents]:
        if (candidate / ".agentlink" / "config.json").exists():
            return candidate
    return cwd


def open_store(args) -> Store:
    root = resolve_root(getattr(args, "root", None))
    store = Store(root).ensure()
    return store


def _agent_names(value: str | None) -> list[str]:
    if not value:
        return list(AGENTS)
    names = [v.strip() for v in value.split(",") if v.strip()]
    bad = [n for n in names if n not in SOURCES]
    if bad:
        raise SystemExit(f"未知 agent: {', '.join(bad)}（可选: {', '.join(SOURCES)}）")
    return names


# -------------------------------------------------------------------- commands


def cmd_init(args) -> int:
    store = open_store(args)
    sessions = discover_sessions(store)
    per_agent: dict[str, int] = {}
    for s in sessions:
        per_agent[s.agent] = per_agent.get(s.agent, 0) + 1
    _out(f"已初始化状态目录：{store.dir}")
    if per_agent:
        _out("发现历史会话：")
        for agent, count in sorted(per_agent.items()):
            _out(f"  - {AGENT_LABELS.get(agent, agent)}：{count} 个")
    else:
        _out("暂未发现本项目的历史会话（先在该项目里和其他 agent 聊几句，再运行 agentlink sync）。")
    _out("")
    _out("下一步：`agentlink sync` 抽取记录，`agentlink brief` 生成上下文速览。")
    return 0


def cmd_sync(args) -> int:
    store = open_store(args)
    before = len(store.events())
    results = sync_sources(store, agents=_agent_names(args.agent))
    context = build_context(store, budget=args.budget, include_git=not args.no_git)
    store.context_path.write_text(context, encoding="utf-8", newline="\n")
    store.state["last_brief"] = True
    store.save_state()

    if args.json:
        payload = {
            "root": str(store.root),
            "results": [
                {
                    "agent": r.agent,
                    "label": AGENT_LABELS.get(r.agent, r.agent),
                    "sessions": r.sessions,
                    "new_events": r.new_events,
                    "skipped": r.skipped,
                    "errors": r.errors,
                }
                for r in results
            ],
            "journal_total": len(store.events()),
            "context": str(store.context_path),
            "context_width": width(context),
        }
        _out(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    total_new = 0
    for r in results:
        label = AGENT_LABELS.get(r.agent, r.agent)
        if r.errors and not r.sessions:
            _out(f"  {label:<14} 跳过：{r.errors[0]}")
            continue
        total_new += r.new_events
        _out(f"  {label:<14} {r.sessions} 个会话，新增 {r.new_events} 条记录")
        for err in r.errors[:3]:
            _out(f"      ! {err}")
    _out("")
    _out(f"记录累计 {len(store.events())} 条（本次 +{total_new}，之前 {before}），"
         f"上下文速览 {human_size(len(context.encode('utf-8')))} → {store.context_path}")
    if args.quiet:
        return 0
    return 0


def cmd_brief(args) -> int:
    store = open_store(args)
    if not args.no_sync:
        sync_sources(store, agents=_agent_names(args.agent))
    events = store.events(limit=args.max_events or 400)
    context = build_context(store, budget=args.budget, include_git=not args.no_git,
                            max_events=args.max_events)
    store.context_path.write_text(context, encoding="utf-8", newline="\n")
    store.save_state()
    if args.json:
        views = group_sessions(events)
        _out(json.dumps({
            "root": str(store.root),
            "sessions": len(views),
            "events": len(events),
            "context": context,
        }, ensure_ascii=False, indent=2))
        return 0
    sys.stdout.write(context)
    return 0


def cmd_note(args) -> int:
    store = open_store(args)
    text = " ".join(args.text).strip()
    if not text:
        raise SystemExit("note 内容不能为空")
    rec = store.add_note(text, kind=args.kind)
    _out(f"已记录 [{args.kind}]：{rec['text']}")
    return 0


def cmd_status(args) -> int:
    store = open_store(args)
    sessions = discover_sessions(store)
    per_agent: dict[str, list] = {}
    for s in sessions:
        per_agent.setdefault(s.agent, []).append(s)
    stats = store.stats()

    if args.json:
        _out(json.dumps({
            "root": str(store.root),
            "state_dir": str(store.dir),
            "journal_events": stats["events"],
            "sessions_known": stats["sessions"],
            "last_sync": stats["last_sync"],
            "agents": {
                a: {"sessions": len(v), "latest": max((s.modified for s in v), default=0)}
                for a, v in per_agent.items()
            },
        }, ensure_ascii=False, indent=2))
        return 0

    _out(f"项目：{store.root}")
    _out(f"状态目录：{store.dir}")
    _out(f"记录：{stats['events']} 条；已知会话 {stats['sessions']} 个；"
         f"上次同步 {rel_time(stats['last_sync']) if stats['last_sync'] else '从未'}")
    _out("")
    for name in AGENTS:
        src = SOURCES[name]
        label = AGENT_LABELS.get(name, name)
        if not src.available():
            _out(f"  {label:<14} 未安装/无数据（{src.root_dir()}）")
            continue
        found = per_agent.get(name, [])
        if not found:
            _out(f"  {label:<14} 有目录，但本项目暂无会话")
            continue
        latest = max(s.modified for s in found)
        from datetime import datetime

        when = datetime.fromtimestamp(latest).strftime("%Y-%m-%d %H:%M")
        _out(f"  {label:<14} {len(found)} 个会话，最近 {when}")
    return 0


def cmd_show(args) -> int:
    store = open_store(args)
    events = store.events(limit=args.max_events or 2000)
    if args.session:
        events = [e for e in events if e.session.startswith(args.session)]
    if args.agent:
        events = [e for e in events if e.agent == args.agent]
    if args.role:
        events = [e for e in events if e.role == args.role]
    if not events:
        _out("没有匹配的记录。先运行 `agentlink sync`。")
        return 1
    for ev in events[-args.limit:]:
        who = {"user": "用户", "assistant": "助手", "tool": "工具"}.get(ev.role, ev.role)
        head = f"[{ev.agent} {ev.session[:8]} {who}] "
        body = ev.text if args.full else ev.text.replace("\n", " ")[: args.width]
        _out(head + body)
    return 0


def cmd_handoff(args) -> int:
    store = open_store(args)
    sync_sources(store, agents=_agent_names(args.agent))
    text = build_handoff(store, args.to, budget=args.budget)
    store.handoff_path.write_text(text, encoding="utf-8", newline="\n")
    _out(text)
    return 0


def cmd_hook(args) -> int:
    store = open_store(args)
    files = tuple(f.strip() for f in args.files.split(",") if f.strip()) if args.files else POINTER_FILES
    if args.remove:
        removed = remove_pointers(store.root, files)
        if removed:
            _out("已移除上下文提示段：")
            for path in removed:
                _out(f"  - {path}")
        else:
            _out("没有找到 agentlink 写入的提示段。")
        return 0
    sync_sources(store, agents=_agent_names(args.agent))
    synced = store.state.get("last_sync", "")
    touched = write_pointers(store.root, synced, files)
    _out("已写入/刷新上下文提示段：")
    for path in touched:
        _out(f"  - {path}")
    _out("")
    _out(f"提示段内容：读到 `{MARK_BEGIN}` 与 `{MARK_END}` 之间的说明，"
         "让 agent 先看 .agentlink/context.md。")
    return 0


def cmd_install(args) -> int:
    agents = _agent_names(args.agents)
    results = install_skills(agents)
    _out(f"已把 {SKILL_NAME} 安装到：")
    for r in results:
        _out(f"  - {AGENT_LABELS.get(r['agent'], r['agent'])}：{r['dir']}")
    if args.path:
        from .install import ensure_path_entry

        added = ensure_path_entry(repo_root() / "bin")
        _out(f"PATH：{'已追加' if added else '已存在或跳过'} {repo_root() / 'bin'}")
    _out("")
    _out("重启对应客户端（或新开会话）后，技能目录里会出现 agent-context-bridge。")
    return 0


def cmd_doctor(args) -> int:
    ok = True
    _out(f"agentlink {__version__}")
    _out(f"Python      : {sys.executable} ({sys.version.split()[0]})")
    _out(f"仓库        : {repo_root()}")
    try:
        import zstandard

        _out(f"zstandard   : {zstandard.__version__}")
    except Exception:
        ok = False
        _out("zstandard   : 缺失 → python -m pip install zstandard（读取 DSH 会话必需）")
    git = find_git()
    _out(f"git         : {git or '未找到（仅影响进度快照）'}")
    _out("")
    for name in AGENTS:
        src = SOURCES[name]
        home = skill_home(name)
        skill = home / SKILL_NAME / "SKILL.md"
        _out(f"{AGENT_LABELS.get(name, name):<14} 会话目录 {'OK ' if src.available() else '缺失'} "
             f"{src.root_dir()}  |  技能 {'已安装' if skill.exists() else '未安装'}")
    root = resolve_root(getattr(args, "root", None))
    store = Store(root)
    _out("")
    _out(f"当前项目    : {root}")
    _out(f"状态目录    : {store.dir} ({'存在' if store.exists else '未初始化，运行 agentlink init'})")
    if store.exists:
        stats = store.stats()
        _out(f"记录        : {stats['events']} 条，上次同步 {stats['last_sync'] or '从未'}")
    _out("")
    _out("结论：" + ("环境就绪" if ok else "还有依赖缺失，见上面标记"))
    return 0 if ok else 1


# ------------------------------------------------------------------------ main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentlink",
        description="在 DSH / Codex / Claude 之间同步项目上下文与进度。",
    )
    parser.add_argument("--version", action="version", version=f"agentlink {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, root=True):
        if root:
            p.add_argument("--root", help="项目根目录（默认向上查找 .agentlink，否则用当前目录）")
        p.add_argument("--agent", help="只处理这些 agent，逗号分隔：dsh,codex,claude")
        p.add_argument("--budget", type=int, help="速览的最大显示宽度（默认取配置 24000）")
        p.add_argument("--max-events", type=int, help="参与摘要的最近记录条数")

    p = sub.add_parser("init", help="在项目里初始化 .agentlink 并探测历史会话")
    common(p)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("sync", help="把三家 agent 的新记录抽到 .agentlink/ 并刷新 context.md")
    common(p)
    p.add_argument("--no-git", action="store_true", help="不读取 git 状态")
    p.add_argument("--json", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("brief", help="输出项目上下文速览（默认先 sync）")
    common(p)
    p.add_argument("--no-sync", action="store_true", help="只读已有记录，不扫描新内容")
    p.add_argument("--no-git", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_brief)

    p = sub.add_parser("note", help="写入一条人工进度/决定/待办")
    p.add_argument("text", nargs="+", help="内容")
    p.add_argument("--kind", choices=["note", "todo", "decision", "done"], default="note")
    p.add_argument("--root")
    p.set_defaults(func=cmd_note)

    p = sub.add_parser("status", help="查看数据源、会话数与上次同步时间")
    common(p)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("show", help="查看原始记录（可按会话/agent/角色过滤）")
    common(p)
    p.add_argument("--session", help="会话 id 前缀")
    p.add_argument("--role", choices=["user", "assistant", "tool"])
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--width", type=int, default=300)
    p.add_argument("--full", action="store_true")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("handoff", help="生成给指定 agent 的交接说明")
    common(p)
    p.add_argument("--to", choices=list(AGENTS), default="codex")
    p.set_defaults(func=cmd_handoff)

    p = sub.add_parser("hook", help="在 AGENTS.md / CLAUDE.md 里写入上下文提示段")
    common(p)
    p.add_argument("--files", help="逗号分隔的文件名，默认 AGENTS.md,CLAUDE.md")
    p.add_argument("--remove", action="store_true", help="移除提示段")
    p.set_defaults(func=cmd_hook)

    p = sub.add_parser("install", help="把技能装进 DSH / Codex / Claude 的技能目录")
    p.add_argument("--agents", default=",".join(AGENTS), help="默认三家全装")
    p.add_argument("--path", action="store_true", help="把仓库 bin/ 追加到用户 PATH")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("doctor", help="自检：依赖、会话目录、技能安装状态")
    common(p)
    p.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    _setup_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        return 130
    except SystemExit:
        raise
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())