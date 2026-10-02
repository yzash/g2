"""Tool registry: the demo's complete authorisation boundary (PRD section 9).

Agents act only through the tools below. Each tool declares what it reads,
what it writes and which agents may call it; a call from any other agent is
refused. Every call is written to the append-only trace with its parameters,
the evidence rows it returned and any untrusted-text flags.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Callable

import pandas as pd

from .views import OPEN_STATUSES, Snapshot

REGISTRY: dict[str, dict] = {}


class ToolNotAuthorized(PermissionError):
    pass


class ToolDisabled(RuntimeError):
    pass


@dataclass
class ToolResult:
    data: Any
    evidence_ids: list[str] = field(default_factory=list)
    summary: str = ""
    flags: list[str] = field(default_factory=list)


def tool(name: str, reads: str, writes: str, used_by: list[str]):
    def deco(fn: Callable):
        REGISTRY[name] = {"name": name, "reads": reads, "writes": writes, "used_by": used_by, "doc": (fn.__doc__ or "").strip()}

        @wraps(fn)
        def wrapper(ctx: "ToolContext", **params) -> ToolResult:
            agent = ctx.tracer.current_agent
            if agent not in used_by:
                ctx.tracer.refused(name, agent, params)
                raise ToolNotAuthorized(f"{agent} is not registered to call {name}")
            ctx.tracer.begin_call()
            result = fn(ctx, **params)
            ctx.tracer.record(name, params, result)
            return result

        wrapper.tool_name = name
        return wrapper

    return deco


# ---------------------------------------------------------------------------
# Untrusted text: data, never instructions
# ---------------------------------------------------------------------------
INSTRUCTION_PATTERNS = [
    r"ignore (all )?(previous|prior) (rules|instructions)",
    r"\b(system|developer) (note|prompt|message)\b",
    r"\bas an ai\b",
    r"\bmark (every|all) order",
    r"\bsupport score\b",
    r"\bto ai agent\b",
]
UNTRUSTED_FIELDS = ("fixdescription", "finddescription", "inc_short_description", "Diagnosis")


def scan_untrusted(text: str | None) -> bool:
    if not text or not isinstance(text, str):
        return False
    t = text.lower()
    return any(re.search(p, t) for p in INSTRUCTION_PATTERNS)


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------
class ToolContext:
    def __init__(self, snap: Snapshot, cfg: dict, state, tracer, evidence: dict):
        self.snap = snap
        self.cfg = cfg
        self.state = state
        self.tracer = tracer
        self.evidence = evidence

    @property
    def now(self) -> datetime:
        return self.snap.now

    def cite(self, eid: str, source: str, row: dict) -> str:
        if eid not in self.evidence:
            clean = {}
            for k, v in row.items():
                if k.startswith("_") and k != "_arrived_at":
                    continue
                if isinstance(v, float) and math.isnan(v):
                    v = None
                elif isinstance(v, (pd.Timestamp, datetime)):
                    v = None if pd.isna(v) else pd.Timestamp(v).strftime("%Y-%m-%d %H:%M:%S")
                elif v is pd.NaT:
                    v = None
                clean[k] = v
            self.evidence[eid] = {"id": eid, "source": source, "row": clean,
                                  "fetched_by": self.tracer.current_call_id(), "fetched_at": fmt(self.now)}
        return eid


def fmt(t) -> str | None:
    if t is None or (isinstance(t, float) and math.isnan(t)) or t is pd.NaT:
        return None
    return pd.Timestamp(t).strftime("%Y-%m-%d %H:%M:%S")


def wo_id(ctx: ToolContext, r: dict) -> str:
    return ctx.cite(f"WO:{r['workordernumber']}@{fmt(r['lastupdatedate'])}", "FSM work order (oWFM ALL STATUS)", r)


def hm_id(ctx: ToolContext, r: dict) -> str:
    return ctx.cite(f"AUD:{r['audit_no']}", "Handyman diagnostic log", r)


def gw_id(ctx: ToolContext, mac: str, report_time, rx_dbm: float, nap: str | None) -> str:
    raw = round(10 ** (rx_dbm / 10) / 0.0001)
    return ctx.cite(f"GW:{mac}@{fmt(report_time)}", "WMS gateway telemetry", {
        "Gateway MAC Address": mac, "Report Time": fmt(report_time), "Rx Optical Power (raw)": raw,
        "Rx dBm (converted)": round(rx_dbm, 2), "NAP": nap})


def inc_id(ctx: ToolContext, r: dict) -> str:
    return ctx.cite(f"INC:{r['inc_number']}/{r['affected_nap']}@{fmt(r['latest_extract_datetime'])}", "ServiceNow outage (NAP-expanded)", r)


def alarm_id(ctx: ToolContext, r: dict) -> str:
    return ctx.cite(f"ALM:{r['alarm_id']}", "NMS alarm sample", r)


def topo_id(ctx: ToolContext, nap: str) -> str:
    tp = ctx.snap.topology
    return ctx.cite(f"TOPO:{nap}@{fmt(ctx.now)[:10]}", "master_olt_lcp_nap (effective-dated)", {
        "NAP": nap, "LCP": tp.LCP.get(nap), "OLT": tp.OLT.get(nap), "GRID_ID": tp.GRID_ID.get(nap)})


# ---------------------------------------------------------------------------
# UC1 tools
# ---------------------------------------------------------------------------
@tool("ticket_cluster_read", "curated repair orders", "none", ["UC1"])
def ticket_cluster_read(ctx: ToolContext, element_type: str, element_id: str, hours: int = 6) -> ToolResult:
    """Open repair orders on an element inside the rolling window."""
    naps = ctx.snap.naps_under(element_type, element_id)
    o = ctx.snap.open_repairs
    o = o[o.facilityname.isin(naps) & (o.createdate >= ctx.snap.window(hours * 60))]
    rows = o[["workordernumber", "cabinetid", "lcpname", "dpid", "facilityname", "createdate", "faultcode", "status", "accountnumber", "lastupdatedate"]].to_dict("records")
    ids = [wo_id(ctx, r) for r in o.to_dict("records")]
    return ToolResult(rows, ids, f"{len(rows)} open repair orders on {element_id} in {hours}h")


@tool("incident_registry.search", "incident_registry", "none", ["UC1"])
def incident_registry_search(ctx: ToolContext, chain: list[tuple[str, str]], hours: int = 6) -> ToolResult:
    """Open, or resolved in the last 6 hours, incidents on the same NAP or any ancestor element."""
    ids = {eid for _, eid in chain}
    cutoff = fmt(ctx.snap.window(hours * 60))
    out = []
    for inc in ctx.state.incidents.values():
        if inc.state == "Merged" or inc.element_id not in ids:
            continue
        if inc.state in ("Proposed", "Confirmed") or (inc.state == "Closed" and (inc.closed_at or "") >= cutoff):
            out.append(inc)
    return ToolResult(out, [f"SDAL:{i.incident_id}" for i in out], f"{len(out)} matching incidents")


@tool("topology_lookup", "master_olt_lcp_nap", "none", ["UC1", "UC2", "UC3"])
def topology_lookup(ctx: ToolContext, nap: str) -> ToolResult:
    """Resolve NAP to LCP and OLT (effective-dated) and count siblings."""
    tp = ctx.snap.topology
    if nap not in tp.index:
        return ToolResult(None, [], f"{nap} not in topology")
    lcp, olt = tp.LCP[nap], tp.OLT[nap]
    sib_naps = sorted(tp.index[tp.LCP == lcp])
    sib_lcps = sorted(set(tp.LCP[tp.OLT == olt]))
    return ToolResult({"nap": nap, "lcp": lcp, "olt": olt, "sibling_naps": sib_naps, "sibling_lcps": sib_lcps},
                      [topo_id(ctx, nap)], f"{nap} -> {lcp} -> {olt}; {len(sib_naps) - 1} sibling NAPs")


@tool("sibling_health", "curated telemetry, orders", "none", ["UC1"])
def sibling_health(ctx: ToolContext, element_type: str, element_id: str) -> ToolResult:
    """Latest optical median and open-order count for each sibling of the element."""
    snap = ctx.snap
    tp = snap.topology
    if element_type == "NAP":
        parent = tp.LCP[element_id]
        sibs = [n for n in tp.index[tp.LCP == parent] if n != element_id]
        sib_type = "NAP"
    elif element_type == "LCP":
        olt = tp.OLT[tp.LCP == element_id].iloc[0]
        sibs = sorted(set(tp.LCP[tp.OLT == olt]) - {element_id})
        sib_type = "LCP"
    else:
        site = element_id.split("_")[1]
        sibs = sorted(set(tp.OLT[tp.OLT.str.contains(f"_{site}_")]) - {element_id})
        sib_type = "OLT"
    rows = []
    for s in sibs:
        st = snap.element_stats(sib_type, s)
        naps = st["naps"]
        n_orders = int(snap.open_repairs.facilityname.isin(naps).sum())
        rx = snap.nap_stats.reindex(naps).rx_median.median()
        clean = st["optical_share"] < 0.3 and st["reach_share"] < 0.3 and n_orders < ctx.cfg["detectors"]["ticket_burst_nap_min_orders"]
        rows.append({"element": s, "type": sib_type, "rx_median_dbm": None if pd.isna(rx) else round(float(rx), 1),
                     "optical_share": round(st["optical_share"], 2), "reach_share": round(st["reach_share"], 2),
                     "open_orders": n_orders, "clean": bool(clean)})
    clean_share = (sum(r["clean"] for r in rows) / len(rows)) if rows else 1.0
    return ToolResult({"siblings": rows, "clean_share": clean_share}, [],
                      f"{sum(r['clean'] for r in rows)}/{len(rows)} sibling {sib_type}s clean")


@tool("telemetry_read", "curated WMS telemetry (converted units)", "none", ["UC1", "UC2"])
def telemetry_read(ctx: ToolContext, element_type: str, element_id: str, hours: int = 2, cite_limit: int = 16) -> ToolResult:
    """Rx and Tx per gateway on the element over the window, converted to dBm."""
    snap = ctx.snap
    if element_type == "LINE":
        macs = snap.static.lines.mac[snap.static.lines.service_id == element_id].tolist()
    else:
        macs = snap.lines_on(element_type, element_id).mac.tolist()
    if not macs or snap.wms_horizon is None:
        return ToolResult([], [], "no telemetry")
    df = ctx.snap.con.execute("""
        SELECT mac, report_time, rx_dbm, tx_dbm FROM c_telemetry
        WHERE _arrived_at <= ? AND report_time > ?::TIMESTAMP - INTERVAL (?) HOUR AND mac IN (SELECT unnest(?))
        ORDER BY mac, report_time""", [ctx.now, snap.wms_horizon, hours, macs]).fetchdf()
    g = snap.gateways.set_index("mac")
    ids = []
    latest = df.sort_values("report_time").groupby("mac").tail(1)
    for r in latest.head(cite_limit).itertuples():
        ids.append(gw_id(ctx, r.mac, r.report_time, r.rx_dbm, g.nap.get(r.mac)))
    summary_rows = []
    for mac in macs:
        gr = g.loc[mac] if mac in g.index else None
        summary_rows.append({"mac": mac, "baseline_dbm": None if gr is None or pd.isna(gr.baseline_dbm) else round(float(gr.baseline_dbm), 1),
                             "latest_dbm": None if gr is None or pd.isna(gr.rx_latest_dbm) else round(float(gr.rx_latest_dbm), 1),
                             "last_seen": None if gr is None else fmt(gr.last_seen),
                             "dropped": bool(gr is not None and gr.dropped), "silent": bool(gr is not None and gr.silent2)})
    return ToolResult({"gateways": summary_rows, "horizon": fmt(snap.wms_horizon)}, ids,
                      f"{len(macs)} gateways; WMS horizon {fmt(snap.wms_horizon)}")


@tool("exposure_calc", "subscriber bases, product mapping, WMS keys", "none", ["UC1", "UC3", "UC5"])
def exposure_calc(ctx: ToolContext, element_type: str, element_id: str, hours: int = 6) -> ToolResult:
    """Observed lines (orders or Handyman complaints), inferred lines (no contact), VIP/B2B count, MSF band totals."""
    snap = ctx.snap
    lines = snap.lines_on(element_type, element_id)
    accts = set(lines.account_no)
    since = snap.window(hours * 60)
    o = snap.orders
    o = o[(o.skillset == "Repair") & o.accountnumber.isin(accts) & (o.createdate >= since)]
    h = snap.handyman
    hstale = ctx.state.feed_status.get("HANDYMAN") != "on time"
    h = h[h.account_number.isin(accts) & (h.date_time >= since) &
          ((h.LineStatus == "Account has a last mile issue") | (h.Result == "FAILED"))]
    observed = set(o.accountnumber) | set(h.account_number)
    ids = [wo_id(ctx, r) for r in o.to_dict("records")] + [hm_id(ctx, r) for r in h.to_dict("records")]
    bands = {"<1500": 0, "1500-2499": 0, "2500+": 0}
    for m in lines.msf:
        bands["<1500" if m < 1500 else "1500-2499" if m < 2500 else "2500+"] += 1
    data = {"total": len(lines), "observed": len(observed), "inferred": len(lines) - len(observed),
            "observed_accounts": sorted(observed), "vip_b2b": int(lines.vip.sum()), "msf_bands": bands,
            "handyman_stale": hstale}
    return ToolResult(data, ids, f"{len(lines)} lines: {len(observed)} observed, {len(lines) - len(observed)} silent")


# ---------------------------------------------------------------------------
# Shared reads
# ---------------------------------------------------------------------------
@tool("incident_registry_read", "incident_registry", "none", ["UC2", "UC3", "UC5"])
def incident_registry_read(ctx: ToolContext, dpid: str | None = None, lcpname: str | None = None, cabinetid: str | None = None,
                           facilityname: str | None = None) -> ToolResult:
    """Open incident whose element is upstream of (or equal to) the line's NAP."""
    nap = facilityname
    if not nap and dpid:
        nap = dpid.replace("DP-", "").replace("-", "_")
    snap = ctx.snap
    if not nap or nap not in snap.topology.index:
        return ToolResult(None, [], f"line has no NAP (cabinet {cabinetid}); blast radius cannot be resolved")
    chain = {eid for _, eid in snap.chain(nap)}
    hits = [i for i in ctx.state.incidents.values() if i.state in ("Proposed", "Confirmed") and i.element_id in chain]
    hits.sort(key=lambda i: {"OLT": 0, "LCP": 1, "NAP": 2}.get(i.element_type, 3))
    if not hits:
        return ToolResult(None, [topo_id(ctx, nap)], f"no open incident upstream of {nap}")
    inc = hits[0]
    return ToolResult(inc, [f"SDAL:{inc.incident_id}", topo_id(ctx, nap)],
                      f"{nap} inside {inc.incident_id} ({inc.element_type} {inc.element_id}, {inc.state})")


