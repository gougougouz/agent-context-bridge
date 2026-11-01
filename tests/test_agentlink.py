"""Offline tests for the three transcript readers and the digest builder.

Run with:  python -m unittest discover -s tests -v
No real agent data is touched: every fixture is written into a temp directory.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentlink.digest import build_context, group_sessions  # noqa: E402
from agentlink.model import Event  # noqa: E402
from agentlink.sources import sync  # noqa: E402
from agentlink.store import Store  # noqa: E402
from agentlink.util import claude_project_dirname, dsh_session_dirname, width  # noqa: E402

PROJECT = ""  # set per test from the temp project root


def _jsonl(records) -> str:
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n"


class AgentlinkTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="agentlink-test-"))
        self.home = self.tmp / "home"
        self.project = self.tmp / "project"
        self.state = self.tmp / "state"
        global PROJECT
        # resolve(): Windows temp dirs can come back as 8.3 short paths
        # (RUNNER~1) while the store root is the long form.
        PROJECT = str((self.tmp / 'project').resolve())
        for p in (self.home, self.project, self.state):
            p.mkdir(parents=True, exist_ok=True)
        self._env = {}
        self._patch_env("DSH_HOME", self.home / ".dsh")
        self._patch_env("CODEX_HOME", self.home / ".codex")
        self._patch_env("CLAUDE_CONFIG_DIR", self.home / ".claude")
        self._patch_env("AGENTLINK_STATE_DIR", self.state)
        # tests assert Chinese section names: pin the language, don't inherit it
        self._patch_env("AGENTLINK_LANG", "zh")
        from agentlink.i18n import set_lang

        set_lang("zh")

    def tearDown(self):
        from agentlink.i18n import set_lang

        set_lang(None)
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _patch_env(self, key: str, value) -> None:
        self._env[key] = os.environ.get(key)
        os.environ[key] = str(value)

    def store(self) -> Store:
        store = Store(self.project).ensure()

        return store

    # ------------------------------------------------------------- fixtures

    def write_dsh(self, records, cwd: str | None = None) -> Path:
        cwd = cwd or PROJECT
        folder = self.home / ".dsh" / "sessions" / dsh_session_dirname(cwd) / "session-abc123"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "session.v4.jsonl.zstd"
        payload = _jsonl(records).encode("utf-8")
        import zstandard

        path.write_bytes(zstandard.ZstdCompressor().compress(payload))
        return path

    def write_codex(self, records) -> Path:
        folder = self.home / ".codex" / "sessions" / "2026" / "01" / "01"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "rollout-2026-01-01T00-00-00-abc.jsonl"
        path.write_text(_jsonl(records), encoding="utf-8")
        return path

    def write_claude(self, records) -> Path:
        folder = self.home / ".claude" / "projects" / claude_project_dirname(PROJECT)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "session-1.jsonl"
        path.write_text(_jsonl(records), encoding="utf-8")
        return path

    # ---------------------------------------------------------------- tests

    def test_codex_ingest_and_incremental(self):
        path = self.write_codex([
            {"type": "session_meta", "payload": {"id": "codex-1", "cwd": PROJECT}},
            {"type": "response_item", "ordinal": 1, "timestamp": "2026-01-01T00:00:01Z",
             "payload": {"type": "message", "role": "developer",
                         "content": [{"type": "input_text", "text": "<permissions instructions>"}]}},
            {"type": "response_item", "ordinal": 2, "timestamp": "2026-01-01T00:00:02Z",
             "payload": {"type": "message", "role": "user",
                         "content": [{"type": "input_text", "text": "把测试跑通"}]}},
            {"type": "response_item", "ordinal": 3, "timestamp": "2026-01-01T00:00:03Z",
             "payload": {"type": "message", "role": "assistant",
                         "content": [{"type": "output_text", "text": "已经跑通了，下一步补 CI"}]}},
            {"type": "response_item", "ordinal": 4, "timestamp": "2026-01-01T00:00:04Z",
             "payload": {"type": "function_call", "name": "shell",
                         "arguments": json.dumps({"command": "pytest -q"})}},
        ])
        store = self.store()
        results = sync(store, agents=["codex"])
        self.assertEqual(results[0].sessions, 1)
        roles = [(e.role, e.text) for e in store.events()]
        self.assertIn(("user", "把测试跑通"), roles)
        self.assertTrue(any("ci" in text.lower() for role, text in roles if role == "assistant"))
        self.assertTrue(any(role == "tool" and "pytest -q" in text for role, text in roles))
        self.assertFalse(any("permissions instructions" in text for _, text in roles))

        # second sync must not duplicate anything
        before = len(store.events())
        sync(store, agents=["codex"])
        self.assertEqual(len(store.events()), before)

        # appending a line is picked up incrementally
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "type": "response_item", "ordinal": 5, "timestamp": "2026-01-01T00:00:05Z",
                "payload": {"type": "message", "role": "user",
                            "content": [{"type": "input_text", "text": "再补一个用例"}]},
            }, ensure_ascii=False) + "\n")
        sync(store, agents=["codex"])
        self.assertIn("再补一个用例", [e.text for e in store.events()])

    def test_dsh_ingest_filters_runtime_noise(self):
        self.write_dsh([
            {"type": "session", "version": 4, "id": "session-dsh1", "cwd": PROJECT},
            {"type": "session/title", "seq": 1, "time": 1767225600000,
             "data": {"title": "修登录 bug"}},
            {"type": "user/message", "seq": 2, "time": 1767225601000,
             "data": {"role": "user", "source": {"kind": "user"},
                      "content": [{"type": "text", "text": "登录报错了，帮我看看"}]}},
            {"type": "user/message", "seq": 3, "time": 1767225602000,
             "data": {"role": "user", "source": {"kind": "runtime-context"},
                      "content": [{"type": "text", "text": "Current runtime context. ..."}]}},
            {"type": "assistant/message", "seq": 4, "time": 1767225603000,
             "data": {"role": "assistant", "content": [{"type": "text", "text": "是 token 过期导致的"}]}},
            {"type": "tool/call", "seq": 5, "time": 1767225604000,
             "data": {"name": "pwsh", "input": {"command": "npm test"}}},
        ])
        store = self.store()
        results = sync(store, agents=["dsh"])
        self.assertEqual(results[0].sessions, 1)
        texts = [e.text for e in store.events()]
        self.assertIn("登录报错了，帮我看看", texts)
        self.assertIn("是 token 过期导致的", texts)
        self.assertTrue(any("npm test" in t for t in texts))
        self.assertFalse(any("Current runtime context" in t for t in texts))
        self.assertEqual(store.session_meta("dsh:session-dsh1").get("title"), "修登录 bug")

    def test_dsh_ignores_other_projects(self):
        self.write_dsh([
            {"type": "user/message", "seq": 1, "time": 1767225600000,
             "data": {"role": "user", "source": {"kind": "user"},
                      "content": [{"type": "text", "text": "别的项目"}]}},
        ], cwd=r"F:\work\other")
        store = self.store()
        results = sync(store, agents=["dsh"])
        self.assertEqual(results[0].sessions, 0)
        self.assertEqual(store.events(), [])

    def test_claude_ingest(self):
        self.write_claude([
            {"type": "user", "timestamp": "2026-01-01T00:00:01Z", "cwd": PROJECT,
             "message": {"role": "user", "content": "重构一下解析器"}},
            {"type": "assistant", "timestamp": "2026-01-01T00:00:02Z", "cwd": PROJECT,
             "message": {"role": "assistant", "content": [
                 {"type": "text", "text": "我先把入口拆开"},
                 {"type": "tool_use", "name": "Edit", "input": {"file_path": "src/parser.py"}},
             ]}},
            {"type": "user", "timestamp": "2026-01-01T00:00:03Z", "cwd": PROJECT,
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "content": "ok"}]}},
        ])
        store = self.store()
        results = sync(store, agents=["claude"])
        self.assertEqual(results[0].sessions, 1)
        texts = [e.text for e in store.events()]
        self.assertIn("重构一下解析器", texts)
        self.assertIn("我先把入口拆开", texts)
        self.assertTrue(any("src/parser.py" in t for t in texts))

    def test_digest_sections_and_budget(self):
        store = self.store()
        store.append_events([
            # Event objects are appended through the store API used by sources
        ])
        from agentlink.model import Event

        events = [
            Event(agent="codex", session="s1", role="user", text="实现导出功能",
                  ts="2026-01-01T10:00:00+08:00", seq=1),
            Event(agent="codex", session="s1", role="assistant",
                  text="决定：先做 CSV，再接 xlsx", ts="2026-01-01T10:05:00+08:00", seq=2),
            Event(agent="dsh", session="s2", role="user", text="下一步补测试",
                  ts="2026-01-01T11:00:00+08:00", seq=1),
        ]
        store.append_events(events)
        store.add_note("记得更新 README", kind="todo")
        brief = build_context(store, budget=8000, include_git=False)
        self.assertIn("当前任务", brief)
        self.assertIn("各会话卡片", brief)
        self.assertIn("CSV", brief)
        self.assertIn("记得更新 README", brief)
        self.assertLessEqual(width(brief), 8000)

    def test_group_sessions_order(self):
        from agentlink.model import Event

        events = [
            Event(agent="codex", session="old", role="user", text="旧", ts="2026-01-01T00:00:00+08:00"),
            Event(agent="dsh", session="new", role="user", text="新", ts="2026-01-02T00:00:00+08:00"),
        ]
        views = group_sessions(events)
        self.assertEqual(views[0].session, "new")

    # ------------------------------------------------- token budget & AI layer

    def test_brief_respects_token_budget(self):
        from agentlink.digest import build_context, estimate_tokens
        from agentlink.model import Event

        store = self.store()
        events = []
        for i in range(40):
            events.append(Event(
                agent="codex", session="s1", role="user",
                text=f"第 {i} 条需求：" + "细节" * 40, ts=f"2026-01-01T10:{i:02d}:00+08:00", seq=i))
            events.append(Event(
                agent="codex", session="s1", role="assistant",
                text=f"第 {i} 条回答：" + "结论" * 40, ts=f"2026-01-01T10:{i:02d}:30+08:00", seq=1000 + i))
        store.append_events(events)
        small = build_context(store, budget_tokens=400, include_git=False)
        big = build_context(store, budget_tokens=4000, include_git=False)
        self.assertLessEqual(estimate_tokens(small), 460)
        self.assertGreater(estimate_tokens(big), estimate_tokens(small))
        # the cheap brief still keeps the highest-value sections
        self.assertIn("当前任务", small)

    def test_summary_apply_and_merge(self):
        from agentlink import summary as summary_mod

        store = self.store()
        payload = {
            "version": 1,
            "generated_at": "2026-01-02T00:00:00+08:00",
            "project": {"goal": "做导出功能", "status": "编码中"},
            "state": {"in_progress": ["分页"], "decisions": ["只做 CSV"]},
            "sessions": [{"agent": "codex", "id": "s1", "title": "导出",
                          "one_line": "讨论导出格式", "outcome": "定 CSV"}],
        }
        data = summary_mod.save(store, payload)
        self.assertEqual(data["project"]["goal"], "做导出功能")
        brief = build_context(store, budget_tokens=3000, include_git=False)
        self.assertIn("接手摘要", brief)
        self.assertIn("只做 CSV", brief)
        self.assertIn("分页", brief)

    def test_digest_incremental_after_summary(self):
        from agentlink import summary as summary_mod
        from agentlink.digest import build_digest_payload
        from agentlink.model import Event

        store = self.store()
        store.append_events([
            Event(agent="dsh", session="s1", role="user", text="旧消息",
                  ts="2026-01-01T10:00:00+08:00", seq=1),
        ])
        summary_mod.save(store, {
            "generated_at": "2026-01-01T10:05:00+08:00",
            "window": {"from": "2026-01-01T10:00:00+08:00",
                       "to": "2026-01-01T10:00:00+08:00", "events": 1},
            "project": {"goal": "旧目标"},
        })
        store.append_events([
            Event(agent="dsh", session="s1", role="user", text="新消息",
                  ts="2026-01-01T11:00:00+08:00", seq=2),
        ])
        payload = build_digest_payload(store, max_tokens=3000, since_last=True)
        self.assertEqual(payload["mode"], "incremental")
        self.assertEqual(len(payload["new_events"]), 1)
        self.assertIn("新消息", payload["new_events"][0]["text"])
        self.assertIn("旧目标", payload["previous_summary"]["project"]["goal"])
        full = build_digest_payload(store, max_tokens=3000, since_last=False)
        self.assertEqual(full["mode"], "full")
        self.assertTrue(full["sessions"])

    def test_activity_extraction(self):
        from agentlink.activity import extract_activity, short_path
        from agentlink.model import Event

        events = [
            Event(agent="dsh", session="s", role="tool", tool="edit",
                  text=r"edit: F:\work\demo\src\app.py", kind="command"),
            Event(agent="dsh", session="s", role="tool", tool="pwsh",
                  text="pwsh: pytest -q", kind="command"),
            Event(agent="dsh", session="s", role="tool", tool="pwsh",
                  text="pwsh: pytest -q", kind="command"),
            Event(agent="dsh", session="s", role="user", text="跑测试"),
        ]
        act = extract_activity(events)
        self.assertEqual(act["files"][0]["path"], r"F:\work\demo\src\app.py")
        self.assertEqual(act["commands"], ["pytest -q"])
        self.assertEqual(short_path(r"F:\work\demo\src\app.py", r"F:\work\demo"), r"src\app.py")

    def test_token_estimator_is_monotonic(self):
        from agentlink.digest import estimate_tokens

        short = estimate_tokens("你好")
        long = estimate_tokens("你好" * 200)
        self.assertLess(short, long)
        self.assertGreater(short, 0)

    # ------------------------------------------------------- filters & i18n

    def test_since_filter(self):
        from agentlink.model import Event
        from agentlink.util import parse_since

        store = self.store()
        store.append_events([
            Event(agent="dsh", session="s1", role="user", text="很久以前",
                  ts="2020-01-01T10:00:00+08:00", seq=1),
            Event(agent="dsh", session="s1", role="user", text="刚刚说的",
                  ts="2999-01-01T10:00:00+08:00", seq=2),
        ])
        recent = store.events(since=parse_since("1d"))
        self.assertEqual([e.text for e in recent], ["刚刚说的"])
        self.assertIsNotNone(parse_since("3d"))
        self.assertIsNotNone(parse_since("2026-01-01"))
        self.assertIsNone(parse_since("not-a-date"))

    def test_tail_read_skips_corrupt_lines(self):
        store = self.store()
        store.append_events([
            Event(agent="dsh", session="s1", role="user", text=f"消息{i}",
                  ts="2026-01-01T10:00:00+08:00", seq=i)
            for i in range(5)
        ])
        with open(store.journal_path, "a", encoding="utf-8") as fh:
            fh.write("{broken json\n")
        tail = store.events(limit=3, tail=True)
        self.assertEqual(len(tail), 3)
        self.assertEqual(tail[-1].text, "消息4")
        # a full read keeps working too
        self.assertEqual(len(store.events(limit=10, tail=False)), 5)

    def test_english_rendering(self):
        from agentlink.digest import build_context
        from agentlink.i18n import set_lang

        store = self.store()
        store.append_events([
            Event(agent="codex", session="s1", role="user", text="implement export",
                  ts="2026-01-01T10:00:00+08:00", seq=1),
        ])
        set_lang("en")
        try:
            brief = build_context(store, budget_tokens=3000, include_git=False)
        finally:
            set_lang("zh")
        self.assertIn("Session cards", brief)
        self.assertIn("Current asks", brief)
        self.assertNotIn("各会话卡片", brief)

    def test_english_keywords_still_extract(self):
        from agentlink.digest import build_context

        store = self.store()
        store.append_events([
            Event(agent="claude", session="s1", role="assistant",
                  text="We decided to keep CSV only. Next step: add retries.",
                  ts="2026-01-01T10:00:00+08:00", seq=1),
        ])
        brief = build_context(store, budget_tokens=3000, include_git=False)
        self.assertIn("CSV only", brief)

    def test_cli_rejects_unknown_since(self):
        from agentlink import cli

        with self.assertRaises(SystemExit):
            cli.main(["show", "--since", "last-tuesday", "--root", str(self.project)])

    def test_cli_rejects_missing_root(self):
        from agentlink import cli

        with self.assertRaises(SystemExit):
            cli.main(["brief", "--root", str(self.tmp / "nope" / "nowhere")])

    def test_cli_refuses_empty_summary(self):
        import contextlib
        from agentlink import cli

        buf = io.StringIO()
        old = sys.stdin
        sys.stdin = io.StringIO('{"sessions": "oops"}')
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                with self.assertRaises(SystemExit):
                    cli.main(["summary", "apply", "--root", str(self.project)])
        finally:
            sys.stdin = old
        self.assertNotIn("已保存", buf.getvalue())

    def test_installers_are_plain_ascii(self):
        """A BOM breaks `irm | iex`, so the bootstrap scripts stay ASCII and BOM-free."""
        repo = Path(__file__).resolve().parents[1]
        for name in ("install.ps1", "install.sh"):
            raw = (repo / name).read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"{name} starts with a BOM")
            for lineno, line in enumerate(raw.splitlines(), 1):
                if any(byte > 127 for byte in line):
                    self.fail(f"{name}:{lineno} is not ASCII: {line[:60]!r}")

    def test_alias_root_finds_moved_project(self):
        """After a project moves, config.roots lets the old transcripts count."""
        old_root = self.tmp / "old-project"
        old_root.mkdir()
        session = self.write_dsh(
            [{"type": "session_meta", "id": "s1", "cwd": str(old_root), "title": "old"}],
            cwd=str(old_root),
        )
        self.assertTrue(session.exists())

        store = self.store()
        from agentlink.sources import discover_sessions

        self.assertEqual(discover_sessions(store, ["dsh"]), [])  # nothing claims the new root yet

        store.config["roots"] = [str(old_root)]
        store.save_config()

        found = discover_sessions(store, ["dsh"])
        self.assertTrue(found, "alias root should surface the old session")
        self.assertEqual(found[0].cwd, str(old_root))


    # ------------------------------------------------- review regressions

    def test_latest_task_follows_time_not_import_order(self):
        """A tool synced later must not push its older asks to the front."""
        from agentlink.digest import _current_tasks

        store = self.store()
        store.append_events([Event(agent="codex", session="c1", role="user",
                                   text="最新请求：先把对账跑通",
                                   ts="2026-10-30T10:00:00+08:00", seq=1)])
        store.append_events([Event(agent="claude", session="k1", role="user",
                                   text="旧请求：先聊聊架构",
                                   ts="2026-10-01T10:00:00+08:00", seq=1)])

        tasks = _current_tasks(store.events(limit=10))
        self.assertIn("最新请求", tasks[0])

    def test_recent_window_keeps_newest_after_old_backfill(self):
        """500 older records imported later must not push out the newest one."""
        store = self.store()
        store.append_events([Event(agent="codex", session="c1", role="user",
                                   text="最新请求：继续对账",
                                   ts="2026-10-30T10:00:00+08:00", seq=1)])
        store.append_events([
            Event(agent="claude", session="k1", role="user", text=f"旧消息{i}",
                  ts=f"2026-10-01T10:{i // 60:02d}:{i % 60:02d}+08:00", seq=i)
            for i in range(500)
        ])

        window = store.events(limit=400)
        self.assertEqual(len(window), 400)
        self.assertTrue(any("最新请求" in e.text for e in window))
        self.assertIn("最新请求", window[-1].text)

    def test_claude_munged_collision_does_not_import_other_project(self):
        """project-one and project_one share a folder name; cwd must decide."""
        from agentlink.sources import discover_sessions

        other = self.tmp / "project_one"
        other.mkdir()
        folder = self.home / ".claude" / "projects" / claude_project_dirname(str(self.project))
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "session-x.jsonl").write_text(_jsonl([
            {"type": "user", "cwd": str(other), "sessionId": "x",
             "message": {"role": "user", "content": "别的项目的事"}},
        ]), encoding="utf-8")

        self.assertEqual(discover_sessions(self.store(), ["claude"]), [])

    def test_history_discovered_later_enters_incremental_digest(self):
        """A session imported after the summary is new to us even if it is older."""
        from agentlink import summary as summary_mod
        from agentlink.digest import build_digest_payload

        store = self.store()
        store.append_events([Event(agent="codex", session="c1", role="user",
                                   text="一月一日的工作",
                                   ts="2026-01-01T10:00:00+08:00", seq=1)])
        payload = build_digest_payload(store, max_tokens=6000)
        self.assertIn("coverage", payload)
        summary_mod.save(store, {
            "version": 1,
            "project": {"goal": "把对账跑通"},
            "state": {"next": ["跑对账"]},
            "coverage": payload["coverage"],
        })

        store.append_events([Event(agent="claude", session="k1", role="user",
                                   text="补录的旧会话：接口已经改过",
                                   ts="2026-01-01T09:00:00+08:00", seq=1)])

        again = build_digest_payload(store, max_tokens=6000)
        texts = [item["text"] for item in again["new_events"]]
        self.assertIn("补录的旧会话：接口已经改过", texts)
        self.assertGreaterEqual(again["new_event_count"], 1)

    def test_init_hook_creates_the_context_file_it_points_at(self):
        import contextlib
        from agentlink import cli

        # default layout: the pointer promises .agentlink/context.md in the project
        os.environ.pop("AGENTLINK_STATE_DIR", None)
        self.write_codex([
            {"type": "session_meta", "payload": {"id": "codex-1", "cwd": PROJECT}},
            {"type": "response_item", "timestamp": "2026-01-01T10:00:00Z",
             "payload": {"type": "message", "role": "user",
                         "content": [{"type": "input_text", "text": "接着做导出"}]}},
        ])
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["init", "--hook", "--root", str(self.project)])

        context = self.project / ".agentlink" / "context.md"
        self.assertTrue(context.exists(), "the pointer names a file that must exist")
        pointer = (self.project / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("agentlink brief", pointer)

    def test_codex_archived_sessions_are_discovered(self):
        from agentlink.sources import discover_sessions

        folder = self.home / ".codex" / "archived_sessions" / "2025" / "12" / "31"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "rollout-2025-12-31T00-00-00-old.jsonl").write_text(_jsonl([
            {"type": "session_meta", "payload": {"id": "codex-old", "cwd": PROJECT}},
            {"type": "response_item", "timestamp": "2025-12-31T10:00:00Z",
             "payload": {"type": "message", "role": "user",
                         "content": [{"type": "input_text", "text": "归档前的工作"}]}},
        ]), encoding="utf-8")

        found = discover_sessions(self.store(), ["codex"])
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].path.endswith("rollout-2025-12-31T00-00-00-old.jsonl"))

    def test_alias_root_works_after_the_old_directory_is_gone(self):
        """Moving the project deletes the old path; the alias must still match."""
        from agentlink.sources import discover_sessions

        ghost = self.tmp / "gone-project"
        self.write_dsh(
            [{"type": "session_meta", "id": "s1", "cwd": str(ghost), "title": "old"}],
            cwd=str(ghost),
        )
        self.assertFalse(ghost.exists())

        store = self.store()
        store.config["roots"] = [str(ghost)]
        store.save_config()

        found = discover_sessions(store, ["dsh"])
        self.assertTrue(found, "a historical path is an identity, not a directory")
        self.assertEqual(found[0].cwd, str(ghost))

    def test_launchers_do_not_trust_dirname_alone(self):
        """The PATH entry is a symlink/marker consumer, not a bare dirname."""
        repo = Path(__file__).resolve().parents[1]
        sh = (repo / "bin" / "agentlink.sh").read_text(encoding="utf-8")
        self.assertIn("readlink", sh)
        self.assertIn(".agentlink-python", sh)
        cmd = (repo / "bin" / "agentlink.cmd").read_text(encoding="utf-8")
        self.assertIn(".agentlink-python", cmd)
        for name in ("install.sh", "install.ps1"):
            text = (repo / name).read_text(encoding="utf-8")
            self.assertIn(".agentlink-python", text, f"{name} must record the chosen python")


    def test_large_backlog_advances_coverage_without_skipping(self):
        """A batch bigger than the digest window is consumed oldest-first."""
        from agentlink import summary as summary_mod
        from agentlink.digest import build_digest_payload

        store = self.store()
        store.append_events([
            Event(agent="codex", session="c1", role="user", text=f"第{i}条",
                  ts=f"2026-01-01T10:{i // 60:02d}:{i % 60:02d}+08:00", seq=i)
            for i in range(100)
        ])
        first = build_digest_payload(store, max_tokens=6000)
        summary_mod.save(store, {"version": 1, "project": {"goal": "g"}, "coverage": first["coverage"]})

        store.append_events([
            Event(agent="claude", session="k1", role="user", text=f"新{i}",
                  ts=f"2026-01-02T10:{i // 60:02d}:{i % 60:02d}+08:00", seq=i)
            for i in range(200)
        ])
        second = build_digest_payload(store, max_tokens=6000)
        self.assertEqual(second["new_event_count"], 200)
        self.assertLessEqual(len(second["new_events"]), 80)
        self.assertEqual(second["new_events"][0]["text"], "新0")  # oldest unread first
        summary_mod.save(store, {"version": 1, "project": {"goal": "g"}, "coverage": second["coverage"]})

        third = build_digest_payload(store, max_tokens=6000)
        self.assertEqual(third["new_event_count"], 200 - len(second["new_events"]))
        self.assertEqual(third["new_events"][0]["text"], f"新{len(second['new_events'])}")


    def test_install_helpers_write_files_on_old_python(self):
        """Path.write_text(newline=) is 3.10+; these helpers must stay 3.9-safe."""
        from agentlink.install import build_launcher, write_pointers

        target = self.tmp / "skill"
        target.mkdir()
        written = build_launcher(target)
        self.assertTrue(all(Path(item).exists() for item in written))

        touched = write_pointers(self.project, "2026-01-01T00:00:00+08:00", ("AGENTS.md",))
        self.assertTrue(Path(touched[0]).exists())
        self.assertIn("agentlink brief", Path(touched[0]).read_text(encoding="utf-8"))

    def test_cli_brief_writes_context_file(self):
        import contextlib
        from agentlink import cli

        os.environ.pop("AGENTLINK_STATE_DIR", None)
        self.write_codex([
            {"type": "session_meta", "payload": {"id": "codex-1", "cwd": PROJECT}},
            {"type": "response_item", "timestamp": "2026-01-01T10:00:00Z",
             "payload": {"type": "message", "role": "user",
                         "content": [{"type": "input_text", "text": "接着做导出"}]}},
        ])
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["brief", "--root", str(self.project), "--no-git"])

        context = self.project / ".agentlink" / "context.md"
        self.assertTrue(context.exists())
        self.assertIn("导出", context.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()



