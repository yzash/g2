"""Guardrails as code, outside the agents (PRD section 9).

`decide` is the UC2 decision rule set. The confidence floor is checked before
any other branch, so below the floor the suppress and hold outcomes are
unreachable: the function can only return "dispatch".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DispatchEvidence:
    incident_id: Optional[str] = None
    incident_state: Optional[str] = None          # Proposed / Confirmed / Closed
    incident_support: Optional[float] = None
    incident_has_physical: bool = False
    incident_crew_or_snow: bool = False
    incident_physical_ids: list[str] = field(default_factory=list)
    incident_closed_recently: bool = False
    line_gateway_healthy: bool = False
    signature: str = "none"                       # cpe / drop / silent_line / last_mile / none
    handyman_fresh: bool = False
    handyman_age_h: Optional[float] = None
    handyman_stalled: bool = False
    line_hold_support: Optional[float] = None
    hold_expired: bool = False
    nap_known: bool = True


@dataclass
class Decision:
    outcome: str
    reason_class: str
    note_key: str
    support: Optional[float]
    floor_applied: bool
    uses_handyman: bool = False


def decide(ev: DispatchEvidence, floor: float) -> Decision:
    # ---- upstream incident path -------------------------------------------
    if ev.incident_id is not None:
        s = ev.incident_support or 0.0
        if s < floor:
            return Decision("dispatch", "insufficient evidence", "below_floor_incident", s, True)
        if ev.incident_state == "Closed" and ev.incident_closed_recently and ev.line_gateway_healthy:
            return Decision("suppress", "shared upstream fault", "restored_upstream", s, False)
        if ev.incident_state == "Confirmed" and ev.incident_crew_or_snow and ev.incident_has_physical and ev.incident_physical_ids:
            return Decision("suppress", "shared upstream fault", "suppress_upstream", s, False)
        if ev.incident_state in ("Proposed", "Confirmed"):
            if ev.hold_expired:
                return Decision("dispatch", "insufficient evidence", "hold_expired", s, False)
            return Decision("hold", "shared upstream fault", "hold_incident_pending", s, False)
    # ---- line-level path ----------------------------------------------------
    if not ev.nap_known:
        return Decision("dispatch", "insufficient evidence", "no_nap", None, False)
    line_hold_candidate = ev.signature == "silent_line" or (
        ev.handyman_age_h is not None and not ev.handyman_fresh and ev.signature in ("none", "silent_line"))
    if line_hold_candidate:
        if ev.handyman_stalled:
            return Decision("dispatch", "insufficient evidence", "handyman_stalled_hold", ev.line_hold_support, False, True)
        s = ev.line_hold_support or 0.0
        if s < floor:
            return Decision("dispatch", "insufficient evidence", "below_floor_line", s, True, True)
        if ev.hold_expired:
            return Decision("dispatch", "insufficient evidence", "hold_expired", s, False, True)
        return Decision("hold", "insufficient evidence", "hold_line_silent", s, False, True)
    if ev.signature == "cpe":
        if ev.handyman_stalled:
            return Decision("dispatch", "insufficient evidence", "handyman_stalled_cpe", None, False, True)
        return Decision("dispatch", "customer, drop or CPE fault", "cpe_signature", None, False, True)
    if ev.signature == "drop":
        return Decision("dispatch", "customer, drop or CPE fault", "drop_signature", None, False)
    return Decision("dispatch", "insufficient evidence", "no_upstream_cause", None, False, ev.handyman_fresh)


def assert_floor(outcome: str, support: Optional[float], floor: float) -> None:
    """Second line of defence used by the engine before any recommendation is stored."""
    if outcome in ("suppress", "hold") and (support is None or support < floor):
        raise AssertionError(f"{outcome} below confidence floor {floor} (support={support})")