# ---------------------------------------------------------------------------
# UC2 tools
# ---------------------------------------------------------------------------
@tool("planned_works_check", "none (returns unavailable)", "none", ["UC2"])
def planned_works_check(ctx: ToolContext, nap: str | None) -> ToolResult:
    """No planned-works source in the pilot: returns unknown, never clear."""
    return ToolResult({"status": "unavailable", "result": "unknown"}, [], "UNAVAILABLE IN PILOT: returns unknown, never clear")


@tool("power_footprint_check", "none (returns unavailable)", "none", ["UC2"])
def power_footprint_check(ctx: ToolContext, nap: str | None) -> ToolResult:
    """No power-outage footprint source in the pilot: returns unknown, never clear."""
    return ToolResult({"status": "unavailable", "result": "unknown"}, [], "UNAVAILABLE IN PILOT: returns unknown, never clear")


@tool("line_history_read", "curated repair orders", "none", ["UC2"])
def line_history_read(ctx: ToolContext, serviceidnumber: str, days: int = 30) -> ToolResult:
    """Prior orders on the line. Free-text fields are returned as data and scanned for instruction-like content."""
    o = ctx.snap.orders
    o = o[(o.serviceidnumber == serviceidnumber) & (o.createdate >= ctx.snap.window(days * 1440))]
    flags, ids = [], []
    for r in o.to_dict("records"):
        eid = wo_id(ctx, r)
        ids.append(eid)
        for f in ("fixdescription", "finddescription"):
            if scan_untrusted(r.get(f)):
                flags.append(f"{eid} field {f}: instruction-like text treated as data and ignored")
    return ToolResult(o[["workordernumber", "status", "FIXSEGMENT", "fixdescription", "createdate"]].to_dict("records"), ids,
                      f"{len(o)} prior orders on the line", flags)


