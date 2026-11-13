import re
import runpy
import subprocess
from datetime import date
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "check_server_freshness.py"
TODAY = date(2026, 11, 12)


def tool_log(created=(), audited=()):
    """Build a TOOL_LOG.md body from (timestamp, server) tuples."""
    lines = ["# Tool Log", "", "## Workers", "", "| Timestamp | Worker |", "|---|---|",
             "| 2026-04-24 00:00:00 | `workers/developer` |", ""]
    lines += ["## Created", "", "| Timestamp | Server | Tools | Description |", "|---|---|---|---|"]
    lines += [f"| {ts} | `{server}` | `t` | desc |" for ts, server in created]
    lines += ["", "## Audited", "", "| Timestamp | Server | Notes |", "|---|---|---|"]
    lines += [f"| {ts} | `{server}` | ok |" for ts, server in audited]
    return "\n".join(lines) + "\n"


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    """Load the script with its paths, clock and notifier redirected into tmp_path."""
    namespace = runpy.run_path(str(SCRIPT), run_name="freshness_under_test")
    live = namespace["main"].__globals__
    logs = tmp_path / "logs"
    logs.mkdir()
    notifications = []
    monkeypatch.setitem(live, "TOOL_LOG", logs / "TOOL_LOG.md")
    monkeypatch.setitem(live, "ALERTS_FILE", logs / "SERVER_FRESHNESS_ALERTS.md")
    monkeypatch.setitem(live, "TODAY", TODAY)
    monkeypatch.setitem(live, "notify", notifications.append)

    class Ctx:
        ns = namespace
        tool_log_path = logs / "TOOL_LOG.md"
        alerts_path = logs / "SERVER_FRESHNESS_ALERTS.md"
        notified = notifications

        @staticmethod
        def write_log(**kwargs):
            logs.joinpath("TOOL_LOG.md").write_text(tool_log(**kwargs))

    return Ctx


# --------------------------------------------------------------------- parsing


def test_parse_sections_splits_on_level_two_headings(fresh):
    sections = fresh.ns["parse_sections"]("# Title\nintro\n## Created\nrow1\n## Audited\nrow2\nrow3\n")
    assert sections == {"Created": ["row1"], "Audited": ["row2", "row3"]}


def test_extract_table_rows_drops_separator_and_non_table_lines(fresh):
    rows = fresh.ns["extract_table_rows"](["| a | b |", "|---|---|", "text", "| c | d | e |", "| lone |"])
    assert rows == [["a", "b"], ["c", "d", "e"]]


def test_audited_last_entry_wins_and_created_first_entry_wins(fresh):
    sections = fresh.ns["parse_sections"](
        tool_log(
            created=[("2026-01-01 00:00:00", "servers/a"), ("2026-02-02 00:00:00", "servers/a")],
            audited=[("2026-03-01 00:00:00", "servers/a"), ("2026-05-05 12:00:00", "servers/a")],
        )
    )
    audited, created = fresh.ns["parse_server_dates"](sections)
    assert audited == {"servers/a": date(2026, 5, 5)}
    assert created == {"servers/a": date(2026, 1, 1)}


def test_rows_with_unparseable_timestamps_are_ignored(fresh):
    sections = fresh.ns["parse_sections"](
        tool_log(created=[("not a date", "servers/a"), ("2026-01-01", "servers/b")], audited=[])
    )
    audited, created = fresh.ns["parse_server_dates"](sections)
    assert audited == {} and created == {}


# ---------------------------------------------------------------- age boundary


def run_main(fresh):
    fresh.ns["main"]()


def test_exactly_30_days_old_is_not_stale(fresh, capsys):
    fresh.write_log(audited=[("2026-10-13 09:00:00", "servers/a")])
    run_main(fresh)
    assert capsys.readouterr().out == "All servers current as of 2026-11-12. No action required.\n"
    assert "STALE" not in fresh.alerts_path.read_text()
    assert fresh.notified == []


