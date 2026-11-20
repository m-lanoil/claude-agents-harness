"""Tests for multi-hop sequencing in coordinator.orchestrator: _execute_chain, run,
and _run_single_hop's malformed-return handling.

No live SDK calls and no network. A fake `query` plays both the workers and the
Validator; it writes the deliverable file the worker was told to produce (found on
the "Expected output:" line of the prompt) so the real acceptance check runs.
Worker dirs are nested two levels under tmp_path so the code's `../../output/...`
intermediate paths land in tmp_path/output.

Run from the repo root:
    uv run --with claude-agent-sdk --with pytest python -m pytest coordinator/tests
"""
import asyncio
import json
import re
from pathlib import Path

import pytest

from coordinator import orchestrator
from coordinator.schemas import RoutingPrompt


# ---------------------------------------------------------------------------
# Helpers and fixture
# ---------------------------------------------------------------------------

def _fence(data: dict) -> str:
    return "Some prose.\n\n```json\n" + json.dumps(data) + "\n```"


def _verdict(verdict="pass", issues=None, confidence=0.9, summary="looks fine") -> str:
    return _fence({
        "verdict": verdict,
        "issues": issues if issues is not None else [],
        "confidence": confidence,
        "summary": summary,
    })


PASS = _verdict()
CRITICAL = {"severity": "critical", "section": "Summary", "description": "Summary is a placeholder"}
FAIL_CRITICAL = _verdict("fail", [CRITICAL], 0.9, "needs work")

_EXPECTED_RE = re.compile(r"^Expected output: (.+)$", re.MULTILINE)


class _InitMessage:
    def __init__(self, session_id):
        self.subtype = "init"
        self.data = {"session_id": session_id}


class _ResultMessage:
    def __init__(self, text):
        self.result = text


class Env:
    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.workers_root = tmp_path / "workers"
        self.dirs = {}
        for name in ("architect", "developer"):
            d = self.workers_root / name
            d.mkdir(parents=True)
            self.dirs[name] = d
        self.log_path = tmp_path / "worker_updates.md"
        self.final = tmp_path / "output" / "final_outputs" / "topic_x" / "report.md"
        self.intermediate_dir = tmp_path / "output" / "intermediate_outputs" / "topic_x"
        # Scripted behaviour. Worker spec: (session_id or None, kind); kind is
        # "complete" | "noop" | "blocked" | "garbage" | {"gaps": [...]}.
        self.worker_script: list[tuple] = []
        self.validator_script: list[str] = []
        self.calls: list[dict] = []      # {"kind", "worker", "prompt", "options"}
        self.inputs: list[str] = []
        self.prompts: list[str] = []
        self.events: list[str] = []      # "validator" / "input:<prompt>" in call order

    def worker_calls(self):
        return [c for c in self.calls if c["kind"] == "worker"]

    def validator_calls(self):
        return [c for c in self.calls if c["kind"] == "validator"]

    def log_text(self) -> str:
        return self.log_path.read_text(encoding="utf-8") if self.log_path.exists() else ""

    def worker_text(self, spec, prompt, worker) -> str:
        match = _EXPECTED_RE.search(prompt)
        path = match.group(1).strip() if match else ""
        if spec == "garbage":
            return "I finished but forgot the JSON block."
        if spec == "blocked":
            return _fence({"status": "blocked", "blocked_sources": [{"source": "s", "reason": "paywall"}]})
        gaps = []
        if isinstance(spec, dict):
            gaps = spec.get("gaps", [])
        if spec != "noop" and path:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# Summary\nbody\n\n# Results\nmore\n", encoding="utf-8")
        return _fence({
            "deliverable_path": path,
            "status": "complete",
            "self_critique": f"critique from {worker}",
            "gaps": gaps,
        })


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = Env(tmp_path)

    async def fake_query(*, prompt, options):
        if options == {"validator": True}:
            e.events.append("validator")
            e.calls.append({"kind": "validator", "worker": None, "prompt": prompt, "options": options})
            yield _ResultMessage(e.validator_script.pop(0))
            return
        e.calls.append({"kind": "worker", "worker": options["worker"], "prompt": prompt, "options": options})
        session_id, spec = e.worker_script.pop(0)
        if session_id is not None:
            yield _InitMessage(session_id)
        yield _ResultMessage(e.worker_text(spec, prompt, options["worker"]))

    def fake_input(prompt=""):
        e.prompts.append(prompt)
        e.events.append(f"input:{prompt}")
        assert e.inputs, f"unexpected input() call: {prompt!r}"
        return e.inputs.pop(0)

    monkeypatch.setattr(orchestrator, "query", fake_query)
    monkeypatch.setattr(
        orchestrator, "build_options",
        lambda worker, resume=None: {"worker": worker, "resume": resume},
    )
    monkeypatch.setattr(orchestrator, "build_validator_options", lambda: {"validator": True})
    monkeypatch.setattr(orchestrator, "input", fake_input, raising=False)
    monkeypatch.setattr(orchestrator, "WORKER_DIRS", dict(e.dirs))
    monkeypatch.setattr(orchestrator, "_WORKER_UPDATES_LOG", e.log_path)
    return e


