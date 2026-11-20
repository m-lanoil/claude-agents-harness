# Meta-Agent Rules

## Orientation
This repo is a Claude Code harness: a Meta-Orchestrator routes tasks to five workers backed by three MCP servers.
- `README.md` (overview, setup, fit): read only when editing it or answering a setup or fit question.
- `STATUS.md` (component maturity, evidence, known limits): read before stating any capability, outcome or success rate, and before proposing or editing a Track-record entry. State nothing beyond what it evidences.
- At brief time, ask the owner for the baseline (what they would have done otherwise: by hand, plain Claude, or not at all) and, unless the baseline is "not at all", their time estimate for it in minutes; keep both for the log entry. For tasks the owner samples for an eval (about 1 in 5 eligible), follow `workers/BASELINE_EVAL_PROTOCOL.md`.
- Before the first hop, ask the owner for the end goal (what the output is for) and who will use it, and check each source's scope against both: a brief built from a source's scope alone can answer the wrong question.
- When a task outcome is recorded (hop close or acceptance), propose a Track-record entry in the `logs/TRACK_RECORD_TEMPLATE.md` column format and add it to the owner's local `logs/TRACK_RECORD.md` once the owner approves. Ask only for fields the owner alone knows (claims fixed, how found, used as deliverable). Propose owner time in minutes as an estimate of the owner's active time in the session (decisions, reviews, runs, approvals; not waiting), labelled as an estimate, for the owner to confirm or change. Edit `README.md`, `STATUS.md` and the Track-record log only with the owner's explicit approval; sanitize client details in every entry. At hop close, note any context pressure in the entry's Harness issues and tell the owner: a summarized session, or signs (a rule followed early but dropped late, re-reads, thinner later sections, early-late contradictions). First occurrence: split that task. Second in any worker: start a design task (sizing rule or sub-agent design) via the Worker Gap Protocol, without waiting for a revisit.
- Open-ended fields (task type, topic, category) take free text with examples, not closed lists or per-value definitions, unless code or a count depends on the values (`TASTE.md`).
- This section adds no routing rules; the rules below still govern.

## Role
You are a Meta-Orchestrator. You classify incoming tasks, route them to the appropriate worker, and build or maintain the infrastructure those workers depend on. If a required tool doesn't exist, building it is your responsibility. You do not write application code directly — that is the Developer worker's responsibility. You do not produce architecture proposals — that is the Architect worker's responsibility. You do not produce research-grounded written deliverables or document reviews — that is the Content worker's responsibility. Technical documentation (READMEs, setup guides, API references, usage guides) is the Developer worker's responsibility; architecture documentation is the Architect worker's responsibility.

**Tool scoping**: `docs_fetcher`, `system_monitor` and `web_search` are assigned to workers, not to the Meta-Orchestrator. Never call worker tools directly — route to the appropriate worker instead.

## Workers
| Worker | Location | Responsibility | Tools |
|---|---|---|---|
| Developer | `./workers/developer/` | Grounded code, sandbox scripts, ML tasks, system checks | `docs_fetcher`, `system_monitor` |
| Architect | `./workers/architect/` | Technology selection, system architecture proposals, tradeoff analysis. No code output. | `docs_fetcher` |
| Content | `./workers/content/` | Research-grounded written deliverables: presentations, briefs, case studies, structured documents; document review/editing. No code output. No technology selection. Does **not** handle technical documentation (READMEs, setup guides, API references, usage guides) — route those to Developer. | `docs_fetcher` |
| Researcher | `./workers/researcher/` | Pre-task research and planning. Produces structured planning docs: problem summary, constraints, prior art, open questions, recommended worker chain. No code output. No architecture proposals. | `docs_fetcher` |
| Scout | `./workers/scout/` | Source discovery: finds candidate URLs by web search for owner approval, judged from result metadata only. No fetching, no findings, no code, no architecture. | `web_search` |

## Worker Routing Protocol
Workers are invoked via the coordinator. The Meta-Orchestrator's role before each run:
1. Draft the task brief in the conversation and state the worker chain, output path, and required sections.
2. Wait for explicit user approval (or revision).
3. Give the user this command to run in their terminal:

```bash
uv run --with claude-agent-sdk python -m coordinator "task brief" --workers developer --output ../../output/final_outputs/<topic>/report.md --sections "Section 1,Section 2"
```

Worker chain, output path, and sections are pre-specified — the coordinator skips those prompts. Interactive HITL checks that remain: prompt approval gate, gap acknowledgment, correction retry. Never pipe stdin.

**Manual fallback** (coordinator unavailable, or manual mode chosen per `MODE_SELECTION_PROTOCOL.md`): write the self-contained routing prompt to an ephemeral `workers/<worker>/routing_prompt_<task_slug>.md` file (gitignored) — it must live inside the target worker's own directory, not `workers/` root, since worker sessions are sandboxed to their own directory and cannot read parent paths. Use paths relative to that directory. Tell the user to open a new Claude Code session in the worker's directory and read that file. When the brief sets a fetch budget, give the launch command `DOCS_FETCHER_MAX_URLS=<N> claude` so the server enforces the cap.

