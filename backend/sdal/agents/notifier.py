"""Agent 4: Customer Notification (UC5).

Turns a Confirmed incident into a draft, policy-checked notification package
routed to Globe's communications approver. Nothing is sent: ng1_handoff is the
single governed write and no code path in the demo calls it.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from .. import tools as T
from ..models import NotificationPackage, PolicyResult

NAME = "UC5"


def fmt(t) -> str | None:
    return None if t is None else pd.Timestamp(t).strftime("%Y-%m-%d %H:%M:%S")


def h12(s: str) -> str:
    return pd.Timestamp(s).strftime("%-I:%M %p")


class Notifier:
    def __init__(self, engine):
        self.e = engine
        self.cfg = engine.cfg

    def build(self, ctx: T.ToolContext, inc, kind: str, trigger: str) -> NotificationPackage:
        e = self.e
        run_id = e.tracer.start(NAME, f"{trigger}: {inc.incident_id}")
        res = T.subscriber_resolve(ctx, incident=inc)
        recipients = res.data
        rt = T.restoration_target_read(ctx, snow_refs=inc.snow_refs)
        pol = T.contact_policy_check(ctx, recipients=recipients, incident_id=inc.incident_id, kind=kind)
        earliest = pol.data["earliest_send"]

        geo = ctx.snap.static.nap_geo
        g = geo.loc[inc.naps[0]]
        area = f"Barangay {g.barangay}, {g.town}" if inc.element_type == "NAP" else (
            f"parts of {g.town}" if inc.element_type in ("LCP", "OLT") else g.town)
        ref = inc.snow_refs[0] if inc.snow_refs else inc.incident_id
        start = (inc.first_signal_at or inc.proposed_at)
        target = rt.data["target"] if rt.data else None
        next_update = None
        if kind == "restoration":
            text = (f"Service advisory: Fibre internet service in {area} was restored at {h12(inc.closed_at)}. "
                    f"If your connection is still down, please restart your modem; if that does not help, reply to this message. "
                    f"Reference {ref}.")
        else:
            if target:
                tsent = f"Our current restoration target is {h12(target)}."
            else:
                next_update = fmt(max(pd.Timestamp(earliest), pd.Timestamp(ctx.now)) + timedelta(hours=self.cfg["notification"]["next_update_hours_if_no_target"]))
                tsent = f"We will send the next update by {h12(next_update)}."
            text = (f"Service advisory: We are aware of an issue affecting fibre internet service in {area} since {h12(start)}. "
                    f"Our technical team is working on it. {tsent} Reference {ref}. You do not need to report this issue again.")
        obs = sum(1 for r in recipients if r["observed"])
        vip = sum(1 for r in recipients if r["segment"] == "VIP/B2B")
        pid = e.next_package_id()
        # supersede an earlier unapproved draft for the same incident
        for p in list(e.state.packages.values()):
            if p.incident_id == inc.incident_id and p.state == "Draft":
                q = p.model_copy(deep=True)
                q.state = "Withheld"
                q.decision_note = f"Superseded by {pid} before approval"
                q.decided_at = fmt(ctx.now)
                e.state.put_package(q, "superseded")
        T.notification_package_build(ctx, package_id=pid, incident_id=inc.incident_id, kind=kind)
        T.reply_capture_read(ctx, package_id=pid)
        pkg = NotificationPackage(
            package_id=pid, incident_id=inc.incident_id, kind=kind, recipients_total=len(recipients), recipients_observed=obs,
            recipients_inferred=len(recipients) - obs, recipients_vip=vip, recipients_mass=len(recipients) - vip,
            recipient_tokens_sample=[r["subscriber_id"] for r in recipients[:6]], text=text, restoration_target=target,
            next_update_at=next_update, scheduled_send_at=earliest,
            policy_results=[PolicyResult(**x) for x in pol.data["results"]], built_at=fmt(ctx.now), trigger=trigger,
            ng1_payload_preview={"endpoint": "NG1 notification handoff (DISABLED IN DEMO)", "package_id": pid, "template": f"outage_{kind}_en",
                                 "recipient_tokens": len(recipients), "send_at": earliest, "re_identification": "inside Globe at the point of contact"},
            run_id=run_id, evidence_ids=[f"SDAL:{inc.incident_id}"] + res.evidence_ids[:8] + rt.evidence_ids,
        )
        e.state.package_recipients[pid] = [r["subscriber_id"] for r in recipients]
        e.tracer.note("Consent source unavailable in pilot: package is draft-only by rule. ng1_handoff not called.")
        e.tracer.output("notification_package", pid)
        e.tracer.end()
        e.state.put_package(pkg, "built")
        return pkg
