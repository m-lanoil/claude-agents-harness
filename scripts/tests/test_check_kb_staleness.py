import runpy
from datetime import date, timedelta
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "check_kb_staleness.py"
TODAY = date(2026, 11, 14)
CLEAN_LINE = "Clean run: All kb files current — no stale entries."


def kb_text(fetched):
    return f"---\nlibrary: x\nsource: https://example.com\nfetched: {fetched}\n---\nbody\n"


@pytest.fixture
def stale_mod(tmp_path, monkeypatch):
    """Load the script with its paths, clock and notifier redirected into tmp_path."""
    namespace = runpy.run_path(str(SCRIPT), run_name="kb_staleness_under_test")
    live = namespace["main"].__globals__
    logs = tmp_path / "logs"
    logs.mkdir()
    dev = tmp_path / "developer_kb"
    dev.mkdir()
    srv = tmp_path / "servers_kb"
    srv.mkdir()
    notifications = []
    monkeypatch.setitem(live, "KB_LOG", logs / "KB_STALENESS_LOG.md")
    monkeypatch.setitem(live, "KB_DIRS", {"developer": dev, "servers": srv})
    monkeypatch.setitem(live, "TODAY", TODAY)
    monkeypatch.setitem(live, "notify", notifications.append)

    class Ctx:
        ns = namespace
        log_path = logs / "KB_STALENESS_LOG.md"
        dev_dir = dev
        srv_dir = srv
        notified = notifications
        live_globals = live

    return Ctx


def days_ago(n):
    return TODAY - timedelta(days=n)


# get_fetched_date

def test_get_fetched_date_reads_the_front_matter_date(stale_mod, tmp_path):
    f = tmp_path / "kb_a.md"
    f.write_text(kb_text("2026-10-05"))
    assert stale_mod.ns["get_fetched_date"](f) == date(2026, 10, 5)


def test_get_fetched_date_returns_none_when_no_fetched_line(stale_mod, tmp_path):
    f = tmp_path / "kb_a.md"
    f.write_text("---\nlibrary: x\n---\nbody\n")
    assert stale_mod.ns["get_fetched_date"](f) is None


def test_get_fetched_date_returns_none_for_an_invalid_date(stale_mod, tmp_path):
    f = tmp_path / "kb_a.md"
    f.write_text(kb_text("2026-13-45"))
    assert stale_mod.ns["get_fetched_date"](f) is None


def test_get_fetched_date_returns_none_for_a_malformed_date(stale_mod, tmp_path):
    f = tmp_path / "kb_a.md"
    f.write_text(kb_text("yesterday"))
    assert stale_mod.ns["get_fetched_date"](f) is None


def test_get_fetched_date_ignores_an_indented_fetched_line(stale_mod, tmp_path):
    f = tmp_path / "kb_a.md"
    f.write_text("body\n    fetched: 2026-10-05\n")
    assert stale_mod.ns["get_fetched_date"](f) is None


# scan

def test_scan_at_exactly_30_days_is_not_stale(stale_mod):
    (stale_mod.dev_dir / "kb_edge.md").write_text(kb_text(days_ago(30)))
    assert stale_mod.ns["scan"]() == []


def test_scan_at_31_days_is_stale(stale_mod):
    fetched = days_ago(31)
    (stale_mod.dev_dir / "kb_edge.md").write_text(kb_text(fetched))
    assert stale_mod.ns["scan"]() == [("developer", "kb_edge.md", fetched, 31)]


def test_scan_skips_a_missing_kb_directory(stale_mod, monkeypatch, tmp_path):
    (stale_mod.srv_dir / "kb_old.md").write_text(kb_text(days_ago(60)))
    monkeypatch.setitem(
        stale_mod.live_globals, "KB_DIRS",
        {"architect": tmp_path / "does_not_exist", "servers": stale_mod.srv_dir},
    )
    assert stale_mod.ns["scan"]() == [("servers", "kb_old.md", days_ago(60), 60)]


def test_scan_skips_files_without_a_valid_date_and_non_kb_names(stale_mod):
    (stale_mod.dev_dir / "kb_nodate.md").write_text("no front matter\n")
    (stale_mod.dev_dir / "kb_baddate.md").write_text(kb_text("2026-02-30"))
    (stale_mod.dev_dir / "notes_old.md").write_text(kb_text(days_ago(90)))
    (stale_mod.dev_dir / "kb_old.txt").write_text(kb_text(days_ago(90)))
    assert stale_mod.ns["scan"]() == []


