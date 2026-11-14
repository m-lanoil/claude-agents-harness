import runpy
import subprocess
from datetime import date
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "check_server_freshness.py"
TODAY = date(2026, 11, 12)

STALE_LOG = (
    "# Tool Log\n\n## Created\n\n| Timestamp | Server | Tools | Description |\n|---|---|---|---|\n\n"
    "## Audited\n\n| Timestamp | Server | Notes |\n|---|---|---|\n"
    "| 2026-01-01 00:00:00 | `servers/a` | ok |\n"
)


@pytest.fixture
def loaded(tmp_path, monkeypatch):
    """Load the script with paths and clock redirected into tmp_path; notify stays real."""
    namespace = runpy.run_path(str(SCRIPT), run_name="freshness_notify_failure_under_test")
    live = namespace["main"].__globals__
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setitem(live, "TOOL_LOG", logs / "TOOL_LOG.md")
    monkeypatch.setitem(live, "ALERTS_FILE", logs / "SERVER_FRESHNESS_ALERTS.md")
    monkeypatch.setitem(live, "TODAY", TODAY)

    class Ctx:
        notify = staticmethod(namespace["notify"])
        main = staticmethod(namespace["main"])
        tool_log_path = logs / "TOOL_LOG.md"
        alerts_path = logs / "SERVER_FRESHNESS_ALERTS.md"

    return Ctx


def capture_runs(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs)))
    return calls


def raise_on_run(monkeypatch, exc):
    def fake_run(args, **kwargs):
        raise exc

    monkeypatch.setattr(subprocess, "run", fake_run)


def script_arg(calls):
    assert len(calls) == 1
    return calls[0][0][2]


def test_missing_osascript_is_skipped_with_a_stderr_note(loaded, monkeypatch, capsys):
    raise_on_run(monkeypatch, FileNotFoundError("osascript"))
    loaded.notify("hello")
    captured = capsys.readouterr()
    assert captured.err == "notification skipped: osascript\n"
    assert captured.out == ""


def test_other_oserror_is_also_skipped(loaded, monkeypatch, capsys):
    raise_on_run(monkeypatch, PermissionError("not allowed"))
    loaded.notify("hello")
    assert capsys.readouterr().err == "notification skipped: not allowed\n"


def test_main_finishes_normally_when_osascript_is_missing(loaded, monkeypatch, capsys):
    raise_on_run(monkeypatch, FileNotFoundError("osascript"))
    loaded.tool_log_path.write_text(STALE_LOG)
    assert loaded.main() is None
    text = loaded.alerts_path.read_text()
    assert "## 2026-11-12 — STALE" in text
    assert "| `servers/a` | Audited | 2026-01-01 | 315 |" in text
    captured = capsys.readouterr()
    assert captured.out.startswith("STALE: 1 server(s) flagged")
    assert captured.err == "notification skipped: osascript\n"


def test_quote_in_message_is_escaped(loaded, monkeypatch):
    calls = capture_runs(monkeypatch)
    loaded.notify('say "hi"')
    assert script_arg(calls) == 'display notification "say \\"hi\\"" with title "Server Freshness Alert"'


def test_backslash_in_message_is_escaped(loaded, monkeypatch):
    calls = capture_runs(monkeypatch)
    loaded.notify("a\\b")
    assert script_arg(calls) == 'display notification "a\\\\b" with title "Server Freshness Alert"'


def test_backslash_before_quote_becomes_backslash_backslash_backslash_quote(loaded, monkeypatch):
    calls = capture_runs(monkeypatch)
    loaded.notify('\\"')
    assert script_arg(calls) == 'display notification "\\\\\\"" with title "Server Freshness Alert"'


def test_plain_message_command_is_unchanged(loaded, monkeypatch):
    calls = capture_runs(monkeypatch)
    loaded.notify("hello")
    assert calls == [
        (["osascript", "-e", 'display notification "hello" with title "Server Freshness Alert"'], {"check": False})
    ]