def _chain(env, workers=("architect", "developer"), sections=("Summary",), output=None, task="Produce the thing."):
    return asyncio.run(orchestrator._execute_chain(
        hop_workers=list(workers),
        task=task,
        expected_output_path=str(output or env.final),
        required_sections=list(sections),
    ))


def _two_hop_happy(env):
    env.worker_script = [("a1", "complete"), ("d1", "complete")]
    env.validator_script = [PASS, PASS]
    env.inputs = ["yes", "yes"]  # approve each hop's prompt


# ---------------------------------------------------------------------------
# Happy path: hand-off between hops
# ---------------------------------------------------------------------------

def test_two_hop_chain_succeeds_and_writes_both_outputs(env, capsys):
    _two_hop_happy(env)
    assert _chain(env) is True
    hop1_file = env.intermediate_dir / "coordinator_hop_1_architect.md"
    assert hop1_file.exists() and env.final.exists()
    log = env.log_text()
    assert "Hop 1/2 accepted" in log and "Hop 2/2 accepted" in log
    assert [c["worker"] for c in env.worker_calls()] == ["architect", "developer"]
    assert len(env.validator_calls()) == 2
    assert "Hop 2/2 passed." in capsys.readouterr().out


def test_hop_two_prompt_carries_hop_one_output_path_and_critique(env):
    _two_hop_happy(env)
    _chain(env)
    hop1_path = str((env.intermediate_dir / "coordinator_hop_1_architect.md").resolve())
    p1, p2 = (c["prompt"] for c in env.worker_calls())
    assert "Prior hop context" not in p1
    assert "Prior hop context:" in p2
    assert "Hop 1 (architect) completed." in p2
    assert f"Output path: {hop1_path}" in p2
    assert "critique from architect" in p2
    assert "This is hop 1 of 2" in p1 and "This is hop 2 of 2" in p2


def test_intermediate_hop_writes_to_intermediate_path_and_last_hop_to_final(env):
    _two_hop_happy(env)
    _chain(env)
    p1, p2 = (c["prompt"] for c in env.worker_calls())
    hop1_path = str((env.intermediate_dir / "coordinator_hop_1_architect.md").resolve())
    assert f"Expected output: {hop1_path}" in p1
    assert f"Expected output: {env.final}" in p2


def test_required_sections_apply_to_the_last_hop_only(env):
    _two_hop_happy(env)
    _chain(env, sections=("Summary", "Results"))
    p1, p2 = (c["prompt"] for c in env.worker_calls())
    assert "Required sections:\n- (none specified)" in p1
    assert "Required sections:\n- Summary\n- Results" in p2


def test_single_hop_chain_writes_straight_to_final_path(env):
    env.worker_script = [("d1", "complete")]
    env.validator_script = [PASS]
    env.inputs = ["yes"]
    assert _chain(env, workers=("developer",)) is True
    assert env.final.exists()
    # no intermediate hop output; the only file there is the brief record
    assert not (env.intermediate_dir / "coordinator_hop_1_developer.md").exists()
    assert "multi-hop" not in env.worker_calls()[0]["prompt"]


def test_output_path_without_topic_folder_uses_misc(env, capsys):
    env.worker_script = [("a1", "complete"), ("d1", "complete")]
    env.validator_script = [PASS, PASS]
    env.inputs = ["yes", "yes"]
    flat = env.tmp_path / "flat_report.md"
    assert _chain(env, output=flat) is True
    assert (env.tmp_path / "output" / "intermediate_outputs" / "misc" / "coordinator_hop_1_architect.md").exists()
    assert "Warning" in capsys.readouterr().out


def test_each_hop_has_its_own_approval_gate(env):
    _two_hop_happy(env)
    _chain(env)
    assert env.prompts.count("Approve? (yes / edit / abort): ") == 2


# ---------------------------------------------------------------------------
# A failing hop stops the chain
# ---------------------------------------------------------------------------