@tool("symptom_signature_check", "Handyman, telemetry", "none", ["UC2"])
def symptom_signature_check(ctx: ToolContext, accountnumber: str, nap: str | None) -> ToolResult:
    """Customer-side signature from Handyman (ModemStatus, LineStatus, PortStatus, optics) and WMS (gateway Rx, reporting)."""
    snap = ctx.snap
    cfg = ctx.cfg["dispatch"]
    line = snap.static.acct_to_line.loc[accountnumber]
    mac = line.mac
    g = snap.gateways.set_index("mac").loc[mac]
    ids = []
    h = snap.handyman[snap.handyman.account_number == accountnumber].sort_values("date_time")
    last_h = h.iloc[-1].to_dict() if len(h) else None
    hm_age_h = None
    if last_h:
        ids.append(hm_id(ctx, last_h))
        hm_age_h = (ctx.now - pd.Timestamp(last_h["date_time"]).to_pydatetime()).total_seconds() / 3600
    if not pd.isna(g.last_seen):
        ids.append(gw_id(ctx, mac, g.last_seen, float(g.rx_latest_dbm), nap))
    sib = None
    if nap and nap in snap.nap_stats.index:
        st = snap.nap_stats.loc[nap]
        g_all = snap.gateways[(snap.gateways.nap == nap) & (snap.gateways.mac != mac)]
        healthy = (g_all.fresh & ~g_all.dropped).sum()
        sib = {"siblings": int(len(g_all)), "healthy": int(healthy), "share": float(healthy / len(g_all)) if len(g_all) else 0.0}
    rx_ok = bool(g.fresh and not pd.isna(g.drop_db) and g.drop_db < cfg["cpe_rx_tolerance_db"])
    silent = bool(g.silent2)
    silence_since = None if pd.isna(g.last_seen) else fmt(g.last_seen)
    data = {
        "gateway_mac": mac, "gateway_rx_dbm": None if pd.isna(g.rx_latest_dbm) else round(float(g.rx_latest_dbm), 1),
        "gateway_baseline_dbm": None if pd.isna(g.baseline_dbm) else round(float(g.baseline_dbm), 1),
        "gateway_rx_ok": rx_ok, "gateway_silent": silent, "gateway_last_seen": silence_since,
        "gateway_dropped": bool(g.dropped),
        "handyman_last": None if not last_h else {k: last_h.get(k) for k in ("audit_no", "date_time", "LineStatus", "ModemStatus", "PortStatus", "Last Mile Status", "Diagnosis")},
        "handyman_age_h": None if hm_age_h is None else round(hm_age_h, 1),
        "siblings": sib, "handyman_feed": ctx.state.feed_status.get("HANDYMAN", "on time"),
    }
    sig = "none"
    fresh_h = last_h is not None and hm_age_h <= cfg["stale_handyman_hours"]
    if fresh_h and rx_ok and last_h.get("ModemStatus") == "Inactive/Modem not found" and (sib is None or sib["share"] >= 0.8):
        sig = "cpe"
    elif g.dropped and (sib is None or sib["share"] >= 0.8):
        sig = "drop"
    elif silent and sib is not None and sib["share"] >= 0.8:
        sig = "silent_line"
    elif fresh_h and last_h.get("LineStatus") == "Account has a last mile issue":
        sig = "last_mile"
    data["signature"] = sig
    data["handyman_fresh"] = bool(fresh_h)
    return ToolResult(data, ids, f"signature={sig}; Rx ok={rx_ok}; silent={silent}; Handyman age={data['handyman_age_h']}h")


