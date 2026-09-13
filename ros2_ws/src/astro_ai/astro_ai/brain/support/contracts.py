"""ASTRO V1 — Cognitive Architecture Support Layer Contracts and Types.

Data structures, enums, and response models for the offline/development-time
cognitive architecture support system (Gemini Flash + Groq Qwen 3.6 27B).

IMPORTANT ARCHITECTURAL INVARIANTS:
  1. NOT RUNTIME CONSCIOUSNESS: This layer never runs in the 10 Hz cognitive loop.
  2. NO MOTOR CONTROL: Cannot emit ActionIntents or command hardware.
  3. NO SILENT REWRITES: Default mode is PROPOSE; modifications require explicit authorization.
  4. NO PASS-THROUGH API USAGE: All requests are budgeted, cached, and context-minimized.
"""

from __future__ import annotations

import enum
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set


class SupportControlMode(str, enum.Enum):
    """Execution control mode for architecture support operations."""
    OBSERVE = "OBSERVE"   # Read-only architectural inspection; no proposals or file edits
    PROPOSE = "PROPOSE"   # Default mode: produce structured proposals; strictly no file modifications
    APPLY = "APPLY"       # Explicit invocation only: modify authorized consciousness files, verify invariants & tests


class SupportStatus(str, enum.Enum):
    """Execution outcome status of an architecture support request."""
    SUCCESS = "SUCCESS"
    DEGRADED = "DEGRADED"
    CACHED = "CACHED"
    REJECTED_BY_BUDGET = "REJECTED_BY_BUDGET"
    SUPPRESSED_BY_COOLDOWN = "SUPPRESSED_BY_COOLDOWN"
    TOKEN_BUDGET_EXCEEDED = "TOKEN_BUDGET_EXCEEDED"
    UNAUTHORIZED_FILE_ACCESS = "UNAUTHORIZED_FILE_ACCESS"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    ERROR = "ERROR"


@dataclass
class BudgetDecision:
    """Decision output produced by the local budget gate before any network request."""
    allowed: bool
    reason: str = "OK"
    provider: str = ""
    requests_minute: int = 0
    requests_hour: int = 0
    requests_day: int = 0
    estimated_input_tokens: int = 0
    daily_tokens_used: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SupportRequest:
    """A structured request submitted to the Cognitive Architecture Support Layer."""
    topic: str
    prompt: str
    mode: SupportControlMode = SupportControlMode.PROPOSE
    provider_override: Optional[str] = None
    target_files: List[str] = field(default_factory=list)
    context_data: Dict[str, Any] = field(default_factory=dict)
    allow_fallback: bool = False             # HARD REQUIREMENT: Default False to avoid doubling usage
    requires_comparison: bool = False        # Explicit independent review
    request_id: str = field(default_factory=lambda: f"req_{uuid.uuid4().hex[:10]}")
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["mode"] = self.mode.value
        return d


@dataclass
class ProposedChange:
    """A specific architectural change proposed by the support assistant."""
    file_path: str
    description: str
    rationale: str
    diff_snippet: str = ""
    target_invariants: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ApplyResult:
    """Results from an explicit APPLY mode execution."""
    files_modified: List[str] = field(default_factory=list)
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    rollback_information: Dict[str, Any] = field(default_factory=dict)
    invariants_verified: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ArchitectureSupportResponse:
    """Consolidated, structured response emitted by the support layer."""
    request_id: str
    provider: str
    model: str
    mode: SupportControlMode
    status: SupportStatus
    summary: str
    observations: List[str] = field(default_factory=list)
    architectural_concerns: List[str] = field(default_factory=list)
    proposed_changes: List[ProposedChange] = field(default_factory=list)
    affected_files: List[str] = field(default_factory=list)
    invariant_checks: Dict[str, bool] = field(default_factory=dict)
    test_plan: List[str] = field(default_factory=list)
    confidence: float = 0.8
    requires_human_approval: bool = True     # Always True in PROPOSE and APPLY
    cache_hit: bool = False
    budget_decision: Optional[BudgetDecision] = None
    reasoning_level: Optional[str] = None
    error_code: Optional[str] = None
    apply_result: Optional[ApplyResult] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "provider": self.provider,
            "model": self.model,
            "mode": self.mode.value if isinstance(self.mode, SupportControlMode) else str(self.mode),
            "status": self.status.value if isinstance(self.status, SupportStatus) else str(self.status),
            "summary": self.summary,
            "observations": self.observations,
            "architectural_concerns": self.architectural_concerns,
            "proposed_changes": [c.to_dict() for c in self.proposed_changes],
            "affected_files": self.affected_files,
            "invariant_checks": self.invariant_checks,
            "test_plan": self.test_plan,
            "confidence": round(self.confidence, 3),
            "requires_human_approval": self.requires_human_approval,
            "cache_hit": self.cache_hit,
            "budget_decision": self.budget_decision.to_dict() if self.budget_decision else None,
            "reasoning_level": self.reasoning_level,
            "error_code": self.error_code,
            "apply_result": self.apply_result.to_dict() if self.apply_result else None,
            "timestamp": round(self.timestamp, 3),
        }


@dataclass
class ArchitectureComparisonResult:
    """Synthesized comparison result from independent review mode."""
    request_id: str
    gemini_observations: List[str] = field(default_factory=list)
    qwen_observations: List[str] = field(default_factory=list)
    agreements: List[str] = field(default_factory=list)
    disagreements: List[str] = field(default_factory=list)
    unresolved_questions: List[str] = field(default_factory=list)
    gemini_response: Optional[ArchitectureSupportResponse] = None
    qwen_response: Optional[ArchitectureSupportResponse] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "gemini_observations": self.gemini_observations,
            "qwen_observations": self.qwen_observations,
            "agreements": self.agreements,
            "disagreements": self.disagreements,
            "unresolved_questions": self.unresolved_questions,
            "gemini_response": self.gemini_response.to_dict() if self.gemini_response else None,
            "qwen_response": self.qwen_response.to_dict() if self.qwen_response else None,
            "timestamp": round(self.timestamp, 3),
        }
