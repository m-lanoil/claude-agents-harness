"""Tests for the Validator path in coordinator.orchestrator:
_invoke_validator and _handle_validator_result (pass, low-confidence pass,
soft gate, hard gate, semantic correction retry, gap/low-confidence acknowledgment).

No live SDK calls and no network: `query`, `build_options`, `build_validator_options`
and `input` are replaced on the orchestrator module, and every path the code writes
is redirected into tmp_path.

Run from the repo root:
    uv run --with claude-agent-sdk --with pytest python -m pytest coordinator/tests
"""
import asyncio
import json

import pytest

from coordinator import orchestrator
from coordinator.schemas import RoutingPrompt, ValidatorResult, WorkerResult


# ---------------------------------------------------------------------------
# Helpers and fixture
# ---------------------------------------------------------------------------

def _fence(data: dict) -> str:
    return "Some prose.\n\n```json\n" + json.dumps(data) + "\n```"


def _verdict_text(verdict="pass", issues=None, confidence=0.9, summary="looks fine") -> str:
    return _fence({
        "verdict": verdict,
        "issues": issues if issues is not None else [],
        "confidence": confidence,
        "summary": summary,
    })


def _vr(verdict="pass", issues=None, confidence=0.9, summary="the summary") -> ValidatorResult:
    return ValidatorResult(
        verdict=verdict, issues=issues or [], confidence=confidence, summary=summary
    )


CRITICAL = {"severity": "critical", "section": "Summary", "description": "Summary is a placeholder"}
MINOR = {"severity": "minor", "section": "Results", "description": "Typo in the table"}


class _InitMessage:
    def __init__(self, session_id):
        self.subtype = "init"
        self.data = {"session_id": session_id}


class _ResultMessage:
    def __init__(self, text):
        self.result = text


class Env:
    """Scripted stand-ins for the SDK and the terminal."""

    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.worker_dir = tmp_path / "workers" / "developer"
        self.worker_dir.mkdir(parents=True)
        self.log_path = tmp_path / "worker_updates.md"
        self.deliverable = tmp_path / "deliverable.md"
        self.deliverable.write_text("# Summary\nbody\n", encoding="utf-8")
        self.responses: list[tuple] = []  # (session_id or None, text)
        self.calls: list[dict] = []       # {"prompt", "options"} per query()
        self.inputs: list[str] = []
        self.prompts: list[str] = []
        self.routing = RoutingPrompt(
            worker="developer",
            prompt_text="the original task",
            expected_output_path=str(self.deliverable),
            required_sections=["Summary"],
        )
        self.result = WorkerResult(
            raw_text="",
            deliverable_path=str(self.deliverable),
            status="complete",
            self_critique="ok",
            gaps=[],
            session_id="s1",
        )

    def complete(self, path=None) -> str:
        return _fence({
            "deliverable_path": str(path or self.deliverable),
            "status": "complete",
            "self_critique": "fixed",
            "gaps": [],
        })

    def blocked(self) -> str:
        return _fence({
            "status": "blocked",
            "blocked_sources": [{"source": "src", "reason": "paywall"}],
        })

    def log_text(self) -> str:
        return self.log_path.read_text(encoding="utf-8") if self.log_path.exists() else ""


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = Env(tmp_path)

    async def fake_query(*, prompt, options):
        e.calls.append({"prompt": prompt, "options": options})
        session_id, text = e.responses.pop(0)
        if session_id is not None:
            yield _InitMessage(session_id)
        yield _ResultMessage(text)

    def fake_input(prompt=""):
        e.prompts.append(prompt)
        assert e.inputs, f"unexpected input() call: {prompt!r}"
        return e.inputs.pop(0)

    monkeypatch.setattr(orchestrator, "query", fake_query)
    monkeypatch.setattr(
        orchestrator, "build_options",
        lambda worker, resume=None: {"worker": worker, "resume": resume},
    )
    monkeypatch.setattr(orchestrator, "build_validator_options", lambda: {"validator": True})
    monkeypatch.setattr(orchestrator, "input", fake_input, raising=False)
    monkeypatch.setattr(orchestrator, "WORKER_DIRS", {"developer": e.worker_dir})
    monkeypatch.setattr(orchestrator, "_WORKER_UPDATES_LOG", e.log_path)
    return e


