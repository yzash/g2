"""Agent 2: Dispatch Reviewer (UC2).

Reviews every dispatch-eligible work order before it rolls and recommends
dispatch, suppress or hold-and-recheck with cited evidence. The decision rules
are code (guardrails.decide), not agent judgement. The agent cannot cancel
anything; the dispatcher decides.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from .. import tools as T
from ..guardrails import DispatchEvidence, assert_floor, decide
from ..models import Check, DispatchRecommendation

NAME = "UC2"
ELIGIBLE = ("Open", "Unassigned", "Pending")


def fmt(t) -> str:
    return pd.Timestamp(t).strftime("%Y-%m-%d %H:%M:%S")


def hm(t) -> str:
    return fmt(t)[11:16]


def eligible(row: dict, now) -> bool:
    if row.get("skillset") != "Repair" or row.get("status") not in ELIGIBLE:
        return False
    appt = row.get("appointmentdate")
    return appt is not None and not pd.isna(appt) and pd.Timestamp(appt) <= pd.Timestamp(now) + pd.Timedelta(hours=24)


class DispatchReviewer:
    def __init__(self, engine):
        self.e = engine
        self.cfg = engine.cfg
        self.floor = engine.cfg["dispatch"]["confidence_floor"]

    def line_hold_support(self, sig: dict) -> float:
        w = self.cfg["dispatch"]["line_hold_weights"]
        sib = sig["siblings"]["share"] if sig.get("siblings") else 0.0
        silent = 1.0 if sig["gateway_silent"] else 0.0
        last_h = sig.get("handyman_last")
        after = 1.0 if (sig["gateway_last_seen"] and last_h and sig["gateway_last_seen"] >= str(last_h["date_time"])[:19]) else 0.0
        no_fresh = 0.0 if sig["handyman_fresh"] else 1.0
        raw = w["siblings_healthy"] * sib + w["gateway_silent"] * silent + w["silence_after_last_contact"] * after + w["no_fresh_complaint"] * no_fresh
        # a silent gateway is exactly what a power outage looks like, and the power check is unavailable
        return round(raw * self.cfg["dispatch"]["unavailable_check_penalty"], 2)

    def review(self, ctx: T.ToolContext, row: dict, trigger: str) -> DispatchRecommendation | None:
        e = self.e
        wo = row["workordernumber"]
        nap = row.get("facilityname") if isinstance(row.get("facilityname"), str) else None
        e.tracer.start(NAME, f"{trigger}: {wo}")
        inc_r = T.incident_registry_read(ctx, dpid=row.get("dpid") if isinstance(row.get("dpid"), str) else None,
                                         lcpname=row.get("lcpname") if isinstance(row.get("lcpname"), str) else None,
                                         cabinetid=row.get("cabinetid"), facilityname=nap)
        pw = T.planned_works_check(ctx, nap=nap)
        pf = T.power_footprint_check(ctx, nap=nap)
        sig_r = T.symptom_signature_check(ctx, accountnumber=row["accountnumber"], nap=nap)
        hist = T.line_history_read(ctx, serviceidnumber=row["serviceidnumber"])
        for f in hist.flags:
            e.tracer.note(f"UNTRUSTED TEXT IGNORED: {f}")
        sig = sig_r.data

        inc = inc_r.data
        closed_inc = None
        if inc is None and nap:
            chain = {eid for _, eid in ctx.snap.chain(nap)}
            cutoff = fmt(ctx.now - timedelta(hours=6))
            cands = [i for i in e.state.incidents.values() if i.state == "Closed" and i.element_id in chain and (i.closed_at or "") >= cutoff]
            closed_inc = cands[0] if cands else None
        use = inc or closed_inc
        anchor_key = (wo, use.incident_id if use else "line")
        hold_until = e.hold_anchor.get(anchor_key)
        ev = DispatchEvidence(
            incident_id=use.incident_id if use else None,
            incident_state=use.state if use else None,
            incident_support=use.support_score if use else None,
            incident_has_physical=bool(use and use.has_physical_signal),
            incident_crew_or_snow=bool(use and (use.crew_assigned or use.snow_refs)),
            incident_physical_ids=e.physical_ids.get(use.incident_id, []) if use else [],
            incident_closed_recently=closed_inc is not None,
            line_gateway_healthy=bool(sig["gateway_rx_ok"]),
            signature=sig["signature"], handyman_fresh=sig["handyman_fresh"], handyman_age_h=sig["handyman_age_h"],
            handyman_stalled=e.state.feed_status.get("HANDYMAN") != "on time",
            line_hold_support=self.line_hold_support(sig) if use is None else None,
            hold_expired=bool(hold_until and pd.Timestamp(hold_until) <= pd.Timestamp(ctx.now)),
            nap_known=nap is not None,
        )
        d = decide(ev, self.floor)
        assert_floor(d.outcome, d.support, self.floor)

        if d.outcome == "hold" and not hold_until:
            hold_until = fmt(ctx.now + timedelta(hours=self.cfg["dispatch"]["hold_hours_default"]))
            e.hold_anchor[anchor_key] = hold_until

        # evidence: the order itself, incident + physical signal, Handyman, gateway
        own = T.wo_id(ctx, row)
        evidence = [own]
        if use:
            evidence += [f"SDAL:{use.incident_id}"] + ev.incident_physical_ids[:3]
        evidence += [x for x in sig_r.evidence_ids] + inc_r.evidence_ids[1:]
        if d.uses_handyman is False and d.outcome == "suppress":
            evidence = [x for x in evidence if not x.startswith("AUD:")]

        note = self.note(d.note_key, row, use, sig, hold_until, ev)
        checks = [
            Check(question="Is the line inside an open incident's blast radius?", tool="incident_registry_read", status="available",
                  result=inc_r.summary if not closed_inc else f"{nap} inside {closed_inc.incident_id} (Closed {hm(closed_inc.closed_at)})",
                  evidence_ids=[f"SDAL:{use.incident_id}"] if use else inc_r.evidence_ids),
            Check(question="Is it inside planned works?", tool="planned_works_check", status="unavailable", result=pw.summary),
            Check(question="Is it inside a known power-outage footprint?", tool="power_footprint_check", status="unavailable", result=pf.summary),
            Check(question="Does the symptom signature point to a customer-side cause?", tool="symptom_signature_check", status="available",
                  result=self.signature_text(sig), evidence_ids=sig_r.evidence_ids),
        ]
        prev = e.state.latest_rec(wo)
        sig_key = (d.outcome, d.reason_class, d.note_key, ev.incident_id, d.floor_applied)
        if prev is not None and e.rec_keys.get(wo) == sig_key:
            e.tracer.note(f"Re-review of {wo}: recommendation unchanged ({d.outcome}).")
            e.tracer.end()
            return None
        seq = (prev.review_seq + 1) if prev else 1
        territory = ctx.snap.static.svc_to_line.territory.get(row["serviceidnumber"], "")
        rec = DispatchRecommendation(
            rec_id=f"REC-{wo}-{seq}", workordernumber=wo, review_seq=seq, outcome=d.outcome, reason_class=d.reason_class,
            note=note, support_score=d.support, floor=self.floor, floor_applied=d.floor_applied, incident_id=ev.incident_id,
            checks=checks,
            estimated_avoidable_cost=("1 truck roll x unit cost (placeholder until Finance supplies one)" if d.outcome != "dispatch" else "none"),
            hold_until=hold_until if d.outcome == "hold" else None, recommended_at=fmt(ctx.now), territory=territory, trigger=trigger,
            untrusted_text_flags=hist.flags, run_id=e.tracer.current["run_id"], evidence_ids=evidence + hist.evidence_ids[:3],
        )
        e.rec_keys[wo] = sig_key
        e.tracer.output("dispatch_recommendation", rec.rec_id)
        e.tracer.end()
        e.state.put_rec(rec)
        e.request_rerank("dispatch recommendation")
        return rec

    @staticmethod
    def signature_text(sig: dict) -> str:
        h = sig.get("handyman_last")
        htxt = (f"Handyman {h['audit_no']} {str(h['date_time'])[11:16]} ({sig['handyman_age_h']}h old): "
                f"{h.get('ModemStatus')}; {h.get('LineStatus') or 'line status n/a'}") if h else "no Handyman result"
        gtxt = ("gateway silent since " + sig["gateway_last_seen"][11:16]) if sig["gateway_silent"] else \
            (f"gateway Rx {sig['gateway_rx_dbm']} dBm vs baseline {sig['gateway_baseline_dbm']}" if sig["gateway_rx_dbm"] is not None else "no gateway reading")
        sib = sig.get("siblings")
        stxt = f"{sib['healthy']} of {sib['siblings']} neighbours healthy" if sib else "neighbours unknown"
        return f"signature={sig['signature']}; {gtxt}; {stxt}; {htxt}; Handyman feed {sig['handyman_feed']}"

    def note(self, key: str, row: dict, inc, sig: dict, hold_until, ev: DispatchEvidence) -> str:
        f = self.floor
        if key == "suppress_upstream":
            return (f"Upstream fault: line is inside {inc.incident_id} ({inc.element_type} {inc.element_id}, Confirmed, "
                    f"{'crew assigned' if inc.crew_assigned else 'SNOW ' + ', '.join(inc.snow_refs)}). Physical signal on the same element "
                    f"({'optical drop' if inc.score_components.get('_optical_share', 0) >= 0.5 else 'reachability loss' if inc.score_components.get('_reach_share', 0) >= 0.5 else 'repeat LOS'}). "
                    f"Support {inc.support_score:.2f} >= floor {f:.2f}. A truck roll would not fix this line.")
        if key == "restored_upstream":
            return (f"Upstream fault {inc.incident_id} restored at {hm(inc.closed_at)}; gateway Rx back to "
                    f"{sig['gateway_rx_dbm']} dBm. Recommend closing the order after customer confirmation; no truck roll.")
        if key == "hold_incident_pending":
            why = "awaiting NOC confirmation" if inc.state == "Proposed" else "awaiting a SNOW reference or physical signal"
            return (f"Line is inside {inc.incident_id} ({inc.element_type} {inc.element_id}, {inc.state}, {why}). "
                    f"Hold and recheck until {hm(hold_until)}; suppress only after confirmation.")
        if key == "below_floor_incident":
            return f"Line is inside {inc.incident_id} but support {inc.support_score:.2f} is below the floor {f:.2f}: suppress and hold are unreachable. Dispatch."
        if key == "below_floor_line":
            return f"Line-level hold support {ev.line_hold_support:.2f} is below the floor {f:.2f}: hold is unreachable. Dispatch."
        if key == "hold_line_silent":
            h = sig.get("handyman_last")
            return (f"Only evidence is a {sig['handyman_age_h']:.0f}-hour-old Handyman check"
                    f"{' (' + h['audit_no'] + ')' if h else ''}; gateway silent since {sig['gateway_last_seen'][11:16] if sig['gateway_last_seen'] else 'unknown'} "
                    f"while {sig['siblings']['healthy']} of {sig['siblings']['siblings']} neighbours are healthy. Looks like customer-side power or "
                    f"equipment off, but the power check is unavailable. Hold support {ev.line_hold_support:.2f}. Recheck at {hm(hold_until)}; "
                    f"dispatch then if nothing changes.")
        if key == "hold_expired":
            return "Hold expired with no new evidence. Dispatch."
        if key == "handyman_stalled_hold":
            return "Handyman feed is stalled: the hold depends on Handyman evidence that cannot be refreshed. Falls back to dispatch until the feed resumes."
        if key == "handyman_stalled_cpe":
            return "Handyman feed is stalled: the CPE signature cannot be refreshed. Dispatch by default."
        if key == "cpe_signature":
            return (f"CPE signature: healthy optical ({sig['gateway_rx_dbm']} dBm vs baseline {sig['gateway_baseline_dbm']}), "
                    f"ModemStatus = Inactive/Modem not found in Handyman, {sig['siblings']['healthy']} of {sig['siblings']['siblings']} neighbours healthy, "
                    f"no incident upstream. Customer-side fault: dispatch with CPE replacement kit.")
        if key == "drop_signature":
            return f"Drop-fibre signature: this gateway's Rx is {sig['gateway_rx_dbm']} dBm while neighbours are healthy. Dispatch."
        if key == "no_nap":
            return "Subscriber record has a blank nap: the line cannot be placed inside any blast radius. Dispatch; reported at cluster level."
        return "No upstream cause found and no customer-side signature that justifies holding. Standard dispatch."
