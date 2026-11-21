"""Tests for the brief record in coordinator.orchestrator: every prompt sent to a
worker is saved, verbatim and before the worker receives it, to
output/intermediate_outputs/<topic>/coordinator_hop_<N>_<worker>_brief_<stamp>.md.

No live SDK calls and no network. A fake `query` plays the workers and the
Validator. Worker dirs sit two levels under tmp_path so the code's
`../../output/...` paths land in tmp_path/output.

Run from the repo root:
    uv run --with claude-agent-sdk --with pytest python -m pytest coordinator/tests/test_brief_record.py
"""
import asyncio
import json
import re
from pathlib import Path

import pytest

from coordinator import orchestrator


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
FAIL_CRITICAL = _verdict(
    "fail",
    [{"severity": "critical", "section": "Summary", "description": "Summary is a placeholder"}],
    0.9,
    "needs work",
)

_EXPECTED_RE = re.compile(r"^Expected output: (.+)$", re.MULTILINE)
_HEADING_RE = re.compile(r"^## (\d+)\. (.+) — (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})$")
_FENCE_OPEN_RE = re.compile(r"^(`{3,})text$")
_TIMESTAMP_FILE_RE = re.compile(r"_brief_\d{8}-\d{6}\.md$")

KIND_ROUTING = "routing prompt"
KIND_ACCEPTANCE = "acceptance correction prompt"
KIND_SEMANTIC = "semantic correction prompt"
KIND_RESUME = "blocked-fetch resume prompt"


def parse_record(path: Path) -> list[tuple[str, str, str]]:
    """Return [(kind, timestamp, text)] from a brief-record file, in file order.

    The text of an entry is the lines between its opening fence and the next line
    equal to that fence, so a prompt holding backtick fences must come back intact.
    """
    lines = path.read_text(encoding="utf-8").split("\n")
    entries = []
    i = 0
    while i < len(lines):
        heading = _HEADING_RE.match(lines[i])
        if not heading:
            i += 1
            continue
        assert int(heading.group(1)) == len(entries) + 1
        assert lines[i + 1] == ""
        opening = _FENCE_OPEN_RE.match(lines[i + 2])
        assert opening, f"no fence after heading {lines[i]!r}"
        fence = opening.group(1)
        end = lines.index(fence, i + 3)
        entries.append((heading.group(2), heading.group(3), "\n".join(lines[i + 3:end])))
        i = end + 1
    return entries


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
        self.dirs = {}
        for name in ("architect", "developer"):
            d = tmp_path / "workers" / name
            d.mkdir(parents=True)
            self.dirs[name] = d
        self.log_path = tmp_path / "worker_updates.md"
        self.output_root = tmp_path / "output"
        self.final = self.output_root / "final_outputs" / "topic_x" / "report.md"
        self.record_dir = self.output_root / "intermediate_outputs" / "topic_x"
        self.workers: list[tuple] = []        # (session_id or None, spec)
        self.validator: list[str] = []
        self.worker_prompts: list[str] = []
        self.validator_prompts: list[str] = []
        self.record_text_at_call: list[str] = []  # all record files' text when each worker call began
        self.inputs: list[str] = []
        self.expected = str(self.final)       # deliverable path the fake worker reports

    def worker_text(self, spec) -> str:
        if spec == "blocked":
            return _fence({"status": "blocked", "blocked_sources": [{"source": "s", "reason": "paywall"}]})
        if spec != "noop":
            target = Path(self.expected)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# Summary\nbody\n", encoding="utf-8")
        return _fence({
            "deliverable_path": self.expected,
            "status": "complete",
            "self_critique": "ok",
            "gaps": [],
        })

    def record_files(self) -> list[Path]:
        return sorted(self.output_root.glob("intermediate_outputs/*/*_brief_*.md"))

    def log_text(self) -> str:
        return self.log_path.read_text(encoding="utf-8") if self.log_path.exists() else ""


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = Env(tmp_path)

    async def fake_query(*, prompt, options):
        if options == {"validator": True}:
            e.validator_prompts.append(prompt)
            yield _ResultMessage(e.validator.pop(0))
            return
        e.record_text_at_call.append(
            "\n".join(p.read_text(encoding="utf-8") for p in e.record_files())
        )
        e.worker_prompts.append(prompt)
        match = _EXPECTED_RE.search(prompt)
        if match:
            e.expected = match.group(1).strip()
        session_id, spec = e.workers.pop(0)
        if session_id is not None:
            yield _InitMessage(session_id)
        yield _ResultMessage(e.worker_text(spec))

    def fake_input(prompt=""):
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


