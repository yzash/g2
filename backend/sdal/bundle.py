"""Writes the replay bundle the operator surface plays back.

Everything on screen comes from here: Globe-shaped tables (with arrival
stamps), the engine's timestamped events, per-minute surface snapshots, the
full trace and the evidence rows every card links to.
"""

from __future__ import annotations

import json
import math
from datetime import datetime

import numpy as np
import pandas as pd

from . import BUNDLE_PATH, ROOT, TRACE_PATH
from .engine import Engine
from .tools import registry_table


def clean(v):
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    if isinstance(v, (pd.Timestamp, datetime)):
        return None if pd.isna(v) else pd.Timestamp(v).strftime("%Y-%m-%d %H:%M:%S")
    if v is pd.NaT:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return None if math.isnan(v) else round(float(v), 4)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def table(df: pd.DataFrame) -> dict:
    """Column-oriented table: {columns, rows} keeps the bundle compact."""
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = df[c].dt.strftime("%Y-%m-%d %H:%M:%S")
    rows = [[clean(v) for v in r] for r in df.itertuples(index=False, name=None)]
    return {"columns": list(df.columns), "rows": rows}


CHAPTERS = [
    {"t": "2026-10-27 05:30:00", "label": "Overnight", "screen": "tower", "text": "SDAL-0405 (OLT_DAV_207 fibre cut) has been open since 23:42 with a crew assigned."},
    {"t": "2026-10-27 06:00:00", "label": "06:00 Shift opens", "screen": "tower", "text": "One map, eight territories; every feed on time."},
    {"t": "2026-10-27 06:07:00", "label": "06:07 A cluster forms", "screen": "tower", "text": "Three customers on CAV_118_L004_N07B; no alarm. The Investigator watches but abstains: the WMS batch has not landed."},
    {"t": "2026-10-27 06:12:00", "label": "06:12 SDAL-0412 proposed", "screen": "element", "target": "CAV_118_L004_N07B", "text": "Optical Rx below -27 dBm on 11 of 14 gateways since 05:48. NAP-level fibre fault, support 0.86."},
    {"t": "2026-10-27 06:15:00", "label": "06:15 Dispatch reacts", "screen": "dispatch", "text": "Suppress on the incident's orders, dispatch on a CPE signature next door; planned works and power shown as unavailable."},
    {"t": "2026-10-27 06:31:00", "label": "06:30 Queue re-ranks", "screen": "queue", "text": "SDAL-0412 above the older OLT incident SDAL-0405: no crew yet, and its window breaches first."},
    {"t": "2026-10-27 06:40:00", "label": "06:40 Silent majority", "screen": "comms", "text": "14 recipients, 10 of them silent. Approved as a draft; nothing is sent."},
    {"t": "2026-10-27 06:51:00", "label": "06:45 Feed stall", "screen": "tower", "text": "Handyman stops arriving. Late, then stalled; detectors that depend on it pause."},
    {"t": "2026-10-27 07:13:00", "label": "07:10 Restoration", "screen": "element", "target": "CAV_118_L004_N07B", "text": "Rx back to -20 dBm; closure proposed and confirmed."},
    {"t": "2026-10-27 07:30:00", "label": "07:30 The question", "screen": "tower", "chat": "Which NAPs had three or more repeat orders this week with no SNOW incident?", "text": "Answered from curated rows, with citations."},
    {"t": "2026-10-27 07:42:00", "label": "07:32 Flapping NAP", "screen": "queue", "text": "Short repeat SNOW tickets rolled into one recurring-fault incident; scored on lines, not ticket count."},
    {"t": "2026-10-27 08:32:00", "label": "08:30 Hold expires", "screen": "dispatch", "text": "The 2-hour hold-and-recheck becomes a dispatch: nothing new arrived."},
]

SCENARIOS = [
    {"n": 1, "clock": "05:48", "title": "Non-alarm NAP fibre fault", "element": "CAV_118_L004_N07B", "jump": "2026-10-27 06:12:00", "screen": "element",
     "takeaway": "Non-alarm faults are found from the customer side, with evidence, before the hourly cycle."},
    {"n": 2, "clock": "06:05", "title": "Single-line CPE fault next door", "element": "CAV_118_L004_N07A", "jump": "2026-10-27 06:16:00", "screen": "dispatch",
     "takeaway": "The system does not over-suppress; a customer-side signature rolls a truck."},
    {"n": 3, "clock": "06:20", "title": "OLT outage already in SNOW", "element": "OLT_DAV_207", "jump": "2026-10-27 07:03:00", "screen": "element",
     "takeaway": "Existing outages are linked, never duplicated; the queue explains itself."},
    {"n": 4, "clock": "06:30", "title": "Stale evidence, silent gateway", "element": "DAV_204_L003_N04B", "jump": "2026-10-27 06:32:00", "screen": "dispatch",
     "takeaway": "Hold is a time-boxed decision with a recheck, not a quiet cancellation."},
    {"n": 5, "clock": "06:45", "title": "Handyman feed stall", "element": None, "jump": "2026-10-27 06:51:00", "screen": "tower",
     "takeaway": "Missing data is an alert, never evidence of calm."},
    {"n": 6, "clock": "07:00", "title": "Flapping NAP", "element": "CAV_121_L002_N05A", "jump": "2026-10-27 07:42:00", "screen": "queue",
     "takeaway": "Globe's known data quirks are handled, not hidden."},
]


