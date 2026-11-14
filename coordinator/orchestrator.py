"""coordinator.orchestrator — automated orchestration loop.

Entry point: run(task) async. Called from __main__.py or a future scheduled trigger.
"""
import asyncio
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from claude_agent_sdk import ResultError, query

from .schemas import RoutingPrompt, WorkerResult, AcceptanceResult, ValidatorResult
from .worker_registry import WORKER_DIRS, build_options, build_validator_options
from .acceptance import parse_worker_result, acceptance_check

_REPO_ROOT = Path(__file__).parent.parent
_WORKER_UPDATES_LOG = _REPO_ROOT / "logs" / "worker_updates.md"
_DOCS_FETCHER_DIR = _REPO_ROOT / "servers" / "docs_fetcher"
_REGISTRY_FILES = {
    "libraries": "libraries.json",
    "clis": "clis.json",
    "other": "other_sources.json",
}

_JSON_RETURN_CONVENTION = """
---
At the end of your response, output a JSON block with this exact structure — no trailing text after it:

```json
{
  "deliverable_path": "<path to your deliverable>",
  "status": "complete",
  "self_critique": "<one paragraph — gaps, assumptions, ungrounded claims>",
  "gaps": ["<gap 1>", "<gap 2>"]
}
```

If a required source cannot be fetched, end instead with "status": "blocked" and a "blocked_sources" list of {"source", "reason", "candidates" (optional)}, as WORKER_STANDARDS.md (Human-Retrieved Source Protocol) describes.
"""

# Matches the last ```json ... ``` block — same pattern as acceptance.py
_JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
_VALIDATOR_REQUIRED_KEYS = {"verdict", "issues", "confidence", "summary"}
_VALIDATOR_CONFIDENCE_THRESHOLD = 0.7


# ---------------------------------------------------------------------------
# URL pre-registration
# ---------------------------------------------------------------------------

def _preregister_urls(approved_urls_json: str | None) -> None:
    """Merge approved URLs into the Source Registry JSON files before worker invocation.

    Parses *approved_urls_json* as a JSON object with optional keys "libraries",
    "clis", and "other" (each mapping name → url). For each key, loads the
    corresponding registry file in servers/docs_fetcher/, merges new entries
    (skipping any name already present), and writes back. Creates the file as an
    empty object if it does not exist.

    Idempotent: re-running with the same JSON produces no changes and no errors.
    Returns immediately if *approved_urls_json* is None or empty.
    """
    if not approved_urls_json:
        return
    try:
        approved = json.loads(approved_urls_json)
    except json.JSONDecodeError as exc:
        print(f"[preregister_urls] WARNING: could not parse --approved-urls JSON: {exc}")
        return
    if not isinstance(approved, dict):
        print("[preregister_urls] WARNING: --approved-urls JSON must be an object; nothing registered.")
        return

    for key, filename in _REGISTRY_FILES.items():
        entries = approved.get(key)
        if not entries:
            continue
        if not isinstance(entries, dict):
            print(
                f"[preregister_urls] WARNING: '{key}' must be an object mapping "
                "name to URL; skipped."
            )
            continue
        registry_path = _DOCS_FETCHER_DIR / filename
        if registry_path.exists():
            with registry_path.open("r", encoding="utf-8") as fh:
                existing: dict = json.load(fh)
        else:
            existing = {}
        new_entries = {k: v for k, v in entries.items() if k not in existing}
        if new_entries:
            existing.update(new_entries)
            with registry_path.open("w", encoding="utf-8") as fh:
                json.dump(existing, fh, indent=2)
            print(
                f"[preregister_urls] Registered {len(new_entries)} {key} URL(s): "
                f"{list(new_entries)}"
            )
        else:
            print(
                f"[preregister_urls] No new {key} URLs to register (all already present)."
            )


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def build_routing_prompt(
    worker_name: str,
    task_description: str,
    expected_output_path: str,
    required_sections: list[str],
    hop_index: int = 0,
    total_hops: int = 1,
    hop_context: Optional[str] = None,
) -> str:
    sections_str = (
        "\n".join(f"- {s}" for s in required_sections)
        if required_sections
        else "- (none specified)"
    )
    hop_line = (
        f"This is hop {hop_index + 1} of {total_hops} in a multi-hop chain."
        if total_hops > 1
        else ""
    )
    hop_ctx_block = f"\n\nPrior hop context:\n{hop_context}" if hop_context else ""
    return (
        f"You are the {worker_name.capitalize()} Worker. "
        f"You are receiving a task from the Meta-Orchestrator.\n"
        f"{hop_line}\n"
        f"\nTask:\n{task_description}"
        f"{hop_ctx_block}"
        f"\n\nExpected output: {expected_output_path}"
        f"\nRequired sections:\n{sections_str}"
        f"\n\nRun your Task Start Checklist before taking any action."
        f"\n\nBefore closing the task, review your deliverable against this brief "
        f"and flag any gap or assumption you made."
        f"\n{_JSON_RETURN_CONVENTION}"
    )


