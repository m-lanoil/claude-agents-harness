# Bug Fix Protocol

Used by: Developer Worker
Triggered when: a task is a bug fix (incorrect behavior, broken output, unexpected error).

## Required Steps (in order — do not skip)

1. **Reproduce**: Before touching any code, confirm you can reproduce the bug. State:
   - Exact input or trigger condition
   - Expected behavior
   - Actual behavior

   If you cannot reproduce it, stop and ask the user for reproduction steps before proceeding.

2. **Isolate**: Identify the specific line, function, or module causing the issue.
   State your finding to the user before proposing any fix. Do not propose a fix until the root cause is named.

3. **Propose**: Describe the intended fix and include:
   - What will change
   - Blast radius: what else could be affected

   Wait for explicit user approval before applying.

4. **Apply**: Make the change. Fix the root cause only — no surrounding refactor or cleanup.

5. **Verify**: Confirm the fix addresses the root cause. State which behavior changed and confirm adjacent behavior is unaffected. If verification requires running code, provide the command and wait.

6. **Summarize**: One sentence — what was wrong and what changed.

## Rules
- No fix may be applied before step 2 (Isolate) is complete and stated to the user.
- Do not refactor surrounding code as part of a bug fix — that is a separate task.
- If the root cause is in a different worker's domain (e.g. an architecture flaw), complete steps 1–2 only, then hand off per the Handoff Rule in WORKER_STANDARDS.md.
