# Operator guide

> Moved from the repo [`README.md`](../README.md). Links point from `docs/`; paths in backticks are relative to the repo root, as in the original text.

## Who it's for

**Human operator.** You describe tasks, approve each task brief, and in manual mode open the worker session yourself. At each brief you also give a baseline, a time estimate, the end goal and who will use the output; some tasks are sampled for a baseline eval; and you approve each Track-record entry. You also review deliverables and each worker's self-critique (`CLAUDE.md` Worker Routing Protocol, `workers/MODE_SELECTION_PROTOCOL.md`).

**Agent.** The Meta-Orchestrator follows the Task Start Checklist in `CLAUDE.md`. A worker follows `workers/WORKER_STANDARDS.md` plus its own `workers/<name>/CLAUDE.md`. The Meta-Orchestrator does not write application code and does not call worker tools. Workers do not write routing prompts for other workers (`CLAUDE.md`, `workers/WORKER_STANDARDS.md` Handoff Rule).

## Fit for purpose

This section is derived from the rules in the tracked files. It is not a claim about observed results (see Evidence and track record). Grounding and staleness limits are instructions to the model; write paths and worker Bash are partly enforced by settings (`STATUS.md`).

### Good fit
- Work where claims must trace to sources. Developer, Architect, Content and Researcher all require deliverables to trace to fetched kb files, and failed fetches must be reported (`workers/WORKER_STANDARDS.md`, `workers/*/CLAUDE.md`).
- Work you want gated by a human. Briefs need explicit approval; destructive or system-level commands need confirmation (`CLAUDE.md`). The pipeline is designed to refuse publishing until `Human Verdict: APPROVED`, but it has not been run (`pipeline/PIPELINE.md`).
- Multi-step features that benefit from file-based phase handoffs and a held-back test spec. This is the pipeline's design; it is unused so far (`pipeline/PIPELINE.md`).
- A reusable rule set you can copy into another repo: the pipeline and `TASTE.md` are described as portable, though the pipeline has not been exercised (`pipeline/PIPELINE.md`, Bootstrapping).

### Not a good fit
- Quick one-off edits. Every task starts with a six-step checklist, and code needs a kb file per import and shell command (<=30 days old) before any code is written (`CLAUDE.md`, `workers/developer/CLAUDE.md`). That is the process-overhead cost.
- Fully unattended runs. Prompt approval, gap acknowledgment and correction-retry gates always pause for a human (`coordinator/README.md`), and the coordinator has run live only on four single-hop tasks (three internal Developer runs, one Scout run) (`STATUS.md`).
- Work that needs unregistered URLs on the fly. Workers may fetch only registered or briefed URLs and must flag others (`workers/WORKER_STANDARDS.md`).
- Anyone who needs results on day one. Only a small owner-reported log exists (see `STATUS.md`).

## How it works