def _chain(env, workers=("developer",), output=None, task="Produce the thing.", run_stamp="20261120-101500"):
    return asyncio.run(orchestrator._execute_chain(
        hop_workers=list(workers),
        task=task,
        expected_output_path=str(output or env.final),
        required_sections=["Summary"],
        run_stamp=run_stamp,
    ))


def _single_record(env) -> Path:
    files = env.record_files()
    assert len(files) == 1, files
    return files[0]


# ---------------------------------------------------------------------------
# What is recorded: the four kinds, in order, verbatim
# ---------------------------------------------------------------------------

def test_routing_resume_and_semantic_correction_prompts_are_recorded_in_order_verbatim(env):
    # routing prompt -> blocked -> owner "continue without" -> resume prompt (complete)
    # -> Validator fails critical -> semantic correction prompt (complete) -> Validator passes.
    env.workers = [("s1", "blocked"), ("s1", "complete"), ("s1", "complete")]
    env.validator = [FAIL_CRITICAL, PASS]
    env.inputs = ["yes", "3", "yes"]

    assert _chain(env) is True

    entries = parse_record(_single_record(env))
    assert [kind for kind, _, _ in entries] == [KIND_ROUTING, KIND_RESUME, KIND_SEMANTIC]
    # Exactly what each worker call received, in send order.
    assert [text for _, _, text in entries] == env.worker_prompts
    assert "SEMANTIC CORRECTION REQUIRED" in entries[2][2]
    assert entries[1][2].startswith("The owner has answered for each source you reported as blocked:")
    # Validator prompts are not recorded.
    assert len(env.validator_prompts) == 2
    for prompt in env.validator_prompts:
        assert all(prompt != text for _, _, text in entries)
    assert "You are a Validator" not in _single_record(env).read_text(encoding="utf-8")


def test_acceptance_correction_prompt_is_recorded_verbatim(env):
    env.workers = [("s1", "noop"), ("s1", "complete")]  # first return claims a file it never wrote
    env.validator = [PASS]
    env.inputs = ["yes", "yes", "yes"]  # approve routing, retry, approve correction prompt

    assert _chain(env) is True

    entries = parse_record(_single_record(env))
    assert [kind for kind, _, _ in entries] == [KIND_ROUTING, KIND_ACCEPTANCE]
    assert [text for _, _, text in entries] == env.worker_prompts
    assert "CORRECTION REQUIRED" in entries[1][2]


def test_each_entry_is_on_disk_before_its_worker_call_starts(env):
    env.workers = [("s1", "blocked"), ("s1", "complete"), ("s1", "complete")]
    env.validator = [FAIL_CRITICAL, PASS]
    env.inputs = ["yes", "3", "yes"]
    _chain(env)

    assert len(env.record_text_at_call) == 3
    for n, (prompt, on_disk) in enumerate(zip(env.worker_prompts, env.record_text_at_call), start=1):
        assert prompt in on_disk
        assert len(re.findall(r"^## \d+\. ", on_disk, re.MULTILINE)) == n


def test_headings_carry_kind_and_timestamp(env):
    env.workers = [("d1", "complete")]
    env.validator = [PASS]
    env.inputs = ["yes"]
    _chain(env)

    path = _single_record(env)
    (kind, stamp, _), = parse_record(path)
    assert kind == KIND_ROUTING
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", stamp)


def test_text_with_backtick_fences_comes_back_intact(env):
    # Five-backtick run and a bare fence line inside the task; the routing prompt
    # also carries the ```json fence of the return convention.
    task = "Keep this:\n`````\nnested ```json\n{}\n``` text\n`````\nend\n"
    env.workers = [("d1", "complete")]
    env.validator = [PASS]
    env.inputs = ["yes"]
    _chain(env, task=task)

    (_, _, text), = parse_record(_single_record(env))
    assert text == env.worker_prompts[0]
    assert task in text


