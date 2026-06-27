from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class RoutingPrompt:
    worker: str
    prompt_text: str
    expected_output_path: str
    required_sections: List[str] = field(default_factory=list)
    hop_index: int = 0
    total_hops: int = 1


@dataclass
class WorkerResult:
    raw_text: str
    deliverable_path: str
    status: str
    self_critique: str
    gaps: List[str]
    session_id: Optional[str] = None


@dataclass
class AcceptanceResult:
    passed: bool
    file_exists: bool
    spec_match: bool
    self_critique_present: bool
    gaps: List[str]
    correction_brief: Optional[str] = None