def test_abort_at_first_approval_gate_runs_nothing(env, capsys):
    env.inputs = ["abort"]
    assert _chain(env) is False
    assert env.calls == []
    assert "Task aborted by user." in capsys.readouterr().out


def test_hop_one_acceptance_failure_declined_stops_chain(env):
    env.worker_script = [("a1", "noop")]  # claims a file it never wrote
    env.inputs = ["yes", "abort"]          # approve prompt, then decline the retry
    assert _chain(env) is False
    assert len(env.calls) == 1             # no validator, no hop 2
    assert env.calls[0]["worker"] == "architect"
    assert "Acceptance failed, user escalated" in env.log_text()


def test_hop_one_malformed_return_stops_chain(env):
    env.worker_script = [("a1", "garbage")]
    env.inputs = ["yes", "abort"]
    assert _chain(env) is False
    assert [c["worker"] for c in env.worker_calls()] == ["architect"]


def test_hop_one_blocked_and_owner_aborts_stops_chain(env):
    env.worker_script = [("a1", "blocked")]
    env.inputs = ["yes", "4"]  # approve, then "abort" at the blocked-source prompt
    assert _chain(env) is False
    assert len(env.calls) == 1


def test_hop_one_validator_hard_fail_and_owner_aborts_stops_chain(env):
    env.worker_script = [("a1", "complete")]
    env.validator_script = [FAIL_CRITICAL]
    env.inputs = ["yes", "abort"]  # approve hop, then decline the semantic correction
    assert _chain(env) is False
    assert [c["worker"] for c in env.worker_calls()] == ["architect"]
    log = env.log_text()
    assert "Hop 1/2 not closed by Validator" in log
    assert "Hop 1/2 accepted" not in log


def test_hop_two_failure_keeps_hop_one_accepted_in_log(env):
    env.worker_script = [("a1", "complete"), ("d1", "noop")]
    env.validator_script = [PASS]
    env.inputs = ["yes", "yes", "abort"]
    assert _chain(env) is False
    log = env.log_text()
    assert "Hop 1/2 accepted" in log and "Hop 2/2 accepted" not in log
    assert "Acceptance failed, user escalated" in log


def test_failed_chain_never_reports_the_failing_hop_as_passed(env, capsys):
    env.worker_script = [("a1", "noop")]
    env.inputs = ["yes", "abort"]
    _chain(env)
    out = capsys.readouterr().out
    assert "Acceptance FAILED" in out
    assert "Hop 1/2 passed." not in out


# ---------------------------------------------------------------------------
# Acceptance correction retry inside a hop
# ---------------------------------------------------------------------------

def test_acceptance_retry_prompt_appends_correction_brief(env):
    env.worker_script = [("d1", "noop"), ("d2", "complete")]
    env.validator_script = [PASS]
    env.inputs = ["yes", "yes", "yes"]  # approve, retry, approve correction
    assert _chain(env, workers=("developer",)) is True
    first, second = (c["prompt"] for c in env.worker_calls())
    assert second.startswith(first)
    assert "CORRECTION REQUIRED:\nCorrection required: deliverable not found" in second


def test_acceptance_retry_resumes_the_same_worker_session(env):
    # The code comment says "One correction retry with session resumption", and the
    # semantic-correction path resumes. The acceptance retry should too.
    env.worker_script = [("d1", "noop"), ("d2", "complete")]
    env.validator_script = [PASS]
    env.inputs = ["yes", "yes", "yes"]
    _chain(env, workers=("developer",))
    first, second = env.worker_calls()
    assert first["options"]["resume"] is None
    assert second["options"]["resume"] == "d1"


def test_acceptance_retry_declined_at_correction_prompt(env):
    env.worker_script = [("d1", "noop")]
    env.inputs = ["yes", "yes", "abort"]  # approve, retry yes, correction prompt aborted
    assert _chain(env, workers=("developer",)) is False
    assert len(env.worker_calls()) == 1


def test_acceptance_retry_also_failing_stops(env):
    env.worker_script = [("d1", "noop"), ("d2", "noop")]
    env.inputs = ["yes", "yes", "yes"]
    assert _chain(env, workers=("developer",)) is False
    assert len(env.worker_calls()) == 2 and env.validator_calls() == []
    assert "Retry failed" in env.log_text()