def _build_validator_prompt(routing: RoutingPrompt, result: WorkerResult) -> str:
    """Build the prompt for the Validator internal process."""
    sections_str = (
        "\n".join(f"- {s}" for s in routing.required_sections)
        if routing.required_sections
        else "- (none specified)"
    )
    return (
        "You are a Validator. Your task is to review a completed deliverable against "
        "its original task specification and return a structured verdict.\n\n"
        f"## Original Task\n{routing.prompt_text}\n\n"
        f"## Required Sections\n{sections_str}\n\n"
        f"## Deliverable Path\n{result.deliverable_path}\n\n"
        f"## Worker Self-Critique\n{result.self_critique}\n\n"
        "## Validation Instructions\n"
        "Use the Read tool to read the deliverable at the path above. "
        "Evaluate it against these four criteria:\n\n"
        "1. **Coverage**: Does the deliverable address all aspects of the task description? "
        "Flag any task requirement with no corresponding content.\n"
        "2. **Substantiveness**: Are required sections substantive, or do they contain "
        "placeholder text, vague assertions, or content that merely echoes the task brief "
        "without adding analysis?\n"
        "3. **Internal consistency**: Do the recommendations in one section contradict "
        "those in another?\n"
        "4. **Grounding honesty**: If the deliverable claims external sources, are those "
        "claims plausible given the stated worker tools? Flag structurally suspicious claims.\n\n"
        "## Output Format\n"
        "At the end of your response, output a JSON block with this exact structure — "
        "no trailing text after it:\n\n"
        "```json\n"
        "{\n"
        '  "verdict": "pass",\n'
        '  "issues": [\n'
        '    {\n'
        '      "severity": "critical",\n'
        '      "section": "<section name or global>",\n'
        '      "description": "<what is missing or wrong>"\n'
        '    }\n'
        '  ],\n'
        '  "confidence": 0.85,\n'
        '  "summary": "<one sentence>"\n'
        "}\n"
        "```\n\n"
        'verdict must be "pass" or "fail". '
        "confidence is 0.0–1.0 (your self-assessed certainty that the verdict is correct). "
        "issues is an empty list for a clean pass."
    )


# ---------------------------------------------------------------------------
# Worker invocation
# ---------------------------------------------------------------------------

def _sdk_error_detail(message) -> Optional[str]:
    """Return the fixed-format error line for a ResultMessage with is_error set, else None.

    Every field is read with getattr and a default, so a message object that
    lacks them (a test fake) counts as not an error. A None value prints as None.
    """
    if not getattr(message, "is_error", False):
        return None
    return (
        f"SDK error result: subtype={getattr(message, 'subtype', None)}, "
        f"errors={getattr(message, 'errors', None)}, "
        f"api_error_status={getattr(message, 'api_error_status', None)}, "
        f"terminal_reason={getattr(message, 'terminal_reason', None)}"
    )


def _sdk_error_detail_from_exception(exc: BaseException) -> str:
    """Return the fixed-format error line for a ResultError raised with no error ResultMessage.

    The exception carries only a message and an exit code, so subtype and
    api_error_status stay None; the message goes in errors and the exit code
    in terminal_reason.
    """
    message = getattr(exc, "message", None) or str(exc)
    return (
        f"SDK error result: subtype=None, errors=[{message!r}], "
        f"api_error_status=None, terminal_reason=exit_code={getattr(exc, 'exit_code', None)}"
    )


async def _invoke_worker(
    worker_name: str,
    full_prompt: str,
    resume_session: Optional[str] = None,
) -> tuple[str, Optional[str], Optional[str]]:
    """Stream worker output; return (raw_text, session_id, error_detail).

    session_id is captured from the init SystemMessage for potential correction
    loop resumption (Q5 decision: session resumption enabled). If the init
    message gave none, the ResultMessage session_id is used instead. A result
    of None (the SDK types it str | None) is treated as empty text.
    error_detail is None unless the ResultMessage has is_error set; then it is
    the one-line SDK error description from _sdk_error_detail.
    The real SDK raises ResultError after yielding an error ResultMessage; that
    exception is absorbed here. If no error detail was captured yet, it is built
    from the exception. Any other exception propagates.
    """
    options = build_options(worker_name, resume=resume_session)
    result_text = ""
    session_id: Optional[str] = None
    result_session_id: Optional[str] = None
    error_detail: Optional[str] = None

    try:
        async for message in query(prompt=full_prompt, options=options):
            # Capture session ID from init message for correction loop resumption
            subtype = getattr(message, "subtype", None)
            if subtype == "init":
                data = getattr(message, "data", {})
                session_id = data.get("session_id")
            if hasattr(message, "result"):
                result_text = message.result or ""
                result_session_id = getattr(message, "session_id", None)
                error_detail = _sdk_error_detail(message)
    except ResultError as exc:
        if error_detail is None:
            error_detail = _sdk_error_detail_from_exception(exc)

    return result_text, session_id or result_session_id, error_detail


