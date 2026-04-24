"""Runner-level tests: TZ hardcoded, timeout kills pgroup, parsing."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from apr_agent.defects4j import runner
from apr_agent.defects4j.info import parse_bug_id
from apr_agent.defects4j.test import _read_failing_tests_file


def test_parse_bug_id():
    assert parse_bug_id("Math-12") == ("Math", 12)
    assert parse_bug_id("JacksonCore-1") == ("JacksonCore", 1)


def test_parse_bug_id_bad():
    with pytest.raises(ValueError):
        parse_bug_id("not-a-bug")
    with pytest.raises(ValueError):
        parse_bug_id("12-Math")


def test_read_failing_tests_file_parses_dashes(tmp_path: Path):
    (tmp_path / "failing_tests").write_text(
        "--- org.foo.BarTest::baz\n"
        "\tat org.foo.BarTest.baz(BarTest.java:42)\n"
        "--- org.foo.BarTest::qux\n"
        "--- org.foo.BarTest::baz\n"  # dup: collapsed
    )
    assert _read_failing_tests_file(tmp_path) == [
        "org.foo.BarTest::baz",
        "org.foo.BarTest::qux",
    ]


def test_read_failing_tests_file_missing(tmp_path: Path):
    assert _read_failing_tests_file(tmp_path) == []


def test_defects4j_not_installed_raises(monkeypatch):
    monkeypatch.setattr(runner.shutil, "which", lambda _: None)
    with pytest.raises(runner.Defects4jNotInstalled):
        runner.require_defects4j()


def test_run_defects4j_sets_tz(monkeypatch):
    """The child env must have TZ=America/Los_Angeles regardless of caller."""
    captured_env: dict = {}

    class FakeProc:
        pid = 9999
        returncode = 0

        def communicate(self, timeout=None):
            return ("ok\n", "")

    def fake_popen(args, **kwargs):
        captured_env.update(kwargs.get("env", {}))
        return FakeProc()

    monkeypatch.setattr(runner, "require_defects4j", lambda: "/fake/defects4j")
    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    res = runner.run_defects4j(["info", "-p", "Math"])
    assert captured_env.get("TZ") == "America/Los_Angeles"
    assert res.returncode == 0


def test_run_defects4j_process_group_isolation(monkeypatch):
    """start_new_session=True must be set so we can killpg on timeout."""
    kwargs_seen: dict = {}

    class FakeProc:
        pid = 9999
        returncode = 0

        def communicate(self, timeout=None):
            return ("ok\n", "")

    def fake_popen(args, **kwargs):
        kwargs_seen.update(kwargs)
        return FakeProc()

    monkeypatch.setattr(runner, "require_defects4j", lambda: "/fake/defects4j")
    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    runner.run_defects4j(["info"])
    assert kwargs_seen.get("start_new_session") is True


def test_run_defects4j_timeout_kills_pgroup(monkeypatch):
    """On timeout, run_defects4j must SIGTERM the process group, not just the leader."""
    import subprocess as sp

    killed: list[int] = []

    class FakeProc:
        pid = 1234
        returncode = -15

        def __init__(self):
            self._calls = 0

        def communicate(self, timeout=None):
            self._calls += 1
            if self._calls == 1:
                raise sp.TimeoutExpired(cmd=["fake"], timeout=timeout or 1)
            return ("", "killed")

    monkeypatch.setattr(runner, "require_defects4j", lambda: "/fake/defects4j")
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **kw: FakeProc())
    monkeypatch.setattr(runner.os, "getpgid", lambda _pid: 1234)
    monkeypatch.setattr(runner.os, "killpg",
                        lambda pgid, _sig: killed.append(pgid))

    res = runner.run_defects4j(["test"], timeout_s=0.01)
    assert res.timed_out is True
    assert 1234 in killed


def test_tz_hardcoded_even_if_caller_has_other_tz(monkeypatch):
    """Caller's TZ must NOT leak through — D4J is tz-sensitive."""
    monkeypatch.setenv("TZ", "Asia/Shanghai")

    captured_env: dict = {}

    class FakeProc:
        pid = 9999
        returncode = 0

        def communicate(self, timeout=None):
            return ("", "")

    def fake_popen(args, **kwargs):
        captured_env.update(kwargs.get("env", {}))
        return FakeProc()

    monkeypatch.setattr(runner, "require_defects4j", lambda: "/fake/defects4j")
    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    runner.run_defects4j(["info"])
    assert captured_env["TZ"] == "America/Los_Angeles"
    assert os.environ["TZ"] == "Asia/Shanghai"  # parent untouched