def test_acceptance_retry_blocks_a_second_semantic_retry(env, capsys):
    env.worker_script = [("d1", "noop"), ("d2", "complete")]
    env.validator_script = [FAIL_CRITICAL]
    env.inputs = ["yes", "yes", "yes"]
    assert _chain(env, workers=("developer",)) is False
    assert len(env.worker_calls()) == 2  # no third worker call
    assert "Retry budget exhausted" in capsys.readouterr().out


def test_semantic_correction_in_hop_two_keeps_hop_one_context(env):
    env.worker_script = [("a1", "complete"), ("d1", "complete"), ("d2", "complete")]
    env.validator_script = [PASS, FAIL_CRITICAL, PASS]
    env.inputs = ["yes", "yes", "yes"]  # approve hop 1, approve hop 2, approve semantic correction
    assert _chain(env) is True
    correction = env.worker_calls()[2]
    assert correction["options"]["resume"] == "d1"
    assert "SEMANTIC CORRECTION REQUIRED" in correction["prompt"]
    hop1_path = str((env.intermediate_dir / "coordinator_hop_1_architect.md").resolve())
    assert hop1_path in correction["prompt"], "correction prompt dropped the prior hop context"


# ---------------------------------------------------------------------------
# Gap acknowledgment
# ---------------------------------------------------------------------------

def test_reported_gaps_require_acknowledgment(env, capsys):
    env.worker_script = [("d1", {"gaps": ["g one", "g two"]})]
    env.validator_script = [PASS]
    env.inputs = ["yes", ""]
    assert _chain(env, workers=("developer",)) is True
    out = capsys.readouterr().out
    assert "Worker reported gaps" in out and "g one" in out and "g two" in out
    assert any("Acknowledge gaps" in p for p in env.prompts)
    assert "Gaps: ['g one', 'g two']" in env.log_text()


def test_no_gaps_means_no_acknowledgment_prompt(env):
    env.worker_script = [("d1", "complete")]
    env.validator_script = [PASS]
    env.inputs = ["yes"]
    _chain(env, workers=("developer",))
    assert not any("Acknowledge" in p for p in env.prompts)


def test_validator_runs_before_gap_acknowledgment(env):
    env.worker_script = [("d1", {"gaps": ["g"]})]
    env.validator_script = [PASS]
    env.inputs = ["yes", ""]
    _chain(env, workers=("developer",))
    assert env.events.index("validator") < next(
        i for i, e in enumerate(env.events) if e.startswith("input:Acknowledge gaps")
    )


# ---------------------------------------------------------------------------
# _run_single_hop: malformed return
# ---------------------------------------------------------------------------

def test_malformed_return_becomes_failed_acceptance_with_session_kept(env):
    routing = RoutingPrompt(
        worker="developer", prompt_text="t", expected_output_path=str(env.final), required_sections=[]
    )
    env.worker_script = [("d1", "garbage")]
    check, result = asyncio.run(orchestrator._run_single_hop(routing, "p"))
    assert result.status == "malformed"
    assert result.session_id == "d1"
    assert result.deliverable_path == str(env.final)
    assert "JSON block not found" in result.gaps[0]
    assert not check.passed and not check.self_critique_present


def test_session_id_is_attached_to_parsed_result(env):
    routing = RoutingPrompt(
        worker="developer", prompt_text="t", expected_output_path=str(env.final), required_sections=[]
    )
    env.worker_script = [("sess-9", "complete")]
    prompt = f"p\nExpected output: {env.final}"
    check, result = asyncio.run(orchestrator._run_single_hop(routing, prompt))
    assert result.session_id == "sess-9" and check.passed


def _relative_deliverable(env):
    """Worker returns a worker-relative path; the file exists under the worker dir."""
    rel = "../../output/topic_x/x.md"
    target = (env.dirs["developer"] / rel).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# Summary\nbody\n", encoding="utf-8")
    routing = RoutingPrompt(
        worker="developer", prompt_text="t", expected_output_path=rel, required_sections=["Summary"]
    )
    # "noop": the fake worker returns the path from the Expected output line without writing it.
    env.worker_script = [("d1", "noop")]
    return routing, f"p\nExpected output: {rel}", target


def test_worker_relative_deliverable_path_passes_acceptance(env):
    routing, prompt, target = _relative_deliverable(env)
    check, result = asyncio.run(orchestrator._run_single_hop(routing, prompt))
    assert check.passed
    assert result.deliverable_path == str(target)


def test_validator_prompt_contains_the_absolute_deliverable_path(env):
    routing, prompt, target = _relative_deliverable(env)
    _, result = asyncio.run(orchestrator._run_single_hop(routing, prompt))
    validator_prompt = orchestrator._build_validator_prompt(routing, result)
    assert f"## Deliverable Path\n{target}\n" in validator_prompt
    assert Path(result.deliverable_path).is_absolute()