# ---------------------------------------------------------------------------
# Single hop: invoke → parse → check (with one retry)
# ---------------------------------------------------------------------------

async def _run_single_hop(
    routing: RoutingPrompt,
    full_prompt: str,
    resume_session: Optional[str] = None,
) -> tuple[Optional[AcceptanceResult], WorkerResult]:
    """Invoke worker once; parse result; run acceptance check.

    Returns (AcceptanceResult, WorkerResult). On parse failure, or when the SDK
    result has is_error set, WorkerResult has status='malformed' and acceptance
    fails automatically.
    A worker that ends with status='blocked' (failed-fetch path) has no
    deliverable to check: acceptance is skipped and the AcceptanceResult is None.
    Callers must handle that case (see _run_hop_handling_blocks).
    resume_session: optional session ID for resuming a prior worker session
    (used by _handle_validator_result for semantic correction retries and by
    the blocked-source resume).
    """
    raw_text, session_id, error_detail = await _invoke_worker(
        routing.worker, full_prompt, resume_session
    )

    # An SDK error result is malformed whatever its text says: the return block
    # is not parsed, so a valid-looking block cannot pass an errored run.
    if error_detail:
        result = WorkerResult(
            raw_text=raw_text,
            deliverable_path=routing.expected_output_path,
            status="malformed",
            self_critique="",
            gaps=[error_detail],
            session_id=session_id,
        )
    elif (result := parse_worker_result(raw_text)) is None:
        result = WorkerResult(
            raw_text=raw_text,
            deliverable_path=routing.expected_output_path,
            status="malformed",
            self_critique="",
            gaps=["Worker return block missing or malformed — JSON block not found"],
            session_id=session_id,
        )
    else:
        result.session_id = session_id
        # A relative deliverable path is relative to the worker's cwd (its own
        # directory), not the repo root. Make it absolute once, here, so the
        # acceptance check and the Validator prompt read the same file.
        # Empty and non-string values are left for acceptance_check to reject.
        raw_path = result.deliverable_path
        if isinstance(raw_path, str) and raw_path.strip() and not Path(raw_path).is_absolute():
            result.deliverable_path = str((WORKER_DIRS[routing.worker] / raw_path).resolve())

    if result.status == "blocked":
        return None, result

    check = acceptance_check(result, routing)
    return check, result


# ---------------------------------------------------------------------------
# Blocked-source path (failed fetch): stop, report, resume
# ---------------------------------------------------------------------------

_MAX_BLOCK_RESUMES = 2
_HUMAN_SOURCES_DIRNAME = "human-retrieved-sources"


@dataclass
class _BlockBudget:
    """Block-resume cycles used so far for one hop (shared across its retries)."""
    used: int = 0


def _slug(text: str) -> str:
    """lowercase_snake_case slug: non-alphanumerics become underscores, runs collapse."""
    out: list[str] = []
    for ch in text.strip().lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "_":
            out.append("_")
    return "".join(out).strip("_")


