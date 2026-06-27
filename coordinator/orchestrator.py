"""coordinator.orchestrator — automated orchestration loop.

Entry point: run(task) async. Called from __main__.py or a future scheduled trigger.
"""
import asyncio
import json
from pathlib import Path
from typing import Optional

from claude_agent_sdk import query

from .schemas import RoutingPrompt, WorkerResult, AcceptanceResult
from .worker_registry import WORKER_DIRS, build_options
from .acceptance import parse_worker_result, acceptance_check

_REPO_ROOT = Path(__file__).parent.parent
_WORKER_UPDATES_LOG = _REPO_ROOT / "logs" / "worker_updates.md"

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
) -> tuple[AcceptanceResult, WorkerResult]:
    """Invoke worker once; parse result; run acceptance check.

    Returns (AcceptanceResult, WorkerResult). On parse failure, WorkerResult
    has status='malformed' and acceptance fails automatically.
    """
    raw_text, session_id = await _invoke_worker(routing.worker, full_prompt)

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
# Multi-hop sequencing
# ---------------------------------------------------------------------------

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

        # For multi-hop: intermediate hops write to a temp path; only the final
        # hop writes to expected_output_path.
        if hop_idx < total_hops - 1:
            hop_output = f"../../output/coordinator_hop_{hop_idx + 1}_{worker_name}.md"
        else:
            hop_output = expected_output_path

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
        check, result = await _run_single_hop(routing, approved_prompt)

        if not check.passed:
            print(f"\nAcceptance FAILED: {check.correction_brief}")
            retry = input("Retry this hop with a correction brief? (yes / abort): ").strip().lower()
            if retry != "yes":
                print("Escalating to user — task not closed.")
                _append_worker_updates_log(worker_name, f"Acceptance failed, user escalated: {check.correction_brief}")
                return False

            # One correction retry with session resumption (Q5: enabled)
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

async def run(task: str) -> None:
    """Coordinator main loop. Interactive classification → human checkpoint → invoke → accept → log."""
    print(f"\n{'#' * 60}")
    print("Coordinator: new task")
    print(f"{'#' * 60}")
    print(f"\n{task}\n")

    # Step 1: Classification (human-guided; rules are in root CLAUDE.md)
    print("Step 1: Classification")
    print(f"Workers available: {', '.join(WORKER_DIRS)}")
    worker_input = input("Enter worker name or multi-hop chain (e.g. 'architect,developer'): ").strip().lower()
    hop_workers = [w.strip() for w in worker_input.split(",") if w.strip()]

    unknown = [w for w in hop_workers if w not in WORKER_DIRS]
    if unknown:
        print(f"Unknown worker(s): {unknown}. Aborting.")
        return

    # Step 2: Routing details
    expected_output_path = input("Expected output path (e.g. ../../output/report.md): ").strip()
    sections_raw = input("Required sections (comma-separated; leave blank for none): ").strip()
    required_sections = [s.strip() for s in sections_raw.split(",") if s.strip()]

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
