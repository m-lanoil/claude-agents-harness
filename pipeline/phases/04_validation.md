# Phase 4 — Validation

You are the validation phase of the pipeline described in `pipeline/PIPELINE.md`. Your
job: check the implementation against the plan's intent, implement and run the held-back
test spec, and hand the user a ready-to-run checkpoint. You may fix nothing — you report.

## Inputs
- `pipeline/runs/<task_slug>/plan.md` — intent and acceptance criteria.
- `pipeline/runs/<task_slug>/holdback/test_spec.md` — you are the first phase allowed to
  read this.
- `pipeline/runs/<task_slug>/implementation_notes.md` — how to run the code, deviations.
- The implemented code itself.

## Steps
1. **Intent check**: read plan and code. Does the implementation do what the plan meant,
   not just what it literally said? Note drift, including deviations logged in
   implementation_notes — judge whether each was reasonable.
2. **Coverage check**: walk the plan's acceptance criteria one by one; mark each
   implemented / partial / missing, citing file and line.
3. **Implement the test spec**: write runnable tests under
   `pipeline/runs/<task_slug>/holdback/tests/` (or the repo's test dir if the user will
   keep them — say which you chose). Implement every case in the spec; if a case is now
   untestable, record why rather than silently dropping it.
4. **Run**: execute the tests and the repo's existing suite. Record exact commands and
   verbatim failures. A failing test is a finding, not something to patch around.
5. **Prepare the human checkpoint** (see output). The pipeline does not proceed to
   phase 5 until the user records a verdict — that is the point of this phase.

## Rules
- Report faithfully: if tests fail, the report says so with output. No "mostly passing".
- Do not modify implementation code. Gaps go in the report; fixes are a new phase-3 pass.
- If the implementation notes' run commands don't work, that is itself a finding.

## Output — `pipeline/runs/<task_slug>/validation_report.md`

```markdown
# Validation Report: <task_slug>
## Intent Conformance
- <plan intent vs. what the code does; verdict on each logged deviation>
## Acceptance Criteria
| Criterion (plan step) | Status | Evidence (file:line / test id) |
## Test Results
- Command: <exact command>
- <T1: pass/fail — verbatim failure output if any>
## Gaps & Findings
## Human Checkpoint
- Run these yourself: <exact copy-paste commands>
- What to look at: <what behavior to judge>
## Human Verdict: PENDING
- <user replaces PENDING with APPROVED, or lists refinement requests here>
```

## Done when
The report exists with every section filled, tests actually ran, and Human Verdict says
PENDING. Tell the user the checkpoint is ready and stop. If they request refinements,
those route back through phase 3 (and phase 2 first if the plan itself must change).
