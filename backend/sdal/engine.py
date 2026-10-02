"""Replay engine: runs the synthetic day minute by minute.

Feeds land on their cadence, detectors and the Investigator run every five
minutes, the other agents react to events, and scripted human decisions are
applied at their clock times. Everything the operator surface shows is
recorded as a timestamped event so the morning replays identically.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pandas as pd

from . import RAW_DIR
from . import tools as T
from .agents.dispatch import DispatchReviewer, eligible
from .agents.investigator import Investigator
from .agents.notifier import Notifier
from .agents.prioritizer import Prioritizer
from .config import load_config, ts
from .curated import FeedModel, build_curated
from .detectors import run_detectors
from .models import AdoptionRecord
from .script import SCRIPT
from .trace import Tracer
from .views import Snapshot, Static


def fmt(t) -> str | None:
    return None if t is None else pd.Timestamp(t).strftime("%Y-%m-%d %H:%M:%S")


class State:
    def __init__(self, engine: "Engine"):
        self.e = engine
        self.incidents: dict = {}
        self.recs: dict[str, list] = {}
        self.queue: list = []
        self.packages: dict = {}
        self.package_recipients: dict = {}
        self.adoption: list = []
        self.contact_policy_rows: list = []
        self.abstentions: list = []
        self.feed_status: dict = {}
        self.events: list = []

    def _ev(self, kind: str, change: str, oid: str, obj: dict) -> None:
        self.events.append({"t": fmt(self.e.now), "kind": kind, "change": change, "id": oid, "obj": obj})

    def put_incident(self, inc, change: str) -> None:
        old = self.incidents.get(inc.incident_id)
        if old is not None:
            inc.version = old.version + 1
        self.incidents[inc.incident_id] = inc
        self._ev("incident", change, inc.incident_id, inc.model_dump())

    def latest_rec(self, wo: str):
        v = self.recs.get(wo)
        return v[-1] if v else None

    def put_rec(self, rec) -> None:
        self.recs.setdefault(rec.workordernumber, []).append(rec)
        self._ev("rec", "recommended" if rec.review_seq == 1 else "re-reviewed", rec.rec_id, rec.model_dump())

    def update_rec(self, rec, change: str) -> None:
        self._ev("rec", change, rec.rec_id, rec.model_dump())

    def put_queue(self, rows, reason: str, run_id: str) -> None:
        self.queue = rows
        self._ev("queue", reason, f"QR-{fmt(self.e.now)}", {"reason": reason, "run_id": run_id, "rows": [r.model_dump() for r in rows]})

    def put_package(self, pkg, change: str) -> None:
        self.packages[pkg.package_id] = pkg
        self._ev("package", change, pkg.package_id, pkg.model_dump())

    def add_adoption(self, rec: AdoptionRecord) -> None:
        self.adoption.append(rec)
        self._ev("adoption", rec.decision, rec.record_id, rec.model_dump())

    def add_abstention(self, a: dict) -> None:
        self.abstentions.append(a)
        self._ev("abstention", "abstained", a["abstention_id"], a)


class Engine:
    def __init__(self, con=None, script=None, cfg_overrides: dict | None = None):
        self.cfg = json.loads(json.dumps(load_config()))
        for path, value in (cfg_overrides or {}).items():
            node = self.cfg
            keys = path.split(".")
            for k in keys[:-1]:
                node = node[k]
            node[keys[-1]] = value
        self.con = con or build_curated()
        self.static = Static(self.con)
        Snapshot.drop_db = self.cfg["detectors"]["optical_drop_db"]
        self.feeds = FeedModel(self.cfg)
        self.tracer = Tracer()
        self.state = State(self)
        self.evidence: dict = {}
        self.cache: dict = {}
        self.truth = json.load(open(RAW_DIR / "_generator_truth.json"))["truth"]
        self.script = sorted(script if script is not None else SCRIPT, key=lambda s: s["at"])

        self.uc1 = Investigator(self)
        self.uc2 = DispatchReviewer(self)
        self.uc3 = Prioritizer(self)
        self.uc5 = Notifier(self)

        self.now: datetime = ts(self.cfg["clock"]["engine_start"])
        self.seq = self.cfg["registry"]["seq_start"]
        self.pkg_seq = 0
        self.adopt_seq = 0
        self.watch: dict = {}
        self.first_signal: dict = {}
        self.observed_accounts: dict = {}
        self.physical_ids: dict = {}
        self.covered_keys: dict = {}
        self.hold_anchor: dict = {}
        self.rec_keys: dict = {}
        self.abstained: set = set()
        self.current_signal_naps: set = set()
        self.current_alarm_elements: set = set()
        self.paused_detectors: list = []
        self.last_scorer = None
        self.uc2_due: dict[str, tuple[datetime, str]] = {}
        self.uc5_due: list = []
        self.rerank_due: tuple[datetime, str] | None = None
        self.prev_orders: dict = {}
        self.snapshots: list = []
        self.feed_events: list = []
        self.detector_log: list = []

    # ---- ids ----------------------------------------------------------------
    def next_incident_id(self) -> str:
        i = f"{self.cfg['registry']['id_prefix']}{self.seq:04d}"
        self.seq += 1
        return i

    def next_package_id(self) -> str:
        self.pkg_seq += 1
        return f"PKG-{self.pkg_seq:03d}"

    def ctx(self, snap: Snapshot) -> T.ToolContext:
        return T.ToolContext(snap, self.cfg, self.state, self.tracer, self.evidence)

    # ---- triggers ------------------------------------------------------------
    def request_rerank(self, reason: str, delay: int = 0) -> None:
        due = self.now + timedelta(minutes=delay)
        if self.rerank_due is None or due < self.rerank_due[0]:
            self.rerank_due = (due, reason)

    def request_review(self, wo: str, reason: str, delay: int = 1) -> None:
        due = self.now + timedelta(minutes=delay)
        cur = self.uc2_due.get(wo)
        if cur is None or due < cur[0]:
            self.uc2_due[wo] = (due, reason)

    def on_incident_change(self, inc, change: str) -> None:
        snap = Snapshot(self.con, self.static, self.now, self.cache)
        o = snap.orders
        o = o[o.facilityname.isin(inc.naps)]
        for r in o.to_dict("records"):
            if eligible(r, self.now):
                self.request_review(r["workordernumber"], f"incident {inc.incident_id} {change}")
        if change in ("created", "confirmed", "closed", "crew", "merged", "closure proposed"):
            self.request_rerank(f"incident {inc.incident_id} {change}")
        if change == "confirmed":
            self.uc5_due.append((self.now + timedelta(minutes=2), inc.incident_id, "initial", "incident confirmed"))
        if change == "closed":
            self.uc5_due.append((self.now + timedelta(minutes=2), inc.incident_id, "restoration", "incident closed"))

    # ---- human actions ---------------------------------------------------------
    def adoption(self, actor, role, otype, oid, recommendation, decision, reason, evidence, scripted=True, batch=False) -> None:
        self.adopt_seq += 1
        self.state.add_adoption(AdoptionRecord(record_id=f"ADR-{self.adopt_seq:04d}", at=fmt(self.now), actor=actor, role=role,
                                               object_type=otype, object_id=oid, recommendation=recommendation, decision=decision,
                                               reason=reason, scripted=scripted, batch=batch, evidence_ids=evidence))

    def find_incident(self, element: str, states=("Proposed", "Confirmed")):
        c = [i for i in self.state.incidents.values() if i.element_id == element and i.state in states]
        return c[-1] if c else None

    def resolve_wo(self, target: dict) -> str:
        v = self.truth[target["truth"]]
        return v[target["index"]] if "index" in target else v

    def apply_human(self, act: dict) -> None:
        a = act["action"]
        self.tracer.start("HUMAN", f"{act['actor']}: {a}")
        if a == "confirm_incident":
            inc = self.find_incident(act["target"]["element"], ("Proposed",))
            if inc is None:
                self.tracer.note(f"No proposed incident on {act['target']['element']}; scripted action skipped")
            else:
                p = inc.model_copy(deep=True)
                p.state, p.decided_by, p.decided_at, p.decision_reason = "Confirmed", act["actor"], fmt(self.now), act.get("reason")
                if act.get("snow_ref") and act["snow_ref"] not in p.snow_refs:
                    p.snow_refs = sorted(p.snow_refs + [act["snow_ref"]])
                p.updated_at = fmt(self.now)
                self.state.put_incident(p, "confirmed")
                self.adoption(act["actor"], act["role"], "incident", p.incident_id, f"Proposed {p.element_type}-level incident, support {p.support_score:.2f}",
                              "confirmed", act.get("reason"), [f"SDAL:{p.incident_id}"])
                self.on_incident_change(p, "confirmed")
        elif a == "confirm_closure":
            inc = self.find_incident(act["target"]["element"], ("Confirmed",))
            if inc is None or not inc.closure_proposed_at:
                self.tracer.note("No closure proposal to confirm; scripted action skipped")
            else:
                p = inc.model_copy(deep=True)
                p.state, p.closed_at, p.updated_at = "Closed", fmt(self.now), fmt(self.now)
                self.state.put_incident(p, "closed")
                self.adoption(act["actor"], act["role"], "closure", p.incident_id, f"Closure proposed {p.closure_proposed_at[11:16]}",
                              "confirmed", act.get("reason"), [f"SDAL:{p.incident_id}"])
                self.on_incident_change(p, "closed")
        elif a in ("decide_rec", "accept_pending"):
            if a == "decide_rec":
                wos = [self.resolve_wo(act["target"])]
            else:
                terr = act["target"]["territory"]
                wos = [wo for wo, v in self.state.recs.items() if v[-1].dispatcher_decision is None
                       and (terr == "*" or v[-1].territory == terr) and v[-1].recommended_at < fmt(self.now)]
            for wo in wos:
                rec = self.state.latest_rec(wo)
                if rec is None or rec.dispatcher_decision is not None:
                    continue
                if a == "accept_pending" and any(v.dispatcher_decision == "overridden" for v in self.state.recs[wo]):
                    continue  # the dispatcher already took ownership of this order
                r = rec.model_copy(deep=True)
                r.dispatcher_decision = act.get("decision", "accepted")
                actor = act["actor"] if a == "decide_rec" or act["target"]["territory"] != "*" else f"Dispatcher {r.territory}"
                r.decided_by, r.decided_at = actor, fmt(self.now)
                if r.dispatcher_decision == "overridden":
                    r.override_reason, r.override_outcome = act.get("reason"), act.get("override_outcome")
                self.state.recs[wo][-1] = r
                self.state.update_rec(r, r.dispatcher_decision)
                self.adoption(actor, act["role"], "dispatch", r.rec_id, f"{r.outcome} ({r.reason_class})",
                              r.dispatcher_decision, r.override_reason, r.evidence_ids[:3], batch=(a == "accept_pending"))
        elif a == "approve_package":
            inc = self.find_incident(act["target"]["element"], ("Confirmed", "Closed"))
            pk = [p for p in self.state.packages.values() if inc and p.incident_id == inc.incident_id and p.state == "Draft"]
            if not pk:
                self.tracer.note("No draft package to approve; scripted action skipped")
            else:
                p = pk[-1].model_copy(deep=True)
                p.state, p.approver, p.decided_at, p.decision_note = "Approved", act["actor"], fmt(self.now), act.get("reason")
                p.send_state = "Approved draft. Not sent: NG1 handoff disabled in demo (consent source unavailable in pilot)."
                self.state.put_package(p, "approved")
                self.adoption(act["actor"], act["role"], "package", p.package_id, f"{p.kind} notice to {p.recipients_total} recipients",
                              "approved", act.get("reason"), [f"SDAL:{p.incident_id}"])
        self.tracer.end()

    # ---- main loop ------------------------------------------------------------
    def run(self) -> "Engine":
        end = ts(self.cfg["clock"]["replay_end"])
        replay_start = ts(self.cfg["clock"]["replay_start"])
        script = list(self.script)
        while self.now <= end:
            self.tracer.now = self.now
            snap = Snapshot(self.con, self.static, self.now, self.cache)
            ctx = self.ctx(snap)

            # 1. feed health
            for src in self.cfg["feeds"]:
                if src.startswith("_"):
                    continue
                h = self.feeds.health(src, self.now)
                prev = self.state.feed_status.get(src)
                self.state.feed_status[src] = h["status"]
                if prev is not None and prev != h["status"]:
                    self.feed_events.append({"t": fmt(self.now), "source": src, "from": prev, "to": h["status"]})
                    self.state._ev("feed", h["status"], src, h)
                    if src == "HANDYMAN":
                        for wo, v in self.state.recs.items():
                            if v[-1].incident_id is None:
                                self.request_review(wo, f"Handyman feed {h['status']}")

            # 2. scripted human decisions
            while script and script[0]["at"] <= self.now.strftime("%Y-%m-%d %H:%M"):
                act = script.pop(0)
                if act["at"] == self.now.strftime("%Y-%m-%d %H:%M"):
                    self.apply_human(act)

            # 3. FSM landing: new or changed eligible orders
            if self.now.minute % 5 == 0:
                cur = {}
                for r in snap.orders.to_dict("records"):
                    cur[r["workordernumber"]] = r["lastupdatedate"]
                    if eligible(r, self.now) and self.prev_orders.get(r["workordernumber"]) != r["lastupdatedate"]:
                        rec = self.state.latest_rec(r["workordernumber"])
                        self.request_review(r["workordernumber"], "new order" if rec is None else "order updated")
                self.prev_orders = cur

            # 4. detectors + Investigator, two minutes after each landing
            if self.now.minute % 5 == 2:
                signals, paused = run_detectors(snap, self.cfg, self.state.feed_status)
                self.detector_log.append({"t": fmt(self.now), "signals": [(s.detector, s.element_id) for s in signals], "paused": paused})
                if paused:
                    for p in paused:
                        self.state._ev("detector", "paused", p["detector"], p)
                self.uc1.tick(ctx, signals, paused)
                # restoration targets published since the last tick
                rt = self.static.restoration
                for r in rt[(rt._arrived_at > pd.Timestamp(self.now - timedelta(minutes=5))) & (rt._arrived_at <= pd.Timestamp(self.now))].to_dict("records"):
                    for inc in self.state.incidents.values():
                        if inc.state == "Confirmed" and r["inc_number"] in inc.snow_refs:
                            self.uc5_due.append((self.now + timedelta(minutes=1), inc.incident_id, "update", "restoration target changed"))
                # update due after an approved message
                for inc in self.state.incidents.values():
                    if inc.state != "Confirmed":
                        continue
                    appr = [p for p in self.state.packages.values() if p.incident_id == inc.incident_id and p.state == "Approved"]
                    if appr:
                        last = max(pd.Timestamp(p.scheduled_send_at) for p in appr)
                        if last + pd.Timedelta(hours=self.cfg["notification"]["update_trigger_hours"]) <= pd.Timestamp(self.now) and \
                                not any(p.incident_id == inc.incident_id and p.built_at > fmt(last) for p in self.state.packages.values()):
                            self.uc5_due.append((self.now, inc.incident_id, "update", "2 hours since last update"))

            # 5. hold expiries
            for (wo, _), until in list(self.hold_anchor.items()):
                rec = self.state.latest_rec(wo)
                if rec and rec.outcome == "hold" and until <= fmt(self.now) and wo not in self.uc2_due:
                    self.request_review(wo, "hold expired", delay=1)

            # 6. UC2 reviews due
            for wo, (due, reason) in sorted(self.uc2_due.items()):
                if due <= self.now:
                    self.uc2_due.pop(wo)
                    row = snap.orders[snap.orders.workordernumber == wo]
                    if row.empty:
                        continue
                    r = row.iloc[0].to_dict()
                    if eligible(r, self.now):
                        self.uc2.review(ctx, r, reason)

            # 7. UC5 packages due
            for item in sorted([x for x in self.uc5_due if x[0] <= self.now]):
                self.uc5_due.remove(item)
                inc = self.state.incidents[item[1]]
                self.uc5.build(ctx, inc, item[2], item[3])

            # 8. UC3 re-rank (events, plus every 15 minutes)
            if self.now.minute % self.cfg["queue"]["rerank_every_min"] == 0:
                self.request_rerank("scheduled (every 15 minutes)")
            if self.rerank_due and self.rerank_due[0] <= self.now:
                reason = self.rerank_due[1]
                self.rerank_due = None
                self.uc3.rerank(ctx, reason)

            # 9. snapshot for the surface
            if self.now >= replay_start or self.now.minute % 5 == 0:
                self.snapshots.append(self.snapshot(snap))
            self.now += timedelta(minutes=1)
        self.now = end
        self.finalize()
        return self

    # ---- surface snapshot -------------------------------------------------------
    def snapshot(self, snap: Snapshot) -> dict:
        states: dict[str, str] = {}
        rank = {"confirmed": 4, "proposed": 3, "signal": 2, "snow": 1}

        def put(nap, s):
            if rank[s] > rank.get(states.get(nap, ""), 0):
                states[nap] = s

        for n in snap.open_snow.affected_nap:
            put(n, "snow")
        for n in self.current_signal_naps:
            put(n, "signal")
        for inc in self.state.incidents.values():
            if inc.state in ("Proposed", "Confirmed"):
                for n in inc.naps:
                    put(n, "confirmed" if inc.state == "Confirmed" else "proposed")
        pending = sum(1 for v in self.state.recs.values() if v[-1].dispatcher_decision is None
                      and eligible(snap.orders[snap.orders.workordernumber == v[-1].workordernumber].iloc[0].to_dict(), self.now))
        return {
            "t": fmt(self.now),
            "feeds": {s: self.feeds.health(s, self.now) for s in self.cfg["feeds"] if not s.startswith("_")},
            "nap_states": states,
            "alarm_elements": sorted(self.current_alarm_elements),
            "paused": self.paused_detectors,
            "wms_horizon": fmt(snap.wms_horizon),
            "counts": {
                "open_orders": int(len(snap.open_repairs)),
                "open_incidents": sum(1 for i in self.state.incidents.values() if i.state in ("Proposed", "Confirmed")),
                "proposed": sum(1 for i in self.state.incidents.values() if i.state == "Proposed"),
                "pending_reviews": pending,
                "open_snow": int(snap.open_snow.inc_number.nunique()),
                "drafts": sum(1 for p in self.state.packages.values() if p.state == "Draft"),
            },
        }

    # ---- after the morning: observed outcomes, lead times, safety class -----------
    def finalize(self) -> None:
        snap = Snapshot(self.con, self.static, self.now, self.cache)
        final = snap.orders.set_index("workordernumber")

        def outcome_for(wo: str) -> str:
            if wo not in final.index:
                return "unknown"
            r = final.loc[wo]
            if r.status == "Cancelled":
                return f"Closed without visit: {r.cancellationreason} (FSM {str(r.lastupdatedate)[11:16]})"
            if r.status == "Completed":
                return f"Visit completed {str(r.lastupdatedate)[11:16]}: {r.FIXSEGMENT}; {r.finddescription}"
            return f"Still {r.status} at {fmt(self.now)[11:16]}"

        self.safety = []
        for wo, versions in self.state.recs.items():
            out = outcome_for(wo)
            for v in versions:
                v.outcome_observed = out
            last = versions[-1]
            r = final.loc[wo] if wo in final.index else None
            followed_non_dispatch = any(v.outcome in ("suppress", "hold") and v.dispatcher_decision != "overridden" for v in versions)
            if followed_non_dispatch and r is not None and r.status == "Completed" and r.FIXSEGMENT in ("CUSTOMER PREMISE", "FIBERDROP TO NAP", "CUSTOMER RELATED"):
                self.safety.append({"workordernumber": wo, "fix": r.FIXSEGMENT})
        for a in self.state.adoption:
            if a.object_type == "dispatch":
                wo = a.object_id.split("-")[1]
                a.outcome_observed = outcome_for(wo)
            elif a.object_type in ("incident", "closure"):
                inc = self.state.incidents.get(a.object_id)
                a.outcome_observed = f"{inc.state}" + (f" at {inc.closed_at[11:16]}" if inc and inc.closed_at else "") if inc else None
            elif a.object_type == "package":
                a.outcome_observed = "Approved draft; not sent (NG1 handoff disabled in demo)"

        # detection lead time against today's hourly manual cycle (ticket counts + NMS alarms, top of each hour)
        o_all = self.con.execute("SELECT * FROM c_order_versions").fetchdf()
        alarms = self.con.execute("SELECT * FROM c_alarms").fetchdf()
        snow_all = self.con.execute("SELECT * FROM c_snow_versions").fetchdf()
        for inc in self.state.incidents.values():
            if inc.state == "Merged":
                continue
            first_snow = snow_all[snow_all.affected_nap.isin(inc.naps)].ticket_created_datetime.min()
            if not pd.isna(first_snow) and first_snow <= pd.Timestamp(inc.proposed_at):
                inc.hourly_cycle_at = None
                inc.detection_lead_min = None
                continue
            t = pd.Timestamp(inc.first_signal_at or inc.proposed_at).floor("h")
            thr = self.cfg["detectors"]["ticket_burst_olt_min_orders" if inc.element_type == "OLT" else "ticket_burst_nap_min_orders"]
            for _ in range(24):
                t += pd.Timedelta(hours=1)
                vis = o_all[o_all._arrived_at <= t].sort_values("lastupdatedate").groupby("workordernumber").tail(1)
                vis = vis[(vis.skillset == "Repair") & vis.status.isin(["Open", "Unassigned", "Pending", "Delayed", "Ongoing"]) &
                          vis.facilityname.isin(inc.naps) & (vis.createdate >= t - pd.Timedelta(hours=6))]
                al = alarms[(alarms._arrived_at <= t) & alarms.ne_name.isin(set(inc.naps) | {inc.lcp, inc.olt})]
                if len(vis) >= thr or len(al):
                    inc.hourly_cycle_at = fmt(t)
                    inc.detection_lead_min = int((t - pd.Timestamp(inc.proposed_at)).total_seconds() // 60)
                    break
        # refresh the last event of each incident with the evaluation fields
        for inc in self.state.incidents.values():
            for ev in reversed(self.state.events):
                if ev["kind"] == "incident" and ev["id"] == inc.incident_id:
                    ev["obj"]["hourly_cycle_at"] = inc.hourly_cycle_at
                    ev["obj"]["detection_lead_min"] = inc.detection_lead_min
            for ev in self.state.events:
                if ev["kind"] == "incident" and ev["id"] == inc.incident_id:
                    ev["obj"]["hourly_cycle_at"] = inc.hourly_cycle_at
                    ev["obj"]["detection_lead_min"] = inc.detection_lead_min
        for ev in self.state.events:
            if ev["kind"] == "rec":
                wo = ev["obj"]["workordernumber"]
                ev["obj"]["outcome_observed"] = outcome_for(wo)
            if ev["kind"] == "adoption":
                match = next((a for a in self.state.adoption if a.record_id == ev["id"]), None)
                if match:
                    ev["obj"]["outcome_observed"] = match.outcome_observed
