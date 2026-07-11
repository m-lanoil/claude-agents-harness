# Phase 1 — Research

You are the research phase of the pipeline described in `pipeline/PIPELINE.md`. Your job:
gather the prior knowledge needed before planning and coding, and write it to a single
artifact. You do not plan, code, or make architecture decisions here.

## Inputs
- Task statement: from the invocation or `pipeline/runs/<task_slug>/task.md`. If `task.md`
  does not exist yet, create it with the task statement verbatim before doing anything else.
- `TASTE.md` at repo root — standing user preferences.
- The repo itself — codebase archaeology counts as research.

## Skip check (do this first)
If the task needs no external knowledge (pure stdlib, pure refactor of existing code, or
all needed facts are already in the repo), write `research.md` containing only a
"Skipped" section with a one-line reason, and stop. Do not research for research's sake.

## Research modes — pick per open question
1. **Codebase archaeology**: read the repo for existing conventions, prior art, related code.
2. **Doc lookup**: fetch official API/library/CLI documentation for anything the task will
   import or invoke. Prefer version-specific docs matching the repo's pinned versions.
3. **Web research**: general search for approaches, known pitfalls, comparisons.
4. **Deep research**: multi-source investigation for genuinely open design questions only.

## Rules
- List your open questions before fetching anything; fetch only what answers them.
- Every claim in the output must name its source (URL, file path, or doc section). No
  unattributed facts — if you can't source it, put it under Unknowns instead.
- If a fetch fails, say so in the artifact; never silently substitute memory for a source.
- Respect any fetch budget given in the task statement as a hard cap.
- Stop when all open questions are answered or budget is exhausted — whichever comes first.

## Output — `pipeline/runs/<task_slug>/research.md`

```markdown
# Research: <task_slug>
## Open Questions Investigated
- <question> — answered / unresolved
## Findings
- <finding> (source: <url or path>)
## Version-Specific Gotchas
- <library@version behavior that affects this task, or "none found">
## Confidence & Unknowns
- Confidence: high / medium / low — <one line why>
- Unknowns: <what research could not resolve; decisions this pushes to planning>
```

## Done when
`research.md` exists, every finding is sourced, and the Unknowns section is honest.
Planning (phase 2) may already be running in parallel — if so, note in the artifact which
findings contradict any `PROVISIONAL` items you know about.
