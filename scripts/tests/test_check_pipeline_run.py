import runpy
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "check_pipeline_run.py"
ARGV0 = "check_pipeline_run.py"
ORDER = [
    "task.md",
    "research.md",
    "plan.md",
    "holdback/test_spec.md",
    "implementation_notes.md",
    "validation_report.md",
    "publish_report.md",
]
APPROVED = "Human Verdict: APPROVED\n"
STATUSES = {"PRESENT", "MISSING", "OUT_OF_ORDER"}


@pytest.fixture
def run_check(monkeypatch, capsys):
    """Return a callable that runs the script's main() on an argv list and gives (exit code, stdout lines)."""
    namespace = runpy.run_path(str(SCRIPT), run_name="pipeline_run_under_test")

    def run(*args):
        monkeypatch.setattr(sys, "argv", [ARGV0, *map(str, args)])
        with pytest.raises(SystemExit) as info:
            namespace["main"]()
        return info.value.code, capsys.readouterr().out.splitlines()

    return run


def make_run(tmp_path, present, contents=None):
    """Create a run directory holding the named artifacts; contents maps artifact -> text."""
    contents = contents or {}
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    for artifact in present:
        path = run_dir / artifact
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents.get(artifact, "x\n"))
    return run_dir


def statuses(lines):
    result = {}
    for line in lines:
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[0] in STATUSES:
            result[parts[1]] = parts[0]
    return result


def line_for(status, artifact):
    return f"{status:12} {artifact}"


# exit code 2: bad invocation

def test_no_argument_exits_2_with_usage(run_check):
    code, out = run_check()
    assert code == 2
    assert out == [f"usage: {ARGV0} pipeline/runs/<task_slug>"]


def test_too_many_arguments_exits_2(run_check, tmp_path):
    code, out = run_check(tmp_path, tmp_path)
    assert code == 2
    assert out[0].startswith("usage:")


def test_nonexistent_directory_exits_2(run_check, tmp_path):
    code, out = run_check(tmp_path / "missing")
    assert code == 2
    assert out[0].startswith("usage:")


def test_a_file_instead_of_a_directory_exits_2(run_check, tmp_path):
    f = tmp_path / "file.md"
    f.write_text("x")
    code, _ = run_check(f)
    assert code == 2


# exit code 0: no violations

def test_empty_run_directory_exits_0_with_every_artifact_missing(run_check, tmp_path):
    code, out = run_check(make_run(tmp_path, []))
    assert code == 0
    assert statuses(out) == {a: "MISSING" for a in ORDER}
    assert line_for("MISSING", "task.md") in out
    assert out[-1] == "RESUME AT: phase 1 — research (earliest gap: task.md)"


def test_complete_approved_run_exits_0(run_check, tmp_path):
    run_dir = make_run(tmp_path, ORDER, {"validation_report.md": APPROVED})
    code, out = run_check(run_dir)
    assert code == 0
    assert statuses(out) == {a: "PRESENT" for a in ORDER}
    assert line_for("PRESENT", "holdback/test_spec.md") in out
    assert out[-1] == "RUN COMPLETE: all artifacts present"
    assert not any(line.startswith("RESUME AT") for line in out)


def test_in_order_partial_run_exits_0_and_resumes_at_the_first_gap(run_check, tmp_path):
    run_dir = make_run(tmp_path, ["task.md", "research.md", "plan.md"])
    code, out = run_check(run_dir)
    assert code == 0
    assert statuses(out) == {
        "task.md": "PRESENT", "research.md": "PRESENT", "plan.md": "PRESENT",
        "holdback/test_spec.md": "MISSING", "implementation_notes.md": "MISSING",
        "validation_report.md": "MISSING", "publish_report.md": "MISSING",
    }
    assert out[-1] == "RESUME AT: phase 2 — planning (earliest gap: holdback/test_spec.md)"


@pytest.mark.parametrize("missing,phase,name", [
    ("implementation_notes.md", 3, "coding"),
    ("validation_report.md", 4, "validation"),
    ("publish_report.md", 5, "publicizing"),
])
def test_resume_line_names_the_phase_of_the_earliest_gap(run_check, tmp_path, missing, phase, name):
    present = ORDER[:ORDER.index(missing)]
    run_dir = make_run(tmp_path, present, {"validation_report.md": APPROVED})
    code, out = run_check(run_dir)
    assert code == 0
    assert out[-1] == f"RESUME AT: phase {phase} — {name} (earliest gap: {missing})"


# exit code 1: violations

def test_artifact_after_a_gap_is_out_of_order_and_exits_1(run_check, tmp_path):
    run_dir = make_run(tmp_path, ["task.md", "plan.md"])
    code, out = run_check(run_dir)
    assert code == 1
    found = statuses(out)
    assert found["task.md"] == "PRESENT"
    assert found["research.md"] == "MISSING"
    assert found["plan.md"] == "OUT_OF_ORDER"
    assert line_for("OUT_OF_ORDER", "plan.md") in out
    assert out[-1] == "RESUME AT: phase 1 — research (earliest gap: research.md)"