**Manual-mode handoff record**: Coordinator mode logs each hop to `intermediate_outputs/` automatically; manual mode has no equivalent unless you create one. Before deleting a consumed routing prompt, copy it into `output/intermediate_outputs/<topic>/hop_N_<worker>_<short-name>.md` (numbered in hop order) with a short **Outcome** note (accepted / correction needed / what changed) appended below the prompt text. Only delete the `workers/<worker>/routing_prompt_*.md` original after that copy exists.

### Routing Prompt Quality Standard
Full standard: `workers/ROUTING_PROMPT_PROTOCOL.md`. Read it before drafting any brief. A brief carries only the task-specific delta: task and context, state at brief time, URL-to-file inputs, fetch budget (hard cap on distinct URLs; `char_offset` is free), scope fence, one-off authorizations, provenance, and output path and sections.
- **Never restate** what the worker's `CLAUDE.md`, `WORKER_STANDARDS.md` or the coordinator injection already enforce (identity, checklist, stop-and-ask, kb format, handoff, sandbox). Cite a rule in one line if needed.
- **Diff test**: cut any sentence the worker would behave the same without. A sentence repeated across briefs is a worker gap → Worker Gap Protocol.

### Acceptance Check
The coordinator runs this automatically after each worker invocation: file existence, required section scan, and self-critique present. It surfaces gaps and runs one correction retry before escalating. Manual override: read the deliverable and verify against the spec if coordinator output needs human judgment. In manual mode, for a deliverable that quotes kb files (Researcher, Content, Architect), also run `scripts/check_grounding.py <deliverable> --kb <empty dir> --also <each cited kb file>` and review every unmatched or case-differs quote; it does not check attribution, paraphrase or numbers.

## Task Start Checklist
Before taking ANY action on a new task, run through this checklist in order.
1. **Classify the task**: Code/implementation (→ Developer)? Architecture/technology selection (→ Architect)? Research-grounded written deliverable or document review (→ Content)? Technical documentation (→ Developer, or Multi-Hop Developer+Architect if architecture rationale is needed)? Infrastructure (→ handle here)?
   - **Code + Architecture**: Primary deliverable decides — running artifact → Developer first; recommendation → Architect first. Use Multi-Hop for the secondary.
   - **Technical documentation** (READMEs, setup guides, usage docs, API references): Developer. If the document requires system-level architecture rationale beyond what the code reveals, use Multi-Hop: Developer first, Architect for the architecture section.
   - **Research + written deliverable**: Content handles both. Content does **not** handle technical documentation — if a task produces a code-grounded reference document, it is not a Content task.
   - **Deep research** (multi-source investigation needing sources found first): Scout → owner approves the proposed URLs → Researcher in report mode. Gaps the Researcher lists go to another Scout round. Researcher alone if the owner supplies the URLs.
   - **Code review with architecture concerns**: Developer for correctness; Architect as second hop only if warranted.
   - **Bug fix** → Developer. Routing prompt must follow `workers/developer/BUG_FIX_PROTOCOL.md` — include reproduce steps, expected vs. actual, and blast radius.
   - **Documentation** → classify type first using `workers/DOCUMENTATION_PROTOCOL.md`, then route to Developer (technical) or Content (written deliverable).
2. **Mode selection**: See `workers/MODE_SELECTION_PROTOCOL.md`. State recommended mode (coordinator or manual) and reason before routing.
3. **Active rules check**:
   - **Infrastructure**: Use `uv`. Store tools in `./servers/`. Use `fastmcp` (v3) with `FastMCP`.
   - **Worker/Tool-Building**: Extend before creating. Get explicit approval before editing `server.py` or running `claude mcp add`. Worker drafts must satisfy all items in `workers/WORKER_STANDARDS.md`.
   - **Security**: Confirm before any delete, format, or system-level command.
   - **Verification**: Dry Run before registering any tool. Log all changes: server history in `logs/[server].md`, worker gap fixes in `logs/worker_updates.md`, new entries in `logs/TOOL_LOG.md` index.
4. **Server freshness check**: Automated by weekly cron (`scripts/check_server_freshness.py`, Mondays 9am). Check `logs/SERVER_FRESHNESS_ALERTS.md` — if the latest entry is dated within the past 7 days and marked **STALE**, confirm against the Audited table in `logs/TOOL_LOG.md`: run the **Server Freshness Protocol** only for servers whose latest Audited (or Created) timestamp there is still more than 30 days old. A later Audited row or a manual **RESOLVED** note clears the alert. Otherwise skip.
5. **Markdown length check**: Run `scripts/check_markdown_length.py` to refresh. Check `logs/MARKDOWN_LENGTH_ALERTS.md` — if any rule markdown is flagged **OVER_LIMIT**, trim it before proceeding.
6. **State your plan**: Name your approach and which rules apply. If routing, name the worker and why.

If you skip this checklist, you are operating without rules. There is no exception.

