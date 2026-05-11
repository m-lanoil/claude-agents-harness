# Worker Standards

**Workers: read this file at the start of every task.** All shared rules live here — do not rely on copies in your own `CLAUDE.md`. Your `CLAUDE.md` contains only mandate-specific content.

**Meta-Orchestrator**: This file is the canonical source for worker rules. The Worker-Building Loop (step 4) and Worker Gap Protocol both reference it. No worker draft is complete until all items below are present.

## Worker Security Baseline
Every worker `CLAUDE.md` must include all six items, regardless of mandate.

| # | Requirement | What it must say |
|---|---|---|
| 1 | **URL approval gate** | Before fetching any URL not already registered in the Source Registry (`list_libraries`, `list_clis`, `list_other_sources`), propose it to the user and wait for explicit approval. No silent fetches. |
| 2 | **Failure modes** | If a fetch fails or returns insufficient content, stop immediately, say so, and ask how to proceed. No silent fallback to training data or unverified content. |
| 3 | **Citation requirement** | Every factual claim, benchmark, or recommendation must trace to a named `kb/` file — not just a URL. "Cite sources inline" alone is not sufficient. |
| 4 | **No unverified data** | If a claim cannot be traced to a fetched source in `kb/`, flag it explicitly in the deliverable rather than including it as fact. |
| 5 | **Sandboxing** | File writes explicitly scoped based on worker type. **Deliverable workers** (Architect, Content): `./kb/` and `../../output/` only. **Code workers** (Developer): intermediate artifacts to `./sandbox/<task_name>/output/`; final deliverables (PDFs, structured outputs for the user) to `../../output/`. No writes elsewhere. |
| 6 | **Human-in-the-loop** | Confirm before any action that is hard to reverse or that fetches from an unregistered external source. |

These six items must appear as explicit rules — not implied by other sections. If a worker's mandate makes one item not applicable, note that explicitly rather than omitting the section.

## Worker Standard Components
These reusable process patterns govern correctness and consistency, not safety. Every worker `CLAUDE.md` must include all of them.

### Task Start Checklist minimum structure
Every worker's checklist must follow this order:
1. **Classify** the task type and identify which sections apply.
2. **Active rules check** — confirm relevant protocols are active for this task type.
3. **Source inventory** — list every source (import, technology, topic) the task will need. For each, apply the KB staleness check before reaching for `docs_fetcher`.
4. **State the plan** — describe approach and name which rules apply.

### KB staleness check (three-branch logic)
Before using any kb file, and before any fetch, apply this logic to each source:
- **kb file exists, `fetched:` ≤30 days** → use directly. Do not re-fetch.
- **kb file exists, `fetched:` >30 days** → stale. Re-fetch and update before using.
- **kb file missing** → fetch (subject to URL approval gate). Save before proceeding.

### KB frontmatter format
All kb files must use this header — adapt the primary key name to the worker's domain:
```
---
[library / technology / topic]: [name]
source: [url]
fetched: YYYY-MM-DD
---
```

### Token Budget Protocol
1. **Pre-task declaration** — before any fetch, list expected call count, sources, and any planned `crawl_docs`. Wait for user acknowledgment.
2. **Checkpoint rule** — every 3 fetch calls, call `get_fetch_stats` and report one-line summary. Wait for "continue."
3. **Large-fetch gate** — `crawl_docs` requires explicit approval with URL and `max_pages` stated.
4. **Budget cap** — the routing prompt's suggested fetch budget is a hard cap; worker must ask before exceeding it.

### Source Registry
After any session that fetches new content, register each new source URL in the correct store:

| Store | Check | Register | What belongs here |
|---|---|---|---|
| `libraries.json` | `list_libraries` | `add_library` | External Python packages, language SDKs (e.g. PyTorch, sklearn, FastMCP) |
| `clis.json` | `list_clis` | `add_cli` | CLI tools invoked as shell commands |
| `other_sources.json` | `list_other_sources` | `add_other_source` | Hardware specs, RFCs, platform docs, REST APIs, reports, reference pages |

**Python stdlib exemption**: Sources from `docs.python.org` do not need to be registered — stdlib format is stable and these are fetched for grounding only. All other KB rules still apply. All external sources must be registered as normal.

Register only sources fetched this session — not existing kb files. **Stale server warning**: If `server.py` was edited this session, the running process may be stale — edit the JSON files in `servers/docs_fetcher/` directly instead of calling the tool.