# ---------------------------------------------------------------------------
# UC3 tools
# ---------------------------------------------------------------------------
@tool("crew_availability_read", "static team field only", "none", ["UC3"])
def crew_availability_read(ctx: ToolContext, incident=None, order: dict | None = None) -> ToolResult:
    """Crew assigned from the static team field / SNOW assignment group. Live crew availability is unavailable in the pilot."""
    if incident is not None:
        return ToolResult({"crew": incident.crew_assigned, "live_availability": "unavailable"}, [], f"crew={incident.crew_assigned}")
    crew = bool(order and isinstance(order.get("team"), str) and order.get("team"))
    return ToolResult({"crew": crew, "live_availability": "unavailable"}, [], f"crew={crew}")


@tool("queue_read", "queue_rank, incident_registry, orders", "none", ["UC3"])
def queue_read(ctx: ToolContext) -> ToolResult:
    """Current queue members: Proposed/Confirmed incidents plus dispatch-eligible orders outside any incident."""
    return ToolResult(None, [], "queue members")


@tool("sla_clock", "orders", "none", ["UC3"])
def sla_clock(ctx: ToolContext, createdates: list) -> ToolResult:
    """Clock start = earliest createdate among the item's open orders; breach = start + 6h."""
    if not createdates:
        return ToolResult({"start": None, "breach": None}, [], "clock not running (no open customer orders)")
    start = min(pd.Timestamp(c) for c in createdates)
    breach = start + pd.Timedelta(hours=ctx.cfg["queue"]["window_hours"])
    return ToolResult({"start": fmt(start), "breach": fmt(breach)}, [], f"clock from {fmt(start)}")