def test_31_days_old_is_stale(fresh, capsys):
    fresh.write_log(audited=[("2026-10-12 09:00:00", "servers/a")])
    run_main(fresh)
    assert capsys.readouterr().out == "STALE: 1 server(s) flagged. Written to SERVER_FRESHNESS_ALERTS.md\n"
    assert "| `servers/a` | Audited | 2026-10-12 | 31 |" in fresh.alerts_path.read_text()


def test_audit_date_beats_creation_date_for_age(fresh):
    fresh.write_log(
        created=[("2026-01-01 00:00:00", "servers/a")],
        audited=[("2026-11-01 00:00:00", "servers/a")],
    )
    run_main(fresh)
    assert "STALE" not in fresh.alerts_path.read_text()


def test_never_audited_server_is_aged_from_creation(fresh):
    fresh.write_log(created=[("2026-09-01 00:00:00", "servers/a")])
    run_main(fresh)
    assert "| `servers/a` | Created | 2026-09-01 | 72 |" in fresh.alerts_path.read_text()


def test_only_stale_servers_are_listed_in_name_order(fresh):
    fresh.write_log(
        audited=[
            ("2026-01-01 00:00:00", "servers/zeta"),
            ("2026-11-10 00:00:00", "servers/middle"),
            ("2026-01-02 00:00:00", "servers/alpha"),
        ]
    )
    run_main(fresh)
    text = fresh.alerts_path.read_text()
    assert text.index("servers/alpha") < text.index("servers/zeta")
    assert "servers/middle" not in text


# --------------------------------------------------- alert file format (checklist)


def test_alert_entry_format_matches_what_the_checklist_reads(fresh):
    fresh.write_log(audited=[("2026-06-16 00:00:00", "servers/a"), ("2026-06-15 00:00:00", "servers/b")])
    run_main(fresh)
    text = fresh.alerts_path.read_text()
    assert re.search(r"^## 2026-11-12 — STALE$", text, re.MULTILINE)
    assert "| Server | Basis | Last Audit/Creation | Age (days) |" in text
    assert "|--------|-------|---------------------|------------|" in text
    assert text.startswith("# Server Freshness Alerts\n")


def test_header_is_created_once_and_entries_are_appended(fresh):
    fresh.alerts_path.write_text("# Server Freshness Alerts\n\n## 2026-11-05 — STALE\n\nold entry\n")
    fresh.write_log(audited=[("2026-01-01 00:00:00", "servers/a")])
    run_main(fresh)
    text = fresh.alerts_path.read_text()
    assert text.count("# Server Freshness Alerts") == 1
    assert "old entry" in text
    assert text.index("## 2026-11-05 — STALE") < text.index("## 2026-11-12 — STALE")


def test_current_run_creates_header_only_alert_file(fresh):
    fresh.write_log(audited=[("2026-11-11 00:00:00", "servers/a")])
    run_main(fresh)
    assert fresh.alerts_path.read_text() == "# Server Freshness Alerts\n"


# ------------------------------------------------------------------ notification


def test_notification_names_stale_servers_by_basename(fresh):
    fresh.write_log(audited=[("2026-01-01 00:00:00", "servers/docs_fetcher"), ("2026-01-01 00:00:00", "servers/web_search")])
    run_main(fresh)
    assert fresh.notified == ["2 stale server(s): docs_fetcher, web_search"]


def test_long_notification_falls_back_to_a_short_message(fresh):
    servers = [f"servers/very_long_server_name_number_{i}" for i in range(6)]
    fresh.write_log(audited=[("2026-01-01 00:00:00", s) for s in servers])
    run_main(fresh)
    assert fresh.notified == ["6 stale server(s) — see SERVER_FRESHNESS_ALERTS.md"]


def test_notify_calls_osascript_with_the_message(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs)))
    real_notify = runpy.run_path(str(SCRIPT), run_name="freshness_notify")["notify"]
    real_notify("hello")
    assert calls == [
        (["osascript", "-e", 'display notification "hello" with title "Server Freshness Alert"'], {"check": False})
    ]


# ------------------------------------------------------------------- missing log


def test_missing_tool_log_exits_1_with_error_and_writes_nothing(fresh, capsys):
    with pytest.raises(SystemExit) as excinfo:
        run_main(fresh)
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("ERROR:") and "not found" in err
    assert not fresh.alerts_path.exists()
