import re
import runpy
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "check_markdown_length.py"


def lines(nonempty, blank=0):
    body = [f"line {i}" for i in range(nonempty)] + ["", "   "][:1] * blank
    return "\n".join(body) + "\n"


@pytest.fixture
def md(tmp_path, monkeypatch):
    """Load the script with PROJECT_ROOT and ALERTS_FILE redirected into tmp_path."""
    namespace = runpy.run_path(str(SCRIPT), run_name="markdown_length_under_test")
    live = namespace["main"].__globals__
    (tmp_path / "logs").mkdir()
    monkeypatch.setitem(live, "PROJECT_ROOT", tmp_path)
    monkeypatch.setitem(live, "ALERTS_FILE", tmp_path / "logs" / "MARKDOWN_LENGTH_ALERTS.md")

    class Ctx:
        ns = namespace
        root = tmp_path
        alerts_path = tmp_path / "logs" / "MARKDOWN_LENGTH_ALERTS.md"

        @staticmethod
        def put(relative, nonempty, blank=0):
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(lines(nonempty, blank))
            return path

        @staticmethod
        def run():
            """Run main(); return its exit code."""
            with pytest.raises(SystemExit) as excinfo:
                namespace["main"]()
            return excinfo.value.code

        @staticmethod
        def rows():
            return re.findall(r"^\| (\S.*?) \| (\d+) \| (OK|OVER_LIMIT) \|$", Ctx.alerts_path.read_text(), re.MULTILINE)

    return Ctx


# ------------------------------------------------------------------ counting


def test_count_nonempty_ignores_blank_and_whitespace_only_lines(md, tmp_path):
    path = tmp_path / "x.md"
    path.write_text("a\n\n   \n\t\nb\n")
    assert md.ns["count_nonempty"](path) == 2


# ----------------------------------------------------------- limit boundary


def test_limit_is_100_nonempty_lines(md):
    assert md.ns["LIMIT"] == 100


def test_exactly_100_lines_is_ok_and_exits_0(md, capsys):
    md.put("CLAUDE.md", 100)
    assert md.run() == 0
    assert md.rows() == [("CLAUDE.md", "100", "OK")]
    assert capsys.readouterr().out == "1 files checked, 0 OVER_LIMIT\n"


def test_101_lines_is_over_limit_and_exits_1(md, capsys):
    md.put("CLAUDE.md", 101)
    assert md.run() == 1
    assert md.rows() == [("CLAUDE.md", "101", "OVER_LIMIT")]
    assert capsys.readouterr().out == "1 files checked, 1 OVER_LIMIT\n"


def test_blank_lines_do_not_count_toward_the_limit(md):
    md.put("CLAUDE.md", 100, blank=50)
    assert md.run() == 0
    assert md.rows() == [("CLAUDE.md", "100", "OK")]


def test_one_file_over_limit_fails_the_run_but_all_files_are_listed(md):
    md.put("CLAUDE.md", 10)
    md.put("TASTE.md", 150)
    md.put("workers/a/CLAUDE.md", 20)
    assert md.run() == 1
    assert {row[0]: row[2] for row in md.rows()} == {
        "CLAUDE.md": "OK",
        "TASTE.md": "OVER_LIMIT",
        "workers/a/CLAUDE.md": "OK",
    }


# ------------------------------------------------------------ file selection


def test_only_files_matching_the_patterns_are_checked(md):
    md.put("CLAUDE.md", 5)
    md.put("README.md", 500)
    md.put("pipeline/PIPELINE.md", 5)
    md.put("pipeline/phases/phase_one.md", 5)
    md.put("pipeline/runs/x/notes.md", 500)
    md.put("scripts/NOTES.md", 5)
    md.put("logs/EPHEMERAL_TASK_LOG_PROTOCOL.md", 5)
    md.put("logs/MARKDOWN_LENGTH_ALERTS.md", 500)
    assert md.run() == 0
    assert sorted(row[0] for row in md.rows()) == [
        "CLAUDE.md",
        "logs/EPHEMERAL_TASK_LOG_PROTOCOL.md",
        "pipeline/PIPELINE.md",
        "pipeline/phases/phase_one.md",
        "scripts/NOTES.md",
    ]


def test_rows_follow_pattern_order_then_sorted_within_a_pattern(md):
    md.put("TASTE.md", 1)
    md.put("workers/zeta/CLAUDE.md", 1)
    md.put("workers/alpha/CLAUDE.md", 1)
    md.put("CLAUDE.md", 1)
    md.run()
    assert [row[0] for row in md.rows()] == [
        "CLAUDE.md",
        "workers/alpha/CLAUDE.md",
        "workers/zeta/CLAUDE.md",
        "TASTE.md",
    ]


def test_a_file_matched_by_two_patterns_is_listed_once(md, monkeypatch):
    monkeypatch.setitem(md.ns["main"].__globals__, "PATTERNS", ["CLAUDE.md", "*.md"])
    md.put("CLAUDE.md", 3)
    md.run()
    assert [row[0] for row in md.rows()] == ["CLAUDE.md"]


def test_no_matching_files_still_writes_a_header_and_exits_0(md, capsys):
    assert md.run() == 0
    assert md.rows() == []
    assert capsys.readouterr().out == "0 files checked, 0 OVER_LIMIT\n"
    assert "| File | Lines | Status |" in md.alerts_path.read_text()


# --------------------------------------------------- alert file format (checklist)


def test_alert_file_format_matches_what_the_checklist_reads(md):
    md.put("CLAUDE.md", 101)
    md.run()
    text = md.alerts_path.read_text()
    assert text.startswith("# Markdown Length Alerts\n")
    assert re.search(r"^\*Last checked: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\*$", text, re.MULTILINE)
    assert "| File | Lines | Status |" in text
    assert "|------|-------|--------|" in text
    assert "| CLAUDE.md | 101 | OVER_LIMIT |" in text
    assert text.endswith("\n")


def test_alert_file_is_rewritten_not_appended(md):
    md.alerts_path.write_text("stale content from a previous run\n")
    md.put("CLAUDE.md", 1)
    md.run()
    text = md.alerts_path.read_text()
    assert "stale content" not in text
    assert text.count("# Markdown Length Alerts") == 1