@tool("ranking_explain", "queue_rank", "none", ["UC3"])
def ranking_explain(ctx: ToolContext, a: dict, b: dict) -> ToolResult:
    """Explain why item a is above item b from their recorded inputs."""
    return ToolResult({"a": a, "b": b}, [], "explained")


# ---------------------------------------------------------------------------
# UC5 tools
# ---------------------------------------------------------------------------
@tool("subscriber_resolve", "bases, WMS keys (pseudonymised)", "none", ["UC5"])
def subscriber_resolve(ctx: ToolContext, incident) -> ToolResult:
    """All subscribers on the element, split observed (called or ran Handyman) from inferred (silent)."""
    lines = ctx.snap.lines_on(incident.element_type, incident.element_id)
    exp = exposure_calc.__wrapped__(ctx, element_type=incident.element_type, element_id=incident.element_id, hours=24)
    obs = set(exp.data["observed_accounts"])
    out = [{"subscriber_id": r.subscriber_id, "segment": "VIP/B2B" if r.vip else "mass", "observed": r.account_no in obs, "nap": r.nap}
           for r in lines.itertuples()]
    ids = [ctx.cite(f"SUB:{r['subscriber_id']}", "Subscriber base (pseudonymised)", r) for r in out[:20]]
    return ToolResult(out, ids, f"{len(out)} recipients resolved")


