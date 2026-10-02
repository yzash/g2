"""Deterministic support score and isolation hypothesis (UC1).

The score is a weighted sum of ticket density, physical signal share, sibling
cleanliness and alarm presence, with weights from config. It is shown as a
support score, not a probability, until calibrated on adjudicated cases.
No language model computes or adjusts it.
"""

from __future__ import annotations

import pandas as pd

from .views import Snapshot


class Scorer:
    def __init__(self, snap: Snapshot, cfg: dict, signals: list):
        self.snap = snap
        self.cfg = cfg
        self.w = cfg["support_score"]["weights"]
        self.thr = cfg["support_score"]["ticket_density_threshold"]
        tp = snap.topology
        self.tp = tp
        since = snap.window(cfg["detectors"]["ticket_burst_window_hours"] * 60)

        acct_nap = snap.static.acct_to_line.nap
        o = snap.orders
        o = o[(o.skillset == "Repair") & (o.createdate >= since)]
        h = snap.handyman
        h = h[(h.date_time >= since) & ((h.LineStatus == "Account has a last mile issue") | (h.Result == "FAILED"))]
        obs = pd.concat([o.accountnumber, h.account_number]).drop_duplicates()
        self.obs_by_nap: dict[str, set] = {}
        for acct in obs:
            nap = acct_nap.get(acct)
            if isinstance(nap, str):
                self.obs_by_nap.setdefault(nap, set()).add(acct)
        orp = snap.open_repairs
        orp = orp[orp.createdate >= since]
        self.open_orders_by_nap = orp.facilityname.value_counts().to_dict()
        self.flap_by_nap = {s.element_id: set(s.detail["tickets"]) for s in signals if s.detector == "flap"}
        self.alarm_elements = {s.element_id for s in signals if s.detector == "alarm"}
        self.signal_naps = {n for s in signals if not s.corroboration_only for n in s.naps}
        self._cache: dict = {}

    # -- element helpers --------------------------------------------------------
    def naps(self, etype: str, eid: str) -> list[str]:
        return self.snap.naps_under(etype, eid)

    def observed(self, etype: str, eid: str) -> set:
        out = set()
        for n in self.naps(etype, eid):
            out |= self.obs_by_nap.get(n, set())
        return out

    def flap_tickets(self, etype: str, eid: str) -> set:
        out = set()
        for n in self.naps(etype, eid):
            out |= self.flap_by_nap.get(n, set())
        return out

    def is_clean(self, etype: str, eid: str) -> bool:
        key = ("clean", etype, eid)
        if key not in self._cache:
            st = self.snap.element_stats(etype, eid)
            orders = sum(self.open_orders_by_nap.get(n, 0) for n in st["naps"])
            limit = self.thr[etype] if etype in self.thr else 3
            self._cache[key] = st["optical_share"] < 0.3 and st["reach_share"] < 0.3 and orders < limit and not self.flap_tickets(etype, eid)
        return self._cache[key]

    def siblings(self, etype: str, eid: str) -> list[tuple[str, str]]:
        key = ("sib", etype, eid)
        if key in self._cache:
            return self._cache[key]
        tp = self.tp
        if etype == "NAP":
            lcp = tp.LCP[eid]
            out = [("NAP", n) for n in self.snap.naps_under("LCP", lcp) if n != eid]
        elif etype == "LCP":
            olt = tp.OLT[self.snap.naps_under("LCP", eid)[0]]
            out = [("LCP", l) for l in sorted({tp.LCP[n] for n in self.snap.naps_under("OLT", olt)}) if l != eid]
        else:
            site = eid.split("_")[1]
            out = [("OLT", o) for o in sorted(set(tp.OLT)) if o != eid and o.split("_")[1] == site]
        self._cache[key] = out
        return out

    def alarm_on(self, etype: str, eid: str) -> bool:
        if not self.alarm_elements:
            return False
        naps = set(self.naps(etype, eid))
        chain = set()
        for n in naps:
            chain |= {n, self.tp.LCP[n], self.tp.OLT[n]}
        return bool(self.alarm_elements & chain)

    # -- score -------------------------------------------------------------------
    def components(self, etype: str, eid: str) -> dict:
        key = (etype, eid)
        if key in self._cache:
            return self._cache[key]
        st = self.snap.element_stats(etype, eid)
        flaps = self.flap_tickets(etype, eid)
        obs = self.observed(etype, eid)
        ticket = min(1.0, (len(obs) + len(flaps)) / self.thr[etype])
        # repeat LOS is a physical signal on the flapping NAPs only; it dilutes at LCP and OLT level
        flap_gw = sum(self.snap.element_stats("NAP", n)["n_gw"] for n in self.flap_by_nap if n in set(st["naps"]))
        flap_c = min(1.0, len(flaps) / 2) * (flap_gw / st["n_gw"] if st["n_gw"] else 0.0)
        physical = max(st["optical_share"], st["reach_share"], flap_c)
        sibs = self.siblings(etype, eid)
        sib_clean = (sum(self.is_clean(t, s) for t, s in sibs) / len(sibs)) if sibs else 0.5
        alarm = 1.0 if self.alarm_on(etype, eid) else 0.0
        c = {"ticket_density": round(ticket, 4), "physical_signal": round(physical, 4),
             "sibling_cleanliness": round(sib_clean, 4), "alarm_presence": alarm,
             "_observed": len(obs), "_optical_share": round(st["optical_share"], 4), "_reach_share": round(st["reach_share"], 4),
             "_flap_tickets": len(flaps), "_n_gw": int(st["n_gw"]), "_siblings": len(sibs),
             "_siblings_clean": int(round(sib_clean * len(sibs))) if sibs else 0}
        self._cache[key] = c
        return c

    def score(self, etype: str, eid: str) -> tuple[float, dict]:
        c = self.components(etype, eid)
        s = sum(self.w[k] * c[k] for k in self.w)
        return round(s, 2), c

    def best(self, nap: str) -> list[dict]:
        """Ranked isolation hypotheses for a NAP: NAP-, LCP- and OLT-level."""
        key = ("best", nap)
        if key in self._cache:
            return self._cache[key]
        out = []
        for etype, eid in self.snap.chain(nap):
            s, c = self.score(etype, eid)
            out.append({"element_type": etype, "element_id": eid, "score": s, "components": c})
        level = {"NAP": 0, "LCP": 1, "OLT": 2}
        out.sort(key=lambda h: (-h["score"], level[h["element_type"]]))
        self._cache[key] = out
        return out


def severity_for(cfg: dict, etype: str, lines: int) -> str:
    for cut, label in cfg["severity"][etype]:
        if lines >= cut:
            return label
    return cfg["severity"][etype][-1][1]
