import os
import runpy
import subprocess
from datetime import date
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "check_docs_state.py"
REFRESH = (
    "To refresh the docs, ask Claude to refresh the README, operator guide or STATUS; "
    "it follows workers/DOCS_REFRESH_PROTOCOL.md."
)


def run_git(cwd, *args, when="2026-11-01T12:00:00+0000"):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
        "GIT_AUTHOR_DATE": when,
        "GIT_COMMITTER_DATE": when,
    }
    result = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True)
    return result.stdout.strip()


@pytest.fixture
def ns():
    return runpy.run_path(str(SCRIPT), run_name="docs_state_under_test")


@pytest.fixture
def repo(tmp_path, monkeypatch, ns, capsys):
    """A fixture git repo in tmp_path, with the script's PROJECT_ROOT pointed at it."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    root = tmp_path / "repo"
    root.mkdir()
    run_git(root, "init", "-q")
    run_git(root, "config", "commit.gpgsign", "false")
    monkeypatch.setitem(ns["main"].__globals__, "PROJECT_ROOT", root)
    monkeypatch.chdir(root)

    class Ctx:
        path = root

        @staticmethod
        def put(relative, text):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            return path

        @staticmethod
        def commit(relative, text="content\n", when="2026-11-01T12:00:00+0000"):
            Ctx.put(relative, text)
            run_git(root, "add", relative, when=when)
            run_git(root, "commit", "-q", "-m", f"add {relative}", when=when)
            return run_git(root, "rev-parse", "HEAD")

        @staticmethod
        def short(sha):
            return run_git(root, "log", "-1", "--format=%h", sha)

        @staticmethod
        def run(*args):
            """Run main(); return (exit code, stdout, stderr)."""
            with pytest.raises(SystemExit) as excinfo:
                ns["main"](list(args))
            captured = capsys.readouterr()
            return excinfo.value.code, captured.out, captured.err

    return Ctx


# ------------------------------------------------------------- check 1: hashes


def test_hash_that_is_an_ancestor_of_head_is_not_listed(repo):
    sha = repo.commit("a.md")
    repo.commit("b.md")
    repo.put("README.md", f"First commit {sha} is on main.\n")
    code, out, _ = repo.run("README.md")
    assert code == 0
    assert sha not in out
    assert "== Check 1: commit hashes not reachable from HEAD ==\nNone found." in out


def test_hash_on_a_side_branch_is_not_on_head(repo):
    repo.commit("a.md")
    main_branch = run_git(repo.path, "rev-parse", "--abbrev-ref", "HEAD")
    run_git(repo.path, "checkout", "-q", "-b", "side")
    side = repo.commit("side.md")
    run_git(repo.path, "checkout", "-q", main_branch)
    repo.put("README.md", f"intro\nSee {side}.\n")
    code, out, _ = repo.run("README.md")
    assert code == 1
    assert f"README.md:2  {side}  not on HEAD" in out
    assert "check 1: 1 flagged (1 not on HEAD, 0 unknown)" in out


def test_hash_that_does_not_resolve_is_unknown(repo):
    repo.commit("a.md")
    repo.put("README.md", "line one\nline two\nfixed in deadbee1\n")
    code, out, _ = repo.run("README.md")
    assert code == 1
    assert "README.md:3  deadbee1  unknown" in out
    assert "check 1: 1 flagged (0 not on HEAD, 1 unknown)" in out


def test_hex_words_without_a_digit_or_a_letter_are_not_hashes(repo, ns):
    repo.commit("a.md")
    text = "deadbeef cafebabe 1234567 20261126 2026-11-20 abc1234_x x_abc1234 " + "a1" * 21
    assert ns["hash_tokens"](text) == []
    assert ns["hash_tokens"]("see abc1234, then (0f1e2d3c4b) and " + "a1" * 20) == ["abc1234", "0f1e2d3c4b", "a1" * 20]
    repo.put("README.md", text + "\n")
    code, out, _ = repo.run("README.md")
    assert code == 0
    assert "check 1: 0 flagged" in out


# ------------------------------------------------------- check 2: state claims


def test_claim_line_listed_with_pattern_and_dates_without_changing_exit_code(repo):
    repo.commit("a.md")
    repo.put("README.md", "# Title\nSuite: 228 passed as of 2026-11-20, launchd job (cron) checked 2026-11-21.\n")
    code, out, _ = repo.run("README.md")
    assert code == 0
    assert "checklist for the reviewer, not a finding" in out
    assert "README.md:2  [N passed, as of, cron, launchd]  dates: 2026-11-20, 2026-11-21  | Suite: 228" in out
    assert "check 2: 1 claim lines to review (not findings)" in out


def test_each_claim_pattern_matches(ns):
    cases = [
        ("3 skipped", "N skipped"),
        ("41 commits", "N commits"),
        ("1 commit", "N commits"),
        ("12 entries", "N entries"),
        ("1 entry", "N entries"),
        ("1,204 tests", "N tests"),
        ("it was run live", "run live / ran live"),
        ("we ran live once", "run live / ran live"),
        ("see crontab -l", "cron"),
        ("Last run: never", "last run"),
    ]
    for line, label in cases:
        rows = ns["check_claims"]([("X.md", [line])])
        assert rows and label in rows[0][2], line


def test_line_without_claims_is_not_listed(ns):
    lines = ["Plain prose with no state.", "passed the test", "an alias offered", "macron", "launchdaemon"]
    assert ns["check_claims"]([("X.md", lines)]) == []


# ------------------------------------------- check 3: Last reviewed vs. cited


def test_last_reviewed_found_from_section(ns):
    lines = ["# Status", "", "## Last reviewed", "", "2026-11-20", "", "## Next"]
    assert ns["find_last_reviewed"](lines) == (date(2026, 11, 20), "section")


def test_last_reviewed_found_inline_case_insensitive(ns):
    lines = ["From [`STATUS.md`](STATUS.md), Last Reviewed 2026-11-20. A dash means none."]
    assert ns["find_last_reviewed"](lines) == (date(2026, 11, 20), "inline")


def test_last_reviewed_section_stops_at_next_heading(ns):
    lines = ["## Last reviewed", "", "## Other", "2026-01-01"]
    assert ns["find_last_reviewed"](lines) == (None, None)


def test_cited_path_changed_after_date_is_flagged_and_one_before_is_not(repo):
    repo.commit("old.md", when="2026-11-01T12:00:00+0000")
    repo.commit("tools/run.py", when="2026-11-10T12:00:00+0000")
    new = repo.commit("new.md", when="2026-11-25T12:00:00+0000")
    repo.commit("tools/later.py", when="2026-11-26T12:00:00+0000")
    repo.put("untracked.md", "x\n")
    repo.put(
        "docs/STATUS.md",
        "# Status\nSee `old.md`, [new](../new.md), `tools/`, `untracked.md`, `missing.md` "
        "and [site](https://example.com).\n\n## Last reviewed\n\n2026-11-20\n",
    )
    code, out, _ = repo.run("docs/STATUS.md")
    assert code == 1
    assert "docs/STATUS.md (Last reviewed 2026-11-20, section; 4 cited paths checked):" in out
    assert f"  new.md  2026-11-25  {repo.short(new)}" in out
    assert "  tools  2026-11-26  " in out
    assert "old.md  2026-11-01" not in out
    assert "Not tracked by git, not checked: untracked.md" in out
    assert "missing.md" not in out.split("== Check 3")[1]
    assert "check 3: 2 cited paths changed after Last reviewed, 0 targets skipped" in out


def test_inline_last_reviewed_with_nothing_newer_exits_0(repo):
    repo.commit("old.md", when="2026-11-01T12:00:00+0000")
    repo.put("README.md", "Based on `old.md`, last reviewed 2026-11-20.\n")
    code, out, _ = repo.run("README.md")
    assert code == 0
    assert "README.md (Last reviewed 2026-11-20, inline; 1 cited paths checked):\n  None changed after that date." in out


def test_target_without_date_is_reported_as_skipped(repo):
    repo.commit("new.md", when="2026-11-25T12:00:00+0000")
    repo.put("README.md", "See `new.md`.\n")
    code, out, _ = repo.run("README.md")
    assert code == 0
    assert "README.md: no Last reviewed date; check 3 skipped" in out
    assert "0 cited paths changed after Last reviewed, 1 targets skipped" in out


# -------------------------------------------------- report ending, exit codes


def test_refresh_line_ends_clean_and_dirty_reports(repo):
    repo.commit("a.md")
    for body, expected_code in [("Clean text.\n", 0), ("Bad ref deadbee1.\n", 1)]:
        repo.put("README.md", body)
        code, out, _ = repo.run("README.md")
        assert code == expected_code
        lines = out.rstrip("\n").splitlines()
        assert lines[-1] == REFRESH
        assert lines[-2].startswith("Summary: ")


def test_default_targets_are_read_from_repo_root(repo):
    repo.commit("a.md")
    repo.put("README.md", "readme\n")
    repo.put("docs/OPERATOR_GUIDE.md", "guide deadbee1\n")
    repo.put("STATUS.md", "status\n")
    code, out, _ = repo.run()
    assert code == 1
    assert "Targets: README.md, docs/OPERATOR_GUIDE.md, STATUS.md" in out
    assert "docs/OPERATOR_GUIDE.md:1  deadbee1  unknown" in out


def test_exit_2_when_not_a_git_repo(tmp_path, monkeypatch, ns, capsys):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "README.md").write_text("text\n")
    monkeypatch.setitem(ns["main"].__globals__, "PROJECT_ROOT", plain)
    monkeypatch.chdir(plain)
    with pytest.raises(SystemExit) as excinfo:
        ns["main"](["README.md"])
    captured = capsys.readouterr()
    assert excinfo.value.code == 2
    assert "not a git repository" in captured.err
    assert captured.out == ""


def test_exit_2_when_repo_has_no_commit(repo):
    repo.put("README.md", "text\n")
    code, _, err = repo.run("README.md")
    assert code == 2
    assert "not a git repository with a HEAD commit" in err


def test_exit_2_when_target_is_missing(repo):
    repo.commit("a.md")
    code, out, err = repo.run("nope.md")
    assert code == 2
    assert "target not found: nope.md" in err
    assert out == ""


def test_exit_2_on_unknown_option(repo):
    code, _, err = repo.run("--bogus")
    assert code == 2
    assert "usage:" in err


def test_script_never_writes_files(repo):
    repo.commit("a.md")
    repo.put("README.md", "deadbee1 and 3 tests as of 2026-11-20, last reviewed 2026-11-20 `a.md`\n")
    def snapshot():
        return sorted((p, p.read_bytes() if p.is_file() else None) for p in repo.path.rglob("*") if ".git" not in p.parts)

    before = snapshot()
    repo.run("README.md")
    after = snapshot()
    assert before == after