def _handle(env, validator_result, retry_available=True):
    return asyncio.run(
        orchestrator._handle_validator_result(
            validator_result, env.routing, env.result, retry_available=retry_available
        )
    )


# ---------------------------------------------------------------------------
# _invoke_validator
# ---------------------------------------------------------------------------

def test_invoke_validator_parses_verdict(env):
    env.responses = [(None, _verdict_text("fail", [CRITICAL], 0.65, "bad"))]
    vr = asyncio.run(orchestrator._invoke_validator(env.routing, env.result))
    assert vr.verdict == "fail"
    assert vr.issues == [CRITICAL]
    assert vr.confidence == 0.65
    assert vr.summary == "bad"


def test_invoke_validator_uses_validator_options_and_prompt(env):
    env.responses = [(None, _verdict_text())]
    asyncio.run(orchestrator._invoke_validator(env.routing, env.result))
    assert env.calls[0]["options"] == {"validator": True}
    assert "the original task" in env.calls[0]["prompt"]
    assert str(env.deliverable) in env.calls[0]["prompt"]


def test_invoke_validator_uses_last_json_block(env):
    text = _verdict_text("fail", [CRITICAL]) + "\n\nOn reflection:\n" + _verdict_text("pass")
    env.responses = [(None, text)]
    vr = asyncio.run(orchestrator._invoke_validator(env.routing, env.result))
    assert vr.verdict == "pass"


def test_invoke_validator_confidence_string_is_coerced(env):
    env.responses = [(None, _verdict_text(confidence="0.8"))]
    vr = asyncio.run(orchestrator._invoke_validator(env.routing, env.result))
    assert vr.confidence == 0.8


def _assert_parse_error_fail(vr, env):
    assert vr.verdict == "fail"
    assert vr.confidence == 0.0
    assert len(vr.issues) == 1 and vr.issues[0]["severity"] == "critical"
    assert "parse error" in env.log_text()


def test_invoke_validator_no_block_is_fail(env):
    env.responses = [(None, "I think it is fine.")]
    vr = asyncio.run(orchestrator._invoke_validator(env.routing, env.result))
    _assert_parse_error_fail(vr, env)


def test_invoke_validator_invalid_json_is_fail(env):
    env.responses = [(None, "```json\n{broken}\n```")]
    vr = asyncio.run(orchestrator._invoke_validator(env.routing, env.result))
    _assert_parse_error_fail(vr, env)


def test_invoke_validator_missing_key_is_fail(env):
    env.responses = [(None, _fence({"verdict": "pass", "issues": [], "confidence": 0.9}))]
    vr = asyncio.run(orchestrator._invoke_validator(env.routing, env.result))
    _assert_parse_error_fail(vr, env)


def test_invoke_validator_non_numeric_confidence_is_fail(env):
    env.responses = [(None, _verdict_text(confidence="high"))]
    vr = asyncio.run(orchestrator._invoke_validator(env.routing, env.result))
    _assert_parse_error_fail(vr, env)


def test_invoke_validator_null_issues_is_fail(env):
    env.responses = [(None, _fence(
        {"verdict": "pass", "issues": None, "confidence": 0.9, "summary": "s"}
    ))]
    vr = asyncio.run(orchestrator._invoke_validator(env.routing, env.result))
    _assert_parse_error_fail(vr, env)


# ---------------------------------------------------------------------------
# _handle_validator_result: pass
# ---------------------------------------------------------------------------

def test_pass_high_confidence_proceeds_without_prompt(env, capsys):
    assert _handle(env, _vr("pass", confidence=0.95)) is True
    assert env.prompts == [] and env.calls == []
    out = capsys.readouterr().out
    assert "the summary" in out and "PASS (confidence: 0.95)" in out


def test_pass_at_exactly_the_threshold_is_not_low_confidence(env):
    assert _handle(env, _vr("pass", confidence=orchestrator._VALIDATOR_CONFIDENCE_THRESHOLD)) is True
    assert env.prompts == []


