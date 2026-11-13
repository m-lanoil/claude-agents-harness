"""Tests for coordinator.acceptance: parse_worker_result and acceptance_check.

Pure functions, no SDK and no network. Relative deliverable paths resolve against
acceptance._REPO_ROOT, which is redirected into tmp_path.

Run from the repo root:
    uv run --with claude-agent-sdk --with pytest python -m pytest coordinator/tests
"""
import json

import pytest

from coordinator import acceptance
from coordinator.acceptance import acceptance_check, parse_worker_result
from coordinator.schemas import RoutingPrompt, WorkerResult


def _fence(data) -> str:
    return "Prose.\n\n```json\n" + json.dumps(data) + "\n```"


def _complete(path: str, **over) -> dict:
    data = {"deliverable_path": path, "status": "complete", "self_critique": "ok", "gaps": []}
    data.update(over)
    return data


def _routing(path, sections=()):
    return RoutingPrompt(
        worker="developer",
        prompt_text="task",
        expected_output_path=str(path),
        required_sections=list(sections),
    )


def _result(path, **over) -> WorkerResult:
    fields = dict(
        raw_text="",
        deliverable_path=str(path),
        status="complete",
        self_critique="ok",
        gaps=[],
    )
    fields.update(over)
    return WorkerResult(**fields)


@pytest.fixture
def deliverable(tmp_path):
    path = tmp_path / "report.md"
    path.write_text("# Summary\nbody\n\n## Results\nmore\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# parse_worker_result
# ---------------------------------------------------------------------------

def test_parse_valid_complete_block():
    result = parse_worker_result(_fence(_complete("a/b.md", gaps=["g1", "g2"])))
    assert result is not None
    assert result.deliverable_path == "a/b.md"
    assert result.status == "complete"
    assert result.gaps == ["g1", "g2"]
    assert result.session_id is None
    assert result.raw_text.startswith("Prose.")


def test_parse_no_block_returns_none():
    assert parse_worker_result("") is None
    assert parse_worker_result("just prose, no fence") is None
    assert parse_worker_result("```\n" + json.dumps(_complete("x")) + "\n```") is None  # not tagged json


def test_parse_invalid_json_returns_none():
    assert parse_worker_result('```json\n{"deliverable_path": "x", }\n```') is None
    assert parse_worker_result("```json\n{not json}\n```") is None


def test_parse_missing_each_required_key_returns_none():
    for missing in ("deliverable_path", "status", "self_critique", "gaps"):
        data = _complete("x")
        del data[missing]
        assert parse_worker_result(_fence(data)) is None, missing


def test_parse_uses_the_last_block():
    first = _fence(_complete("first.md"))
    second = _fence(_complete("second.md"))
    result = parse_worker_result(first + "\n\nmore text\n\n" + second)
    assert result.deliverable_path == "second.md"


def test_parse_last_block_malformed_does_not_fall_back_to_earlier_valid_one():
    raw = _fence(_complete("good.md")) + "\n\n```json\n{broken}\n```"
    assert parse_worker_result(raw) is None


def test_parse_array_block_is_not_matched():
    assert parse_worker_result("```json\n[1, 2]\n```") is None


def test_parse_extra_keys_are_ignored():
    result = parse_worker_result(_fence(_complete("x.md", extra="y")))
    assert result is not None and result.deliverable_path == "x.md"


def test_parse_nested_object_in_block():
    data = _complete("x.md")
    data["meta"] = {"inner": {"k": 1}}
    result = parse_worker_result(_fence(data))
    assert result is not None and result.deliverable_path == "x.md"


def test_parse_blocked_without_deliverable_keys_is_allowed():
    raw = _fence({"status": "blocked", "blocked_sources": [{"source": "s", "reason": "paywall"}]})
    result = parse_worker_result(raw)
    assert result.status == "blocked"
    assert result.blocked_sources == [{"source": "s", "reason": "paywall"}]


def test_parse_blocked_filters_unusable_entries_but_keeps_good_ones():
    raw = _fence({
        "status": "blocked",
        "blocked_sources": ["not a dict", {"reason": "no source"}, {"source": ""}, {"source": "ok"}],
    })
    result = parse_worker_result(raw)
    assert result.blocked_sources == [{"source": "ok"}]


def test_parse_blocked_sources_not_a_list_is_malformed():
    assert parse_worker_result(_fence({"status": "blocked", "blocked_sources": "s"})) is None


# ---------------------------------------------------------------------------
# acceptance_check: the three parts
# ---------------------------------------------------------------------------

def test_accept_all_good(deliverable):
    check = acceptance_check(_result(deliverable), _routing(deliverable, ["Summary", "Results"]))
    assert check.passed and check.file_exists and check.spec_match and check.self_critique_present
    assert check.correction_brief is None


def test_accept_no_required_sections_only_needs_file(deliverable):
    check = acceptance_check(_result(deliverable), _routing(deliverable, []))
    assert check.passed and check.spec_match


def test_missing_output_file(tmp_path):
    missing = tmp_path / "nope.md"
    check = acceptance_check(_result(missing), _routing(missing, ["Summary"]))
    assert not check.passed
    assert not check.file_exists
    assert check.spec_match is True  # nothing to scan; the failure is reported as file_exists
    assert "deliverable not found" in check.correction_brief
    assert str(missing) in check.correction_brief


def test_missing_required_section_is_named(deliverable):
    check = acceptance_check(
        _result(deliverable), _routing(deliverable, ["Summary", "Risks", "Appendix"])
    )
    assert not check.passed and check.file_exists and not check.spec_match
    assert "missing required sections" in check.correction_brief
    assert "Risks" in check.correction_brief and "Appendix" in check.correction_brief
    assert "Summary" not in check.correction_brief.split("missing required sections")[1]


def test_section_match_is_case_insensitive_substring(deliverable):
    check = acceptance_check(_result(deliverable), _routing(deliverable, ["SUMMARY", "results"]))
    assert check.passed


def test_empty_self_critique_fails(deliverable):
    for critique in ("", "   \n"):
        check = acceptance_check(
            _result(deliverable, self_critique=critique), _routing(deliverable, ["Summary"])
        )
        assert not check.passed
        assert check.file_exists and check.spec_match and not check.self_critique_present
        assert "self_critique absent" in check.correction_brief


def test_non_string_self_critique_fails_without_raising(deliverable):
    check = acceptance_check(_result(deliverable, self_critique=None), _routing(deliverable))
    assert not check.passed and not check.self_critique_present


def test_gaps_not_a_list_fails(deliverable):
    check = acceptance_check(_result(deliverable, gaps="none"), _routing(deliverable))
    assert not check.passed and not check.self_critique_present


def test_empty_gaps_list_is_fine(deliverable):
    check = acceptance_check(_result(deliverable, gaps=[]), _routing(deliverable))
    assert check.passed and check.gaps == []


def test_gaps_are_passed_through(deliverable):
    check = acceptance_check(_result(deliverable, gaps=["g1"]), _routing(deliverable))
    assert check.gaps == ["g1"]


def test_all_three_failures_are_reported_together(tmp_path):
    missing = tmp_path / "nope.md"
    check = acceptance_check(_result(missing, self_critique=""), _routing(missing, ["Summary"]))
    brief = check.correction_brief
    assert brief.startswith("Correction required: ")
    assert "deliverable not found" in brief and "self_critique absent" in brief
    assert "; " in brief


def test_section_and_critique_failures_reported_together(deliverable):
    check = acceptance_check(
        _result(deliverable, self_critique=""), _routing(deliverable, ["Nowhere"])
    )
    assert "missing required sections" in check.correction_brief
    assert "self_critique absent" in check.correction_brief


def test_relative_deliverable_path_resolves_against_repo_root(tmp_path, monkeypatch):
    monkeypatch.setattr(acceptance, "_REPO_ROOT", tmp_path)
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "r.md").write_text("# Summary", encoding="utf-8")
    check = acceptance_check(_result("out/r.md"), _routing("out/r.md", ["Summary"]))
    assert check.passed


