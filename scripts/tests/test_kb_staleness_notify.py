import runpy
import subprocess
from datetime import date
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "check_kb_staleness.py"
TODAY = date(2026, 11, 14)


@pytest.fixture
def loaded(tmp_path, monkeypatch):
    """Load the script with paths and clock redirected into tmp_path; notify stays real."""
    namespace = runpy.run_path(str(SCRIPT), run_name="kb_staleness_notify_under_test")
    live = namespace["main"].__globals__
    logs = tmp_path / "logs"
    logs.mkdir()
    kb = tmp_path / "kb"
    kb.mkdir()
    monkeypatch.setitem(live, "KB_LOG", logs / "KB_STALENESS_LOG.md")
    monkeypatch.setitem(live, "KB_DIRS", {"developer": kb})
    monkeypatch.setitem(live, "TODAY", TODAY)

    class Ctx:
        notify = staticmethod(namespace["notify"])
        main = staticmethod(namespace["main"])
        log_path = logs / "KB_STALENESS_LOG.md"
        kb_dir = kb

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


def entry(filename, age=40, worker="developer"):
    return (worker, filename, date(2026, 10, 5), age)


def test_missing_osascript_is_skipped_with_a_stderr_note(loaded, monkeypatch, capsys):
    raise_on_run(monkeypatch, FileNotFoundError("osascript"))
    loaded.notify([entry("kb_a.md")])
    captured = capsys.readouterr()
    assert captured.err == "notification skipped: osascript\n"
    assert captured.out == ""


def test_other_oserror_is_also_skipped(loaded, monkeypatch, capsys):
    raise_on_run(monkeypatch, PermissionError("not allowed"))
    loaded.notify([entry("kb_a.md")])
    assert capsys.readouterr().err == "notification skipped: not allowed\n"


def test_main_finishes_normally_when_osascript_is_missing(loaded, monkeypatch, capsys):
    raise_on_run(monkeypatch, FileNotFoundError("osascript"))
    (loaded.kb_dir / "kb_old.md").write_text("---\nfetched: 2026-10-01\n---\n")
    assert loaded.main() is None
    assert "| developer | `kb_old.md` | 2026-10-01 | 44 |" in loaded.log_path.read_text()
    captured = capsys.readouterr()
    assert captured.out.startswith("STALE: 1 kb file(s) flagged")
    assert captured.err == "notification skipped: osascript\n"


def test_quote_in_file_name_is_escaped(loaded, monkeypatch):
    calls = capture_runs(monkeypatch)
    loaded.notify([entry('kb_"x".md')])
    assert script_arg(calls) == (
        'display notification "1 stale kb file(s) — oldest: kb_\\"x\\".md" '
        'with title "KB Staleness Alert"'
    )


def test_backslash_in_file_name_is_escaped(loaded, monkeypatch):
    calls = capture_runs(monkeypatch)
    loaded.notify([entry("kb_a\\b.md")])
    assert script_arg(calls) == (
        'display notification "1 stale kb file(s) — oldest: kb_a\\\\b.md" '
        'with title "KB Staleness Alert"'
    )


def test_backslash_before_quote_becomes_backslash_backslash_backslash_quote(loaded, monkeypatch):
    calls = capture_runs(monkeypatch)
    loaded.notify([entry('\\"')])
    assert script_arg(calls) == (
        'display notification "1 stale kb file(s) — oldest: \\\\\\"" '
        'with title "KB Staleness Alert"'
    )


def test_plain_command_is_unchanged(loaded, monkeypatch):
    calls = capture_runs(monkeypatch)
    loaded.notify([entry("kb_a.md")])
    assert calls == [
        (["osascript", "-e",
          'display notification "1 stale kb file(s) — oldest: kb_a.md" with title "KB Staleness Alert"'],
         {"check": False})
    ]


def test_message_names_the_oldest_file_and_the_count(loaded, monkeypatch):
    calls = capture_runs(monkeypatch)
    loaded.notify([entry("kb_young.md", age=31), entry("kb_oldest.md", age=90), entry("kb_mid.md", age=50)])
    assert script_arg(calls) == (
        'display notification "3 stale kb file(s) — oldest: kb_oldest.md" with title "KB Staleness Alert"'
    )


def test_message_of_exactly_100_characters_is_kept(loaded, monkeypatch):
    # The prefix "1 stale kb file(s) — oldest: " is 29 characters, so a 71-character name gives 100.
    name = "a" * 71
    calls = capture_runs(monkeypatch)
    loaded.notify([entry(name)])
    assert script_arg(calls) == (
        f'display notification "1 stale kb file(s) — oldest: {name}" with title "KB Staleness Alert"'
    )


def test_message_over_100_characters_falls_back_to_the_log_pointer(loaded, monkeypatch):
    calls = capture_runs(monkeypatch)
    loaded.notify([entry("a" * 72)])
    assert script_arg(calls) == (
        'display notification "1 stale kb file(s) — check KB_STALENESS_LOG.md" with title "KB Staleness Alert"'
    )
