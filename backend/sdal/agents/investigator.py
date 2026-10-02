"""Agent 1: Incident Investigator (UC1).

Turns candidate signals into one deduplicated, explainable incident object.
Fixed contract, implemented as tool calls in this order: ticket_cluster_read,
incident_registry.search, topology_lookup, sibling_health, telemetry_read,
exposure_calc, incident_registry.create, rationale. It never creates an
incident in any state other than Proposed; a human confirms.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from .. import tools as T
from ..detectors import Signal
from ..models import Hypothesis, Incident
from ..scoring import Scorer, severity_for

NAME = "UC1"


def hhmm(s: str | None) -> str:
    return s[11:16] if s else "--:--"


class Investigator:
    def __init__(self, engine):
        self.e = engine
        self.cfg = engine.cfg

    # ------------------------------------------------------------------
    def tick(self, ctx: T.ToolContext, signals: list[Signal], paused: list[dict]) -> None:
        e = self.e
        scorer = Scorer(ctx.snap, self.cfg, signals)
        e.last_scorer = scorer
        groups: dict[tuple[str, str], dict] = {}
        for s in signals:
            if s.corroboration_only:
                continue
            anchor = s.naps[0]
            if s.element_type == "OLT":
                o = ctx.snap.open_repairs
                counts = o[o.facilityname.isin(s.naps)].facilityname.value_counts()
                anchor = counts.index[0] if len(counts) else s.naps[0]
            ranked = scorer.best(anchor)
            top = ranked[0]
            key = (top["element_type"], top["element_id"])
            g = groups.setdefault(key, {"signals": [], "ranked": ranked, "anchor": anchor})
            g["signals"].append(s)

        e.current_signal_naps = {n for s in signals if not s.corroboration_only for n in s.naps}
        e.current_alarm_elements = {s.element_id for s in signals if s.corroboration_only}
        e.paused_detectors = paused

        for key, g in sorted(groups.items()):
            existing = self.covering_incident(ctx, key)
            if existing is not None:
                self.link(ctx, existing, key, g, scorer)
                continue
            score = g["ranked"][0]["score"]
            if score < self.cfg["support_score"]["propose_min_support"]:
                self.watch(ctx, key, g)
                continue
            self.propose(ctx, key, g, scorer)

        for key in list(e.watch):
            if key not in groups:
                e.watch.pop(key)
        self.refresh_open(ctx, scorer)
        self.closure_checks(ctx)
        self.abstentions(ctx)

    # ------------------------------------------------------------------
    def chain_of(self, ctx, key) -> list[tuple[str, str]]:
        etype, eid = key
        tp = ctx.snap.topology
        if etype == "NAP":
            return ctx.snap.chain(eid)
        if etype == "LCP":
            olt = tp.OLT[tp.LCP == eid].iloc[0]
            return [("LCP", eid), ("OLT", olt)]
        return [("OLT", eid)]

    def covering_incident(self, ctx, key) -> Incident | None:
        ids = {eid for _, eid in self.chain_of(ctx, key)}
        cutoff = (ctx.now - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
        best = None
        for inc in self.e.state.incidents.values():
            if inc.state == "Merged" or inc.element_id not in ids:
                continue
            if inc.state in ("Proposed", "Confirmed") or (inc.state == "Closed" and (inc.closed_at or "") >= cutoff):
                if best is None or inc.state != "Closed":
                    best = inc
        return best

    def dedupe_keys(self, ctx, signals: list[Signal]) -> set:
        out = set()
        tp = ctx.snap.topology
        for s in signals:
            if s.element_type == "NAP":
                out.add((s.detector, tp.LCP.get(s.element_id, s.element_id)))
            else:
                out.add((s.detector, s.element_id))
        return out

    # ------------------------------------------------------------------
    def watch(self, ctx, key, g) -> None:
        e = self.e
        dets = tuple(sorted({s.detector for s in g["signals"]}))
        prev = e.watch.get(key)
        e.watch[key] = {"since": prev["since"] if prev else ctx.now, "score": g["ranked"][0]["score"], "detectors": dets}
        e.first_signal.setdefault(key, ctx.now)
        if prev and prev["detectors"] == dets and abs(prev["score"] - g["ranked"][0]["score"]) < 0.01:
            return
        etype, eid = key
        e.tracer.start(NAME, f"candidate signal: {', '.join(dets)} on {eid}")
        T.ticket_cluster_read(ctx, element_type=etype, element_id=eid)
        T.topology_lookup(ctx, nap=g["anchor"])
        T.sibling_health(ctx, element_type=etype, element_id=eid)
        T.exposure_calc(ctx, element_type=etype, element_id=eid)
        top = g["ranked"][0]
        horizon = ctx.snap.wms_horizon
        e.tracer.note(
            f"ABSTAIN: support {top['score']:.2f} below the proposal threshold "
            f"{self.cfg['support_score']['propose_min_support']:.2f}; watching {eid}. "
            f"Physical signal share {top['components']['physical_signal']:.2f} "
            f"(WMS horizon {horizon:%H:%M} — the next batch has not landed)." if horizon is not None else "")
        e.tracer.output("watch", eid)
        e.tracer.end()

    # ------------------------------------------------------------------
    def propose(self, ctx, key, g, scorer: Scorer) -> Incident:
        e = self.e
        etype, eid = key
        dets = sorted({s.detector for s in g["signals"]})
        run_id = e.tracer.start(NAME, f"candidate signal: {', '.join(dets)} on {eid}")
        cluster = T.ticket_cluster_read(ctx, element_type=etype, element_id=eid)
        T.incident_registry_search(ctx, chain=self.chain_of(ctx, key))
        topo = T.topology_lookup(ctx, nap=g["anchor"])
        sib = T.sibling_health(ctx, element_type=etype, element_id=eid)
        tel = T.telemetry_read(ctx, element_type=etype, element_id=eid, hours=2)
        exp = T.exposure_calc(ctx, element_type=etype, element_id=eid)

        top = g["ranked"][0]
        comps = top["components"]
        score = top["score"]
        naps = ctx.snap.naps_under(etype, eid)
        tp = ctx.snap.topology
        lcp = tp.LCP[naps[0]] if etype in ("NAP", "LCP") else None
        olt = tp.OLT[naps[0]]
        territory = ctx.snap.static.nap_geo.territory.get(naps[0])

        # physical evidence: dropped / silent gateways on the element
        gws = ctx.snap.gateways
        gws = gws[gws.nap.isin(naps) & (gws.dropped | gws.silent2)]
        phys_ids = [T.gw_id(ctx, r.mac, r.last_seen, float(r.rx_latest_dbm), r.nap) for r in gws.head(24).itertuples() if not pd.isna(r.last_seen)]
        alarm_ids = [T.alarm_id(ctx, r) for r in ctx.snap.alarms_open.to_dict("records") if r["ne_name"] in {eid, olt, lcp, *naps}]
        snow = ctx.snap.snow
        flap_incs = sorted(scorer.flap_tickets(etype, eid))
        open_snow = ctx.snap.open_snow[ctx.snap.open_snow.affected_nap.isin(naps)]
        snow_rows = pd.concat([open_snow, snow[snow.inc_number.isin(flap_incs)]]).drop_duplicates(["inc_number", "affected_nap"])
        snow_ids = [T.inc_id(ctx, r) for r in snow_rows.to_dict("records")]
        snow_refs = sorted(set(snow_rows.inc_number))
        crew = self.crew_for(ctx, snow_refs, naps)

        lines_total = exp.data["total"]
        observed = set(exp.data["observed_accounts"])
        e.observed_accounts[eid] = set(observed)
        kind = "recurring fault" if flap_incs else "outage"
        inc_id = e.next_incident_id()
        first = e.first_signal.get(key, ctx.now)
        inc = Incident(
            incident_id=inc_id, element_type=etype, element_id=eid, kind=kind,
            hypothesis_rank=[Hypothesis(element_type=h["element_type"], element_id=h["element_id"], score=h["score"],
                                        components={k: v for k, v in h["components"].items() if not k.startswith("_")}) for h in g["ranked"]],
            observed_lines=len(observed), inferred_lines=lines_total - len(observed), vip_b2b_count=exp.data["vip_b2b"],
            msf_band_total=exp.data["msf_bands"], severity=severity_for(self.cfg, etype, lines_total),
            support_score=score, score_components={k: v for k, v in comps.items()},
            rationale="", state="Proposed", proposed_at=fmt(ctx.now),
            snow_refs=snow_refs, crew_assigned=crew, has_physical_signal=comps["physical_signal"] >= 0.5 and bool(phys_ids or flap_incs),
            flap_count=len(flap_incs), detectors=dets, olt=olt, lcp=lcp, naps=naps, territory=territory,
            first_signal_at=fmt(first), run_id=run_id, updated_at=fmt(ctx.now),
            evidence_ids=cluster.evidence_ids + exp.evidence_ids + phys_ids + alarm_ids + snow_ids + topo.evidence_ids,
        )
        inc.rationale = self.rationale(ctx, inc, cluster, sib, tel, exp, phys_ids, alarm_ids, snow_refs, flap_incs)
        e.physical_ids[inc_id] = phys_ids or [i for i in snow_ids]
        e.covered_keys[inc_id] = {k: ctx.now for k in self.dedupe_keys(ctx, g["signals"])}
        T.incident_registry_create(ctx, incident=inc)
        e.tracer.output("incident", inc_id)
        e.tracer.end()
        e.watch.pop(key, None)
        e.on_incident_change(inc, "created")
        return inc

    def crew_for(self, ctx, snow_refs: list[str], naps: list[str]) -> bool:
        s = ctx.snap.snow
        s = s[s.inc_number.isin(snow_refs)]
        if s.inc_assignment_group.fillna("").str.startswith("FLD-").any():
            return True
        o = ctx.snap.open_repairs
        o = o[o.facilityname.isin(naps)]
        return bool(o.team.fillna("").str.len().gt(0).any())

    # ------------------------------------------------------------------
    def rationale(self, ctx, inc: Incident, cluster, sib, tel, exp, phys_ids, alarm_ids, snow_refs, flap_incs) -> str:
        c = inc.score_components
        parts = []
        orders = [r["workordernumber"] for r in cluster.data]
        if flap_incs:
            parts.append(f"{len(flap_incs)} short SNOW auto-tickets on {inc.element_id} in the last 2 hours "
                         f"({', '.join(flap_incs)}), each resolved within 15 minutes: a recurring fault, not {len(flap_incs)} separate outages.")
        if orders:
            parts.append(f"{inc.observed_lines} customers on {inc.element_id} have reported a fault "
                         f"({len(orders)} open repair orders: {', '.join(orders[:5])}{'…' if len(orders) > 5 else ''}).")
        elif inc.observed_lines:
            parts.append(f"{inc.observed_lines} customers on {inc.element_id} reported a fault through Handyman.")
        n_gw = int(c.get("_n_gw", 0))
        if c.get("_optical_share", 0) >= 0.5:
            dropped = [g for g in tel.data["gateways"] if g["dropped"]]
            ex = dropped[0] if dropped else None
            parts.append(f"WMS shows optical Rx on {round(c['_optical_share'] * n_gw)} of {n_gw} gateways more than 6 dB below their "
                         f"24-hour baseline" + (f" (e.g. {ex['mac']}: {ex['latest_dbm']} dBm against {ex['baseline_dbm']})." if ex else "."))
        if c.get("_reach_share", 0) >= 0.5:
            parts.append(f"{round(c['_reach_share'] * n_gw)} of {n_gw} gateways have stopped reporting for at least two intervals.")
        sibs = sib.data["siblings"]
        if sibs:
            clean = sum(s["clean"] for s in sibs)
            level = {"NAP": "LCP", "LCP": "OLT", "OLT": "site"}[inc.element_type]
            parts.append(f"{clean} of {len(sibs)} sibling {sibs[0]['type']}s are clean, so the fault is isolated to the "
                         f"{inc.element_type}, not the {level}." if clean >= len(sibs) / 2 else
                         f"Only {clean} of {len(sibs)} sibling {sibs[0]['type']}s are clean.")
        parts.append(f"NMS alarm sample: {', '.join(a.split(':')[1] for a in alarm_ids)} (corroboration only)." if alarm_ids else "No NMS alarm on this element.")
        if snow_refs and not flap_incs:
            parts.append(f"Open SNOW outage {', '.join(snow_refs)} covers this element; linked, not duplicated.")
        elif not flap_incs:
            parts.append("No SNOW incident covers this element.")
        parts.append(f"{inc.observed_lines + inc.inferred_lines} lines are inferred affected: {inc.observed_lines} observed, "
                     f"{inc.inferred_lines} silent; {inc.vip_b2b_count} VIP/B2B. Support score {inc.support_score:.2f} "
                     f"(not a probability until calibrated).")
        return " ".join(parts)

    # ------------------------------------------------------------------
    def link(self, ctx, parent: Incident, key, g, scorer: Scorer) -> None:
        """A signal already covered by an open (or recently resolved) incident is linked, not duplicated."""
        e = self.e
        keys = self.dedupe_keys(ctx, g["signals"])
        seen = e.covered_keys.setdefault(parent.incident_id, {})
        gap = timedelta(minutes=60)
        new = {k for k in keys if k not in seen or ctx.now - seen[k] > gap}
        for k in keys:
            seen[k] = ctx.now
        etype, eid = key
        if parent.flap_count and any(s.detector == "flap" for s in g["signals"]):
            flaps = sorted(scorer.flap_tickets(parent.element_type, parent.element_id) | set(parent.snow_refs))
            if len(flaps) > parent.flap_count:
                p = parent.model_copy(deep=True)
                p.flap_count = len(flaps)
                p.snow_refs = flaps
                p.rationale = (f"Flap count now {len(flaps)}: " + ", ".join(flaps) + ". " +
                               parent.rationale.split(". ", 1)[-1] if parent.rationale else "")
                p.updated_at = fmt(ctx.now)
                e.tracer.start(NAME, f"new flap ticket on {parent.element_id}")
                e.tracer.note(f"Rolled into {parent.incident_id}: flap count {parent.flap_count} -> {len(flaps)}. Scored on lines affected, not ticket count.")
                e.tracer.output("incident", parent.incident_id)
                e.tracer.end()
                e.state.put_incident(p, "updated")
                e.on_incident_change(p, "updated")
        if not new or parent.state == "Closed":
            return
        dets = sorted({s.detector for s in g["signals"]})
        e.tracer.start(NAME, f"candidate signal: {', '.join(dets)} on {eid}")
        cluster = T.ticket_cluster_read(ctx, element_type=etype, element_id=eid)
        found = T.incident_registry_search(ctx, chain=self.chain_of(ctx, key))
        T.topology_lookup(ctx, nap=g["anchor"])
        exp = T.exposure_calc(ctx, element_type=etype, element_id=eid)
        top = g["ranked"][0]
        mid = e.next_incident_id()
        merged = Incident(
            incident_id=mid, element_type=etype, element_id=eid, kind="outage",
            hypothesis_rank=[Hypothesis(element_type=h["element_type"], element_id=h["element_id"], score=h["score"],
                                        components={k: v for k, v in h["components"].items() if not k.startswith("_")}) for h in g["ranked"]],
            observed_lines=exp.data["observed"], inferred_lines=exp.data["inferred"], vip_b2b_count=exp.data["vip_b2b"],
            severity=severity_for(self.cfg, etype, exp.data["total"]), support_score=top["score"],
            score_components=top["components"], state="Merged", parent_id=parent.incident_id,
            rationale=(f"Duplicate cluster ({', '.join(dets)}) on {eid} falls inside {parent.incident_id} "
                       f"({parent.element_type} {parent.element_id}, {parent.state}"
                       f"{', SNOW ' + ', '.join(parent.snow_refs) if parent.snow_refs else ''}). Linked to the existing incident instead of "
                       f"creating a new one; {len(cluster.data)} open orders and {exp.data['observed']} observed lines added to its evidence."),
            proposed_at=fmt(ctx.now), decided_by="UC1 dedupe rule", decided_at=fmt(ctx.now), detectors=dets,
            olt=parent.olt, lcp=parent.lcp, naps=ctx.snap.naps_under(etype, eid), territory=parent.territory,
            run_id=e.tracer.current["run_id"], updated_at=fmt(ctx.now),
            evidence_ids=[f"SDAL:{parent.incident_id}"] + cluster.evidence_ids + exp.evidence_ids,
        )
        p = parent.model_copy(deep=True)
        p.evidence_ids = list(dict.fromkeys(parent.evidence_ids + cluster.evidence_ids[:10]))
        p.updated_at = fmt(ctx.now)
        T.incident_registry_merge(ctx, merged=merged, parent=p)
        e.tracer.output("merge", mid)
        e.tracer.end()
        e.on_incident_change(p, "merged")

    # ------------------------------------------------------------------
    def refresh_open(self, ctx, scorer: Scorer) -> None:
        """Keep observed lines, crew and SNOW links current on open incidents (platform-internal refresh)."""
        e = self.e
        for inc in list(e.state.incidents.values()):
            if inc.state not in ("Proposed", "Confirmed"):
                continue
            obs = e.observed_accounts.setdefault(inc.element_id, set()) | scorer.observed(inc.element_type, inc.element_id)
            e.observed_accounts[inc.element_id] = obs
            total = inc.observed_lines + inc.inferred_lines
            open_snow = ctx.snap.open_snow[ctx.snap.open_snow.affected_nap.isin(inc.naps)]
            refs = sorted(set(inc.snow_refs) | set(open_snow.inc_number))
            crew = self.crew_for(ctx, refs, inc.naps)
            if len(obs) != inc.observed_lines or refs != inc.snow_refs or crew != inc.crew_assigned:
                p = inc.model_copy(deep=True)
                p.observed_lines, p.inferred_lines = len(obs), total - len(obs)
                changed_crew = crew != inc.crew_assigned
                p.snow_refs, p.crew_assigned = refs, crew
                p.updated_at = fmt(ctx.now)
                e.state.put_incident(p, "crew assigned" if changed_crew and crew else "updated")
                e.on_incident_change(p, "crew" if changed_crew else "updated")

    def closure_checks(self, ctx) -> None:
        e = self.e
        for inc in list(e.state.incidents.values()):
            if inc.state != "Confirmed" or inc.closure_proposed_at or inc.kind != "outage":
                continue
            st = ctx.snap.element_stats(inc.element_type, inc.element_id)
            o = ctx.snap.orders
            recent = o[(o.skillset == "Repair") & o.facilityname.isin(inc.naps) & (o.createdate >= ctx.snap.window(30))]
            if st["optical_share"] < 0.1 and st["reach_share"] < 0.1 and recent.empty and ctx.snap.wms_horizon is not None \
                    and ctx.snap.wms_horizon > pd.Timestamp(inc.proposed_at):
                e.tracer.start(NAME, f"closure check on {inc.incident_id}")
                tel = T.telemetry_read(ctx, element_type=inc.element_type, element_id=inc.element_id, hours=1)
                T.ticket_cluster_read(ctx, element_type=inc.element_type, element_id=inc.element_id, hours=1)
                p = inc.model_copy(deep=True)
                p.closure_proposed_at = fmt(ctx.now)
                healthy = [g for g in tel.data["gateways"] if g["latest_dbm"] is not None and not g["dropped"]]
                p.rationale = inc.rationale + (f" CLOSURE PROPOSED {hhmm(fmt(ctx.now))}: optical Rx back within 6 dB of baseline on "
                                               f"{len(healthy)} of {len(tel.data['gateways'])} gateways (WMS horizon {hhmm(tel.data['horizon'])}) and "
                                               f"no new orders for 30 minutes.")
                p.evidence_ids = list(dict.fromkeys(inc.evidence_ids + tel.evidence_ids))
                p.updated_at = fmt(ctx.now)
                T.incident_registry_close(ctx, incident=p)
                e.tracer.output("closure", inc.incident_id)
                e.tracer.end()
                e.on_incident_change(p, "closure proposed")

    def abstentions(self, ctx) -> None:
        """Orders whose subscriber has a blank nap cannot be placed inside a blast radius: report at cluster level."""
        e = self.e
        o = ctx.snap.open_repairs
        o = o[o.facilityname.isna() & (o.createdate >= ctx.snap.window(360))]
        for r in o.to_dict("records"):
            wo = r["workordernumber"]
            if wo in e.abstained:
                continue
            near = [i for i in e.state.incidents.values() if i.state in ("Proposed", "Confirmed") and i.olt and i.olt.endswith(r["cabinetid"])]
            e.abstained.add(wo)
            e.tracer.start(NAME, f"order {wo} without NAP")
            eid = T.wo_id(ctx, r)
            geo = ctx.snap.static.geo
            town = geo[geo.cabinet == r["cabinetid"]].town.iloc[0] if (geo.cabinet == r["cabinetid"]).any() else ""
            text = (f"ABSTAIN on {wo}: the subscriber record has a blank nap (2.6% of the base), so the line cannot be placed on a NAP "
                    f"or inside any blast radius. Reported at cluster level only: cabinet {r['cabinetid']} ({town})."
                    + (f" {near[0].incident_id} is open in the same cabinet; this line is NOT counted in its exposure." if near else ""))
            e.tracer.note(text)
            e.tracer.output("abstention", wo)
            e.tracer.end()
            e.state.add_abstention({"abstention_id": f"ABS-{len(e.abstained):03d}", "at": fmt(ctx.now), "workordernumber": wo,
                                    "cabinetid": r["cabinetid"], "town": town, "near_incident": near[0].incident_id if near else None,
                                    "text": text, "evidence_ids": [eid]})


def fmt(t) -> str:
    return pd.Timestamp(t).strftime("%Y-%m-%d %H:%M:%S")
