import re
import runpy
from datetime import date
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "check_server_freshness.py"
TODAY = date(2026, 11, 12)

CURRENT_LOG = (
    "# Tool Log\n\n## Created\n\n| Timestamp | Server | Tools | Description |\n|---|---|---|---|\n\n"
    "## Audited\n\n| Timestamp | Server | Notes |\n|---|---|---|\n"
    "| 2026-11-01 00:00:00 | `servers/a` | ok |\n"
)
STALE_LOG = CURRENT_LOG.replace("2026-11-01", "2026-01-01")
STALE_ENTRY = "# Server Freshness Alerts\n\n## 2026-11-05 — STALE\n\n| Server | Basis |\n|---|---|\n| `servers/a` | Audited |\n"


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    namespace = runpy.run_path(str(SCRIPT), run_name="freshness_resolved_under_test")
    live = namespace["main"].__globals__
    logs = tmp_path / "logs"
    logs.mkdir()
    notifications = []
    monkeypatch.setitem(live, "TOOL_LOG", logs / "TOOL_LOG.md")
    monkeypatch.setitem(live, "ALERTS_FILE", logs / "SERVER_FRESHNESS_ALERTS.md")
    monkeypatch.setitem(live, "TODAY", TODAY)
    monkeypatch.setitem(live, "notify", notifications.append)

    class Ctx:
        main = staticmethod(namespace["main"])
        tool_log_path = logs / "TOOL_LOG.md"
        alerts_path = logs / "SERVER_FRESHNESS_ALERTS.md"
        notified = notifications

    return Ctx


def headings(path):
    return [line for line in path.read_text().splitlines() if line.startswith("## ")]


def test_current_servers_after_open_stale_entry_append_resolved(fresh):
    fresh.tool_log_path.write_text(CURRENT_LOG)
    fresh.alerts_path.write_text(STALE_ENTRY)
    fresh.main()
    text = fresh.alerts_path.read_text()
    assert text.startswith(STALE_ENTRY)
    assert headings(fresh.alerts_path) == ["## 2026-11-05 — STALE", "## 2026-11-12 — RESOLVED"]
    assert re.search(r"^## 2026-11-12 — RESOLVED$\n\n.*all servers are current", text, re.MULTILINE | re.DOTALL | re.IGNORECASE)


def test_console_output_for_all_current_case_is_unchanged(fresh, capsys):
    fresh.tool_log_path.write_text(CURRENT_LOG)
    fresh.alerts_path.write_text(STALE_ENTRY)
    fresh.main()
    assert capsys.readouterr().out == "All servers current as of 2026-11-12. No action required.\n"
    assert fresh.notified == []


def test_second_run_does_not_append_another_resolved_entry(fresh):
    fresh.tool_log_path.write_text(CURRENT_LOG)
    fresh.alerts_path.write_text(STALE_ENTRY)
    fresh.main()
    after_first = fresh.alerts_path.read_text()
    fresh.main()
    assert fresh.alerts_path.read_text() == after_first


def test_latest_entry_already_resolved_writes_nothing(fresh):
    manual = STALE_ENTRY + "\n## 2026-10-06 — RESOLVED (manual note)\n\nSuperseded.\n"
    fresh.tool_log_path.write_text(CURRENT_LOG)
    fresh.alerts_path.write_text(manual)
    fresh.main()
    assert fresh.alerts_path.read_text() == manual


def test_header_only_alert_file_writes_nothing(fresh):
    fresh.tool_log_path.write_text(CURRENT_LOG)
    fresh.main()
    assert fresh.alerts_path.read_text() == "# Server Freshness Alerts\n"


def test_stale_servers_still_append_stale_not_resolved(fresh, capsys):
    fresh.tool_log_path.write_text(STALE_LOG)
    fresh.alerts_path.write_text(STALE_ENTRY)
    fresh.main()
    assert headings(fresh.alerts_path) == ["## 2026-11-05 — STALE", "## 2026-11-12 — STALE"]
    assert "RESOLVED" not in fresh.alerts_path.read_text()
    assert capsys.readouterr().out.startswith("STALE: 1 server(s) flagged")
    assert len(fresh.notified) == 1
