"""Tests for the coordinator failed-fetch path (blocked return -> ask owner -> resume).

No live SDK calls and no network: `query`, `build_options`, `build_validator_options`
and `input` are replaced on the orchestrator module, and every path the code writes
(worker dir, Source Registry dir, worker-updates log) is redirected into tmp_path.

Run from the repo root:
    uv run --with claude-agent-sdk --with pytest python -m pytest coordinator/tests
"""
import asyncio
import json

import pytest

from coordinator import orchestrator
from coordinator.acceptance import parse_worker_result
from coordinator.schemas import RoutingPrompt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fence(data: dict) -> str:
    return "Some prose.\n\n```json\n" + json.dumps(data) + "\n```"


def _blocked(*sources: dict) -> str:
    return _fence({"status": "blocked", "blocked_sources": list(sources)})


SRC_A = {
    "source": "uptime_institute_2026_survey",
    "reason": "paywall",
    "candidates": ["https://example.org/a-summary", "https://example.org/a-mirror"],
}
SRC_B = {"source": "https://example.com/dead", "reason": "dead link"}

PASS_VERDICT = _fence(
    {"verdict": "pass", "issues": [], "confidence": 0.9, "summary": "looks fine"}
)


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
        self.worker_dir = tmp_path / "developer"
        self.worker_dir.mkdir()
        self.fetcher_dir = tmp_path / "fetcher"
        self.fetcher_dir.mkdir()
        self.log_path = tmp_path / "worker_updates.md"
        self.deliverable = tmp_path / "deliverable.md"
        self.deliverable.write_text("# Summary\nbody\n", encoding="utf-8")
        self.responses: list[tuple] = []  # (session_id or None, text)
        self.calls: list[dict] = []       # {"prompt", "options"} per query()
        self.inputs: list[str] = []
        self.prompts: list[str] = []
        self.routing = RoutingPrompt(
            worker="developer",
            prompt_text="task",
            expected_output_path=str(self.deliverable),
            required_sections=["Summary"],
        )

    def complete(self) -> str:
        return _fence({
            "deliverable_path": str(self.deliverable),
            "status": "complete",
            "self_critique": "ok",
            "gaps": [],
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
    # `input` is not a module attribute, so raising=False; the module-level name
    # then shadows the builtin for code inside orchestrator only.
    monkeypatch.setattr(orchestrator, "input", fake_input, raising=False)
    monkeypatch.setattr(orchestrator, "WORKER_DIRS", {"developer": e.worker_dir})
    monkeypatch.setattr(orchestrator, "_DOCS_FETCHER_DIR", e.fetcher_dir)
    monkeypatch.setattr(orchestrator, "_WORKER_UPDATES_LOG", e.log_path)
    return e


def _run_hop(env, budget=None):
    budget = budget or orchestrator._BlockBudget()
    return asyncio.run(orchestrator._run_hop_handling_blocks(env.routing, "initial prompt", budget))


# ---------------------------------------------------------------------------
# 1. Parsing
# ---------------------------------------------------------------------------

def test_parse_blocked_return_carries_sources():
    result = parse_worker_result(_blocked(SRC_A, SRC_B))
    assert result is not None
    assert result.status == "blocked"
    assert result.blocked_sources == [SRC_A, SRC_B]
    # Required keys of a normal return are optional when blocked.
    assert result.deliverable_path == ""
    assert result.self_critique == ""
    assert result.gaps == []


def test_parse_blocked_without_usable_sources_is_malformed():
    assert parse_worker_result(_fence({"status": "blocked"})) is None
    assert parse_worker_result(_fence({"status": "blocked", "blocked_sources": []})) is None
    assert parse_worker_result(
        _fence({"status": "blocked", "blocked_sources": [{"reason": "no source key"}]})
    ) is None


def test_parse_complete_return_is_unchanged():
    raw = _fence({
        "deliverable_path": "out/report.md",
        "status": "complete",
        "self_critique": "fine",
        "gaps": ["g1"],
    })
    result = parse_worker_result(raw)
    assert result is not None
    assert (result.deliverable_path, result.status, result.self_critique, result.gaps) == (
        "out/report.md", "complete", "fine", ["g1"],
    )
    assert result.blocked_sources == []


def test_parse_non_blocked_missing_keys_is_still_malformed():
    assert parse_worker_result(_fence({"status": "complete", "gaps": []})) is None
    assert parse_worker_result("no json block at all") is None


# ---------------------------------------------------------------------------
# 2. Branch: blocked skips acceptance
# ---------------------------------------------------------------------------

def test_blocked_result_skips_acceptance(env, monkeypatch):
    def boom(result, routing):
        raise AssertionError("acceptance_check must not run on a blocked result")

    monkeypatch.setattr(orchestrator, "acceptance_check", boom)
    env.responses = [("s1", _blocked(SRC_A))]
    check, result = asyncio.run(orchestrator._run_single_hop(env.routing, "p"))
    assert check is None
    assert result.status == "blocked"
    assert result.session_id == "s1"


def test_complete_result_still_runs_acceptance(env):
    env.responses = [("s1", env.complete())]
    check, result = asyncio.run(orchestrator._run_single_hop(env.routing, "p"))
    assert check is not None and check.passed
    assert result.status == "complete"


# ---------------------------------------------------------------------------
# 3. Each answer type, then resume
# ---------------------------------------------------------------------------

def test_answer_continue_without(env):
    env.responses = [("s1", _blocked(SRC_A)), ("s1", env.complete())]
    env.inputs = ["3"]
    check, result = _run_hop(env)

    assert check.passed and result.status == "complete"
    assert len(env.calls) == 2
    assert env.calls[0]["options"]["resume"] is None
    assert env.calls[1]["options"]["resume"] == "s1"
    assert SRC_A["source"] in env.calls[1]["prompt"]
    assert "continue without" in env.calls[1]["prompt"]
    assert not (env.worker_dir / "human-retrieved-sources").exists()
    assert not (env.fetcher_dir / "other_sources.json").exists()


def test_answer_local_file_is_copied_and_path_given_to_worker(env):
    src = env.tmp_path / "download (1).pdf"
    src.write_bytes(b"%PDF-demo")
    env.responses = [("s1", _blocked(SRC_A)), ("s1", env.complete())]
    env.inputs = ["1", str(src)]
    check, _ = _run_hop(env)

    copied = env.worker_dir / "human-retrieved-sources" / "uptime_institute_2026_survey.pdf"
    assert copied.read_bytes() == b"%PDF-demo"
    assert src.exists()  # copied, not moved
    assert "./human-retrieved-sources/uptime_institute_2026_survey.pdf" in env.calls[1]["prompt"]
    assert env.calls[1]["options"]["resume"] == "s1"
    assert check.passed


def test_answer_local_file_reprompts_when_path_is_not_a_file(env):
    src = env.tmp_path / "real.pdf"
    src.write_bytes(b"x")
    env.responses = [("s1", _blocked(SRC_A)), ("s1", env.complete())]
    env.inputs = ["1", str(env.tmp_path / "missing.pdf"), "1", str(src)]
    check, _ = _run_hop(env)
    assert check.passed
    assert (env.worker_dir / "human-retrieved-sources" / "uptime_institute_2026_survey.pdf").exists()


def test_answer_replacement_url_is_registered(env):
    env.responses = [("s1", _blocked(SRC_A)), ("s1", env.complete())]
    env.inputs = ["2", "https://example.org/replacement"]
    check, _ = _run_hop(env)

    registry = json.loads((env.fetcher_dir / "other_sources.json").read_text(encoding="utf-8"))
    assert registry == {"uptime_institute_2026_survey_replacement": "https://example.org/replacement"}
    assert "https://example.org/replacement" in env.calls[1]["prompt"]
    assert "uptime_institute_2026_survey_replacement" in env.calls[1]["prompt"]
    assert check.passed


def test_resume_prompt_names_new_replacement_entry(env):
    env.responses = [("s1", _blocked(SRC_A)), ("s1", env.complete())]
    env.inputs = ["2", "https://example.org/replacement"]
    _run_hop(env)
    prompt = env.calls[1]["prompt"]
    assert (
        "registered in other_sources.json as 'uptime_institute_2026_survey_replacement': "
        "https://example.org/replacement" in prompt
    )
    assert "not in the Source Registry" not in prompt


def test_resume_prompt_names_existing_entry_when_url_already_registered(env):
    registry_path = env.fetcher_dir / "other_sources.json"
    registry_path.write_text(json.dumps({"held": "https://example.org/replacement"}), encoding="utf-8")
    before = registry_path.read_text(encoding="utf-8")
    env.responses = [("s1", _blocked(SRC_A)), ("s1", env.complete())]
    env.inputs = ["2", "https://example.org/replacement"]
    check, _ = _run_hop(env)

    assert registry_path.read_text(encoding="utf-8") == before
    prompt = env.calls[1]["prompt"]
    assert "registered in other_sources.json as 'held': https://example.org/replacement" in prompt
    assert "uptime_institute_2026_survey_replacement" not in prompt
    assert check.passed


def test_resume_prompt_says_not_registered_when_replacement_name_is_taken(env):
    registry_path = env.fetcher_dir / "other_sources.json"
    registry_path.write_text(
        json.dumps({"uptime_institute_2026_survey_replacement": "https://old"}), encoding="utf-8"
    )
    before = registry_path.read_text(encoding="utf-8")
    env.responses = [("s1", _blocked(SRC_A)), ("s1", env.complete())]
    env.inputs = ["2", "https://new"]
    check, _ = _run_hop(env)

    assert registry_path.read_text(encoding="utf-8") == before
    prompt = env.calls[1]["prompt"]
    assert "the owner approved this replacement URL for this task: https://new" in prompt
    assert "not in the Source Registry" in prompt
    assert "already registered with a different URL" in prompt
    assert "registered in other_sources.json as" not in prompt
    assert check.passed


def _resume_line(prompt: str, source: str) -> str:
    return next(line for line in prompt.splitlines() if line.startswith(f"- {source}:"))


def test_sources_with_the_same_slug_get_distinct_replacement_names(env):
    src_1 = {"source": "Uptime Survey", "reason": "paywall"}
    src_2 = {"source": "uptime-survey", "reason": "dead link"}
    env.responses = [("s1", _blocked(src_1, src_2)), ("s1", env.complete())]
    env.inputs = ["2", "https://example.org/one", "2", "https://example.org/two"]
    check, _ = _run_hop(env)

    registry = json.loads((env.fetcher_dir / "other_sources.json").read_text(encoding="utf-8"))
    assert registry == {
        "uptime_survey_replacement": "https://example.org/one",
        "uptime_survey_replacement_2": "https://example.org/two",
    }
    prompt = env.calls[1]["prompt"]
    assert _resume_line(prompt, "Uptime Survey").endswith(
        "registered in other_sources.json as 'uptime_survey_replacement': https://example.org/one. Fetch it."
    )
    assert _resume_line(prompt, "uptime-survey").endswith(
        "registered in other_sources.json as 'uptime_survey_replacement_2': https://example.org/two. Fetch it."
    )
    assert check.passed


def test_sources_with_empty_slugs_get_distinct_replacement_names(env):
    # Neither title has a letter or digit, so both slug to "" and fall back to "source".
    src_1 = {"source": "★★", "reason": "paywall"}
    src_2 = {"source": "☆☆", "reason": "paywall"}
    src_3 = {"source": "§", "reason": "paywall"}
    env.responses = [("s1", _blocked(src_1, src_2, src_3)), ("s1", env.complete())]
    env.inputs = ["2", "https://u1.example", "2", "https://u2.example", "2", "https://u3.example"]
    _run_hop(env)

    registry = json.loads((env.fetcher_dir / "other_sources.json").read_text(encoding="utf-8"))
    assert registry == {
        "source_replacement": "https://u1.example",
        "source_replacement_2": "https://u2.example",
        "source_replacement_3": "https://u3.example",
    }
    prompt = env.calls[1]["prompt"]
    assert "as 'source_replacement': https://u1.example" in _resume_line(prompt, "★★")
    assert "as 'source_replacement_2': https://u2.example" in _resume_line(prompt, "☆☆")
    assert "as 'source_replacement_3': https://u3.example" in _resume_line(prompt, "§")


def test_unreadable_target_registry_during_resume_does_not_crash(env, capsys):
    registry_path = env.fetcher_dir / "other_sources.json"
    registry_path.write_text("", encoding="utf-8")  # 0-byte file
    env.responses = [("s1", _blocked(SRC_A)), ("s1", env.complete())]
    env.inputs = ["2", "https://example.org/replacement"]
    check, _ = _run_hop(env)

    assert registry_path.read_text(encoding="utf-8") == ""  # never written
    prompt = env.calls[1]["prompt"]
    assert "the owner approved this replacement URL for this task: https://example.org/replacement" in prompt
    assert "registry file could not be read" in prompt
    assert "WARNING" in capsys.readouterr().out
    assert check.passed


def test_unreadable_non_target_registry_during_resume_still_registers(env, capsys):
    (env.fetcher_dir / "clis.json").write_text("[]", encoding="utf-8")
    env.responses = [("s1", _blocked(SRC_A)), ("s1", env.complete())]
    env.inputs = ["2", "https://example.org/replacement"]
    check, _ = _run_hop(env)

    registry = json.loads((env.fetcher_dir / "other_sources.json").read_text(encoding="utf-8"))
    assert registry == {"uptime_institute_2026_survey_replacement": "https://example.org/replacement"}
    assert (env.fetcher_dir / "clis.json").read_text(encoding="utf-8") == "[]"
    assert "clis.json" in capsys.readouterr().out
    assert check.passed


def test_answer_replacement_url_by_candidate_number(env):
    env.responses = [("s1", _blocked(SRC_A)), ("s1", env.complete())]
    env.inputs = ["2", "2"]
    _run_hop(env)
    registry = json.loads((env.fetcher_dir / "other_sources.json").read_text(encoding="utf-8"))
    assert list(registry.values()) == ["https://example.org/a-mirror"]


def test_answer_replacement_url_must_be_https(env):
    env.responses = [("s1", _blocked(SRC_A)), ("s1", env.complete())]
    env.inputs = ["2", "http://example.org/insecure", "2", "https://example.org/ok"]
    _run_hop(env)
    registry = json.loads((env.fetcher_dir / "other_sources.json").read_text(encoding="utf-8"))
    assert list(registry.values()) == ["https://example.org/ok"]


def test_one_answer_per_source_mixed(env):
    src = env.tmp_path / "b.pdf"
    src.write_bytes(b"b")
    env.responses = [("s1", _blocked(SRC_A, SRC_B)), ("s1", env.complete())]
    env.inputs = ["3", "1", str(src)]
    _run_hop(env)
    prompt = env.calls[1]["prompt"]
    assert "continue without" in prompt and "./human-retrieved-sources/" in prompt
    # URL-shaped source key falls back to the file's own stem for the copy name.
    assert (env.worker_dir / "human-retrieved-sources" / "b.pdf").exists()


def test_answer_abort_ends_hop_without_side_effects(env):
    env.responses = [("s1", _blocked(SRC_A))]
    env.inputs = ["4"]
    assert _run_hop(env) is None
    assert len(env.calls) == 1
    assert "aborted" in env.log_text()


def test_abort_on_later_source_leaves_no_copy_behind(env):
    src = env.tmp_path / "a.pdf"
    src.write_bytes(b"a")
    env.responses = [("s1", _blocked(SRC_A, SRC_B))]
    env.inputs = ["1", str(src), "4"]
    assert _run_hop(env) is None
    assert not (env.worker_dir / "human-retrieved-sources").exists()


def test_blocked_without_session_id_cannot_resume(env, capsys):
    env.responses = [(None, _blocked(SRC_A))]
    assert _run_hop(env) is None
    assert env.inputs == [] and env.prompts == []  # owner was never asked
    assert "manual mode" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 4. File copy: never overwrite
# ---------------------------------------------------------------------------

def test_copy_never_overwrites_existing_file(tmp_path):
    dest_dir = tmp_path / "human-retrieved-sources"
    dest_dir.mkdir()
    (dest_dir / "uptime_report.pdf").write_bytes(b"old")
    src = tmp_path / "new.pdf"
    src.write_bytes(b"new")

    first = orchestrator._copy_human_source(src, dest_dir, "uptime_report")
    second = orchestrator._copy_human_source(src, dest_dir, "uptime_report")

    assert (dest_dir / "uptime_report.pdf").read_bytes() == b"old"
    assert first.name == "uptime_report_2.pdf" and first.read_bytes() == b"new"
    assert second.name == "uptime_report_3.pdf" and second.read_bytes() == b"new"


def test_copy_creates_missing_folder(tmp_path):
    src = tmp_path / "f.txt"
    src.write_text("hello", encoding="utf-8")
    dest = orchestrator._copy_human_source(src, tmp_path / "w" / "human-retrieved-sources", "My Source Key")
    assert dest.name == "my_source_key.txt"
    assert dest.read_text(encoding="utf-8") == "hello"


# ---------------------------------------------------------------------------
# 5. Cap: at most 2 block-resume cycles per hop
# ---------------------------------------------------------------------------

def test_third_blocked_return_aborts_with_manual_fallback(env, capsys):
    env.responses = [
        ("s1", _blocked(SRC_A)),
        ("s2", _blocked(SRC_A)),
        ("s3", _blocked(SRC_A)),
    ]
    env.inputs = ["3", "3"]  # exactly two answers; a third prompt would fail the fake input
    assert _run_hop(env) is None

    assert len(env.calls) == 3
    assert [c["options"]["resume"] for c in env.calls] == [None, "s1", "s2"]
    out = capsys.readouterr().out
    assert "manual mode" in out and "intermediate_outputs" in out
    assert "cap" in env.log_text()


def test_budget_is_shared_across_calls_for_one_hop(env):
    env.responses = [("s1", _blocked(SRC_A))]
    assert _run_hop(env, budget=orchestrator._BlockBudget(used=2)) is None
    assert env.prompts == []


def test_two_cycles_then_complete_is_allowed(env):
    env.responses = [
        ("s1", _blocked(SRC_A)),
        ("s2", _blocked(SRC_A)),
        ("s3", env.complete()),
    ]
    env.inputs = ["3", "3"]
    check, result = _run_hop(env)
    assert check.passed and result.status == "complete"
    assert len(env.calls) == 3


# ---------------------------------------------------------------------------
# End to end through the hop loop: Validator runs only after the resumed result
# ---------------------------------------------------------------------------

def test_execute_chain_resumes_then_runs_acceptance_and_validator_once(env, monkeypatch):
    seen = []
    real_check = orchestrator.acceptance_check

    def spy(result, routing):
        seen.append(result.status)
        return real_check(result, routing)

    monkeypatch.setattr(orchestrator, "acceptance_check", spy)
    env.responses = [
        ("s1", _blocked(SRC_A)),
        ("s1", env.complete()),
        ("v1", PASS_VERDICT),
    ]
    env.inputs = ["yes", "3"]  # approve the routing prompt, then "continue without"

    ok = asyncio.run(orchestrator._execute_chain(
        hop_workers=["developer"],
        task="task",
        expected_output_path=str(env.deliverable),
        required_sections=["Summary"],
    ))

    assert ok is True
    assert seen == ["complete"]                      # never ran on the blocked result
    assert len(env.calls) == 3
    assert env.calls[1]["options"]["resume"] == "s1"  # worker resumed
    assert env.calls[2]["options"] == {"validator": True}  # Validator only at the end
