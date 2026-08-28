"""coordinator.orchestrator — automated orchestration loop.

Entry point: run(task) async. Called from __main__.py or a future scheduled trigger.
"""
import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from claude_agent_sdk import query

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

    for key, filename in _REGISTRY_FILES.items():
        entries = approved.get(key)
        if not entries:
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

async def _invoke_worker(
    worker_name: str,
    full_prompt: str,
    resume_session: Optional[str] = None,
) -> tuple[str, Optional[str]]:
    """Stream worker output; return (raw_text, session_id).

    session_id is captured from the init SystemMessage for potential correction
    loop resumption (Q5 decision: session resumption enabled).
    """
    options = build_options(worker_name, resume=resume_session)
    result_text = ""
    session_id: Optional[str] = None

    async for message in query(prompt=full_prompt, options=options):
        # Capture session ID from init message for correction loop resumption
        subtype = getattr(message, "subtype", None)
        if subtype == "init":
            data = getattr(message, "data", {})
            session_id = data.get("session_id")
        if hasattr(message, "result"):
            result_text = message.result

    return result_text, session_id


# ---------------------------------------------------------------------------
# Single hop: invoke → parse → check (with one retry)
# ---------------------------------------------------------------------------

async def _run_single_hop(
    routing: RoutingPrompt,
    full_prompt: str,
    resume_session: Optional[str] = None,
) -> tuple[AcceptanceResult, WorkerResult]:
    """Invoke worker once; parse result; run acceptance check.

    Returns (AcceptanceResult, WorkerResult). On parse failure, WorkerResult
    has status='malformed' and acceptance fails automatically.
    resume_session: optional session ID for resuming a prior worker session
    (used by _handle_validator_result for semantic correction retries).
    """
    raw_text, session_id = await _invoke_worker(routing.worker, full_prompt, resume_session)

    result = parse_worker_result(raw_text)
    if result is None:
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

    check = acceptance_check(result, routing)
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
    Parse errors are treated as a fail verdict with a single critical issue.
    """
    prompt = _build_validator_prompt(routing, result)
    options = build_validator_options()

    raw_text = ""
    async for message in query(prompt=prompt, options=options):
        if hasattr(message, "result"):
            raw_text = message.result

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

    if validator_result.verdict == "pass":
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
    critical = [i for i in validator_result.issues if i.get("severity") == "critical"]
    minor = [i for i in validator_result.issues if i.get("severity") == "minor"]

    print("\n[Validator] FAIL")
    if critical:
        print("  Critical issues:")
        for issue in critical:
            print(f"    • [{issue.get('section', 'global')}] {issue.get('description', '')}")
    if minor:
        print("  Minor issues:")
        for issue in minor:
            print(f"    • [{issue.get('section', 'global')}] {issue.get('description', '')}")

    if not critical:
        # Soft gate: minor issues only — user decides whether to proceed
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
    if retry_validator.verdict != "pass":
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
        check, result = await _run_single_hop(routing, approved_prompt)

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

            check, result = await _run_single_hop(routing, retry_approved)
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