@tool("restoration_target_read", "outage management target (seeded)", "none", ["UC5"])
def restoration_target_read(ctx: ToolContext, snow_refs: list[str]) -> ToolResult:
    """Globe's published restoration target if outage management has one. The platform never computes its own ETA."""
    rt = ctx.snap.static.restoration
    rt = rt[rt.inc_number.isin(snow_refs) & (rt._arrived_at <= ctx.now)].sort_values("published_at")
    if rt.empty:
        return ToolResult(None, [], "no published restoration target")
    r = rt.iloc[-1].to_dict()
    eid = ctx.cite(f"RT:{r['inc_number']}@{fmt(r['published_at'])}", "Outage management restoration target (seeded)", r)
    return ToolResult({"target": fmt(r["restoration_target"]), "published_at": fmt(r["published_at"]), "inc": r["inc_number"]}, [eid],
                      f"target {fmt(r['restoration_target'])}")


@tool("contact_policy_check", "contact_policy_check", "contact_policy_check", ["UC5"])
def contact_policy_check(ctx: ToolContext, recipients: list[dict], incident_id: str, kind: str) -> ToolResult:
    """Quiet hours, frequency cap, cross-incident dedupe, consent (unavailable in pilot) per recipient."""
    cfg = ctx.cfg["notification"]
    now = ctx.now
    qs, qe = [int(x[:2]) for x in cfg["quiet_hours"]]
    in_quiet = now.hour >= qs or now.hour < qe
    earliest = now
    results = []
    if in_quiet:
        end = now.replace(hour=qe, minute=0, second=0)
        if now.hour >= qs:
            end += timedelta(days=1)
        earliest = max(earliest, end)
        results.append({"check": "quiet hours", "status": "hold", "detail": f"{cfg['quiet_hours'][0]}-{cfg['quiet_hours'][1]} local; earliest send {fmt(end)[11:16]}", "affected": len(recipients)})
    else:
        results.append({"check": "quiet hours", "status": "pass", "detail": "outside quiet hours", "affected": 0})
    cap = timedelta(hours=cfg["frequency_cap_hours"])
    prior = [p for p in ctx.state.packages.values() if p.incident_id == incident_id and p.state == "Approved" and p.scheduled_send_at]
    if prior:
        last = max(pd.Timestamp(p.scheduled_send_at).to_pydatetime() for p in prior)
        if last + cap > earliest:
            earliest = last + cap
            results.append({"check": "frequency cap", "status": "hold", "detail": f"one message per incident per {cfg['frequency_cap_hours']}h; previous message scheduled {fmt(last)[11:16]}; earliest {fmt(earliest)[11:16]}", "affected": len(recipients)})
        else:
            results.append({"check": "frequency cap", "status": "pass", "detail": "no message to these recipients for this incident in the cap window", "affected": 0})
    else:
        results.append({"check": "frequency cap", "status": "pass", "detail": "first message for this incident", "affected": 0})
    other = set()
    for p in ctx.state.packages.values():
        if p.incident_id != incident_id and p.state in ("Draft", "Approved"):
            other |= set(ctx.state.package_recipients.get(p.package_id, []))
    dup = sum(1 for r in recipients if r["subscriber_id"] in other)
    results.append({"check": "cross-incident dedupe", "status": "hold" if dup else "pass",
                    "detail": f"{dup} recipients already in another open package; one message per customer per experience", "affected": dup})
    results.append({"check": "consent / opt-out", "status": "unavailable", "detail": "UNAVAILABLE IN PILOT: no consent source, so the package is draft-only by rule", "affected": len(recipients)})
    rows = [{"recipient": r["subscriber_id"], **{x["check"]: x["status"] for x in results}} for r in recipients]
    ctx.state.contact_policy_rows.extend({"incident_id": incident_id, "kind": kind, "checked_at": fmt(now), **r} for r in rows)
    return ToolResult({"results": results, "earliest_send": fmt(earliest)}, [], "; ".join(f"{x['check']}={x['status']}" for x in results))