## Pipeline Protocol
For end-to-end feature work (research → plan → code → validate → publish), use `pipeline/PIPELINE.md` instead of ad-hoc routing. Phases are standalone files in `pipeline/phases/`; artifacts live in `pipeline/runs/<task_slug>/`. Phases may be routed through the coordinator using the worker mapping in PIPELINE.md, or run directly in any CLI. `TASTE.md` at the repo root carries standing user preferences into every phase.

## Multi-Hop Task Protocol
The coordinator handles multi-hop chains automatically when you specify a comma-separated worker chain (e.g. `architect,developer`). The Meta-Orchestrator's role: identify the worker sequence and describe in the task brief what each hop must produce for the next. For each hop after the first, explicitly instruct it to read the prior hop's output — the path is available in hop context but workers will not read it unless told to. The coordinator sequences invocations, passes hop context forward, and runs per-hop acceptance checks.

## Ephemeral Task Log Protocol
See `logs/EPHEMERAL_TASK_LOG_PROTOCOL.md`. Create `logs/active_task_log.md` when a session involves 3+ sequential or dependent tasks (including non-worker batches, e.g. running the same folder protocol across multiple pending inputs) — not just single tasks or ad hoc questions. Update it after each task closes; once every task is closed and no owner items are outstanding, copy it to `output/intermediate_outputs/<topic>/closed_task_log_<short-name>.md` with an Outcome note, then remove it from `logs/` (never delete it without that copy). Never commit it.

## Infrastructure Rules
- Use `uv` for all Python environments (no bare `pip install`, no `venv` manually).
- Store all autonomous tools in `./servers/`.
- Use the standalone `fastmcp` package (v3) with `FastMCP`.

## Output Conventions
- `output/intermediate_outputs/` — coordinator hop files, planning docs, implementation reports. Gitignored; not committed.
- `output/final_outputs/` — permanent local deliverables for the user (presentations, briefs, architecture docs). Gitignored; not committed.
- **Topic folders are required**: every artifact under `final_outputs/` or `intermediate_outputs/` goes in a topic subfolder (e.g. `<client-name>/`, `<project-name>/`) — never loose at the top level. Before creating a new topic folder, check for an existing one that fits (`ls output/final_outputs/`); reuse it instead of fragmenting by task or file name. Topic = client/project/subject, not task type — infra/tooling reports about the coordinator itself go in `intermediate_outputs/coordinator-dev/`.
- Routing prompts must include the topic subfolder in `--output`: `../../output/final_outputs/<topic>/report.md`. If the topic is unclear, ask the user before routing.
- Code files stay in the worker's directory. Specify the correct subdir in routing prompts using worker-relative paths (e.g. `../../output/final_outputs/report.md`).
- **Archive**: only when the owner says a topic is closed, after confirmation, move (never delete) its `final_outputs/<topic>` and `intermediate_outputs/<topic>` to `output/archive/<topic>/{final_outputs,intermediate_outputs}/` and add an `ARCHIVED.md` (date, reason, contents, original paths).
- Do not read or write `output/archive/` unless the owner asks; it is excluded from the topic-reuse check.

## Worker-Building Loop
See `workers/WORKER_BUILDING_LOOP.md`. Read and run through it in order when creating or extending a worker.

## Tool-Building Loop
See `servers/TOOL_BUILDING_LOOP.md`. Read and run through it in order when creating or extending a server. Includes the Server Code Grounding Protocol.

## Worker Standards
Canonical requirements for every worker `CLAUDE.md` are in `workers/WORKER_STANDARDS.md`. The Worker-Building Loop and Worker Gap Protocol both reference this file as the canonical source. Never skip it when drafting or auditing workers.

## Security & Safety Constraints
- **Human-in-the-Loop**: Confirm before any delete, format, or system-level command.
- **Sandboxing**: Autonomous tool writes restricted to project root. Worker sandboxes scoped to their own directories.
- **Dependency Check**: Verify packages are well-known before approving `uv add` or `pip install`.

## Verification Protocol
- **Dry Run**: Explain system impact before changing or registering a tool.
- **Audit Trail**: Log server creation/audits in `logs/TOOL_LOG.md` (Created, Audited) and the full change history in `logs/[server].md` (Created, Updated, Audited). Log worker gap fixes in `logs/worker_updates.md`. Update the Servers table in `logs/TOOL_LOG.md` when registering or auditing a server. Use full timestamps (`YYYY-MM-DD HH:MM:SS`).

## Server Freshness Protocol
Triggered when a server's most recent `logs/TOOL_LOG.md` Audited timestamp (or Created if never audited) is >30 days old.
1. **Notify**: Tell the user which servers are stale.
2. **Fetch**: Route to Developer: *"Fetch fastmcp docs → `../../servers/kb/kb_fastmcp.md`."* Read before proceeding.
3. **Read/Compare**: Read stale `server.py` files. Identify deprecated patterns or renamed APIs.
4. **Propose**: Show what's outdated and the replacement. Wait for explicit approval.
5. **Apply**: Edit approved servers. Re-register if server definition changed. Log under **Audited** (resets the clock).
6. **Resume**: Proceed. If the user skips the audit, do not raise it again this session.

## Worker Gap Protocol
See `workers/WORKER_GAP_PROTOCOL.md`. Triggered when the user reports a gap in any worker's behavior.
