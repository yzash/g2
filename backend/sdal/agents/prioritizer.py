"""Agent 3: Queue Prioritizer (UC3).

S = w_t*min(t/6h, 1.5) + w_l*log10(1+lines) + w_s*sev + w_v*vip + w_c*(1-crew)

Arithmetic the operations lead can inspect. No language model ranks anything.
Re-ranks on incident create/confirm/close, on crew change, and every 15 minutes.
"""

from __future__ import annotations

import math

import pandas as pd

from .. import tools as T
from ..models import QueueRow
from .dispatch import eligible

NAME = "UC3"


def fmt(t) -> str | None:
    return None if t is None else pd.Timestamp(t).strftime("%Y-%m-%d %H:%M:%S")


def score(inputs: dict, w: dict, cfg_q: dict) -> float:
    t = min(inputs["t_elapsed_h"] / cfg_q["window_hours"], cfg_q["time_cap"])
    return round(w["w_t"] * t + w["w_l"] * math.log10(1 + inputs["lines"]) + w["w_s"] * inputs["sev"]
                 + w["w_v"] * inputs["vip"] + w["w_c"] * (1 - inputs["crew"]), 4)


class Prioritizer:
    def __init__(self, engine):
        self.e = engine
        self.cfg = engine.cfg
        self.q = engine.cfg["queue"]

    def rerank(self, ctx: T.ToolContext, reason: str) -> list[QueueRow]:
        e = self.e
        now = pd.Timestamp(ctx.now)
        run_id = e.tracer.start(NAME, f"re-rank: {reason}")
        T.queue_read(ctx)
        items = []
        o = ctx.snap.orders
        open_rep = ctx.snap.open_repairs
        for inc in e.state.incidents.values():
            if inc.state not in ("Proposed", "Confirmed"):
                continue
            cluster = open_rep[open_rep.facilityname.isin(inc.naps)]
            clock = T.sla_clock(ctx, createdates=list(cluster.createdate))
            crew = T.crew_availability_read(ctx, incident=inc).data["crew"]
            lines = inc.observed_lines + inc.inferred_lines
            start = clock.data["start"]
            inputs = {"t_elapsed_h": round(((now - pd.Timestamp(start)).total_seconds() / 3600) if start else 0.0, 3),
                      "lines": lines, "sev": self.q["sev_values"][inc.element_type], "sev_class": inc.severity,
                      "element_type": inc.element_type, "vip": round(inc.vip_b2b_count / lines, 4) if lines else 0.0,
                      "crew": 1 if crew else 0, "state": inc.state, "open_orders": int(len(cluster))}
            items.append({"item_id": inc.incident_id, "item_type": "incident",
                          "label": f"{inc.incident_id} · {inc.element_type} {inc.element_id}" + (" · recurring" if inc.kind != "outage" else ""),
                          "inputs": inputs, "clock_start": start, "breach_eta": clock.data["breach"], "territory": inc.territory,
                          "evidence_ids": [f"SDAL:{inc.incident_id}"] + [T.wo_id(ctx, r) for r in cluster.head(5).to_dict("records")]})
        covered = set()
        for inc in e.state.incidents.values():
            if inc.state in ("Proposed", "Confirmed"):
                covered |= set(inc.naps)
        for r in o.to_dict("records"):
            if not eligible(r, ctx.now) or r.get("facilityname") in covered:
                continue
            line = ctx.snap.static.svc_to_line.loc[r["serviceidnumber"]]
            crew = T.crew_availability_read(ctx, order=r).data["crew"]
            clock = T.sla_clock(ctx, createdates=[r["createdate"]])
            inputs = {"t_elapsed_h": round((now - pd.Timestamp(r["createdate"])).total_seconds() / 3600, 3), "lines": 1,
                      "sev": self.q["sev_values"]["LINE"], "sev_class": "5.3", "element_type": "LINE",
                      "vip": 1.0 if bool(line.vip) else 0.0, "crew": 1 if crew else 0, "state": r["status"], "open_orders": 1}
            rec = e.state.latest_rec(r["workordernumber"])
            items.append({"item_id": r["workordernumber"], "item_type": "order",
                          "label": f"{r['workordernumber']} · single line · {r['facilityname'] if isinstance(r.get('facilityname'), str) else r.get('cabinetid') + ' (no NAP)'}"
                                   + (f" · {rec.outcome}" if rec else ""),
                          "inputs": inputs, "clock_start": clock.data["start"], "breach_eta": clock.data["breach"],
                          "territory": line.territory, "evidence_ids": [T.wo_id(ctx, r)]})
        w = self.q["weights"]
        for it in items:
            it["score"] = score(it["inputs"], w, self.q)
        items.sort(key=lambda x: (-x["score"], x["item_id"]))
        rows = []
        for i, it in enumerate(items):
            exc, txt = False, None
            for higher in items[:i]:
                if it["item_type"] == "incident" and higher["item_type"] == "incident" and higher["inputs"]["sev"] > it["inputs"]["sev"] and it["breach_eta"] and higher["breach_eta"] \
                        and it["breach_eta"] < higher["breach_eta"]:
                    exc = True
                    txt = (f"Breaches its 6-hour window at {it['breach_eta'][11:16]}, before higher-ranked, higher-severity "
                           f"{higher['item_id']} ({higher['breach_eta'][11:16]}).")
                    break
            rows.append(QueueRow(item_id=it["item_id"], item_type=it["item_type"], label=it["label"], rank=i + 1, score=it["score"],
                                 inputs=it["inputs"], clock_start=it["clock_start"], breach_eta=it["breach_eta"], exception_flag=exc,
                                 exception_text=txt, ranked_at=fmt(ctx.now), territory=it["territory"], evidence_ids=it["evidence_ids"]))
        e.tracer.note(f"Ranked {len(rows)} items with weights {w}." + (f" Top: {rows[0].item_id} ({rows[0].score:.3f})." if rows else ""))
        e.tracer.output("queue_rank", f"QR-{fmt(ctx.now)}")
        e.tracer.end()
        e.state.put_queue(rows, reason, run_id)
        return rows
