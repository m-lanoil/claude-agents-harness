# Mode Selection Protocol

Used by: Meta-Orchestrator
Triggered when: a new task arrives, after worker classification.

State the recommended mode and reason before routing. The user can override.

## Default
Default **Manual**; Coordinator only for tasks meeting the criteria below, chosen per task by the owner.
The standing override (2026-09-28 to 2026-11-09) was lifted by the owner on 2026-11-09: the per-brief
eligibility record and the six exit criteria were overhead, so they no longer gate coordinator use.
The `coordinator/` program is unchanged; known limits (no tracked tests, failed-fetch path undefined,
workers cannot ask mid-task) stay listed in `STATUS.md`.

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

## Error cost
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
