import re
import runpy
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "check_markdown_length.py"


def body(nonempty, first=b"caf\xe9\n"):
    """Bytes with `nonempty` non-empty lines; the first one is `first`."""
    return first + b"".join(b"line %d\n" % i for i in range(nonempty - 1))


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
        alerts_path = tmp_path / "logs" / "MARKDOWN_LENGTH_ALERTS.md"

        @staticmethod
        def put_bytes(relative, data):
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return path

        @staticmethod
        def run():
            """Run main(); return its exit code."""
            with pytest.raises(SystemExit) as excinfo:
                namespace["main"]()
            return excinfo.value.code

        @staticmethod
        def rows():
            text = Ctx.alerts_path.read_text(encoding="utf-8")
            return re.findall(r"^\| (\S.*?) \| (\d+) \| (OK|OVER_LIMIT) \|$", text, re.MULTILINE)

    return Ctx


def test_file_with_an_invalid_byte_is_counted(md, tmp_path):
    path = md.put_bytes("x.md", b"caf\xe9\nok\n")
    assert md.ns["count_nonempty"](path) == 2


def test_invalid_byte_file_with_101_lines_is_over_limit_and_exits_1(md):
    md.put_bytes("CLAUDE.md", body(101))
    assert md.run() == 1
    assert md.rows() == [("CLAUDE.md", "101", "OVER_LIMIT")]


def test_invalid_byte_file_with_100_lines_is_ok_and_exits_0(md):
    md.put_bytes("CLAUDE.md", body(100))
    assert md.run() == 0
    assert md.rows() == [("CLAUDE.md", "100", "OK")]


def test_other_files_are_listed_and_alerts_file_is_rewritten_with_an_invalid_byte(md):
    md.alerts_path.write_text("stale content from a previous run\n")
    md.put_bytes("CLAUDE.md", b"a\nb\n")
    md.put_bytes("TASTE.md", body(3))
    md.put_bytes("workers/a/CLAUDE.md", b"c\n")
    assert md.run() == 0
    text = md.alerts_path.read_text(encoding="utf-8")
    assert "stale content" not in text
    assert text.startswith("# Markdown Length Alerts\n")
    assert {row[0]: (row[1], row[2]) for row in md.rows()} == {
        "CLAUDE.md": ("2", "OK"),
        "workers/a/CLAUDE.md": ("1", "OK"),
        "TASTE.md": ("3", "OK"),
    }


def test_valid_utf8_with_non_ascii_character_counts_as_before(md):
    path = md.put_bytes("x.md", "a — b\n\nsecond line\n".encode("utf-8"))
    assert md.ns["count_nonempty"](path) == 2
