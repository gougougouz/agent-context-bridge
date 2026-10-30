"""Command line interface: agentlink <sync|brief|note|status|show|handoff|install|doctor>."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from . import summary as summary_mod
from .digest import (
    build_context,
    build_digest_payload,
    build_handoff,
    estimate_tokens,
    group_sessions,
)
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
from .i18n import set_lang, t
from .util import human_size, now_iso, parse_since, rel_time, width


# --------------------------------------------------------------------- helpers


def _out(text: str = "") -> None:
    sys.stdout.write(text + "\n")


def _err(text: str = "") -> None:
    sys.stderr.write(text + "\n")


def _setup_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def resolve_root(explicit: str | None) -> Path:
    """--root wins; otherwise the nearest .agentlink/ above cwd; finally cwd."""
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_dir():
            raise SystemExit(f"目录不存在：{path}")
        return path
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
    results = sync_sources(store, agents=_agent_names(getattr(args, "agent", None)))
    sessions = sum(r.sessions for r in results)
    new_events = sum(r.new_events for r in results)
    _out(t("init.header", dir=store.dir))
    if sessions:
        for r in results:
            if not r.sessions:
                continue
            _out(t("init.agent", agent=AGENT_LABELS.get(r.agent, r.agent),
                   sessions=r.sessions, events=r.new_events))
        _out(t("init.totals", sessions=sessions, events=new_events))
    else:
        _out(t("init.empty"))
    if getattr(args, "hook", False):
        touched = write_pointers(store.root, store.state.get("last_sync", ""))
        _out("")
        for path in touched:
            _out(t("init.hook", path=path))
    _out("")
    _out(t("init.next.hook") if getattr(args, "hook", False) else t("init.next"))
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


def _parse_since_or_die(value: str | None):
    if not value:
        return None
    parsed = parse_since(value)
    if parsed is None:
        raise SystemExit(f"看不懂的时间表达式：{value}（试试 3d / 12h / today / 2026-10-28）")
    return parsed


def cmd_brief(args) -> int:
    store = open_store(args)
    if not args.no_sync:
        sync_sources(store, agents=_agent_names(args.agent))
    since = _parse_since_or_die(getattr(args, "since", None))
    events = store.events(limit=args.max_events or 400, since=since)
    context = build_context(
        store,
        budget=args.budget,
        include_git=not args.no_git,
        max_events=args.max_events,
        budget_tokens=args.budget_tokens,
        full=args.full,
        with_ai=not args.no_ai,
        since=since,
    )
    store.context_path.write_text(context, encoding="utf-8", newline="\n")
    store.state["last_brief_ts"] = now_iso()
    store.save_state()
    if getattr(args, "out", None):
        from .util import atomic_write_text

        atomic_write_text(Path(args.out), context)
        _err(t("brief.saved", path=args.out))
    if getattr(args, "copy", False):
        from .util import copy_to_clipboard

        ok_copy = copy_to_clipboard(context)
        _err(t("brief.copied", n=len(context)) if ok_copy else t("brief.copy_failed"))
    tokens = estimate_tokens(context)
    if args.json:
        views = group_sessions(events)
        _out(json.dumps({
            "root": str(store.root),
            "sessions": len(views),
            "events": len(events),
            "tokens": tokens,
            "context": context,
        }, ensure_ascii=False, indent=2))
        return 0
    sys.stdout.write(context)
    if args.stats:
        ai = summary_mod.load(store)
        pending = summary_mod.new_events_since(store, ai) if ai else []
        if not ai:
            ai_state = t("cli.stats.ai_none")
        elif pending:
            ai_state = t("cli.stats.ai_fresh", n=len(pending))
        else:
            ai_state = t("cli.stats.ai_ok")
        _err("")
        _err(t("cli.stats", tokens=tokens, ai=ai_state, path=store.context_path))
    return 0


def cmd_digest(args) -> int:
    """Print the compact input an agent needs in order to write summary.json."""
    store = open_store(args)
    if not args.no_sync:
        sync_sources(store, agents=_agent_names(args.agent))
    cfg = store.config["digest"].get("ai") or {}
    max_tokens = args.max_tokens or int(cfg.get("max_input_tokens") or 6000)
    payload = build_digest_payload(
        store,
        max_tokens=max_tokens,
        since_last=not args.full,
        max_events=args.max_events or 400,
    )
    text = json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.out:
        from .util import atomic_write_text

        atomic_write_text(Path(args.out), text + "\n")
        _err(t("digest.saved", path=args.out, tokens=estimate_tokens(text), mode=payload["mode"]))
    else:
        sys.stdout.write(text + "\n")
    return 0


def cmd_summary(args) -> int:
    store = open_store(args)
    if args.action == "show":
        data = summary_mod.load(store)
        if not data:
            _out("还没有 AI 摘要。运行 `agentlink digest` 拿到材料后，"
                 "让 agent 写一份 JSON 再 `agentlink summary apply`。")
            return 0
        sys.stdout.write("\n".join(summary_mod.render(store, data)) + "\n")
        return 0
    if args.action == "clear":
        path = summary_mod.path_for(store)
        if path.exists():
            path.unlink()
            _out(f"已删除 {path}")
        else:
            _out("没有可删除的摘要。")
        return 0
    # apply
    if args.file and args.file != "-":
        raw = Path(args.file).read_text(encoding="utf-8")
    else:
        raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"JSON 解析失败：{exc}") from None
    preview = summary_mod.normalize(payload)
    if not (preview["project"]["goal"] or preview["sessions"]
            or any(preview["state"].values()) or preview["notes_for_next_agent"]):
        raise SystemExit("这份摘要里没有可用的内容：至少要有 project.goal、state 或 sessions 之一。")
    data = summary_mod.save(store, payload)
    pending, count = summary_mod.needs_refresh(
        store, data, int((store.config["digest"].get("ai") or {}).get("min_new_events") or 6))
    _out(f"已保存 AI 摘要：{summary_mod.path_for(store)}")
    window = data["window"]
    if window["from"] and window["to"]:
        _out(t("summary.cover", frm=window["from"], to=window["to"],
               sessions=len(data["sessions"]), todos=len(data["state"]["in_progress"])))
    else:
        _out(t("summary.cover.open", ts=data.get("generated_at") or "-",
               sessions=len(data["sessions"]), todos=len(data["state"]["in_progress"])))
    if pending:
        _out(f"提示：此后还有 {count} 条新记录，需要时可以再整理一次。")
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

    _out(t("cli.status.project", root=store.root))
    _out(t("cli.status.state", dir=store.dir))
    last = rel_time(stats["last_sync"]) if stats["last_sync"] else t("cli.status.never")
    _out(t("cli.status.records", events=stats["events"], sessions=stats["sessions"], sync=last))
    ai = summary_mod.load(store)
    if ai:
        pending, count = summary_mod.needs_refresh(
            store, ai, int((store.config["digest"].get("ai") or {}).get("min_new_events") or 6))
        verdict = t("cli.status.suggest") if pending else t("cli.status.enough")
        _out(t("cli.status.ai", when=rel_time(ai.get("generated_at") or ""),
               n=count, verdict=verdict))
    else:
        _out(t("cli.status.ai.none"))
    if store.context_path.exists():
        cached = store.context_path.read_text(encoding="utf-8", errors="replace")
        _out(t("cli.status.brief", tokens=estimate_tokens(cached),
               name=store.context_path.name))
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
    since = _parse_since_or_die(getattr(args, "since", None))
    events = store.events(limit=args.max_events or 2000, since=since)
    if args.session:
        events = [e for e in events if e.session.startswith(args.session)]
    if args.agent:
        events = [e for e in events if e.agent == args.agent]
    if args.role:
        events = [e for e in events if e.role == args.role]
    if not events:
        _out(t("show.empty"))
        return 1
    for ev in events[-args.limit:]:
        who = {"user": t("role.user"), "assistant": t("role.assistant"),
               "tool": t("role.tool")}.get(ev.role, ev.role)
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
    _out(t("install.header", name=SKILL_NAME))
    for r in results:
        _out(f"  - {AGENT_LABELS.get(r['agent'], r['agent'])}: {r['dir']}")
    if args.path:
        from .install import ensure_path_entry

        added = ensure_path_entry(repo_root() / "bin")
        _out(t("install.path", state=t("install.path.added") if added else t("install.path.exists"),
               path=repo_root() / "bin"))
    _out("")
    _out(t("install.restart", name=SKILL_NAME))
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
        state = t("doctor.skill.ok") if skill.exists() else t("doctor.skill.missing")
        label = AGENT_LABELS.get(name, name)
        _out(t("doctor.skill.line", label=label, state=state, path=home / SKILL_NAME))
        available = "OK" if src.available() else t("doctor.dir.missing")
        _out(t("doctor.dir.line", label="", state=available, path=src.root_dir()))
    root = resolve_root(getattr(args, "root", None))
    store = Store(root)
    _out("")
    _out(f"当前项目    : {root}")
    _out(f"状态目录    : {store.dir} ({'存在' if store.exists else '未初始化，运行 agentlink init'})")
    if store.exists:
        stats = store.stats()
        _out(f"记录        : {stats['events']} 条，上次同步 {stats['last_sync'] or '从未'}")
    _out("")
    _out(t("doctor.ready") if ok else t("doctor.missing"))
    return 0 if ok else 1


# ------------------------------------------------------------------------ main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentlink",
        description="在 DSH / Codex / Claude 之间同步项目上下文与进度。",
    )
    parser.add_argument("--version", action="version", version=f"agentlink {__version__}")
    parser.add_argument("--lang", choices=["zh", "en"], help="输出语言（默认跟随系统）")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, root=True):
        if root:
            p.add_argument("--root", help="项目根目录（默认向上查找 .agentlink，否则用当前目录）")
        p.add_argument("--agent", help="只处理这些 agent，逗号分隔：dsh,codex,claude")
        p.add_argument("--budget", type=int, help="速览的最大显示宽度（一般不直接用，见 --budget-tokens）")
        p.add_argument("--max-events", type=int, help="参与摘要的最近记录条数")

    p = sub.add_parser("init", help="在项目里初始化 .agentlink，抽取历史会话")
    common(p)
    p.add_argument("--hook", action="store_true",
                   help="同时在 AGENTS.md / CLAUDE.md 写入提示段")
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
    p.add_argument("--no-ai", action="store_true", help="不合并 AI 摘要，只用规则结果")
    p.add_argument("--budget-tokens", type=int, help="速览的 token 预算（默认 1500）")
    p.add_argument("--full", action="store_true", help="用完整预算（默认 6000 tokens）")
    p.add_argument("--stats", action="store_true", help="末尾附带 token 与摘要状态")
    p.add_argument("--out", help="同时把速览写到这个文件")
    p.add_argument("--copy", action="store_true", help="把速览复制到剪贴板")
    p.add_argument("--since", help="只看这段时间：3d / 12h / 2026-10-28 / today")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_brief)

    p = sub.add_parser("digest", help="输出给 agent 做 AI 摘要的紧凑材料（增量，默认封顶 6000 tokens）")
    common(p)
    p.add_argument("--no-sync", action="store_true")
    p.add_argument("--full", action="store_true", help="不用已有摘要，输出完整会话卡片")
    p.add_argument("--max-tokens", type=int, help="材料上限，默认 6000")
    p.add_argument("--out", help="写入文件而不是打印")
    p.add_argument("--pretty", action="store_true")
    p.set_defaults(func=cmd_digest)

    p = sub.add_parser("summary", help="应用/查看/清除 agent 写的结构化摘要")
    p.add_argument("action", choices=["apply", "show", "clear"])
    p.add_argument("--file", "-f", help="JSON 文件；- 或省略则读 stdin")
    p.add_argument("--root")
    p.set_defaults(func=cmd_summary)

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
    p.add_argument("--since", help="只看这段时间：3d / 12h / today")
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
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        parser.print_help()
        return 0
    # --lang may appear before or after the subcommand: lift it out of argv
    lang_flag = None
    clean = []
    skip = False
    for i, item in enumerate(argv):
        if skip:
            skip = False
            continue
        if item == "--lang" and i + 1 < len(argv):
            lang_flag = argv[i + 1]
            skip = True
            continue
        if item.startswith("--lang="):
            lang_flag = item.split("=", 1)[1]
            continue
        clean.append(item)
    argv = clean
    set_lang(lang_flag or os.environ.get("AGENTLINK_LANG"))
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        return 130
    except SystemExit:
        raise
    except BrokenPipeError:
        return 0
    except Exception as exc:  # noqa: BLE001 - one clean line beats a traceback
        if os.environ.get("AGENTLINK_DEBUG"):
            raise
        print(f"agentlink: {exc}", file=sys.stderr)
        if isinstance(exc, FileNotFoundError):
            print("  hint: run `agentlink doctor` to check paths and dependencies", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())