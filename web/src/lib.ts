import type { QueueRow } from "./types";
import type { Weights } from "./store";
import { toMs, toStr } from "./data";

export interface QCfg { window_hours: number; time_cap: number }

/** The UC3 score, term by term (same arithmetic as backend/sdal/agents/prioritizer.py). */
export function terms(inp: QueueRow["inputs"], w: Weights, q: QCfg, tElapsedH?: number) {
  const t = Math.min((tElapsedH ?? inp.t_elapsed_h) / q.window_hours, q.time_cap);
  return {
    time: w.w_t * t,
    lines: w.w_l * Math.log10(1 + inp.lines),
    severity: w.w_s * inp.sev,
    vip: w.w_v * inp.vip,
    "no crew": w.w_c * (1 - inp.crew),
  };
}
export const total = (tm: Record<string, number>) => Object.values(tm).reduce((a, b) => a + b, 0);

/** Re-rank queue rows at clock time `now` with the given weights (the sandbox panel). */
export function rerank(rows: QueueRow[], w: Weights, q: QCfg, now: string) {
  const nowMs = toMs(now);
  const scored = rows.map((r) => {
    const te = r.clock_start ? (nowMs - toMs(r.clock_start)) / 3_600_000 : 0;
    const tm = terms(r.inputs, w, q, te);
    return { row: r, terms: tm, score: total(tm), tElapsed: te };
  });
  scored.sort((a, b) => b.score - a.score || a.row.item_id.localeCompare(b.row.item_id));
  return scored.map((s, i) => {
    let exc: string | null = null;
    for (const h of scored.slice(0, i)) {
      if (s.row.item_type === "incident" && h.row.item_type === "incident" && h.row.inputs.sev > s.row.inputs.sev && s.row.breach_eta && h.row.breach_eta && s.row.breach_eta < h.row.breach_eta) {
        exc = `Breaches its 6-hour window at ${s.row.breach_eta.slice(11, 16)}, before higher-ranked, higher-severity ${h.row.item_id} (${h.row.breach_eta.slice(11, 16)}).`;
        break;
      }
    }
    return { ...s, rank: i + 1, exception: exc };
  });
}

export function explain(a: ReturnType<typeof rerank>[number], b: ReturnType<typeof rerank>[number]) {
  const lines: { term: string; a: number; b: number; diff: number }[] = Object.keys(a.terms).map((k) => ({
    term: k, a: (a.terms as any)[k], b: (b.terms as any)[k], diff: (a.terms as any)[k] - (b.terms as any)[k],
  }));
  lines.sort((x, y) => Math.abs(y.diff) - Math.abs(x.diff));
  return lines;
}

export function inputText(r: QueueRow, tElapsed: number) {
  const i = r.inputs;
  return `${tElapsed.toFixed(2)}h on the clock · ${i.lines} line${i.lines > 1 ? "s" : ""} · ${i.element_type} (sev ${i.sev}) · crew ${i.crew ? "assigned" : "none"} · VIP share ${(i.vip * 100).toFixed(0)}%`;
}

export const ELIGIBLE = ["Open", "Unassigned", "Pending"];
export function eligible(o: Record<string, any>, now: string) {
  if (o.skillset !== "Repair" || !ELIGIBLE.includes(o.status) || !o.appointmentdate) return false;
  return toMs(o.appointmentdate) <= toMs(now) + 24 * 3_600_000;
}

export function csv(rows: Record<string, any>[]): string {
  if (!rows.length) return "";
  const cols = Object.keys(rows[0]);
  const esc = (v: any) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
}

export const minus = (s: string, h: number) => toStr(toMs(s) - h * 3_600_000);