def test_scan_lists_files_sorted_per_worker_in_kb_dirs_order(stale_mod):
    (stale_mod.dev_dir / "kb_b.md").write_text(kb_text(days_ago(40)))
    (stale_mod.dev_dir / "kb_a.md").write_text(kb_text(days_ago(50)))
    (stale_mod.srv_dir / "kb_c.md").write_text(kb_text(days_ago(35)))
    result = stale_mod.ns["scan"]()
    assert [(w, n) for w, n, _, _ in result] == [
        ("developer", "kb_a.md"), ("developer", "kb_b.md"), ("servers", "kb_c.md"),
    ]
    assert [age for _, _, _, age in result] == [50, 40, 35]


# ensure_header

def test_ensure_header_creates_the_log_when_missing(stale_mod):
    stale_mod.ns["ensure_header"]()
    assert stale_mod.log_path.read_text() == "# KB Staleness Log\n"


def test_ensure_header_leaves_an_existing_log_alone(stale_mod):
    stale_mod.log_path.write_text("# KB Staleness Log\n\n## 2026-11-01\nold entry\n")
    stale_mod.ns["ensure_header"]()
    assert stale_mod.log_path.read_text() == "# KB Staleness Log\n\n## 2026-11-01\nold entry\n"


# append_entry

def test_append_entry_clean_case(stale_mod):
    stale_mod.ns["ensure_header"]()
    stale_mod.ns["append_entry"]([])
    assert stale_mod.log_path.read_text() == f"# KB Staleness Log\n\n## 2026-11-14\n\n{CLEAN_LINE}\n\n"


def test_append_entry_stale_case_writes_a_table_row_per_file(stale_mod):
    stale_mod.ns["ensure_header"]()
    stale_mod.ns["append_entry"]([
        ("developer", "kb_a.md", date(2026, 10, 1), 44),
        ("servers", "kb_b.md", date(2026, 9, 1), 74),
    ])
    text = stale_mod.log_path.read_text()
    assert text.startswith("# KB Staleness Log\n\n## 2026-11-14\n")
    assert "| Worker | File | Fetched | Age (days) |\n|--------|------|---------|------------|\n" in text
    assert "| developer | `kb_a.md` | 2026-10-01 | 44 |\n" in text
    assert "| servers | `kb_b.md` | 2026-09-01 | 74 |\n" in text
    assert CLEAN_LINE not in text


def test_append_entry_appends_and_keeps_earlier_entries(stale_mod):
    stale_mod.ns["ensure_header"]()
    stale_mod.ns["append_entry"]([])
    stale_mod.ns["append_entry"]([("developer", "kb_a.md", date(2026, 10, 1), 44)])
    text = stale_mod.log_path.read_text()
    assert text.count("## 2026-11-14") == 2
    assert text.index(CLEAN_LINE) < text.index("| developer | `kb_a.md`")


# main

def test_main_stale_run_logs_prints_and_notifies(stale_mod, capsys):
    fetched = days_ago(44)
    (stale_mod.dev_dir / "kb_old.md").write_text(kb_text(fetched))
    (stale_mod.srv_dir / "kb_fresh.md").write_text(kb_text(days_ago(5)))
    assert stale_mod.ns["main"]() is None
    assert capsys.readouterr().out == "STALE: 1 kb file(s) flagged. Written to KB_STALENESS_LOG.md\n"
    text = stale_mod.log_path.read_text()
    assert text.startswith("# KB Staleness Log\n")
    assert f"| developer | `kb_old.md` | {fetched} | 44 |" in text
    assert "kb_fresh.md" not in text
    assert stale_mod.notified == [[("developer", "kb_old.md", fetched, 44)]]


def test_main_clean_run_logs_prints_and_does_not_notify(stale_mod, capsys):
    (stale_mod.dev_dir / "kb_fresh.md").write_text(kb_text(days_ago(30)))
    stale_mod.ns["main"]()
    assert capsys.readouterr().out == "All kb files current as of 2026-11-14.\n"
    assert CLEAN_LINE in stale_mod.log_path.read_text()
    assert stale_mod.notified == []


def test_main_run_twice_keeps_one_header_and_two_entries(stale_mod):
    stale_mod.ns["main"]()
    stale_mod.ns["main"]()
    text = stale_mod.log_path.read_text()
    assert text.count("# KB Staleness Log") == 1
    assert text.count("## 2026-11-14") == 2