@tool("notification_package_build", "package inputs", "notification_package", ["UC5"])
def notification_package_build(ctx: ToolContext, **kw) -> ToolResult:
    """Template-based English text; identifiers stay pseudonymised."""
    return ToolResult(kw, [], "package built")


@tool("ng1_handoff", "none", "the single external write; disabled in demo", ["UC5"])
def ng1_handoff(ctx: ToolContext, package_id: str) -> ToolResult:
    """The only external write in the design. Disabled: no code path in the demo calls it."""
    raise ToolDisabled("ng1_handoff is disabled in the demo; nothing is sent")


@tool("reply_capture_read", "m360 placeholder", "none", ["UC5"])
def reply_capture_read(ctx: ToolContext, package_id: str) -> ToolResult:
    """Placeholder for m360 delivery and reply signal (pending the m360/ISDP decision)."""
    return ToolResult({"status": "pending m360/ISDP decision"}, [], "placeholder")


@tool("adoption_record_write", "none", "adoption_record, platform-internal", ["UC1", "UC2", "UC3", "UC5", "HUMAN"])
def adoption_record_write(ctx: ToolContext, record) -> ToolResult:
    """Append one recommendation and its human decision."""
    ctx.state.adoption.append(record)
    return ToolResult(record.record_id, [], "written")


