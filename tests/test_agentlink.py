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
        PROJECT = str(self.tmp / 'project')
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
        self.assertIn("## 2. 当前任务", brief)
        self.assertIn("## 3. 各 agent", brief)
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


if __name__ == "__main__":
    unittest.main()
