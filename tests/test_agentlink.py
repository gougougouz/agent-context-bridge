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
import zstandard
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentlink.digest import build_context, group_sessions  # noqa: E402
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

    def tearDown(self):
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


if __name__ == "__main__":
    unittest.main()