# ---------------------------------------------------------------------------
# Conversational surface (role-scoped, read-only)
# ---------------------------------------------------------------------------
@tool("curated_query", "curated orders, SNOW, topology, queue_rank (read-only views)", "none", ["SURFACE"])
def curated_query(ctx: ToolContext, intent: str, **params) -> ToolResult:
    """Parameterised read-only queries behind the conversational panel; every answer cites the rows it returns."""
    return ToolResult({"intent": intent, "params": params}, [], intent)


@tool("feed_health_read", "feed_health", "none", ["SURFACE", "UC1"])
def feed_health_read(ctx: ToolContext) -> ToolResult:
    """Expected-arrival status per source."""
    return ToolResult(dict(ctx.state.feed_status), [], "feed health")


def registry_table() -> list[dict]:
    order = ["ticket_cluster_read", "telemetry_read", "topology_lookup", "sibling_health", "exposure_calc",
             "incident_registry.search", "incident_registry.create", "incident_registry.merge", "incident_registry.close",
             "incident_registry_read", "planned_works_check", "power_footprint_check", "line_history_read",
             "symptom_signature_check", "adoption_record_write", "queue_read", "sla_clock", "ranking_explain",
             "crew_availability_read", "subscriber_resolve", "restoration_target_read", "contact_policy_check",
             "notification_package_build", "ng1_handoff", "reply_capture_read", "curated_query", "feed_health_read"]
    return [REGISTRY[n] for n in order if n in REGISTRY]


# ---------------------------------------------------------------------------
# Registry writes (UC1 only; platform-internal)
# ---------------------------------------------------------------------------
@tool("incident_registry.create", "incident_registry", "incident_registry, platform-internal", ["UC1"])
def incident_registry_create(ctx: ToolContext, incident) -> ToolResult:
    """Write a new incident object with state Proposed."""
    ctx.state.put_incident(incident, "created")
    return ToolResult(incident.incident_id, [f"SDAL:{incident.incident_id}"], f"{incident.incident_id} {incident.state}")


@tool("incident_registry.merge", "incident_registry", "incident_registry, platform-internal", ["UC1"])
def incident_registry_merge(ctx: ToolContext, merged, parent) -> ToolResult:
    """Record a duplicate cluster as Merged into an existing incident and refresh the parent."""
    ctx.state.put_incident(merged, "merged")
    ctx.state.put_incident(parent, "updated")
    return ToolResult(merged.incident_id, [f"SDAL:{merged.incident_id}", f"SDAL:{parent.incident_id}"], f"{merged.incident_id} merged into {parent.incident_id}")


@tool("incident_registry.close", "incident_registry", "incident_registry, platform-internal", ["UC1"])
def incident_registry_close(ctx: ToolContext, incident) -> ToolResult:
    """Propose closure (optical back to baseline, no new orders for 30 minutes)."""
    ctx.state.put_incident(incident, "closure proposed")
    return ToolResult(incident.incident_id, [f"SDAL:{incident.incident_id}"], f"closure proposed for {incident.incident_id}")
