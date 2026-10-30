# Ephemeral Task Log Protocol

## What it is
A short-lived markdown file that tracks in-progress multi-step work within a single session. It is created when a session spans multiple routed tasks, updated after each acceptance check, and, when all tasks are closed, copied to `output/intermediate_outputs/<topic>/` as a closed record before it leaves `logs/`. While active it is not a permanent record — commit history and `logs/worker_updates.md` serve that role.

## When to create one
Create an ephemeral task log when:
- A session involves 3 or more sequential tasks routed to workers
- Tasks have dependencies (output of one feeds the next)
- Open items or owner decisions need to be surfaced across task boundaries

Do not create one for single-task sessions or ad hoc questions.

## Location
`logs/active_task_log_<topic>.md` (lowercase snake_case topic, e.g. `active_task_log_edge_mcp_eval.md`) — one file per topic. Use `logs/active_task_log.md` only when a session has a single unnamed log.

**Parallel logs**: when the owner has an unclosed task in one log and asks for a separate log, create a new `logs/active_task_log_<topic>.md` instead. Never overwrite or edit another task's log. Each log is closed and archived independently, and the `logs/*` ignore rule already covers the new names.

## Structure
Copy `logs/TASK_LOG_TEMPLATE.md` to start a new log. The structure below is the canonical definition.

```markdown
# Active Task Log — [Session Name]

| | |
|---|---|
| **Project** | [path] |
| **Session goal** | [one line] |
| **Started** | YYYY-MM-DD |
| **Close when** | All tasks closed |

---

## Closed

### Task N — [Name]
- **Worker**: [Developer / Architect / Content]
- **Deliverables**: [file paths]
- **Owner items outstanding**: [numbered list, or "None"]
- **Self-critique gaps**: [gaps flagged by worker that need confirmation — or "None"]
- **Worker assumptions**: [assumptions made that need verification — or "None"]

---

## Up Next

### Task N — [Name]
- **Worker**: [worker]
- **Deliverable**: [expected output path and format]

---

## Remaining

N+1. [Task name]
N+2. [Task name]
...
```

## Rules

- **Create** the log at the start of the session, before routing the first task.
- **Update** after every acceptance check: move the completed task to Closed, promote the next task to Up Next.
- **Surface owner items** in the Closed section — do not let them disappear into conversation history.
- **Log self-critique gaps and worker assumptions** verbatim from the worker's self-critique output. These must be explicitly confirmed addressed before a task can be considered fully signed off, not just accepted.
- **Never add narrative** — status, deliverables, and outstanding items only.
- **Close** the log when all tasks reach Closed and no owner items are blocking. Never delete it outright: copy it to `output/intermediate_outputs/<topic>/closed_task_log_<short-name>.md` (reuse the topic folder of the work it tracked) with a short **Outcome** note appended (close date, final state, items still open or parked and where they are now tracked). Only remove `logs/active_task_log_*.md` after that copy exists. Confirm with the user. Do not archive a log while owner items are still outstanding unless the owner chooses to.
- **Do not commit** the active log — it is ephemeral by design. Add `logs/active_task_log*.md` to `.gitignore` if not already present.
