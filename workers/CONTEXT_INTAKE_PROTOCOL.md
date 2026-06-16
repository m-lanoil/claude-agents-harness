# Context Intake Protocol

Used by: all workers
Triggered when: the user provides additional context, clarification, or new constraints after a task has started.

## Required Steps

1. **Acknowledge**: Quote or paraphrase the new context in one sentence so it is on record.

2. **Re-evaluate**: Compare the new context against your current plan. Ask: does this change what I'm doing, what I'm producing, or how I'm producing it?

3. **Surface impact**: State one of:
   - *"This does not change the plan — continuing."*
   - *"This changes [specific part of the plan]. Here is what I will do differently: [description]."*
   - *"This context conflicts with the original brief. Clarification needed: [question]."*

4. **Get approval if plan changes**: If the plan changes, wait for explicit user approval before continuing. Do not silently absorb new context and proceed.

5. **If work must be redone**: State which steps need to be repeated and redo them cleanly. Do not paper over earlier work.

## Rules
- Never silently continue after receiving new context — acknowledgement is mandatory.
- If the new context reveals the task belongs to a different worker, do not continue — flag it per the Handoff Rule in WORKER_STANDARDS.md.
- Context that arrives after a deliverable is complete is a new task, not a revision — return to the Meta-Orchestrator.