def test_fence_is_longer_than_any_backtick_run_in_the_text(tmp_path):
    rec = orchestrator._BriefRecord(tmp_path / "d", 1, "developer", "20261120-101500")
    text = "a\n```````\nb\n```\n"  # trailing newline and a 7-backtick run must survive too
    rec.record(KIND_ROUTING, text)
    lines = rec.path.read_text(encoding="utf-8").split("\n")
    opening = [ln for ln in lines if ln.endswith("text") and set(ln[:-4]) == {"`"}]
    assert opening == ["`" * 8 + "text"]
    assert parse_record(rec.path)[0][2] == text


# ---------------------------------------------------------------------------
# Owner edits and aborts
# ---------------------------------------------------------------------------

def test_owner_edited_routing_text_is_what_is_saved(env):
    edited = ["Owner rewrote this brief.", "```python", "print('hi')", "```"]
    env.workers = [("d1", "complete")]
    env.validator = [PASS]
    env.inputs = ["edit", *edited, "---END---"]
    _chain(env)

    (_, _, text), = parse_record(_single_record(env))
    assert text == "\n".join(edited)
    assert text == env.worker_prompts[0]
    assert "You are the Developer Worker" not in text


def test_aborted_prompt_is_not_recorded(env):
    env.inputs = ["abort"]
    assert _chain(env) is False
    assert env.worker_prompts == []
    assert env.record_files() == []


def test_aborted_semantic_correction_prompt_is_not_recorded(env):
    env.workers = [("s1", "complete")]
    env.validator = [FAIL_CRITICAL]
    env.inputs = ["yes", "abort"]  # approve routing, abort the semantic correction prompt
    assert _chain(env) is False

    entries = parse_record(_single_record(env))
    assert [kind for kind, _, _ in entries] == [KIND_ROUTING]


# ---------------------------------------------------------------------------
# Where: file name, topic, one file per hop per run
# ---------------------------------------------------------------------------

def test_single_hop_run_gets_a_record(env):
    env.workers = [("d1", "complete")]
    env.validator = [PASS]
    env.inputs = ["yes"]
    _chain(env, run_stamp="20261120-101500")

    assert _single_record(env) == env.record_dir / "coordinator_hop_1_developer_brief_20261120-101500.md"
    assert len(parse_record(_single_record(env))) == 1


def test_two_hop_run_has_one_file_per_hop_sharing_the_run_stamp(env):
    env.workers = [("a1", "complete"), ("d1", "complete")]
    env.validator = [PASS, PASS]
    env.inputs = ["yes", "yes"]
    _chain(env, workers=("architect", "developer"), run_stamp="20261120-101500")

    assert sorted(p.name for p in env.record_files()) == [
        "coordinator_hop_1_architect_brief_20261120-101500.md",
        "coordinator_hop_2_developer_brief_20261120-101500.md",
    ]
    for path, prompt in zip(env.record_files(), env.worker_prompts):
        (kind, _, text), = parse_record(path)
        assert kind == KIND_ROUTING and text == prompt
    # The hop-1 deliverable itself is still written beside its record.
    assert (env.record_dir / "coordinator_hop_1_architect.md").exists()


@pytest.mark.parametrize("marker", ["final_outputs", "intermediate_outputs"])
def test_topic_comes_from_final_or_intermediate_outputs_path(env, marker):
    output = env.output_root / marker / "topic_y" / "report.md"
    env.expected = str(output)
    env.workers = [("d1", "complete")]
    env.validator = [PASS]
    env.inputs = ["yes"]
    _chain(env, output=output)

    expected_file = env.output_root / "intermediate_outputs" / "topic_y" / (
        "coordinator_hop_1_developer_brief_20261120-101500.md"
    )
    assert env.record_files() == [expected_file]


