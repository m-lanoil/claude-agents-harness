import re
import json
from pathlib import Path
from typing import Optional

from .schemas import RoutingPrompt, WorkerResult, AcceptanceResult

_REPO_ROOT = Path(__file__).parent.parent

# Matches the last ```json ... ``` block in worker output
_JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
_REQUIRED_RETURN_KEYS = {"deliverable_path", "status", "self_critique", "gaps"}


def parse_worker_result(raw_text: str) -> Optional[WorkerResult]:
    """Extract structured WorkerResult from the final JSON block in worker output.

    Returns None if the block is absent, unparseable, or missing required keys.
    A None return triggers automatic acceptance failure (malformed return).

    A return with status "blocked" (failed-fetch path) is parsed separately: it
    must carry a non-empty `blocked_sources` list of objects with a `source`
    key; deliverable_path, self_critique and gaps are optional and default to
    empty. A blocked return without usable blocked_sources is malformed (None),
    since the owner could not be asked anything.
    """
    matches = list(_JSON_BLOCK_RE.finditer(raw_text))
    if not matches:
        return None
    try:
        data = json.loads(matches[-1].group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    if data.get("status") == "blocked":
        raw_sources = data.get("blocked_sources")
        if not isinstance(raw_sources, list):
            return None
        blocked = [s for s in raw_sources if isinstance(s, dict) and s.get("source")]
        if not blocked:
            return None
        return WorkerResult(
            raw_text=raw_text,
            deliverable_path=str(data.get("deliverable_path") or ""),
            status="blocked",
            self_critique=str(data.get("self_critique") or ""),
            gaps=list(data.get("gaps") or []),
            blocked_sources=blocked,
        )

    if not _REQUIRED_RETURN_KEYS.issubset(data):
        return None
    return WorkerResult(
        raw_text=raw_text,
        deliverable_path=data["deliverable_path"],
        status=data["status"],
        self_critique=data["self_critique"],
        gaps=data["gaps"],
    )


def acceptance_check(result: WorkerResult, routing: RoutingPrompt) -> AcceptanceResult:
    """Three-part automated acceptance check per architecture spec section 3."""
    # Step 1: file existence
    target = Path(result.deliverable_path)
    if not target.is_absolute():
        target = (_REPO_ROOT / result.deliverable_path).resolve()
    file_exists = target.exists()

    # Step 2: spec match — section-level scan of required headers
    spec_match = True
    if file_exists and routing.required_sections:
        content = target.read_text(encoding="utf-8").lower()
        spec_match = all(s.lower() in content for s in routing.required_sections)

    # Step 3: self-critique presence
    self_critique_present = (
        isinstance(result.self_critique, str)
        and bool(result.self_critique.strip())
        and isinstance(result.gaps, list)
    )

    passed = file_exists and spec_match and self_critique_present

    correction_brief: Optional[str] = None
    if not passed:
        issues: list[str] = []
        if not file_exists:
            issues.append(f"deliverable not found at '{result.deliverable_path}'")
        elif not spec_match:
            content = target.read_text(encoding="utf-8").lower()
            missing = [s for s in routing.required_sections if s.lower() not in content]
            issues.append(f"missing required sections: {missing}")
        if not self_critique_present:
            issues.append("self_critique absent or gaps field missing from JSON return block")
        correction_brief = "Correction required: " + "; ".join(issues)

    return AcceptanceResult(
        passed=passed,
        file_exists=file_exists,
        spec_match=spec_match,
        self_critique_present=self_critique_present,
        gaps=result.gaps,
        correction_brief=correction_brief,
    )
