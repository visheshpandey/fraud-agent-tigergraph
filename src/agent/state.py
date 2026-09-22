"""Case state for the fraud-investigation LangGraph agent.

Field names and enums here match the HHGOA README's "Answer Format" section verbatim
(`data/raw/README.md`) rather than a generic internal shape, so that Phase 6's benchmark
runner can serialize `CaseState` into the graded JSON with no translation layer — the
translation layer is exactly where a typo would silently zero out a scored field.
"""

from __future__ import annotations

from typing import Literal, Optional, TypedDict

from pydantic import BaseModel, Field

TriggerType = Literal["risk_score", "customer_report", "analyst_request"]

Verdict = Literal["fraud", "legitimate", "uncertain"]

CaseStatus = Literal["open", "closed_fraud", "closed_legitimate", "escalated"]

Pattern = Literal[
    "card_testing",
    "card_not_present_fraud",
    "card_not_present_new_device",
    "out_of_region_use",
    "account_takeover",
    "undocumented",
    "none",
]

# Policy §1 — exact identifiers required in output.
ActionName = Literal[
    "ALLOW_TRANSACTION",
    "DECLINE_TRANSACTION",
    "MONITOR_CARD",
    "MONITOR_CONNECTED_CARDS",
    "WARN_CUSTOMER",
    "VERIFY_WITH_CUSTOMER",
    "STEP_UP_AUTH",
    "BLOCK_CARD",
    "BLOCK_ALL_CARDS",
    "GENERATE_REPORT",
    "CREATE_CASE",
    "FILE_REPORT",
    "ESCALATE_TO_ANALYST",
    "CLOSE_NO_FRAUD",
]

# Policy §2 — auto may be executed by the agent; L1/L2 wait for a human.
ApprovalRoute = Literal["auto", "L1", "L2"]

EvidenceSource = Literal["graph", "document", "customer", "external"]

EvidenceRequestType = Literal["customer_validation", "step_up_auth", "analyst_info"]


class TriggerInfo(TypedDict):
    """Normalized incoming signal, whatever its original shape."""

    trigger_type: TriggerType
    entity_id: str  # flagged_txn_id for real cases; card/customer id for mock scenarios
    raw_risk_score: Optional[float]
    description: str


class ToolEvidence(TypedDict):
    """Raw output of one tool call — reasoning fuel for `assess`, not itself scored.
    Distinct from `EvidenceItem`, which is the graded, human-readable claim."""

    source: str  # tool name that produced it
    round: int  # which gather_evidence round this came from (0 = initial)
    summary: str
    data: dict


class EvidenceItem(TypedDict):
    """One entry of `case.evidence` in the answer format — a claim, not raw data."""

    claim: str
    source: EvidenceSource
    ref: str  # query name, document section, or evidence_request id
    entity_ids: list[str]


class EvidenceRequestRecord(TypedDict):
    """One entry of top-level `evidence_requests` in the answer format."""

    type: EvidenceRequestType
    asked_after_step: int
    assumed_response: str


class RiskAssessment(BaseModel):
    """Structured output of the `assess` node's LLM call — mirrors `case.*` fields
    the README scores for calibration, not a generic internal risk score."""

    verdict: Verdict
    fraud_probability: float = Field(ge=0.0, le=1.0)
    pattern: Pattern
    pattern_description: str = Field(
        default="", description="Required (non-empty) only when pattern='undocumented'"
    )
    evidence_gaps: list[str] = Field(default_factory=list)
    rationale: str = ""


class ActionItem(BaseModel):
    """One `{action, route, reason}` entry as required in `next_best_actions.initial/final`."""

    action: ActionName
    route: ApprovalRoute
    reason: str  # must cite a policy rule, e.g. "R2: customer denied"


class CaseState(TypedDict, total=False):
    # trigger
    trigger: TriggerInfo

    # case bookkeeping
    case_id: str
    status: CaseStatus

    # evidence gathering (internal reasoning fuel)
    tool_evidence: list[ToolEvidence]
    round_count: int
    max_rounds: int

    # assessment (latest)
    risk_assessment: Optional[RiskAssessment]

    # `case` fields from the answer format, kept as first-class state so Phase 6
    # serializes them directly rather than reconstructing them from risk_assessment
    verdict: Optional[Verdict]
    fraud_probability: Optional[float]
    pattern: Optional[Pattern]
    pattern_description: str
    affected_txn_ids: list[str]
    first_suspicious_txn_id: str
    connected_card_ids: list[str]
    connected_device_profiles: list[str]
    exposure_usd: float
    case_evidence: list[EvidenceItem]  # -> answer format `case.evidence`
    similar_prior_cases: list[str]
    summary: str
    written_to_graph: bool
    graph_case_id: str

    # top-level answer format fields
    evidence_requests: list[EvidenceRequestRecord]
    stop_reason: str

    # next_best_actions — README calls these `initial`/`final`, not before/after,
    # because `decide_action` may run more than twice if evidence is requested
    # more than once (capped at `max_rounds`); only the first and most recent
    # calls are kept, matching what the answer format actually asks for.
    initial_actions: list[ActionItem]
    what_changed: str
    final_actions: list[ActionItem]

    # explainability
    explanation: Optional[str]

    # ReAct-style scratchpad: free-form log of tool calls / reasoning steps
    messages: list[str]

    finalized: bool