The flow diagram and worker table are in the [`README`](../README.md#how-it-works).

**Tools.** `docs_fetcher` has 11 tools (list/add for libraries, CLIs and other sources; `fetch_docs`, `fetch_url`, `search_docs`, `crawl_docs`, `get_fetch_stats`). `system_monitor` has 5 (CPU, memory, disk, directory size, large-file scan). `web_search` has 1 (read-only web search) (`servers/*/server.py`).

**Manual vs coordinator mode.** Manual: the Meta-Orchestrator writes a self-contained routing prompt to `workers/<worker>/routing_prompt_<slug>.md` (gitignored), and you open a Claude Code session in that worker directory and have it read the file. Before the prompt is deleted, a copy goes to `output/intermediate_outputs/<topic>/hop_N_<worker>_<name>.md` with an outcome note (`CLAUDE.md`). Coordinator: `python -m coordinator` runs the chain through the Claude Agent SDK, with automated acceptance checks (file exists, required sections present, self-critique present) and an internal read-only Validator (`coordinator/README.md`, `coordinator/acceptance.py`, `coordinator/worker_registry.py`). Manual is the default; the owner chooses the coordinator per task. A standing override that disabled coordinator selection ran from 2026-09-28 and was lifted on 2026-11-09 (`workers/MODE_SELECTION_PROTOCOL.md`).

**Pipeline.** Built but not currently used: no runs exist, and it is kept for future buildouts. For end-to-end feature work, `pipeline/PIPELINE.md` defines five phases (research, planning, coding, validation, publicizing) as standalone files in `pipeline/phases/`. Phases communicate only through artifacts in `pipeline/runs/<task_slug>/`. The test spec is written in planning and withheld from coding, and publicizing is blocked until a human verdict of APPROVED. See [`pipeline/PIPELINE.md`](../pipeline/PIPELINE.md).

## Getting started

Setup is derived only from the templates, `servers/*/pyproject.toml` and `CLAUDE.md`. Steps marked (unverified) are inferences from file names or `.gitignore`, not stated instructions.

1. Prerequisites: `uv` on PATH; an authenticated `claude` CLI (`coordinator/README.md`, `CLAUDE.md` Infrastructure Rules). Python >=3.11 for the servers (`servers/*/pyproject.toml`).
2. Copy `.mcp.template.json` to `.mcp.json` and replace `<YOUR_PROJECT_ROOT>` with the absolute repo path. It registers `system_monitor` and `docs_fetcher` over stdio via `uv`. (Filename observed on the maintainer's machine, not on a fresh clone.)
3. Copy `.claude/settings.template.json` to `.claude/settings.json` (SessionStart health-check and CLAUDE.md-reminder hooks; replace the same placeholder) and `.claude/settings.local.template.json` to `.claude/settings.local.json` (enables both servers). (Filenames observed on the maintainer's machine, not on a fresh clone.)
4. Copy the three `servers/docs_fetcher/*.template.json` files to `libraries.json`, `clis.json`, `other_sources.json` and fill them with the documentation URLs workers may fetch. `WORKER_STANDARDS.md` says these files are gitignored and may be absent, and says to create one as `{}` if missing.
5. Optional runtime logs: the `logs/*TEMPLATE*` files are blank examples of the gitignored logs. To keep your own Track-record log, copy `logs/TRACK_RECORD_TEMPLATE.md` to `logs/TRACK_RECORD.md`. (Whether to copy them is unverified; the scripts create their own alert files.)
6. Whether `uv` installs server dependencies automatically on first run, or needs a separate sync, is not stated in tracked files (unverified). `uv.lock` files are present for both servers.
7. Per worker: copy `workers/<worker>/.claude/settings.local.template.json` to `settings.local.json` in the same folder for architect, content, developer, researcher and scout, and replace `<YOUR_PROJECT_ROOT>` with the absolute repo path (the `Read(/<YOUR_PROJECT_ROOT>/**)` entries then start with `//`). Each template enables only the servers that worker is assigned in `CLAUDE.md`. The templates also set `claudeMdExcludes` (the root `CLAUDE.md`) and `autoMemoryEnabled: false`, so a worker session does not inherit the Meta-Orchestrator rules or the owner's auto-memory; this is checked by offline contract tests, not live (`STATUS.md`). (Filenames observed on the maintainer's machine, not on a fresh clone.) The templates carry write-path deny rules for protected repo paths and sandboxed Bash for the four workers that have Bash (verified live 2026-11-07; limits in `STATUS.md`). `uv run` and network access from worker Bash are blocked unless a task adds them. When a brief sets a fetch budget, launch the worker with `DOCS_FETCHER_MAX_URLS=<N> claude` (`CLAUDE.md`).
   Scout only (optional): copy `workers/scout/.mcp.template.json` to `workers/scout/.mcp.json`, replace `<YOUR_PROJECT_ROOT>`, and export `BRAVE_SEARCH_API_KEY`. The root `.mcp.template.json` intentionally has no `web_search`. (Scout ran live on 2026-10-22 and 2026-11-13. Export the key where an interactive shell reads it: a login-only export failed the first run.)
8. Start Claude Code at the repo root. The KB staleness and server freshness checks run weekly (Mondays 9am) from local launchd agents on the maintainer's machine; the plists are not tracked, so on a new machine schedule them yourself or run the scripts by hand. The markdown-length check has no agent and is run by hand. The SessionStart hooks come from `.claude/settings.json` (step 3).

## Current state

Components and what each is (details and maturity signals in [`STATUS.md`](../STATUS.md)):
- Meta-Orchestrator rules and protocols: `CLAUDE.md`, `workers/*_PROTOCOL.md`, `workers/WORKER_STANDARDS.md`, `logs/EPHEMERAL_TASK_LOG_PROTOCOL.md`, `servers/TOOL_BUILDING_LOOP.md`.
- Five workers: `workers/{developer,architect,content,researcher,scout}/CLAUDE.md`.
- Three MCP servers with lockfiles: `servers/docs_fetcher/`, `servers/system_monitor/`, `servers/web_search/` (plus two SessionStart hook scripts).
- Research report format: `workers/RESEARCH_REPORT_PROTOCOL.md`.
- Coordinator program (five modules, used only when the owner chooses it per task): `coordinator/`.
- Pipeline (five phase files and a run-contract checker; unused, kept for future buildouts): `pipeline/`, `scripts/check_pipeline_run.py`.
- Maintenance scripts: KB staleness, server freshness, markdown length (<=100 non-empty lines for rule files), pipeline run check, grounding quote checker, import-versus-kb checker (all six have tests), plus the test runner `scripts/run_tests.py`: `scripts/`.
- Tests: offline pytest suites for the three servers (`servers/*/tests/`, including the `system_monitor` hooks), the maintenance scripts (`scripts/tests/`), config templates (`tests/`) and the coordinator (`coordinator/tests/`, stubbed `query` plus offline SDK contract tests; the live runs and the opt-in live SDK smoke test are not part of the default suite). Run all of them with `uv run python scripts/run_tests.py` (929 passed, 3 skipped on 2026-11-20); `.github/workflows/tests.yml` runs the same command on push and pull request, and `.github/PULL_REQUEST_TEMPLATE.md` lists what a PR must report.
- Baseline eval protocol: `workers/BASELINE_EVAL_PROTOCOL.md`.
- `TASTE.md`: standing preferences read by pipeline phases.

## Evidence and track record

What the tracked repo can show: the build-out timeline in `git log`, 151 commits from 2026-03-30 (e4f93d5) to 2026-11-20 (5b5d3fe), a snapshot at that commit (`git rev-list --count 5b5d3fe` reproduces it); later commits, including the refresh that wrote this line, are not counted. Hashes are those on `main` today; the older ones changed in a history rewrite (inferred: the earlier hashes no longer exist on `main`, and each has a commit with the same subject).
- 2026-03-30 to 2026-04-06: initial structure with the `docs_fetcher` server, then `system_monitor` and the CLI/other-sources registries (1ba3a97, 5720b58, 682b4cd, per commit messages).
- 2026-05-11 to 2026-05-15: worker standards extracted into a shared file (98a0582), a template-only branch initialized (b08f2c7), and runtime logs untracked (fc2f818, 705660d), all per commit messages.
- 2026-06-16 to 2026-06-29: bug-fix, documentation and context-intake protocols (df8a044); Agent SDK coordinator and two-mode architecture (10d7405, ec16c6c), per commit messages.
- 2026-07-08 to 2026-07-23: five-phase pipeline, taste config and run checker (f203d78, e1d54b4, cb9688b), per commit messages.
- 2026-08-28 to 2026-09-28: ephemeral task log (d362cfb), human-retrieved-sources protocol (b25fa5b), coordinator mode disabled and manual-mode handoff archiving required (bb55a71), `docs_fetcher` fixes (14cf8d6), per commit messages.
- 2026-10-06 to 2026-10-14: README and STATUS added (5a1f97e), read-only annotations on MCP tools (120c6fe), track-record fields and owner-triggered archive protocol (734f345, b832daa), per commit messages.
- 2026-10-22 to 2026-11-07: scout and `web_search` (b93706e), routing prompt standard (6ff189f), per-worker settings templates (0a94a9c), `logs/` reorganized (4b936d7), then `docs_fetcher` tests (927480d), `check_grounding.py` (329cac9), baseline eval protocol (42e4d64), `check_imports.py` (b67de1b), fetch-cap gate (e171612), write-path deny rules (4b588b2), Markdown fix (dbf9ebc), sandboxed Bash (1324b1e), per commit messages.
- 2026-11-09 to 2026-11-15: coordinator override lifted (70e16c2) and a failed-fetch path added (4cfdf19); tracked tests for the coordinator, hooks, servers, scripts and templates with a runner and CI workflow (46191c3, 9baacf8); bug fixes found by those tests (6b26b0a, 7c5d3f4, 962b5f8); offline SDK contract tests and the fixes they drove (af4d4b7, 1d3eaae, 8e0b975, daca593); a pull request template (b1d9d2f); root `CLAUDE.md` and auto-memory excluded from worker sessions (67adc98), per commit messages.
- 2026-11-16 to 2026-11-20: the 20-entry Track-record revisit's rule fixes (b97a361), eval due check stratified by main worker (f2410f9) and an "n/a" eval reason with a 5-eval threshold (3437e38), and a per-hop coordinator brief record (da55eb3), per commit messages; the two live SDK smoke tests were run once by the owner (2 passed).

What it cannot show: early history held a full working-state archive, later reset to a template-only branch (b08f2c7); the published history omits that archive, and the current tracked tree contains no outputs, logs, kb files or run artifacts. The owner keeps a local, gitignored Track-record log (30 owner-reported, sanitized entries as of 2026-11-20; the tracked tree holds only `logs/TRACK_RECORD_TEMPLATE.md`), so the entries cannot be re-checked from the repo. Success rates and cost per task are not evidenced; owner time is recorded only from 2026-11-07. Nothing here should be read as a claim that the harness works well on real tasks; see "Not yet evidenced" in [`STATUS.md`](../STATUS.md).

## Design rationale


### Why an orchestrator with specialized workers

The root `CLAUDE.md` gives the main session one job: classify, route and build infrastructure. It does not write application code, architecture proposals or research deliverables (`CLAUDE.md`, Role). Each worker has one mandate and a short rule file: Developer for code and technical docs, Architect for technology selection with no code, Content for written deliverables, Researcher for pre-task planning and research reports, Scout for source discovery (`workers/*/CLAUDE.md`). The routing rules also fix who owns ambiguous work, for example technical docs go to Developer and Content must refuse them (`CLAUDE.md` Task Start Checklist; `workers/content/CLAUDE.md`; a007b35).

What the split buys:
- **Narrow tool surface.** Only Developer gets `system_monitor`; only Scout gets `web_search`; the other three get `docs_fetcher` only (`CLAUDE.md` Workers table; `coordinator/worker_registry.py`, `_WORKER_MCP_NAMES`). The building loop says to "err toward fewer tools" (`workers/WORKER_BUILDING_LOOP.md`, step 3).
- **Scoped writes (instruction plus settings).** Each worker is instructed to write only to its own `kb/`, `human-retrieved-sources/` and `../../output/`; Developer also has `sandbox/` (`workers/WORKER_STANDARDS.md` item 5). Settings templates also deny writes to protected repo paths (`STATUS.md`). The coordinator runs each worker with its own directory as `cwd` so that worker's `CLAUDE.md` loads, and passes inline settings that exclude the root `CLAUDE.md` and auto-memory (`coordinator/README.md`, CLAUDE.md loading; `coordinator/worker_registry.py`, 67adc98).
- **One place for shared rules.** Common rules live in `workers/WORKER_STANDARDS.md`; worker files hold only mandate-specific content. Commit 98a0582 describes this refactor, and `workers/WORKER_GAP_PROTOCOL.md` routes fixes to the shared file first.
- **No cross-worker prompt writing.** Workers state the next hand-off and stop; only the orchestrator drafts routing prompts (`workers/WORKER_STANDARDS.md`, Handoff Rule). Inferred from that rule: this keeps classification and the audit trail in one place.

Scoping is mostly a rule, with exceptions. Each worker's settings template denies writes to protected repo paths and enables sandboxed Bash for the four workers that have Bash, verified live 2026-11-07. The built-in file tools, MCP tools and hooks are outside the sandbox. The coordinator gives workers `Write` with `permission_mode="acceptEdits"` (`coordinator/worker_registry.py`); its directory limits come from `cwd` and the worker's `CLAUDE.md` text.

### Why human gates

The gates sit where an error is expensive or hard to see:
- **Brief approval.** The orchestrator drafts the brief and waits for explicit approval before giving the run command (`CLAUDE.md`, Worker Routing Protocol). In coordinator mode workers cannot ask mid-task, and URL approval always happens before the task, so the brief must be complete but carry only the task-specific delta (`CLAUDE.md`, Routing Prompt Quality Standard; full rules in `workers/ROUTING_PROMPT_PROTOCOL.md`).
- **URL approval up front.** Workers fetch only registered or briefed URLs and flag the rest instead of fetching (`workers/WORKER_STANDARDS.md` item 1). Approval happens before the task, not during it (items 1 and 6). Inferred from `workers/WORKER_STANDARDS.md`: this bounds what external content reaches a deliverable.
- **Failed fetch stops the task.** A failed or thin fetch must be reported and the worker asks how to proceed; there is no silent fall back to training data (item 2). When the user supplies a replacement, the substitution is disclosed (Human-Retrieved Source Protocol; b25fa5b).
- **Acceptance and gaps.** The coordinator checks file existence, required sections and a self-critique, and every reported gap pauses for acknowledgment with no severity filter (`coordinator/README.md`, Q3; `coordinator/acceptance.py`). The README gives the reason: surface worker judgment to the human rather than make editorial calls.
- **Destructive and outward-facing actions.** Confirm before delete, format or system-level commands (`CLAUDE.md`, Security); `TASTE.md` extends this to push, PR and publish. The pipeline will not publish until `validation_report.md` records `Human Verdict: APPROVED` (`pipeline/PIPELINE.md`), and `scripts/check_pipeline_run.py` can verify that gate.

### Why two modes (manual and coordinator)

`workers/MODE_SELECTION_PROTOCOL.md` assigns tasks by whether they can run unattended. Coordinator mode fits a complete spec, a defined output format, no mid-task clarification and pre-approvable URLs. Manual mode fits bug fixes, exploratory or iterative work, context-dependent work and unknown URLs, where the user must steer mid-task. Eligibility is not enough: the owner also confirms error cost at brief time. If an eligible task has high error cost (it could reach a client or third party, be used without review, or be hard to reverse), only earlier hops run in the coordinator and the final hop and its acceptance are manual (`workers/MODE_SELECTION_PROTOCOL.md`, Error cost). The history shows the coordinator was built on the Agent SDK (10d7405) and the two-mode split came in ec16c6c.

Coordinator mode is available per task, but manual is the default. A standing override from 2026-09-28 told the orchestrator to always recommend manual mode; the stated reason was that the tasks run so far needed owner judgment on sources and acceptance that a hop chain could not give (owner, 2026-10-06). The owner lifted it on 2026-11-09, judging the override and its per-brief record-keeping to be overhead. The six exit criteria no longer gate use, and known limits remain: `coordinator/` has 270 offline tests (stubbed `query`, plus SDK contract tests) and two opt-in live SDK smoke tests that passed once on 2026-11-20 (init-message session ID and the real error path only), three live single-hop Developer runs on 2026-11-12 (one false acceptance failure, since fixed), one live single-hop Scout run on 2026-11-13, and an untested live blocked-fetch resume. Commit bb55a71 paired the override with a requirement to archive manual-mode hand-offs (per its message), and `CLAUDE.md` still requires a copy of each consumed routing prompt in `output/intermediate_outputs/`.

### Why template-plus-local-state

The tracked repo holds rules, code and blank templates. Runtime state is gitignored: `kb/`, `sandbox/`, `output/*`, `logs/*`, `.mcp.json`, `.claude/*`, `pipeline/runs/`, the docs_fetcher registries, routing prompts and `human-retrieved-sources/` (`.gitignore`). Templates (`*_TEMPLATE.*`, `*.template.json`) are tracked as the onboarding path.

The history shows this was a deliberate reset: a full working-state archive (omitted from the published history), then a "template branch: architecture only" (b08f2c7), then untracking of logs (fc2f818, 705660d). Inferred from `.gitignore` and those messages: the state holds per-user paths, fetched third-party documentation and personal source lists that should not be published, so the structure is shared and the content is not. `TASTE.md` and `pipeline/PIPELINE.md` (Bootstrapping) also treat the rule set as copyable into another repo.

### Tradeoffs and costs

- **Process overhead.** Every task runs a six-step checklist, and Developer may not write code until each import and shell command has a kb file at most 30 days old (`CLAUDE.md`; `workers/developer/CLAUDE.md`). Small edits pay the same cost as large ones. Each brief also asks the owner for a baseline, a time estimate, the end goal and who will use the output; about 1 in 5 eligible tasks are sampled for a baseline eval; and Track-record entries need the owner's approval (`CLAUDE.md` Orientation).
- **KB maintenance.** Each kb file carries a 30-day staleness rule, and a weekly launchd job reports it (`workers/WORKER_STANDARDS.md`, KB staleness check). Server freshness is also scheduled; the markdown-length check is not, so a flagged file can go unnoticed until someone runs it (`CLAUDE.md` steps 4-5). The cache is gitignored, so it must be rebuilt on a new machine.
- **Instruction-level enforcement.** Grounding and staleness are rules the model follows; `check_grounding.py` and `check_imports.py` check quotes and imports only when run at acceptance. Write denies, sandboxed Bash and the fetch cap are enforced (`STATUS.md`). `pipeline/PIPELINE.md` says test isolation is instruction-level unless the owner adds a deny rule.
- **Single-operator assumption.** The approval gates, local-only logs and manual session hand-off assume one person doing the routing. Inferred from `.gitignore`, `CLAUDE.md` and `coordinator/README.md`: nothing covers concurrent operators or shared state.
- **Manual mode cost.** Manual is the default, and the coordinator is lightly proven: four live single-hop runs and two live smoke tests (`STATUS.md`), so each hop usually needs the user to open a worker session and read a prompt file, and the hop record is created by hand (`CLAUDE.md`).
- **Markdown cap.** Rule files are limited to 100 non-empty lines (`TASTE.md`; `scripts/check_markdown_length.py`). This keeps rules readable but forces detail into separate protocol files, which adds the cost of finding them.
- **Instruction drift.** Rules live in prose across about 40 tracked markdown files, and the same rule is sometimes repeated. The history includes trims (2d5db57) and a cleanup of agent artifacts (a284adb).
- **Local-only evidence.** The Track-record log is gitignored, so no reader of the repo can re-check an entry. This is a cost of keeping client details out of the tracked tree.
- **Open decisions the design does not settle.** Whether to add a hard deny rule for pipeline test isolation (worker write paths already have one); whether the grounding checks should run automatically instead of by hand.

### What the design does not establish

This section explains why the repo is built this way. It is not evidence that the design works: no run artifacts are tracked and the Track-record log is owner-reported, and several rationales above are inferred. See [`STATUS.md`](../STATUS.md) for what is and is not evidenced.