def telemetry_series(e: Engine, featured_naps: set[str]) -> dict:
    cfg = e.cfg
    start = cfg["clock"]["telemetry_start"].replace("T", " ")
    df = e.con.execute("""
        SELECT l.mac, l.nap, epoch(t.report_time - TIMESTAMP '%s') / 300 AS slot, t.rx_dbm
        FROM c_telemetry t JOIN c_lines l USING (mac)""" % start).fetchdf()
    n_slots = int((pd.Timestamp(cfg["clock"]["telemetry_end"]) - pd.Timestamp(cfg["clock"]["telemetry_start"])).total_seconds() // 300)
    out_full, out_coarse = {}, {}
    df["v"] = np.rint(df.rx_dbm * 10).astype(int)
    df["slot"] = df.slot.astype(int)
    for mac, g in df.groupby("mac"):
        arr = [None] * n_slots
        for s, v in zip(g.slot, g.v):
            arr[s] = int(v)
        nap = g.nap.iloc[0]
        if nap in featured_naps:
            out_full[mac] = arr
        else:
            # 15-minute resolution: last available reading in each 15-minute bucket
            out_coarse[mac] = [next((x for x in reversed(arr[i:i + 3]) if x is not None), None) for i in range(0, n_slots, 3)]
    return {"start": start, "step_min": 5, "coarse_step_min": 15, "n_slots": n_slots, "full": out_full, "coarse": out_coarse,
            "unit": "dBm x 10 (converted from raw x 0.0001 mW)"}


def repeat_orders_answer(e: Engine, at: str, days: int = 7, min_orders: int = 3) -> dict:
    """Reference answer for the 07:30 question, computed in DuckDB over the curated layer."""
    rows = e.con.execute(f"""
        WITH o AS (
            SELECT * FROM c_order_versions WHERE _arrived_at <= TIMESTAMP '{at}'
            QUALIFY row_number() OVER (PARTITION BY workordernumber ORDER BY lastupdatedate DESC) = 1
        ), s AS (SELECT DISTINCT affected_nap FROM c_snow_versions WHERE _arrived_at <= TIMESTAMP '{at}'
                 AND ticket_created_datetime >= TIMESTAMP '{at}' - INTERVAL {days} DAY)
        SELECT facilityname AS nap, count(*) AS n, list(workordernumber ORDER BY createdate) AS orders
        FROM o WHERE skillset = 'Repair' AND facilityname IS NOT NULL AND createdate >= TIMESTAMP '{at}' - INTERVAL {days} DAY
          AND facilityname NOT IN (SELECT affected_nap FROM s)
        GROUP BY facilityname HAVING count(*) >= {min_orders} ORDER BY n DESC, nap
    """).fetchall()
    return {"question": "Which NAPs had three or more repeat orders this week with no SNOW incident?", "at": at,
            "rows": [{"nap": r[0], "orders": int(r[1]), "workorders": list(r[2])} for r in rows],
            "sql": "latest order version per workordernumber, Repair, createdate in 7 days, NAP not in any SNOW affected_nap in 7 days, count >= 3"}


def build_bundle(e: Engine | None = None, path=BUNDLE_PATH) -> dict:
    e = e or Engine().run()
    cfg = e.cfg
    st = e.static
    geo = st.geo
    n_subs = st.lines.groupby("nap").size()
    naps = [{"NAP": r.NAP, "LCP": r.LCP, "OLT": r.OLT, "site": r.site, "territory": r.territory, "territory_name": r.territory_name,
             "barangay": r.barangay, "town": r.town, "province": r.province, "lat": r.lat, "lon": r.lon,
             "subs": int(n_subs.get(r.NAP, 0))} for r in geo.itertuples()]
    topo_changes = [clean(r) for r in st.topology_all[st.topology_all.valid_to < pd.Timestamp("2099-01-01")].to_dict("records")] + \
                   [clean(r) for r in st.topology_all[st.topology_all.valid_from > pd.Timestamp("2026-01-01")].to_dict("records")]
    lines = st.lines[["subscriber_id", "account_no", "service_id", "nap", "mac", "sn", "prod_desc", "msf", "vip", "base", "territory"]]

    orders = e.con.execute("SELECT * FROM c_order_versions ORDER BY lastupdatedate, workordernumber").fetchdf()
    snow = e.con.execute("SELECT * FROM c_snow_versions ORDER BY latest_extract_datetime").fetchdf()
    hm = e.con.execute("SELECT * FROM c_handyman ORDER BY date_time").fetchdf()
    alarms = e.con.execute("SELECT * FROM c_alarms ORDER BY raised").fetchdf()
    rt = e.con.execute("SELECT * FROM c_restoration").fetchdf()

    featured = set()
    for inc in e.state.incidents.values():
        if inc.element_type == "NAP":
            featured.add(inc.element_id)
            featured |= set(e.static.topology_at(pd.Timestamp("2026-10-27 06:00")).pipe(lambda t: t.index[t.LCP == t.LCP.get(inc.element_id)]))
    featured |= {"CAV_118_L004_N07A", "DAV_204_L003_N04B"}

    o_final = orders.sort_values("lastupdatedate").groupby("workordernumber").tail(1)
    s1_orders = o_final[o_final.workordernumber.isin(e.truth["s1_orders"])]
    s1 = next(i for i in e.state.incidents.values() if i.element_id == "CAV_118_L004_N07B" and i.state != "Merged")
    comparison = {
        "incident_id": s1.incident_id,
        "first_fault": "2026-10-27 05:48:00",
        "orders": [{"workordernumber": r.workordernumber, "createdate": clean(r.createdate), "appointmentdate": clean(r.appointmentdate)}
                   for r in s1_orders.sort_values("createdate").itertuples()],
        "today": {"first_detection": s1.hourly_cycle_at, "process": "Hourly manual cycle: ticket counts per NAP plus manual NMS and AA checks",
                  "dispatched": len(s1_orders), "note": "All four orders roll a truck within 24 hours; no customer is told until they call."},
        "sdal": {"first_detection": s1.proposed_at, "lead_min": s1.detection_lead_min, "confirmed": s1.decided_at, "closed": s1.closed_at},
    }

    trace_runs = e.tracer.runs
    e.tracer.dump(TRACE_PATH)
    summary = {
        "incidents": sum(1 for i in e.state.incidents.values() if i.state != "Merged"),
        "merges": sum(1 for i in e.state.incidents.values() if i.state == "Merged"),
        "recommendations": sum(len(v) for v in e.state.recs.values()),
        "safety_critical": e.safety,
        "trace_runs": len(trace_runs),
        "evidence_rows": len(e.evidence),
        "tool_calls": sum(len(r["tool_calls"]) for r in trace_runs),
        "refused_calls": sum(1 for r in trace_runs for n in r["notes"] if n.startswith("REFUSED")),
        "ng1_calls": 0,
    }
    outline = json.load(open(ROOT / "data" / "ref" / "ph_outline.json"))
    q = cfg["queue"]
    bundle = {
        "meta": {
            "title": "SDAL Control Tower",
            "subtitle": "MVP demo · synthetic morning",
            "day": cfg["demo_day"], "day_label": "Tuesday 27 October 2026 (synthetic)",
            "engine_start": cfg["clock"]["engine_start"].replace("T", " "),
            "replay_start": cfg["clock"]["replay_start"].replace("T", " "),
            "replay_end": cfg["clock"]["replay_end"].replace("T", " "),
            "seed": cfg["seed"],
            "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "disclaimer": "Synthetic rows on Globe's schemas. Nothing shown is sanctioned operational data or a claim about Globe's numbers.",
            "config": {
                "floor": cfg["dispatch"]["confidence_floor"], "hold_hours": cfg["dispatch"]["hold_hours_default"],
                "wrong_suppression_cost_ratio": cfg["dispatch"]["wrong_suppression_cost_ratio"],
                "truck_roll_unit_cost_note": cfg["dispatch"]["truck_roll_unit_cost_note"],
                "queue_weights": q["weights"], "prd_v01_weights": q["prd_v01_weights"], "vip_weight_if_enabled": q["vip_weight_if_enabled"],
                "window_hours": q["window_hours"], "time_cap": q["time_cap"], "sev_values": q["sev_values"],
                "support_weights": cfg["support_score"]["weights"], "propose_min_support": cfg["support_score"]["propose_min_support"],
                "ticket_density_threshold": cfg["support_score"]["ticket_density_threshold"],
                "detectors": cfg["detectors"], "quiet_hours": cfg["notification"]["quiet_hours"],
                "frequency_cap_hours": cfg["notification"]["frequency_cap_hours"], "feeds": cfg["feeds"], "feed_stalls": cfg["feed_stalls"],
            },
            "chapters": CHAPTERS, "scenarios": SCENARIOS, "tool_registry": registry_table(),
            "territories": sorted({(n["territory"], n["territory_name"], n["site"]) for n in naps}),
            "topology_changes": topo_changes, "comparison": comparison, "summary": summary,
        },
        "geo": {"outline": outline["polygons"], "source": outline["source"]},
        "naps": naps,
        "lines": table(lines),
        "tables": {"orders": table(orders), "snow": table(snow), "handyman": table(hm), "alarms": table(alarms), "restoration": table(rt)},
        "telemetry": telemetry_series(e, featured),
        "events": clean(e.state.events),
        "snapshots": clean(e.snapshots),
        "trace": clean(trace_runs),
        "evidence": clean(e.evidence),
        "answers": {"repeat_orders": repeat_orders_answer(e, "2026-10-27 07:30:00")},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(bundle, f, separators=(",", ":"), default=str)
    return bundle