def test_two_runs_on_one_topic_give_two_files(env, monkeypatch):
    stamps = iter(["20261120-101500", "20261120-101501"])
    monkeypatch.setattr(orchestrator, "_run_stamp", lambda: next(stamps))
    for _ in range(2):
        env.workers = [("d1", "complete")]
        env.validator = [PASS]
        env.inputs = ["yes"]
        asyncio.run(orchestrator.run(
            "the task", workers="developer", output=str(env.final), sections="Summary"
        ))

    assert [p.name for p in env.record_files()] == [
        "coordinator_hop_1_developer_brief_20261120-101500.md",
        "coordinator_hop_1_developer_brief_20261120-101501.md",
    ]


def test_run_takes_the_stamp_once_and_names_files_with_it(env, monkeypatch):
    calls = []
    real = orchestrator._run_stamp

    def counting():
        calls.append(1)
        return real()

    monkeypatch.setattr(orchestrator, "_run_stamp", counting)
    env.workers = [("a1", "complete"), ("d1", "complete")]
    env.validator = [PASS, PASS]
    env.inputs = ["yes", "yes"]
    asyncio.run(orchestrator.run(
        "the task", workers="architect,developer", output=str(env.final), sections="Summary"
    ))

    assert len(calls) == 1
    files = env.record_files()
    assert len(files) == 2 and all(_TIMESTAMP_FILE_RE.search(p.name) for p in files)
    assert len({_TIMESTAMP_FILE_RE.search(p.name).group(0) for p in files}) == 1


def test_same_stamp_never_overwrites_an_earlier_file(env):
    for _ in range(2):
        env.workers = [("d1", "complete")]
        env.validator = [PASS]
        env.inputs = ["yes"]
        _chain(env, task="first run" if not env.record_files() else "second run")

    first, second = sorted(env.record_files())
    assert first.name == "coordinator_hop_1_developer_brief_20261120-101500.md"
    assert second.name == "coordinator_hop_1_developer_brief_20261120-101500_2.md"
    assert "first run" in first.read_text(encoding="utf-8")
    assert "second run" in second.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Write failure: warn, log, continue
# ---------------------------------------------------------------------------

def test_write_failure_warns_logs_and_lets_the_hop_finish(env, capsys):
    # A regular file where the intermediate_outputs folder should be makes the
    # record's mkdir fail with an OSError; the final deliverable is unaffected.
    env.output_root.mkdir(parents=True, exist_ok=True)
    (env.output_root / "intermediate_outputs").write_text("not a folder", encoding="utf-8")
    env.workers = [("d1", "complete")]
    env.validator = [PASS]
    env.inputs = ["yes"]

    assert _chain(env) is True

    out = capsys.readouterr().out
    assert "[brief record] WARNING" in out and "NOT recorded" in out and "hop continues" in out
    log = env.log_text()
    assert "brief record write failed" in log and KIND_ROUTING in log
    assert "Hop 1/1 accepted" in log
    assert len(env.worker_prompts) == 1 and Path(env.expected).exists()


def test_failed_entry_is_included_by_the_next_successful_write(tmp_path, monkeypatch):
    log_path = tmp_path / "log.md"
    monkeypatch.setattr(orchestrator, "_WORKER_UPDATES_LOG", log_path)
    blocker = tmp_path / "blocker"
    blocker.write_text("file", encoding="utf-8")
    rec = orchestrator._BriefRecord(blocker / "sub", 1, "developer", "20261120-101500")
    rec.record(KIND_ROUTING, "first")           # fails: parent is a file
    assert rec.path is None
    blocker.unlink()                            # the problem goes away
    rec.record(KIND_RESUME, "second")

    assert [(k, t) for k, _, t in parse_record(rec.path)] == [(KIND_ROUTING, "first"), (KIND_RESUME, "second")]
    assert log_path.read_text(encoding="utf-8").count("brief record write failed") == 1


def test_log_failure_during_a_write_failure_does_not_raise(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(orchestrator, "_WORKER_UPDATES_LOG", tmp_path)  # a directory: open() raises OSError
    blocker = tmp_path / "blocker"
    blocker.write_text("file", encoding="utf-8")
    rec = orchestrator._BriefRecord(blocker / "sub", 1, "developer", "20261120-101500")

    rec.record(KIND_ROUTING, "text")  # must not raise

    out = capsys.readouterr().out
    assert "could not write" in out and "worker updates log" in out