def test_pass_low_confidence_requires_acknowledgment(env, capsys):
    env.inputs = [""]
    assert _handle(env, _vr("pass", confidence=0.5)) is True
    assert len(env.prompts) == 1 and "low-confidence" in env.prompts[0]
    assert "low confidence" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _handle_validator_result: soft gate (minor issues only)
# ---------------------------------------------------------------------------

def test_minor_only_user_continues(env, capsys):
    env.inputs = ["YES"]
    assert _handle(env, _vr("fail", [MINOR])) is True
    out = capsys.readouterr().out
    assert "FAIL" in out and "Minor issues" in out and "Typo in the table" in out
    assert "Critical issues" not in out
    assert env.calls == []  # no correction retry for minor issues


def test_minor_only_user_aborts(env):
    for answer in ("abort", "no", ""):
        env.inputs = [answer]
        env.log_path.write_text("", encoding="utf-8")
        assert _handle(env, _vr("fail", [MINOR])) is False
        assert "minor issues only, user aborted" in env.log_text()
    assert env.calls == []


# ---------------------------------------------------------------------------
# _handle_validator_result: hard gate, no retry left
# ---------------------------------------------------------------------------

def test_critical_without_retry_escalates_immediately(env, capsys):
    assert _handle(env, _vr("fail", [CRITICAL, MINOR]), retry_available=False) is False
    assert env.calls == [] and env.prompts == []
    out = capsys.readouterr().out
    assert "Critical issues" in out and "Summary is a placeholder" in out
    assert "Minor issues" in out and "Typo in the table" in out
    assert "Retry budget exhausted" in out
    log = env.log_text()
    assert "retry budget exhausted" in log and "Summary is a placeholder" in log


# ---------------------------------------------------------------------------
# _handle_validator_result: semantic correction retry
# ---------------------------------------------------------------------------

def test_correction_prompt_content_and_session_resume(env):
    env.inputs = ["yes"]
    env.responses = [("s1", env.complete()), (None, _verdict_text("pass", confidence=0.9))]
    assert _handle(env, _vr("fail", [CRITICAL, MINOR], summary="needs work")) is True

    worker_call, validator_call = env.calls
    assert worker_call["options"] == {"worker": "developer", "resume": "s1"}
    prompt = worker_call["prompt"]
    assert "the original task" in prompt  # base routing prompt rebuilt
    assert f"Expected output: {env.deliverable}" in prompt
    assert "SEMANTIC CORRECTION REQUIRED:\nneeds work" in prompt
    assert "[Summary] (critical) Summary is a placeholder" in prompt
    assert "[Results] (minor) Typo in the table" in prompt  # minor issues ride along
    assert validator_call["options"] == {"validator": True}  # validator re-run after the retry


def test_correction_prompt_is_shown_for_approval_with_label(env, capsys):
    env.inputs = ["abort"]
    assert _handle(env, _vr("fail", [CRITICAL])) is False
    assert "SEMANTIC CORRECTION PROMPT (review before approval)" in capsys.readouterr().out
    assert "Approve?" in env.prompts[0]


def test_correction_aborted_by_user(env, capsys):
    env.inputs = ["abort"]
    assert _handle(env, _vr("fail", [CRITICAL])) is False
    assert env.calls == []
    assert "Escalating to user" in capsys.readouterr().out
    assert "user aborted semantic correction" in env.log_text()


def test_correction_prompt_can_be_edited_before_sending(env):
    env.inputs = ["edit", "edited line 1", "edited line 2", "---END---"]
    env.responses = [("s1", env.complete()), (None, _verdict_text("pass"))]
    assert _handle(env, _vr("fail", [CRITICAL])) is True
    assert env.calls[0]["prompt"] == "edited line 1\nedited line 2"


def test_correction_prompt_keeps_hop_position(env):
    env.routing.hop_index, env.routing.total_hops = 1, 2
    env.inputs = ["yes"]
    env.responses = [("s1", env.complete()), (None, _verdict_text("pass"))]
    _handle(env, _vr("fail", [CRITICAL]))
    assert "This is hop 2 of 2 in a multi-hop chain." in env.calls[0]["prompt"]


