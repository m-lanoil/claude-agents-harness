# Routing Prompt Protocol

A routing prompt carries **only what the worker cannot already know**. The worker's `CLAUDE.md`, `WORKER_STANDARDS.md` and the coordinator's auto-injected block (identity, checklist invocation, self-critique instruction, JSON return block) are the source of truth for standing behaviour. A brief never restates them.

## Include (task-specific delta)
- **Task and context**: what to produce, why, relevant paths, constraints unique to this task.
- **State at brief time**: dated facts the worker cannot derive (kb staleness, what exists or does not, prior-hop outcomes and the path to read; each hop after the first must be told to read the prior hop's output).
- **Inputs**: approved URLs mapped to target files, with scope per source. Mark snippet-derived or otherwise unverified claims as unverified.
- **Fetch budget**: *"Suggested fetch budget: N sources."* Hard cap on distinct URLs; `char_offset` pagination is free. Never word a cap as "one fetch per URL".
- **Scope fence**: what the worker must *not* do in this task (e.g. no `server.py`, no registration, no live API calls).
- **One-off authorizations**: exceptions to a standing rule. Name the rule, the path, and "this task only".
- **Provenance and history**: how sources were found, past failures (e.g. a host that returned 403).
- **Output**: path and required section names. In coordinator mode, section names are entered as inputs and not repeated in the body.
- **Approved URLs (coordinator)**: non-registered URLs go in `--approved-urls` as `'{"libraries": {...}, "clis": {...}, "other": {...}}'` (any key may be omitted); the coordinator pre-registers them.

## Exclude (already enforced elsewhere)
Worker identity; "read standards / CLAUDE.md first"; checklist invocation; failure-mode and stop-and-ask language; the Handoff Rule; kb file format and naming; sandbox and security baselines; grounding workflow steps; anything the coordinator injects.

## Reference, don't restate
If a standing rule is needed for context, cite it in one line (e.g. *"per Developer Grounding Protocol step 0"*). If the brief overrides it, say so as a one-off authorization.

## Pre-send diff test
For each sentence ask: would the worker behave differently without it? If not, cut it. If the same sentence appears in two or more routing prompts, it is a worker gap: fix it in the worker's `CLAUDE.md` or `WORKER_STANDARDS.md` via the Worker Gap Protocol instead of repeating it.

## Size
A typical brief is a short task paragraph plus tables. Long prose sections signal restated rules.

## Existing hop files
Routing prompts already stored under `output/intermediate_outputs/` are historical records; do not rewrite them.
