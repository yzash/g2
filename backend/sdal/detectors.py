"""Deterministic detectors on the curated layer, run every 5 minutes.

ticket-burst (Globe's thresholds), optical-drop, reachability, complaint-burst
(Handyman), flap (short repeat SNOW tickets) and the alarm sample, which is
corroboration only. A detector whose source is late or stalled pauses and says
so; a stalled feed is never read as a quiet network.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .views import Snapshot

DETECTOR_SOURCES = {
    "ticket_burst": ["FSM"],
    "ticket_burst_olt": ["FSM"],
    "optical_drop": ["WMS"],
    "reachability": ["WMS"],
    "complaint_burst": ["HANDYMAN"],
    "flap": ["SNOW"],
    "alarm": ["ALARMS"],
}


@dataclass
class Signal:
    detector: str
    element_type: str
    element_id: str
    naps: list[str]
    detail: dict = field(default_factory=dict)

    @property
    def corroboration_only(self) -> bool:
        return self.detector == "alarm"


def run_detectors(snap: Snapshot, cfg: dict, feed_status: dict) -> tuple[list[Signal], list[dict]]:
    d = cfg["detectors"]
    signals: list[Signal] = []
    paused: list[dict] = []
    tp = snap.topology

    def ok(det: str) -> bool:
        bad = [s for s in DETECTOR_SOURCES[det] if feed_status.get(s, "on time") != "on time"]
        if bad:
            paused.append({"detector": det, "source": bad[0], "status": feed_status.get(bad[0]),
                           "note": f"{det} paused: {bad[0]} feed {feed_status.get(bad[0])}; no detection from this source until it resumes"})
            return False
        return True

    # ---- ticket-burst: 3+ open repair orders on a NAP, 10+ on an OLT, rolling 6h ----
    if ok("ticket_burst"):
        o = snap.open_repairs
        o = o[o.createdate >= snap.window(d["ticket_burst_window_hours"] * 60)]
        o = o[o.facilityname.notna() & o.facilityname.isin(tp.index)]
        for nap, g in o.groupby("facilityname"):
            if len(g) >= d["ticket_burst_nap_min_orders"]:
                signals.append(Signal("ticket_burst", "NAP", nap, [nap], {"orders": sorted(g.workordernumber)}))
        o = o.assign(OLT=o.facilityname.map(tp.OLT))
        for olt, g in o.groupby("OLT"):
            if len(g) >= d["ticket_burst_olt_min_orders"]:
                signals.append(Signal("ticket_burst_olt", "OLT", olt, sorted(set(g.facilityname)), {"orders": sorted(g.workordernumber)}))

    # ---- WMS: optical-drop and reachability -----------------------------------
    if snap.wms_horizon is not None:
        st = snap.nap_stats
        st = st[st.index.isin(tp.index)]
        if ok("optical_drop"):
            hit = st[(st.n_fresh >= 3) & (st.optical_share >= d["optical_drop_min_share"])]
            for nap, r in hit.iterrows():
                signals.append(Signal("optical_drop", "NAP", nap, [nap], {"share": round(float(r.optical_share), 3), "n_drop": int(r.n_drop), "n_fresh": int(r.n_fresh)}))
        if ok("reachability"):
            hit = st[(st.n_known >= 3) & (st.reach_share > d["reachability_min_share"])]
            for nap, r in hit.iterrows():
                signals.append(Signal("reachability", "NAP", nap, [nap], {"share": round(float(r.reach_share), 3), "n_silent": int(r.n_silent), "n_known": int(r.n_known)}))

    # ---- complaint-burst: 3+ distinct accounts with a last-mile failure in 60 min (Handyman) ----
    if ok("complaint_burst"):
        h = snap.handyman
        h = h[(h.date_time >= snap.window(d["complaint_burst_window_min"])) & h.nap.notna() & h.nap.isin(tp.index)]
        h = h[(h.LineStatus == "Account has a last mile issue") | (h.Result == "FAILED")]
        for nap, g in h.groupby("nap"):
            if g.account_number.nunique() >= d["complaint_burst_min_checks"]:
                signals.append(Signal("complaint_burst", "NAP", nap, [nap], {"audits": sorted(g.audit_no)}))

    # ---- flap: short repeat SNOW tickets on one NAP ----------------------------
    if ok("flap"):
        s = snap.snow
        s = s[s.ticket_created_datetime >= snap.window(d["flap_window_hours"] * 60)]
        s = s[s.resolution_hours.notna() & (s.resolution_hours * 60 <= d["flap_max_ticket_minutes"])]
        for nap, g in s.groupby("affected_nap"):
            if g.inc_number.nunique() >= d["flap_min_tickets"] and nap in tp.index:
                signals.append(Signal("flap", "NAP", nap, [nap], {"tickets": sorted(set(g.inc_number))}))

    # ---- alarm sample: corroboration only --------------------------------------
    if ok("alarm"):
        for r in snap.alarms_open.itertuples():
            ne = r.ne_name
            if ne in tp.index:
                signals.append(Signal("alarm", "NAP", ne, [ne], {"alarm_id": r.alarm_id}))
            elif (tp.LCP == ne).any():
                signals.append(Signal("alarm", "LCP", ne, sorted(tp.index[tp.LCP == ne]), {"alarm_id": r.alarm_id}))
            elif (tp.OLT == ne).any():
                signals.append(Signal("alarm", "OLT", ne, sorted(tp.index[tp.OLT == ne]), {"alarm_id": r.alarm_id}))
    return signals, paused
