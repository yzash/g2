"""Typed output objects (platform-owned tables in PRD section 3).

The grounding contract lives here: every consequential output must carry
resolvable evidence IDs or it cannot be constructed. The UI applies the same
rule when rendering (no evidence rows, no card).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

ElementType = Literal["NAP", "LCP", "OLT", "LINE"]
IncidentState = Literal["Proposed", "Confirmed", "Rejected", "Merged", "Closed"]
Outcome = Literal["dispatch", "suppress", "hold"]
ReasonClass = Literal[
    "shared upstream fault",
    "planned work or power",
    "customer, drop or CPE fault",
    "duplicate dispatch",
    "access refusal",
    "insufficient evidence",
]


class GroundingError(ValueError):
    pass


class Grounded(BaseModel):
    evidence_ids: list[str] = Field(min_length=1)

    @field_validator("evidence_ids")
    @classmethod
    def _non_empty(cls, v: list[str]) -> list[str]:
        v = [x for x in v if x]
        if not v:
            raise GroundingError("output has no evidence rows; the agent must abstain")
        return list(dict.fromkeys(v))


class Hypothesis(BaseModel):
    element_type: ElementType
    element_id: str
    score: float
    components: dict[str, float]


class Incident(Grounded):
    incident_id: str
    element_type: ElementType
    element_id: str
    kind: Literal["outage", "recurring fault"] = "outage"
    hypothesis_rank: list[Hypothesis]
    observed_lines: int
    inferred_lines: int
    vip_b2b_count: int
    msf_band_total: dict[str, int] = {}
    severity: str
    support_score: float
    score_components: dict[str, float]
    rationale: str
    state: IncidentState
    proposed_at: str
    decided_by: Optional[str] = None
    decided_at: Optional[str] = None
    decision_reason: Optional[str] = None
    parent_id: Optional[str] = None
    snow_refs: list[str] = []
    crew_assigned: bool = False
    has_physical_signal: bool = False
    closure_proposed_at: Optional[str] = None
    closed_at: Optional[str] = None
    flap_count: int = 0
    detectors: list[str] = []
    olt: Optional[str] = None
    lcp: Optional[str] = None
    naps: list[str] = []
    territory: Optional[str] = None
    hourly_cycle_at: Optional[str] = None
    detection_lead_min: Optional[int] = None
    first_signal_at: Optional[str] = None
    run_id: Optional[str] = None
    version: int = 1
    updated_at: Optional[str] = None


class Check(BaseModel):
    question: str
    tool: str
    status: Literal["available", "unavailable"]
    result: str
    evidence_ids: list[str] = []


class DispatchRecommendation(Grounded):
    rec_id: str
    workordernumber: str
    review_seq: int
    outcome: Outcome
    reason_class: ReasonClass
    note: str
    support_score: Optional[float]
    floor: float
    floor_applied: bool
    incident_id: Optional[str] = None
    checks: list[Check]
    estimated_avoidable_cost: str
    hold_until: Optional[str] = None
    recommended_at: str
    territory: str
    trigger: str
    dispatcher_decision: Optional[Literal["accepted", "overridden"]] = None
    decided_by: Optional[str] = None
    decided_at: Optional[str] = None
    override_reason: Optional[str] = None
    override_outcome: Optional[str] = None
    outcome_observed: Optional[str] = None
    untrusted_text_flags: list[str] = []
    run_id: Optional[str] = None


class QueueRow(Grounded):
    item_id: str
    item_type: Literal["incident", "order"]
    label: str
    rank: int
    score: float
    inputs: dict
    clock_start: Optional[str]
    breach_eta: Optional[str]
    exception_flag: bool
    exception_text: Optional[str] = None
    ranked_at: str
    territory: Optional[str] = None


class PolicyResult(BaseModel):
    check: str
    status: Literal["pass", "hold", "blocked", "unavailable"]
    detail: str
    affected: int = 0


class NotificationPackage(Grounded):
    package_id: str
    incident_id: str
    kind: Literal["initial", "update", "restoration"]
    recipients_total: int
    recipients_observed: int
    recipients_inferred: int
    recipients_vip: int
    recipients_mass: int
    recipient_tokens_sample: list[str]
    text: str
    restoration_target: Optional[str] = None
    next_update_at: Optional[str] = None
    scheduled_send_at: Optional[str] = None
    policy_results: list[PolicyResult]
    state: Literal["Draft", "Approved", "Withheld", "Sent"] = "Draft"
    send_state: str = "Not sent: NG1 handoff disabled in demo"
    approver: Optional[str] = None
    decided_at: Optional[str] = None
    decision_note: Optional[str] = None
    built_at: str
    trigger: str
    ng1_payload_preview: dict = {}
    run_id: Optional[str] = None


class AdoptionRecord(Grounded):
    record_id: str
    at: str
    actor: str
    role: str
    object_type: Literal["incident", "closure", "dispatch", "package", "merge"]
    object_id: str
    recommendation: str
    decision: Literal["accepted", "overridden", "rejected", "approved", "withheld", "confirmed", "auto-linked"]
    reason: Optional[str] = None
    outcome_observed: Optional[str] = None
    scripted: bool = True
    batch: bool = False