def test_relative_path_missing_under_repo_root(tmp_path, monkeypatch):
    monkeypatch.setattr(acceptance, "_REPO_ROOT", tmp_path)
    check = acceptance_check(_result("out/r.md"), _routing("out/r.md"))
    assert not check.file_exists


# ---------------------------------------------------------------------------
# acceptance_check: inputs the parser can hand it (expected to expose defects)
# ---------------------------------------------------------------------------

def test_null_deliverable_path_fails_acceptance_instead_of_crashing():
    # parse_worker_result accepts {"deliverable_path": null, ...} because it only checks key presence.
    parsed = parse_worker_result(_fence(_complete(None)))
    assert parsed is not None
    check = acceptance_check(parsed, _routing("x.md"))
    assert not check.passed and not check.file_exists


def test_empty_deliverable_path_is_not_treated_as_existing(tmp_path, monkeypatch):
    # Path("") is "."; joined onto the repo root it is a directory that exists.
    monkeypatch.setattr(acceptance, "_REPO_ROOT", tmp_path)
    check = acceptance_check(_result(""), _routing("", ["Summary"]))
    assert not check.passed
    assert not check.file_exists


def test_deliverable_path_that_is_a_directory_fails_acceptance(tmp_path):
    check = acceptance_check(_result(tmp_path), _routing(tmp_path, ["Summary"]))
    assert not check.passed


def test_non_utf8_deliverable_with_required_sections_fails_cleanly(tmp_path):
    binary = tmp_path / "report.pdf"
    binary.write_bytes(b"%PDF-1.7\xff\xfe\x00binary")
    check = acceptance_check(_result(binary), _routing(binary, ["Summary"]))
    assert not check.passed
    assert check.file_exists
