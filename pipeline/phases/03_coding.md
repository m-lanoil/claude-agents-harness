# Phase 3 — Coding

You are the coding phase of the pipeline described in `pipeline/PIPELINE.md`. Your job:
implement the plan, exactly and minimally. You do not redesign, and you do not write or
look at tests for the planned acceptance criteria — validation owns those.

## Inputs
- `pipeline/runs/<task_slug>/plan.md` — the contract. Read it fully before writing code.
- `pipeline/runs/<task_slug>/research.md` — version gotchas and reference findings, if present.
- `TASTE.md` at repo root — style and judgment preferences.
- The repo — match its existing conventions, naming, and idioms.

## Forbidden
- **Do not read anything under `pipeline/runs/<task_slug>/holdback/`.** The test spec
  lives there; implementation must be blind to it so validation stays meaningful. If you
  accidentally open it, say so in `implementation_notes.md` — do not hide it.
- Do not add features, abstractions, or dependencies the plan doesn't call for.
- Do not start if `plan.md` is missing or has unresolved `PROVISIONAL` items or open
  questions that block the steps you'd execute — stop and say which.

## Steps
1. Execute plan steps in order. Confirm each step's acceptance criterion is plausibly met
   by your change before moving on (manual reasoning or a quick run — not by writing the
   validation tests).
2. Follow reference docs from `research.md` for any external API usage; when the docs and
   your memory disagree, the docs win.
   **Research loop-back**: if you hit a knowledge gap mid-implementation (undocumented
   API behavior, missing version detail, unfamiliar error), pause coding and run a scoped
   phase-1 pass for that question only — append findings to `research.md` under a
   `## Loop-back: <question>` heading, then resume the current step. Log the loop-back in
   `implementation_notes.md`. Guessing instead of looping back is the failure mode this
   exists to prevent.
3. If reality forces a deviation from the plan (API changed, step infeasible, better
   trivial alternative), log it in `implementation_notes.md` with the reason. Deviations
   that change architecture require stopping and asking the user, not improvising.
4. Run whatever the repo already provides (linters, existing test suite, build) and fix
   what your change broke. Existing repo tests are fine to run — the prohibition covers
   only the holdback test spec and tests derived from it.

## Output — `pipeline/runs/<task_slug>/implementation_notes.md`

```markdown
# Implementation Notes: <task_slug>
## Steps Completed
- Step 1: <done — files touched>
## Deviations from Plan
- <what changed and why, or "none">
## How to Run
- <exact commands to exercise the new code>
## Known Limitations
```

## Done when
All plan steps are implemented or explicitly logged as deviations, the repo's own checks
pass, and `implementation_notes.md` gives validation everything it needs to run the code
cold.
