# Mode Selection Protocol

Used by: Meta-Orchestrator
Triggered when: a new task arrives, after worker classification.

State the recommended mode and reason before routing. The user can override.

## Standing override (active since 2026-09-28)
Coordinator mode is disabled by standing user instruction. Always recommend **Manual mode**,
regardless of which Coordinator/Hybrid criteria below would otherwise apply — do not use them to
select Coordinator. The `coordinator/` program itself is untouched by this override; it is kept in
the repo, just not invoked by the routing workflow.

**Why:** the tasks run so far needed owner judgment on sources and acceptance that a hop chain
could not give (owner, 2026-10-06).
**Intent (owner, 2026-10-23):** manual mode is where the failures a coordinator would hit are found
and fixed. The goal is Coordinator for eligible tasks, with Manual always available as the fallback.
**Re-enable:** when all exit criteria below are met, the owner approves replacing this section with
"Default Manual; Coordinator only for tasks meeting the criteria below, chosen per task by the owner."
Until then, do not recommend Coordinator.
**Record while the override holds:** at each brief, still state the Coordinator-eligible call (yes, no or unsure, with the reason against the "use when all of these hold" criteria) and the error-cost rating for the owner to confirm, and carry both into the Track-record entry. The recommendation stays Manual. Eligibility is the orchestrator's assessment, not a question for the owner; only error cost is owner-confirmed. Exit criteria 1 and 2 count only "yes" entries, so unrecorded entries cannot count toward them.

### Exit criteria (all required)
1. **Acceptance reliability:** the last 5 coordinator-eligible tasks logged no orchestrator acceptance
   misfire (a real quote flagged as ungrounded, or a misattributed claim passed).
2. **Brief accuracy:** the same 5 tasks had no brief item the owner had to reverse. Coordinator workers
   cannot ask mid-task, so a wrong brief goes uncorrected.
3. **Failed-fetch path:** the coordinator has a defined behaviour for a blocked or wrong page (stop,
   report, resume). The Human-Retrieved Source Protocol is manual-only today.
4. **Trial run:** one coordinator run per eligible task type (see Hybrid cases below). The owner reviews
   the output against what manual mode would have produced, and accepts it with no more corrections than
   the manual baseline.
5. **Fallback intact:** a failed coordinator run can be continued in Manual mode from its hop files.
6. **Tests:** `coordinator/` has tracked tests (part of the 10-entry batch in `STATUS.md`).

## Coordinator mode — use when all of these hold
- Spec is complete and self-contained: worker needs no mid-task clarification
- Output format is defined: file path and required sections are known
- No reproduction or interactive verification required
- URLs needed are either registered or can be pre-approved via `--approved-urls`
- User reviews the deliverable after completion, not during

## Manual mode — use when any of these hold
- **Bug fix**: task requires reproduce → isolate → verify loop that needs user interaction
- **Exploratory**: solution path is uncertain; user needs to redirect mid-task based on findings
- **Iterative**: user must review intermediate outputs to decide next steps (ML metrics, data exploration, incremental drafts)
- **Context-dependent**: task may surface new constraints that change the approach mid-run
- **Unknown URLs**: sources cannot be pre-approved because they are not known upfront

For manual mode: give the worker directory path and tell the user to open a Claude Code session there.

## Hybrid cases — coordinator is viable when
- Bug fix where root cause is already isolated and fully described in the brief
- Research task where the question is scoped and all needed URLs are known
- ML task where the next training step is fully specified and no metric review is needed mid-run

In hybrid cases, state the assumption that makes coordinator viable (e.g. "treating the root cause as confirmed per the brief").

## Error cost (applies only after the standing override is lifted)
Eligibility and error cost are separate tests. Coordinator mode needs both.

1. **Eligibility** — the "Coordinator mode — use when all of these hold" list above.
2. **Error cost** — state at brief time, and the owner confirms:
   - **Low**: an error is cheap to catch and reverse. Examples: internal working notes, scoping or source-discovery rounds, exploratory drafts the owner will rewrite.
   - **High**: an error could reach a client or third party, be used as a deliverable without further review, or be hard to reverse. Examples: client-facing documents, anything with figures or quotes the owner will not re-check, system-level or destructive changes.

| Eligible | Error cost | Mode |
|---|---|---|
| yes | low | Coordinator |
| yes | high | Coordinator for earlier hops only; final hop and its acceptance in Manual mode, with the owner reviewing every claim against its source |
| no | any | Manual |

If error cost is unclear, treat it as high.

**Why:** the coordinator's acceptance check confirms structure (file, sections, self-critique) and flags ungrounded claims, but workers cannot ask mid-task. A wrong brief or a missed claim reaches the owner only after the run. Where that is cheap, accept it; where it is not, keep a human at the point where the deliverable is finalised.

## How to communicate
> "Recommended mode: **[coordinator / manual]** — [one-line reason]."

State this before the command or manual routing instruction. If manual, name the worker directory.