def test_retry_validator_pass_returns_true(env, capsys):
    env.inputs = ["yes"]
    env.responses = [("s1", env.complete()), (None, _verdict_text("pass", confidence=0.88, summary="fixed now"))]
    assert _handle(env, _vr("fail", [CRITICAL])) is True
    out = capsys.readouterr().out
    assert "Retry result: fixed now" in out and "Retry PASS (confidence: 0.88)" in out


def test_retry_validator_fail_returns_false(env, capsys):
    env.inputs = ["yes"]
    env.responses = [("s1", env.complete()), (None, _verdict_text("fail", [CRITICAL], summary="still bad"))]
    assert _handle(env, _vr("fail", [CRITICAL])) is False
    assert "Retry also failed" in capsys.readouterr().out
    assert "retry also failed" in env.log_text() and "still bad" in env.log_text()


def test_retry_validator_parse_error_returns_false(env):
    env.inputs = ["yes"]
    env.responses = [("s1", env.complete()), (None, "no json here")]
    assert _handle(env, _vr("fail", [CRITICAL])) is False


def test_retry_low_confidence_pass_is_accepted_without_acknowledgment(env, capsys):
    # The retry branch only checks the verdict; no low-confidence prompt is raised.
    env.inputs = ["yes"]
    env.responses = [("s1", env.complete()), (None, _verdict_text("pass", confidence=0.1))]
    assert _handle(env, _vr("fail", [CRITICAL])) is True
    assert env.prompts == ["Approve? (yes / edit / abort): "]
    assert "Retry PASS (confidence: 0.10)" in capsys.readouterr().out


def test_retry_acceptance_failure_skips_validator(env, capsys):
    missing = env.tmp_path / "gone.md"
    env.inputs = ["yes"]
    env.responses = [("s1", env.complete(path=missing))]
    assert _handle(env, _vr("fail", [CRITICAL])) is False
    assert len(env.calls) == 1  # validator never re-run on a failed structural check
    assert "Correction retry acceptance failed" in capsys.readouterr().out
    assert "correction retry acceptance failed" in env.log_text()


def test_retry_malformed_worker_return_is_acceptance_failure(env):
    env.inputs = ["yes"]
    env.responses = [("s1", "worker forgot the JSON block")]
    assert _handle(env, _vr("fail", [CRITICAL])) is False
    assert len(env.calls) == 1


def test_retry_blocked_on_failed_fetch_escalates(env, capsys):
    env.inputs = ["yes"]
    env.responses = [("s1", env.blocked())]
    assert _handle(env, _vr("fail", [CRITICAL])) is False
    assert len(env.calls) == 1
    assert "ended blocked on a failed fetch" in capsys.readouterr().out
    assert "correction retry ended blocked" in env.log_text()


# ---------------------------------------------------------------------------
# _handle_validator_result: inputs the Validator prompt allows (expected to expose defects)
# ---------------------------------------------------------------------------

def test_fail_with_unrecognised_severity_is_not_silently_dropped(env, capsys):
    # The Validator prompt only shows "critical" as an example severity. An issue with any
    # other label ("major", "high") must still be shown to the owner, not discarded.
    major = {"severity": "major", "section": "Summary", "description": "Core claim is unsupported"}
    env.inputs = ["abort"]
    _handle(env, _vr("fail", [major]))
    assert "Core claim is unsupported" in capsys.readouterr().out


def test_fail_with_unrecognised_severity_does_not_take_the_soft_gate(env):
    major = {"severity": "major", "section": "Summary", "description": "Core claim is unsupported"}
    env.inputs = ["yes"]
    # A failing verdict whose only issue is not "minor" must not be waved through by one "yes".
    assert _handle(env, _vr("fail", [major]), retry_available=False) is False


def test_fail_verdict_with_no_issues_is_not_waved_through(env):
    env.inputs = ["yes"]
    assert _handle(env, _vr("fail", []), retry_available=False) is False


def test_verdict_comparison_is_case_insensitive(env):
    # "Pass" / "PASS" is an easy model variation; it must not be read as a failure.
    assert _handle(env, _vr("PASS", confidence=0.95)) is True