def _copy_human_source(src: Path, dest_dir: Path, source_key: str) -> Path:
    """Copy an owner-supplied file into dest_dir; never overwrite; return the copy.

    The copy is named after the blocked source's registry key (lowercase_snake_case)
    plus the original file's suffix. If that name is taken, _2, _3, ... is appended.
    Exclusive-create mode ("xb") makes the no-overwrite check atomic.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    base = _slug(source_key) if not source_key.lower().startswith("http") else ""
    base = base or _slug(src.stem) or "human_source"
    n = 1
    while True:
        name = f"{base}{src.suffix}" if n == 1 else f"{base}_{n}{src.suffix}"
        dest = dest_dir / name
        try:
            with src.open("rb") as fsrc, dest.open("xb") as fdst:
                shutil.copyfileobj(fsrc, fdst)
        except FileExistsError:
            n += 1
            continue
        return dest


def _present_blocked_sources(result: WorkerResult) -> None:
    print(f"\n{'!' * 60}")
    print("Worker is BLOCKED: it could not fetch the source(s) below and has stopped.")
    print("!" * 60)
    for i, entry in enumerate(result.blocked_sources, start=1):
        print(f"\n[{i}] {entry.get('source')}")
        print(f"    reason: {entry.get('reason', '(not given)')}")
        for j, cand in enumerate(entry.get("candidates") or [], start=1):
            print(f"    candidate {j}: {cand}")


def _collect_block_answers(result: WorkerResult) -> Optional[list[dict]]:
    """Ask the owner for one answer per blocked source. None means abort.

    No side effects here (no copy, no registration), so an abort on a later
    source leaves nothing behind. Answer shapes:
      {"source", "kind": "file", "path": Path}
      {"source", "kind": "url", "url": str, "name": str}
      {"source", "kind": "skip"}
    """
    _present_blocked_sources(result)
    answers: list[dict] = []
    for i, entry in enumerate(result.blocked_sources, start=1):
        source = str(entry.get("source"))
        candidates = [str(c) for c in (entry.get("candidates") or [])]
        while True:
            choice = input(
                f"[{i}] {source}: (1) local file path / (2) replacement URL / "
                "(3) continue without / (4) abort: "
            ).strip()
            if choice == "4":
                return None
            if choice == "3":
                answers.append({"source": source, "kind": "skip"})
                break
            if choice == "1":
                raw = input("  Path to the file: ").strip()
                path = Path(raw).expanduser() if raw else None
                if path is None or not path.is_file():
                    print("  Not a readable file. Try again.")
                    continue
                answers.append({"source": source, "kind": "file", "path": path})
                break
            if choice == "2":
                hint = " (or candidate number)" if candidates else ""
                raw = input(f"  Replacement URL{hint}: ").strip()
                if raw.isdigit() and 1 <= int(raw) <= len(candidates):
                    raw = candidates[int(raw) - 1]
                if not raw.lower().startswith("https://"):
                    print("  Need an https:// URL. Try again.")
                    continue
                # Fresh registry name: the old key already exists and _preregister_urls
                # skips names that are present, so reusing it would register nothing.
                name = f"{_slug(source) or 'source'}_replacement"
                answers.append({"source": source, "kind": "url", "url": raw, "name": name})
                break
            print("  Enter 1, 2, 3 or 4.")
    return answers


def _apply_block_answers(worker_name: str, answers: list[dict]) -> list[str]:
    """Perform the side effects of the answers; return one resume-prompt line each."""
    worker_dir = WORKER_DIRS[worker_name]
    lines: list[str] = []
    urls_by_name: dict[str, str] = {}
    for ans in answers:
        source = ans["source"]
        if ans["kind"] == "file":
            copied = _copy_human_source(ans["path"], worker_dir / _HUMAN_SOURCES_DIRNAME, source)
            print(f"[blocked] Copied {ans['path']} -> {copied}")
            lines.append(
                f"- {source}: the owner supplied a local file, saved at "
                f"./{_HUMAN_SOURCES_DIRNAME}/{copied.name} (relative to your working "
                "directory). Apply the Human-Retrieved Source Protocol."
            )
        elif ans["kind"] == "url":
            urls_by_name[ans["name"]] = ans["url"]
            lines.append(
                f"- {source}: the owner approved this replacement URL, now registered "
                f"as '{ans['name']}' in the Source Registry: {ans['url']}. Fetch it."
            )
        else:
            lines.append(
                f"- {source}: the owner chose to continue without this source. "
                "Proceed and disclose the missing source in the deliverable and self-critique."
            )
    if urls_by_name:
        _preregister_urls(json.dumps({"other": urls_by_name}))
    return lines


def _build_resume_prompt(answer_lines: list[str]) -> str:
    return (
        "The owner has answered for each source you reported as blocked:\n"
        + "\n".join(answer_lines)
        + "\n\nResume the task from where you stopped and finish it as briefed, "
        "ending with the JSON return block."
    )


async def _run_hop_handling_blocks(
    routing: RoutingPrompt,
    full_prompt: str,
    budget: _BlockBudget,
    resume_session: Optional[str] = None,
) -> Optional[tuple[AcceptanceResult, WorkerResult]]:
    """Run a hop; on a blocked return, ask the owner and resume the same session.

    Returns (AcceptanceResult, WorkerResult) for the first non-blocked result, or
    None if the hop must stop (owner aborted, no session to resume, or the
    block-resume cap was exceeded). `budget` is shared by every call for the hop.
    """
    check, result = await _run_single_hop(routing, full_prompt, resume_session)
    while result.status == "blocked":
        if budget.used >= _MAX_BLOCK_RESUMES:
            _present_blocked_sources(result)
            print(
                f"\nBlocked again after {_MAX_BLOCK_RESUMES} resume cycles. Aborting this hop.\n"
                "Manual fallback: continue in manual mode (workers/MODE_SELECTION_PROTOCOL.md) "
                "from the hop files in output/intermediate_outputs/."
            )
            _append_worker_updates_log(
                routing.worker, f"blocked: cap of {_MAX_BLOCK_RESUMES} resume cycles exceeded, aborted"
            )
            return None
        if not result.session_id:
            print(
                "\nWorker is blocked but returned no session ID, so it cannot be resumed.\n"
                "Manual fallback: continue in manual mode (workers/MODE_SELECTION_PROTOCOL.md) "
                "from the hop files in output/intermediate_outputs/."
            )
            _append_worker_updates_log(routing.worker, "blocked: no session id to resume, aborted")
            return None
        answers = _collect_block_answers(result)
        if answers is None:
            print("Task aborted by user.")
            _append_worker_updates_log(routing.worker, "blocked: user aborted at blocked-source prompt")
            return None
        resume_prompt = _build_resume_prompt(_apply_block_answers(routing.worker, answers))
        budget.used += 1
        check, result = await _run_single_hop(
            routing, resume_prompt, resume_session=result.session_id
        )
    return check, result


# ---------------------------------------------------------------------------
# Human checkpoint
# ---------------------------------------------------------------------------

def _present_for_approval(full_prompt: str, label: str = "ROUTING PROMPT") -> str:
    """Show the prompt to the user and return the (possibly edited) version."""
    print(f"\n{'=' * 60}")
    print(f"{label} (review before approval)")
    print("=" * 60)
    print(full_prompt)
    print("=" * 60)

    while True:
        choice = input("Approve? (yes / edit / abort): ").strip().lower()
        if choice == "abort":
            return ""
        if choice == "yes":
            return full_prompt
        if choice == "edit":
            print("Paste edited prompt. End with a line containing only '---END---':")
            lines: list[str] = []
            while True:
                line = input()
                if line == "---END---":
                    break
                lines.append(line)
            return "\n".join(lines)
        print("Enter 'yes', 'edit', or 'abort'.")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _append_worker_updates_log(worker: str, note: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _WORKER_UPDATES_LOG.open("a", encoding="utf-8") as f:
        f.write(f"| {ts} | `coordinator → {worker}` | {note} |\n")


# ---------------------------------------------------------------------------
# Validator internal process
# ---------------------------------------------------------------------------

async def _invoke_validator(routing: RoutingPrompt, result: WorkerResult) -> ValidatorResult:
    """Run semantic validation on a completed deliverable.

    Invokes a read-only Claude Agent session with allowed_tools [Read, Glob, Grep]
    and no MCP servers (grounded: kb_claude_agent_sdk.md, §Core interface and
    §ClaudeAgentOptions). Parses the final JSON block from the response using
    _JSON_BLOCK_RE (same pattern as parse_worker_result in acceptance.py).
    Parse errors are treated as a fail verdict with a single critical issue; so
    is a ResultMessage with is_error set (the issue carries the SDK error detail)
    and a ResultError raised by the SDK. Other exceptions propagate.
    """
    prompt = _build_validator_prompt(routing, result)
    options = build_validator_options()

    raw_text = ""
    error_detail: Optional[str] = None
    try:
        async for message in query(prompt=prompt, options=options):
            if hasattr(message, "result"):
                raw_text = message.result or ""
                error_detail = _sdk_error_detail(message)
    except ResultError as exc:
        # The real SDK raises this after an error ResultMessage; absorb it.
        if error_detail is None:
            error_detail = _sdk_error_detail_from_exception(exc)

    if error_detail:
        # An SDK error result fails the validation whatever its text says.
        print(f"\n[Validator] {error_detail}. Treating as fail.")
        _append_worker_updates_log(routing.worker, f"validator_fail: {error_detail}")
        return ValidatorResult(
            verdict="fail",
            issues=[{
                "severity": "critical",
                "section": "global",
                "description": error_detail,
            }],
            confidence=0.0,
            summary="Validator session ended with an SDK error result — treating as fail.",
        )

    matches = list(_JSON_BLOCK_RE.finditer(raw_text))
    if matches:
        try:
            data = json.loads(matches[-1].group(1))
            if _VALIDATOR_REQUIRED_KEYS.issubset(data):
                return ValidatorResult(
                    verdict=str(data["verdict"]),
                    issues=list(data.get("issues", [])),
                    confidence=float(data.get("confidence", 0.0)),
                    summary=str(data.get("summary", "")),
                )
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # Parse error — no valid JSON block
    print("\n[Validator] Parse error — no valid JSON block in Validator output. Treating as fail.")
    _append_worker_updates_log(
        routing.worker,
        "validator_fail: parse error — no valid JSON block in Validator output",
    )
    return ValidatorResult(
        verdict="fail",
        issues=[{
            "severity": "critical",
            "section": "global",
            "description": "Validator returned malformed output — no valid JSON block found",
        }],
        confidence=0.0,
        summary="Validator output parse error — treating as fail.",
    )


async def _handle_validator_result(
    validator_result: ValidatorResult,
    routing: RoutingPrompt,
    result: WorkerResult,
    retry_available: bool = True,
) -> bool:
    """Handle a ValidatorResult. Returns True to proceed, False to abort.

    Pass paths:
      - confidence >= threshold: print summary and return True.
      - confidence < threshold: print low-confidence warning, prompt user, return True.
    Fail paths:
      - Minor issues only (soft gate): advisory print, user decides.
      - Critical issues (hard gate): semantic correction retry if retry_available;
        otherwise escalate immediately.
    Confidence threshold: _VALIDATOR_CONFIDENCE_THRESHOLD (0.7).
    """
    print(f"\n[Validator] {validator_result.summary}")

    if validator_result.verdict.strip().lower() == "pass":
        if validator_result.confidence >= _VALIDATOR_CONFIDENCE_THRESHOLD:
            print(f"[Validator] PASS (confidence: {validator_result.confidence:.2f})")
            return True
        # Low-confidence pass — surface to user before continuing
        print(
            f"[Validator] PASS with low confidence "
            f"({validator_result.confidence:.2f} < {_VALIDATOR_CONFIDENCE_THRESHOLD}). "
            "Review recommended."
        )
        input("Acknowledge low-confidence pass and press Enter to continue: ")
        return True

    # verdict == "fail"
    # Fail closed: only an explicit "minor" is minor; any other severity is critical.
    minor = [
        i for i in validator_result.issues
        if str(i.get("severity", "")).strip().lower() == "minor"
    ]
    critical = [i for i in validator_result.issues if i not in minor]

    print("\n[Validator] FAIL")
    if critical:
        print("  Critical issues:")
        for issue in critical:
            print(f"    • [{issue.get('section', 'global')}] {issue.get('description', '')}")
    if minor:
        print("  Minor issues:")
        for issue in minor:
            print(f"    • [{issue.get('section', 'global')}] {issue.get('description', '')}")

    if not validator_result.issues:
        print("  No issues listed for a failing verdict; treating it as critical.")

    if minor and not critical:
        # Soft gate: every issue is explicitly minor — user decides whether to proceed
        print(f"\n[Validator] Advisory: {len(minor)} minor issue(s). Core task appears addressed.")
        choice = input("Continue despite minor issues? (yes / abort): ").strip().lower()
        if choice != "yes":
            _append_worker_updates_log(
                routing.worker,
                "validator_fail: minor issues only, user aborted",
            )
            return False
        return True

    # Hard gate: critical issues present
    if not retry_available:
        print("\n[Validator] Retry budget exhausted. Escalating to user.")
        _append_worker_updates_log(
            routing.worker,
            f"validator_fail: critical issues, retry budget exhausted: "
            f"{[i.get('description', '') for i in critical]}",
        )
        return False

    # Build semantic correction brief from Validator issues
    issue_lines = "\n".join(
        f"  [{i.get('section', 'global')}] ({i.get('severity', '?')}) {i.get('description', '')}"
        for i in validator_result.issues
    )
    correction_brief = (
        f"SEMANTIC CORRECTION REQUIRED:\n{validator_result.summary}\n\nIssues:\n{issue_lines}"
    )
    # Rebuild base routing prompt and append correction brief
    base_prompt = build_routing_prompt(
        worker_name=routing.worker,
        task_description=routing.prompt_text,
        expected_output_path=routing.expected_output_path,
        required_sections=routing.required_sections,
        hop_index=routing.hop_index,
        total_hops=routing.total_hops,
        hop_context=routing.hop_context,
    )
    correction_prompt = base_prompt + f"\n\n{correction_brief}"
    correction_approved = _present_for_approval(correction_prompt, label="SEMANTIC CORRECTION PROMPT")
    if not correction_approved:
        print("Escalating to user — task not closed.")
        _append_worker_updates_log(routing.worker, "validator_fail: user aborted semantic correction")
        return False

    # Resume original worker session for correction (grounded: kb_claude_agent_sdk.md, §Sessions)
    retry_check, retry_result = await _run_single_hop(
        routing, correction_approved, resume_session=result.session_id
    )
    if retry_check is None:
        # Worker came back blocked on a failed fetch during the semantic correction.
        print(
            "\n[Validator] Correction retry ended blocked on a failed fetch. Escalating to user.\n"
            "Manual fallback: continue in manual mode (workers/MODE_SELECTION_PROTOCOL.md) "
            "from the hop files in output/intermediate_outputs/."
        )
        _append_worker_updates_log(
            routing.worker, "validator_fail: correction retry ended blocked on a failed fetch"
        )
        return False
    if not retry_check.passed:
        print(f"\n[Validator] Correction retry acceptance failed: {retry_check.correction_brief}")
        _append_worker_updates_log(
            routing.worker,
            f"validator_fail: correction retry acceptance failed: {retry_check.correction_brief}",
        )
        return False

    # Re-run Validator on corrected deliverable
    retry_validator = await _invoke_validator(routing, retry_result)
    print(f"\n[Validator] Retry result: {retry_validator.summary}")
    if retry_validator.verdict.strip().lower() != "pass":
        print("\n[Validator] Retry also failed. Escalating to user.")
        _append_worker_updates_log(
            routing.worker,
            f"validator_fail: retry also failed — {retry_validator.summary}",
        )
        return False

    print(f"[Validator] Retry PASS (confidence: {retry_validator.confidence:.2f})")
    return True


# ---------------------------------------------------------------------------
# Multi-hop sequencing
# ---------------------------------------------------------------------------

def _topic_from_output_path(expected_output_path: str) -> str:
    """Extract the topic subfolder from a `.../final_outputs/<topic>/...` path.

    Per CLAUDE.md -> Output Conventions, --output must include a topic subfolder.
    Falls back to 'misc' (and warns) for paths that don't follow that convention,
    so intermediate hop files still land in a folder instead of loose at the top level.
    """
    parts = Path(expected_output_path).parts
    for marker in ("final_outputs", "intermediate_outputs"):
        if marker in parts:
            idx = parts.index(marker)
            if idx + 1 < len(parts) - 1:
                return parts[idx + 1]
    print(
        f"Warning: --output '{expected_output_path}' has no topic subfolder under "
        f"final_outputs/ — intermediate hop files will land in "
        f"output/intermediate_outputs/misc/. See CLAUDE.md -> Output Conventions."
    )
    return "misc"


async def _execute_chain(
    hop_workers: list[str],
    task: str,
    expected_output_path: str,
    required_sections: list[str],
) -> bool:
    """Execute a multi-hop chain. Returns True if all hops passed."""
    hop_context: Optional[str] = None
    total_hops = len(hop_workers)

    for hop_idx, worker_name in enumerate(hop_workers):
        print(f"\n{'─' * 50}")
        print(f"Hop {hop_idx + 1}/{total_hops}: {worker_name}")
        print("─" * 50)

        # For multi-hop: intermediate hops write to a temp path (topic-sorted, matching
        # the final hop's topic); only the final hop writes to expected_output_path.
        if hop_idx < total_hops - 1:
            topic = _topic_from_output_path(expected_output_path)
            hop_output = f"../../output/intermediate_outputs/{topic}/coordinator_hop_{hop_idx + 1}_{worker_name}.md"
        else:
            hop_output = expected_output_path
        # Resolve to absolute path relative to the worker's cwd so acceptance_check
        # can stat the file without the _REPO_ROOT prepend going two levels too high.
        hop_output = str((WORKER_DIRS[worker_name] / hop_output).resolve())
        Path(hop_output).parent.mkdir(parents=True, exist_ok=True)

        routing = RoutingPrompt(
            worker=worker_name,
            prompt_text=task,
            expected_output_path=hop_output,
            required_sections=required_sections if hop_idx == total_hops - 1 else [],
            hop_index=hop_idx,
            total_hops=total_hops,
            hop_context=hop_context,
        )

        full_prompt = build_routing_prompt(
            worker_name=worker_name,
            task_description=task,
            expected_output_path=hop_output,
            required_sections=routing.required_sections,
            hop_index=hop_idx,
            total_hops=total_hops,
            hop_context=hop_context,
        )

        # Human checkpoint (architecture spec: one approval gate per hop)
        approved_prompt = _present_for_approval(full_prompt)
        if not approved_prompt:
            print("Task aborted by user.")
            return False

        # Invoke + acceptance check
        retry_used = False
        block_budget = _BlockBudget()
        outcome = await _run_hop_handling_blocks(routing, approved_prompt, block_budget)
        if outcome is None:
            return False
        check, result = outcome

        if not check.passed:
            print(f"\nAcceptance FAILED: {check.correction_brief}")
            retry = input("Retry this hop with a correction brief? (yes / abort): ").strip().lower()
            if retry != "yes":
                print("Escalating to user — task not closed.")
                _append_worker_updates_log(worker_name, f"Acceptance failed, user escalated: {check.correction_brief}")
                return False

            # One correction retry with session resumption (Q5: enabled)
            retry_used = True
            correction_prompt = approved_prompt + f"\n\nCORRECTION REQUIRED:\n{check.correction_brief}"
            retry_approved = _present_for_approval(correction_prompt, label="CORRECTION PROMPT")
            if not retry_approved:
                print("Escalating to user — task not closed.")
                return False

            outcome = await _run_hop_handling_blocks(
                routing, retry_approved, block_budget, resume_session=result.session_id
            )
            if outcome is None:
                return False
            check, result = outcome
            if not check.passed:
                print(f"\nRetry also failed: {check.correction_brief}")
                print("Escalating to user — task not closed.")
                _append_worker_updates_log(worker_name, f"Retry failed: {check.correction_brief}")
                return False

        # Semantic validation — runs only when acceptance passes (structural gate first)
        validator_result = await _invoke_validator(routing, result)
        proceed = await _handle_validator_result(
            validator_result, routing, result, retry_available=not retry_used
        )
        if not proceed:
            _append_worker_updates_log(
                worker_name,
                f"validator_fail: Hop {hop_idx + 1}/{total_hops} not closed by Validator",
            )
            return False

        # Gap escalation: surface all gaps to user before moving on (Q3: no silent close)
        if check.gaps:
            print(f"\nWorker reported gaps:\n" + "\n".join(f"  • {g}" for g in check.gaps))
            input("Acknowledge gaps and press Enter to continue: ")

        print(f"\nHop {hop_idx + 1}/{total_hops} passed.")
        _append_worker_updates_log(
            worker_name,
            f"Hop {hop_idx + 1}/{total_hops} accepted. Output: {hop_output}. Gaps: {result.gaps}",
        )

        # Pass this hop's output as context into the next hop
        hop_context = (
            f"Hop {hop_idx + 1} ({worker_name}) completed. "
            f"Output path: {hop_output}. "
            f"Worker self-critique: {result.self_critique}"
        )

    return True


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run(
    task: str,
    workers: Optional[str] = None,
    output: Optional[str] = None,
    sections: Optional[str] = None,
    approved_urls: Optional[str] = None,
) -> None:
    """Coordinator main loop. Interactive classification → human checkpoint → invoke → accept → log.

    Args:
        task: Task description string (required).
        workers: Pre-specified worker chain (e.g. 'developer' or 'architect,developer').
                 When provided, skips the interactive worker-chain prompt.
        output:  Pre-specified output path (e.g. '../../output/report.md').
                 When provided, skips the interactive output-path prompt.
        sections: Pre-specified required sections, comma-separated (e.g. 'Summary,Results').
                  When provided, skips the interactive sections prompt.
        approved_urls: Optional JSON string of URLs to pre-register into the Source Registry
                       before invoking any worker. Format:
                       '{"libraries": {"name": "url"}, "clis": {"name": "url"},
                         "other": {"name": "url"}}' (any key may be omitted).

    Interactive HITL checks that always fire regardless of pre-specified args:
        - Prompt approval gate (approve / edit / abort before each worker invocation)
        - Gap acknowledgment (user must acknowledge worker-reported gaps)
        - Correction retry gate (user approves or aborts before correction attempt)
    """
    print(f"\n{'#' * 60}")
    print("Coordinator: new task")
    print(f"{'#' * 60}")
    print(f"\n{task}\n")

    # Step 1: Classification (human-guided; rules are in root CLAUDE.md)
    print("Step 1: Classification")
    print(f"Workers available: {', '.join(WORKER_DIRS)}")
    if workers is not None:
        worker_input = workers.strip().lower()
        print(f"Worker chain (pre-specified): {worker_input}")
    else:
        worker_input = input("Enter worker name or multi-hop chain (e.g. 'architect,developer'): ").strip().lower()
    hop_workers = [w.strip() for w in worker_input.split(",") if w.strip()]

    if not hop_workers:
        print("No workers specified. Aborting.")
        return

    unknown = [w for w in hop_workers if w not in WORKER_DIRS]
    if unknown:
        print(f"Unknown worker(s): {unknown}. Aborting.")
        return

    # Step 2: Routing details
    if output is not None:
        expected_output_path = output.strip()
        print(f"Output path (pre-specified): {expected_output_path}")
    else:
        expected_output_path = input("Expected output path (e.g. ../../output/report.md): ").strip()

    if sections is not None:
        sections_raw = sections
        print(f"Required sections (pre-specified): {sections_raw if sections_raw else '(none)'}")
    else:
        sections_raw = input("Required sections (comma-separated; leave blank for none): ").strip()
    required_sections = [s.strip() for s in sections_raw.split(",") if s.strip()]

    # Pre-register approved URLs into the Source Registry before worker invocation
    _preregister_urls(approved_urls)

    # Steps 3-6: Human checkpoint + invoke + accept for each hop
    success = await _execute_chain(
        hop_workers=hop_workers,
        task=task,
        expected_output_path=expected_output_path,
        required_sections=required_sections,
    )

    # Step 7: Log
    if success:
        print("\n=== Task complete ===")
    else:
        _append_worker_updates_log(" → ".join(hop_workers), "Task not closed (failed or aborted)")
