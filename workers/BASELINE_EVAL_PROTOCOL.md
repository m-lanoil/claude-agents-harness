# Baseline Eval Protocol

Used by: Meta-Orchestrator
Triggered at brief time for sampled tasks.

## Purpose
Compare the harness against a plain Claude session on the same task, so "is the harness worth it" has data. A single eval proves nothing; do not state a result for a worker from fewer than 5 of its own evals. Report results per main worker (the first worker in the chain; orchestrator-only work is its own group), never pooled; the 5-eval count for a revisit needs evals from at least 2 different main workers; that revisit assesses coverage and bias, not whether the harness wins.

## Eligible tasks
Low error cost, bounded scope (one worker, or at most 3 hops), all inputs known at brief time, not client-facing. The owner chooses at brief time. The harness run always happens as normal; the eval only adds a plain run.

## Due check
At brief time the orchestrator checks eligibility. If the task is eligible and none of the 3 most recent Track-record entries for its main worker has an Eval result other than "n/a" (a run or a decline), it asks one line: "This task is eligible for a baseline eval and one is due. Run one?" The owner answers yes or no; the orchestrator never starts an eval on its own. A decline is recorded as Eval result "declined" and defers the next offer by 3 entries for that worker.

## Procedure
1. **Brief time**: the owner says "eval" (or answers yes to the due check). The orchestrator writes the plain brief to `output/intermediate_outputs/<topic>/eval_plain_brief.md`: the brief's task paragraph, state-at-brief facts, same approved sources and same output format, with the harness-only lines removed (fetch budget, kb, sandbox, worker rules).
2. **Plain run**: the owner opens a plain Claude Code session outside the repo, built-in tools only, pastes the plain brief, and saves the output to `<topic>/eval_plain_output.md`. Note active minutes for each run.
3. **Blind**: the orchestrator copies both outputs to `eval_A.md` and `eval_B.md` in random order and keeps the mapping in `eval_mapping.md`, which the owner does not open until scoring.
4. **Score** (per run): blind preference (A, B or neither); claims fixed (unsupported claims found and corrected; for the harness run, `scripts/check_grounding.py` gives a first pass, the plain run is checked by reading); owner minutes.
5. **Record**: Track-record field "Eval result": `preferred: harness|plain|neither; claims fixed h/p; minutes h/p`; "n/a (<reason>)" when no eval ran, per `logs/TRACK_RECORD_TEMPLATE.md`, so eligible-but-not-offered tasks can be counted.

## Limits
The checker cannot verify the plain run's quotes (no saved sources). Both runs share one owner, so familiarity biases later runs. Minutes are self-reported. Eligibility (low error cost, at most 3 hops, not client-facing) excludes long research chains, so evals say nothing about them.
