# Mode Selection Protocol

Used by: Meta-Orchestrator
Triggered when: a new task arrives, after worker classification.

State the recommended mode and reason before routing. The user can override.

## Standing override (active since 2026-09-28)
Coordinator mode is disabled by standing user instruction. Always recommend **Manual mode**,
regardless of which Coordinator/Hybrid criteria below would otherwise apply — do not use them to
select Coordinator. The `coordinator/` program itself is untouched by this override; it is kept in
the repo, just not invoked by the routing workflow. Remove this section to re-enable Coordinator
mode selection.

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

## How to communicate
> "Recommended mode: **[coordinator / manual]** — [one-line reason]."

State this before the command or manual routing instruction. If manual, name the worker directory.
