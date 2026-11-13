"""Tests for the prompt and path helpers in coordinator.orchestrator:
build_routing_prompt, _build_validator_prompt, _topic_from_output_path, _slug.

Pure functions; no SDK calls and no network.

Run from the repo root:
    uv run --with claude-agent-sdk --with pytest python -m pytest coordinator/tests
"""
import re

from coordinator import orchestrator
from coordinator.orchestrator import (
    _build_validator_prompt,
    _slug,
    _topic_from_output_path,
    build_routing_prompt,
)
from coordinator.schemas import RoutingPrompt, WorkerResult


# ---------------------------------------------------------------------------
# build_routing_prompt
# ---------------------------------------------------------------------------

def _prompt(**over):
    args = dict(
        worker_name="developer",
        task_description="Do the thing.",
        expected_output_path="../../output/final_outputs/t/report.md",
        required_sections=["Summary", "Results"],
    )
    args.update(over)
    return build_routing_prompt(**args)


def test_routing_prompt_core_fields():
    p = _prompt()
    assert p.startswith("You are the Developer Worker.")
    assert "Task:\nDo the thing." in p
    assert "Expected output: ../../output/final_outputs/t/report.md" in p
    assert "Required sections:\n- Summary\n- Results" in p
    assert "Run your Task Start Checklist before taking any action." in p
    assert "flag any gap or assumption you made" in p


def test_routing_prompt_worker_name_is_capitalised():
    assert _prompt(worker_name="scout").startswith("You are the Scout Worker.")


def test_routing_prompt_no_sections_placeholder():
    assert "Required sections:\n- (none specified)" in _prompt(required_sections=[])


def test_routing_prompt_ends_with_json_return_convention():
    p = _prompt()
    assert p.endswith(orchestrator._JSON_RETURN_CONVENTION)
    assert '"status": "complete"' in p
    assert '"status": "blocked"' in p and "blocked_sources" in p


def test_single_hop_has_no_hop_line():
    assert "multi-hop" not in _prompt(hop_index=0, total_hops=1)


def test_multi_hop_line_is_one_based():
    p = _prompt(hop_index=1, total_hops=3)
    assert "This is hop 2 of 3 in a multi-hop chain." in p
    assert "hop 1 of 3" not in p


def test_no_hop_context_block_by_default():
    assert "Prior hop context" not in _prompt()
    assert "Prior hop context" not in _prompt(hop_context="")


def test_hop_context_block_is_included_before_expected_output():
    p = _prompt(hop_index=1, total_hops=2, hop_context="Hop 1 (architect) completed. Output path: /x/y.md.")
    assert "Prior hop context:\nHop 1 (architect) completed. Output path: /x/y.md." in p
    assert p.index("Prior hop context") < p.index("Expected output:")
    assert p.index("Task:") < p.index("Prior hop context")


def test_routing_prompt_does_not_mutate_inputs():
    sections = ["A"]
    _prompt(required_sections=sections)
    assert sections == ["A"]


# ---------------------------------------------------------------------------
# _build_validator_prompt
# ---------------------------------------------------------------------------

def _routing(sections=("Summary", "Results")):
    return RoutingPrompt(
        worker="developer",
        prompt_text="ORIGINAL TASK TEXT",
        expected_output_path="out.md",
        required_sections=list(sections),
    )


def _result(**over):
    fields = dict(
        raw_text="",
        deliverable_path="/abs/out.md",
        status="complete",
        self_critique="THE CRITIQUE",
        gaps=[],
    )
    fields.update(over)
    return WorkerResult(**fields)


def test_validator_prompt_carries_task_sections_path_and_critique():
    p = _build_validator_prompt(_routing(), _result())
    assert "## Original Task\nORIGINAL TASK TEXT" in p
    assert "## Required Sections\n- Summary\n- Results" in p
    assert "## Deliverable Path\n/abs/out.md" in p
    assert "## Worker Self-Critique\nTHE CRITIQUE" in p


def test_validator_prompt_no_sections_placeholder():
    assert "## Required Sections\n- (none specified)" in _build_validator_prompt(_routing([]), _result())


def test_validator_prompt_names_all_four_criteria_and_read_tool():
    p = _build_validator_prompt(_routing(), _result())
    for criterion in ("Coverage", "Substantiveness", "Internal consistency", "Grounding honesty"):
        assert criterion in p
    assert "Read tool" in p


def test_validator_prompt_output_contract_matches_parser_keys():
    p = _build_validator_prompt(_routing(), _result())
    for key in orchestrator._VALIDATOR_REQUIRED_KEYS:
        assert f'"{key}"' in p
    assert 'verdict must be "pass" or "fail"' in p
    assert "```json" in p


def test_validator_prompt_does_not_leak_raw_worker_text():
    p = _build_validator_prompt(_routing(), _result(raw_text="RAW WORKER TRANSCRIPT"))
    assert "RAW WORKER TRANSCRIPT" not in p


# ---------------------------------------------------------------------------
# _topic_from_output_path
# ---------------------------------------------------------------------------

def test_topic_from_final_outputs(capsys):
    assert _topic_from_output_path("../../output/final_outputs/acme/report.md") == "acme"
    assert capsys.readouterr().out == ""  # no warning on the happy path


def test_topic_from_intermediate_outputs():
    assert _topic_from_output_path("../../output/intermediate_outputs/coordinator-dev/x.md") == "coordinator-dev"


def test_topic_from_absolute_path_with_nested_file():
    assert _topic_from_output_path("/home/u/repo/output/final_outputs/topic/sub/dir/r.md") == "topic"


def test_topic_final_outputs_wins_when_both_markers_present():
    assert _topic_from_output_path("intermediate_outputs/a/final_outputs/b/r.md") == "b"


def test_topic_falls_back_to_misc_with_warning_when_file_is_directly_under_marker(capsys):
    assert _topic_from_output_path("../../output/final_outputs/report.md") == "misc"
    out = capsys.readouterr().out
    assert "Warning" in out and "misc" in out and "../../output/final_outputs/report.md" in out


def test_topic_falls_back_to_misc_without_marker(capsys):
    assert _topic_from_output_path("report.md") == "misc"
    assert "Warning" in capsys.readouterr().out


def test_topic_marker_as_last_part_is_not_a_topic(capsys):
    assert _topic_from_output_path("output/final_outputs") == "misc"
    assert "Warning" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _slug
# ---------------------------------------------------------------------------

def test_slug_basic():
    assert _slug("Uptime Institute 2026 Survey") == "uptime_institute_2026_survey"


def test_slug_collapses_runs_and_strips_edges():
    assert _slug("  --Hello,   World!!  ") == "hello_world"
    assert _slug("a---b___c") == "a_b_c"


def test_slug_url():
    assert _slug("https://example.com/a-b") == "https_example_com_a_b"


def test_slug_empty_and_symbol_only():
    assert _slug("") == ""
    assert _slug("!!!") == ""
    assert _slug("   ") == ""


def test_slug_keeps_digits_and_is_idempotent():
    once = _slug("Q3 2026 / Report (v2)")
    assert once == "q3_2026_report_v2"
    assert _slug(once) == once


def test_slug_output_is_lowercase_snake_case_for_ascii_input():
    out = _slug("Some Mixed-CASE name.pdf")
    assert re.fullmatch(r"[a-z0-9]+(_[a-z0-9]+)*", out)