def test_empty_deliverable_path_is_left_untouched_and_fails_acceptance(env):
    routing = RoutingPrompt(
        worker="developer", prompt_text="t", expected_output_path=str(env.final), required_sections=[]
    )
    env.worker_script = [("d1", "complete")]
    check, result = asyncio.run(orchestrator._run_single_hop(routing, "p"))  # no Expected output line
    assert result.deliverable_path == ""
    assert not check.passed


def test_missing_init_message_leaves_session_id_none(env):
    routing = RoutingPrompt(
        worker="developer", prompt_text="t", expected_output_path=str(env.final), required_sections=[]
    )
    env.worker_script = [(None, "complete")]
    _, result = asyncio.run(orchestrator._run_single_hop(routing, "p"))
    assert result.session_id is None


def test_invoke_worker_passes_resume_session_to_build_options(env):
    env.worker_script = [("d1", "complete")]
    asyncio.run(orchestrator._invoke_worker("developer", "some prompt\nExpected output: " + str(env.final), "prev"))
    assert env.calls[0]["options"] == {"worker": "developer", "resume": "prev"}


# ---------------------------------------------------------------------------
# run(): entry point
# ---------------------------------------------------------------------------

def _run(env, task="the task", **kwargs):
    return asyncio.run(orchestrator.run(task, **kwargs))


def test_run_unknown_worker_aborts_before_any_work(env, capsys, monkeypatch):
    registered = []
    monkeypatch.setattr(orchestrator, "_preregister_urls", lambda s: registered.append(s))
    _run(env, workers="developer,wizard", output=str(env.final), sections="Summary", approved_urls='{"other": {}}')
    out = capsys.readouterr().out
    assert "Unknown worker(s): ['wizard']" in out
    assert env.calls == [] and registered == []


def test_run_prespecified_args_ask_nothing_except_approval(env, capsys):
    env.worker_script = [("d1", "complete")]
    env.validator_script = [PASS]
    env.inputs = ["yes"]
    _run(env, workers=" Developer ", output=str(env.final), sections="Summary, Results,, ")
    out = capsys.readouterr().out
    assert "Worker chain (pre-specified): developer" in out
    assert "=== Task complete ===" in out
    assert "Required sections:\n- Summary\n- Results" in env.worker_calls()[0]["prompt"]
    assert env.prompts == ["Approve? (yes / edit / abort): "]


def test_run_prompts_interactively_when_args_omitted(env):
    env.worker_script = [("d1", "complete")]
    env.validator_script = [PASS]
    env.inputs = ["developer", str(env.final), "Summary", "yes"]
    _run(env)
    assert "worker name or multi-hop chain" in env.prompts[0]
    assert "Expected output path" in env.prompts[1]
    assert "Required sections" in env.prompts[2]
    assert len(env.worker_calls()) == 1


def test_run_blank_sections_means_none_required(env):
    env.worker_script = [("d1", "complete")]
    env.validator_script = [PASS]
    env.inputs = ["yes"]
    _run(env, workers="developer", output=str(env.final), sections="")
    assert "Required sections:\n- (none specified)" in env.worker_calls()[0]["prompt"]


def test_run_preregisters_urls_before_the_first_worker_call(env, monkeypatch):
    seen = []
    monkeypatch.setattr(
        orchestrator, "_preregister_urls", lambda s: seen.append((s, len(env.calls)))
    )
    env.worker_script = [("d1", "complete")]
    env.validator_script = [PASS]
    env.inputs = ["yes"]
    _run(env, workers="developer", output=str(env.final), sections="", approved_urls='{"other": {"a": "https://x.y"}}')
    assert seen == [('{"other": {"a": "https://x.y"}}', 0)]


def test_run_failure_logs_the_whole_chain(env, capsys):
    env.inputs = ["abort"]
    _run(env, workers="architect,developer", output=str(env.final), sections="Summary")
    assert "Task not closed (failed or aborted)" in env.log_text()
    assert "architect → developer" in env.log_text()
    assert "=== Task complete ===" not in capsys.readouterr().out


def test_run_empty_chain_is_not_reported_as_complete(env, capsys):
    # "--workers ," (or an empty value) yields no hops; nothing ran, so it must not claim success.
    _run(env, workers=",", output=str(env.final), sections="")
    assert env.calls == []
    assert "=== Task complete ===" not in capsys.readouterr().out
