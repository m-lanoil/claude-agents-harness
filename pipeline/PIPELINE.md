# Pipeline

End-to-end task workflow: Research → Planning → Coding → Validation → Publicizing.
Each phase is a standalone instruction file in `pipeline/phases/`, readable by any coding
CLI (Claude Code, Cursor, Codex, Aider). Phases communicate only through files — a phase
must be runnable in a fresh session with zero conversation memory.

## Quick start (any CLI)

Start a session at the repo root and paste:

```
Read pipeline/phases/01_research.md and execute it.
Task: <your task statement>. Run slug: <task_slug>.
```

Then for each subsequent phase, in the same or a fresh session:

```
Read pipeline/phases/0N_<phase>.md and execute it. Run slug: <task_slug>.
```

Every phase re-derives its full context from the run directory — no session carryover needed.

## Run directory contract

All artifacts for one task live in `pipeline/runs/<task_slug>/` (gitignored, local audit trail):

| Artifact | Written by | Read by |
|---|---|---|
| `task.md` | you (or phase 1/2 kickoff) | all phases |
| `research.md` | phase 1 | 2, 3 |
| `plan.md` | phase 2 | 3, 4, 5 |
| `holdback/test_spec.md` | phase 2 | 4 only — **never phase 3** |
| `implementation_notes.md` | phase 3 | 4, 5 |
| `holdback/tests/` | phase 4 | 4 |
| `validation_report.md` | phase 4 | 5 (checks Human Verdict) |
| `publish_report.md` | phase 5 | you |

## Phase rules

- **Skipping**: Phase 1 is skippable when the task needs no external knowledge — phase 2
  then records "research skipped: <reason>" in `plan.md`. No other phase may be skipped.
- **Parallel research + planning**: planning may start before research finishes. Mark any
  research-dependent plan item `PROVISIONAL` and reconcile `plan.md` once `research.md` lands.
- **Test isolation**: phase 2 writes `holdback/test_spec.md`; phase 3 is forbidden from
  reading anything under `holdback/`. Enforcement is instruction-level. For hard enforcement
  in Claude Code, add a permission deny rule for `Read(pipeline/runs/**/holdback/**)` to
  `.claude/settings.json` before running phase 3; other CLIs rely on the instruction.
- **Human gate**: phase 5 must refuse to run until `validation_report.md` has
  `Human Verdict: APPROVED`. You run the commands in its Human Checkpoint section, then
  record your verdict and any refinement requests in that file.
- **Taste**: all phases read `TASTE.md` at the repo root and treat it as standing user
  preference. Edit it any time; it outranks phase defaults, never security rules.
- **Mid-task entry (backfill rule)**: joining the pipeline partway through — e.g. code
  already half-written with no plan — does not start at your current step. First run
  `python scripts/check_pipeline_run.py pipeline/runs/<task_slug>`; it names the earliest
  gapped phase (`RESUME AT`). Execute that phase first and proceed forward in order until
  you reach where you were. A gap is a missing artifact, an unresolved `PROVISIONAL` item
  in `plan.md`, or an Open Question that blocks the step you want to run. Backfill phases
  must record already-done work honestly (e.g. plan steps marked "already implemented —
  verify in phase 4") rather than pretending the work hasn't happened.

## Running inside this repo's agent harness (optional)

When executing in Claude Code within this repo, the Meta-Orchestrator may route a phase
through the coordinator instead of running it inline. Mapping:

| Phase | Worker chain |
|---|---|
| 1 Research | `researcher` |
| 2 Planning | `researcher,architect` (architect for architecture-heavy tasks) |
| 3 Coding | `developer` |
| 4 Validation | `developer` (implement/run tests) + coordinator's built-in Validator |
| 5 Publicizing | `developer` (technical docs) |

The routing brief must name the run directory and instruct the worker to read/write the
phase's contract artifacts. Worker protocols (grounding, sandboxing, WORKER_STANDARDS.md)
apply on top of the phase instructions. Standalone mode (any other CLI) skips worker
protocols; the phase files alone are sufficient.

## Bootstrapping into another repo

1. Copy `pipeline/` and `TASTE.md` into the target repo root.
2. Add `pipeline/runs/` to its `.gitignore`.
3. Edit `TASTE.md` for that project's stack and preferences.
4. Use the Quick start prompts above in any CLI session at that repo's root.

The phase files reference nothing outside `pipeline/`, `TASTE.md`, and the run directory,
so they work in any repo unchanged.

## Verifying a run

`python scripts/check_pipeline_run.py pipeline/runs/<task_slug>` reports which contract
artifacts exist and whether the human gate is satisfied.