def test_every_artifact_after_the_first_gap_is_out_of_order(run_check, tmp_path):
    present = [a for a in ORDER if a != "task.md"]
    run_dir = make_run(tmp_path, present, {"validation_report.md": APPROVED})
    code, out = run_check(run_dir)
    assert code == 1
    found = statuses(out)
    assert found["task.md"] == "MISSING"
    assert all(found[a] == "OUT_OF_ORDER" for a in present)


def test_publish_without_validation_report_is_a_gate_violation(run_check, tmp_path):
    run_dir = make_run(tmp_path, ORDER[:5] + ["publish_report.md"])
    code, out = run_check(run_dir)
    assert code == 1
    assert "GATE_VIOLATION publish_report.md exists without 'Human Verdict: APPROVED'" in out


def test_publish_with_unapproved_validation_report_is_a_gate_violation(run_check, tmp_path):
    run_dir = make_run(tmp_path, ORDER, {"validation_report.md": "Human Verdict: PENDING\n"})
    code, out = run_check(run_dir)
    assert code == 1
    assert "GATE_VIOLATION publish_report.md exists without 'Human Verdict: APPROVED'" in out
    assert out[-1] == "RUN COMPLETE: all artifacts present"


def test_publish_with_approved_validation_report_has_no_gate_violation(run_check, tmp_path):
    run_dir = make_run(tmp_path, ORDER, {"validation_report.md": "intro\nHuman Verdict: APPROVED\n"})
    code, out = run_check(run_dir)
    assert code == 0
    assert not any(line.startswith("GATE_VIOLATION") for line in out)


def test_approved_verdict_may_be_a_markdown_heading(run_check, tmp_path):
    run_dir = make_run(tmp_path, ORDER, {"validation_report.md": "## Human Verdict: APPROVED\n"})
    code, _ = run_check(run_dir)
    assert code == 0


@pytest.mark.parametrize("text", [
    "Human Verdict: REJECTED\n",
    "The Human Verdict: APPROVED was given\n",
    "Human Verdict: APPROVEDX\n",
    "",
])
def test_verdict_text_that_is_not_an_approval_line_fails_the_gate(run_check, tmp_path, text):
    run_dir = make_run(tmp_path, ORDER, {"validation_report.md": text})
    code, out = run_check(run_dir)
    assert code == 1
    assert any(line.startswith("GATE_VIOLATION") for line in out)


def test_gate_is_not_checked_while_publish_report_is_absent(run_check, tmp_path):
    run_dir = make_run(tmp_path, ORDER[:6], {"validation_report.md": "no verdict yet\n"})
    code, out = run_check(run_dir)
    assert code == 0
    assert not any(line.startswith("GATE_VIOLATION") for line in out)
    assert out[-1] == "RESUME AT: phase 5 — publicizing (earliest gap: publish_report.md)"


# [PROVISIONAL marker

def test_provisional_marker_in_plan_forces_resume_at_phase_2(run_check, tmp_path):
    run_dir = make_run(
        tmp_path, ORDER,
        {"plan.md": "Step 1 [PROVISIONAL: waiting on research]\n", "validation_report.md": APPROVED},
    )
    code, out = run_check(run_dir)
    assert code == 0
    assert "PROVISIONAL   plan.md has unreconciled items — a phase 2 gap" in out
    assert out[-1] == "RESUME AT: phase 2 — planning"
    assert not any(line.startswith("RUN COMPLETE") for line in out)


def test_provisional_marker_pulls_a_later_gap_back_to_phase_2(run_check, tmp_path):
    run_dir = make_run(tmp_path, ORDER[:5], {"plan.md": "[PROVISIONAL]\n"})
    code, out = run_check(run_dir)
    assert code == 0
    assert out[-1] == "RESUME AT: phase 2 — planning"


def test_provisional_marker_does_not_move_an_earlier_gap_forward(run_check, tmp_path):
    present = [a for a in ORDER if a != "task.md"]
    run_dir = make_run(tmp_path, present, {"plan.md": "[PROVISIONAL]\n", "validation_report.md": APPROVED})
    _, out = run_check(run_dir)
    assert out[-1] == "RESUME AT: phase 1 — research (earliest gap: task.md)"


def test_provisional_marker_keeps_the_gap_suffix_when_the_gap_is_in_phase_2(run_check, tmp_path):
    run_dir = make_run(tmp_path, ["task.md", "research.md", "plan.md"], {"plan.md": "[PROVISIONAL]\n"})
    _, out = run_check(run_dir)
    assert out[-1] == "RESUME AT: phase 2 — planning (earliest gap: holdback/test_spec.md)"


@pytest.mark.parametrize("text", ["provisional approach\n", "PROVISIONAL without bracket\n"])
def test_provisional_word_without_the_bracket_is_not_a_gap(run_check, tmp_path, text):
    run_dir = make_run(tmp_path, ORDER, {"plan.md": text, "validation_report.md": APPROVED})
    code, out = run_check(run_dir)
    assert code == 0
    assert not any(line.startswith("PROVISIONAL") for line in out)
    assert out[-1] == "RUN COMPLETE: all artifacts present"


def test_provisional_marker_is_ignored_when_plan_is_absent(run_check, tmp_path):
    run_dir = make_run(tmp_path, ["task.md", "research.md"])
    _, out = run_check(run_dir)
    assert not any(line.startswith("PROVISIONAL") for line in out)
    assert out[-1] == "RESUME AT: phase 2 — planning (earliest gap: plan.md)"
