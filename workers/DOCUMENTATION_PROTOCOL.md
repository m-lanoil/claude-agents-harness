# Documentation Protocol

Used by: Developer Worker (technical docs), Content Worker (written deliverables)
Triggered when: a task produces or edits documentation.

## Step 1 — Classify the documentation type

| Type | Who handles it | Examples |
|---|---|---|
| Technical | Developer | README, setup guide, API reference, usage guide, CLI docs |
| Written deliverable | Content | Brief, case study, presentation, report |

If you receive a documentation task that belongs to the other worker type, do not attempt it — flag it per the Handoff Rule in WORKER_STANDARDS.md.

## Step 2 — Identify audience and scope
Before writing anything, state:
- Who reads this document (developer, end user, stakeholder)
- What it must cover (scope) and what is explicitly out of scope
- Source material: code, existing docs, fetched references

## Step 3 — Outline first
Write an outline in the deliverable header using the task brief's specified structure, then proceed directly to full content. Flag any structural ambiguity in self-critique.

## Step 4 — Write
- **Technical docs**: every statement must be verifiable against the code or a kb file. No invented behavior.
- **Written deliverables**: every factual claim, benchmark, or statistic traces to a named kb file. No training data.

## Step 5 — Self-critique before closing
Review your deliverable against the original brief. Flag any:
- Section that is thinner than requested
- Claim that could not be fully sourced
- Assumption you made about scope or audience

State these gaps explicitly — do not silently omit them.
