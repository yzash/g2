// Point-in-time selectors over the replay bundle. Every screen reads through
// these, so nothing appears on screen before the engine produced it or before
// its source feed would have delivered it.
import type { Bundle, Ev, Incident, NapRef, Pkg, QueueRow, Rec, Row, Snap, Table, Adoption, Abstention } from "./types";

// Timestamps are local Manila time written as "YYYY-MM-DD HH:MM:SS"; we keep them as UTC internally.
export const toMs = (s: string) => Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10), +s.slice(11, 13), +s.slice(14, 16), +s.slice(17, 19) || 0);
export const toStr = (ms: number) => new Date(ms).toISOString().slice(0, 19).replace("T", " ");
export const hhmm = (s?: string | null) => (s ? s.slice(11, 16) : "--:--");
export const MIN = 60_000;

export function rows(t: Table): Row[] {
  return t.rows.map((r) => Object.fromEntries(t.columns.map((c, i) => [c, r[i]])));
}

function lastBefore<T extends { t: string }>(arr: T[], t: string): T | undefined {
  let lo = 0, hi = arr.length - 1, ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (arr[mid].t <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return ans >= 0 ? arr[ans] : undefined;
}

export class Data {
  b: Bundle;
  naps: Map<string, NapRef>;
  napsByLcp = new Map<string, string[]>();
  napsByOlt = new Map<string, string[]>();
  oltsBySite = new Map<string, string[]>();
  lcpOlt = new Map<string, string>();
  lines: Row[];
  linesByNap = new Map<string, Row[]>();
  lineByAcct = new Map<string, Row>();
  lineBySvc = new Map<string, Row>();
  orderVersions = new Map<string, Row[]>();
  snowVersions = new Map<string, Row[]>();
  handyman: Row[];
  alarms: Row[];
  restoration: Row[];
  byKind = new Map<string, Map<string, Ev[]>>();
  queueEvents: Ev[] = [];
  runs: Map<string, any>;
  startMs: number; endMs: number; engineMs: number;

  constructor(b: Bundle) {
    this.b = b;
    this.naps = new Map(b.naps.map((n) => [n.NAP, n]));
    for (const n of b.naps) {
      push(this.napsByLcp, n.LCP, n.NAP);
      push(this.napsByOlt, n.OLT, n.NAP);
      this.lcpOlt.set(n.LCP, n.OLT);
      const olts = this.oltsBySite.get(n.site) || [];
      if (!olts.includes(n.OLT)) olts.push(n.OLT);
      this.oltsBySite.set(n.site, olts);
    }
    this.lines = rows(b.lines);
    for (const l of this.lines) {
      if (l.nap) push(this.linesByNap, l.nap, l);
      this.lineByAcct.set(l.account_no, l);
      this.lineBySvc.set(l.service_id, l);
    }
    for (const o of rows(b.tables.orders)) push(this.orderVersions, o.workordernumber, o);
    for (const s of rows(b.tables.snow)) push(this.snowVersions, `${s.inc_number}|${s.affected_nap}`, s);
    this.handyman = rows(b.tables.handyman);
    this.alarms = rows(b.tables.alarms);
    this.restoration = rows(b.tables.restoration);
    for (const e of b.events) {
      if (e.kind === "queue") { this.queueEvents.push(e); continue; }
      let m = this.byKind.get(e.kind);
      if (!m) this.byKind.set(e.kind, (m = new Map()));
      push(m, e.id, e);
    }
    this.runs = new Map(b.trace.map((r) => [r.run_id, r]));
    this.startMs = toMs(b.meta.replay_start);
    this.endMs = toMs(b.meta.replay_end);
    this.engineMs = toMs(b.meta.engine_start);
  }

  // ---- engine objects at time t --------------------------------------------------
  latest<T>(kind: string, t: string): Map<string, T> {
    const out = new Map<string, T>();
    const m = this.byKind.get(kind);
    if (!m) return out;
    for (const [id, evs] of m) {
      const e = lastBefore(evs, t);
      if (e) out.set(id, e.obj as T);
    }
    return out;
  }
  history(kind: string, id: string, t: string): Ev[] {
    return (this.byKind.get(kind)?.get(id) || []).filter((e) => e.t <= t);
  }
  incidents(t: string) { return this.latest<Incident>("incident", t); }
  packages(t: string) { return this.latest<Pkg>("package", t); }
  /** latest version of each recommendation, keyed by work order */
  recs(t: string): Map<string, Rec> {
    const byRec = this.latest<Rec>("rec", t);
    const out = new Map<string, Rec>();
    for (const r of byRec.values()) {
      const cur = out.get(r.workordernumber);
      if (!cur || r.review_seq > cur.review_seq) out.set(r.workordernumber, r);
    }
    return out;
  }
  recVersions(wo: string, t: string): Rec[] {
    const byRec = this.latest<Rec>("rec", t);
    return [...byRec.values()].filter((r) => r.workordernumber === wo).sort((a, b) => a.review_seq - b.review_seq);
  }
  adoption(t: string): Adoption[] { return [...this.latest<Adoption>("adoption", t).values()].sort((a, b) => a.at.localeCompare(b.at)); }
  abstentions(t: string): Abstention[] { return [...this.latest<Abstention>("abstention", t).values()]; }
  queue(t: string): { t: string; reason: string; rows: QueueRow[]; run_id: string } | null {
    const e = lastBefore(this.queueEvents, t);
    return e ? { t: e.t, ...e.obj } : null;
  }
  snap(t: string): Snap {
    return lastBefore(this.b.snapshots, t) || this.b.snapshots[0];
  }

  // ---- Globe-shaped tables at time t (only rows that have arrived) ------------------
  orders(t: string): Row[] {
    const out: Row[] = [];
    for (const vs of this.orderVersions.values()) {
      let cur: Row | undefined;
      for (const v of vs) if (v._arrived_at <= t && (!cur || v.lastupdatedate >= cur.lastupdatedate)) cur = v;
      if (cur) out.push(cur);
    }
    return out;
  }
  order(wo: string, t: string): Row | undefined {
    let cur: Row | undefined;
    for (const v of this.orderVersions.get(wo) || []) if (v._arrived_at <= t && (!cur || v.lastupdatedate >= cur.lastupdatedate)) cur = v;
    return cur;
  }
  snow(t: string): Row[] {
    const out: Row[] = [];
    for (const vs of this.snowVersions.values()) {
      let cur: Row | undefined;
      for (const v of vs) if (v._arrived_at <= t) cur = v;
      if (cur) out.push(cur);
    }
    return out;
  }
  handymanAt(t: string): Row[] { return this.handyman.filter((h) => h._arrived_at <= t); }

  // ---- topology --------------------------------------------------------------------
  napsUnder(type: string, id: string): string[] {
    if (type === "NAP") return [id];
    if (type === "LCP") return this.napsByLcp.get(id) || [];
    if (type === "OLT") return this.napsByOlt.get(id) || [];
    if (type === "SITE") return (this.oltsBySite.get(id) || []).flatMap((o) => this.napsByOlt.get(o) || []);
    return [];
  }
  elementType(id: string): "NAP" | "LCP" | "OLT" {
    if (this.naps.has(id)) return "NAP";
    if (this.napsByLcp.has(id)) return "LCP";
    return "OLT";
  }

  // ---- telemetry --------------------------------------------------------------------
  series(mac: string, horizon: string | null): { t: number; v: number | null }[] {
    const tel = this.b.telemetry;
    const start = toMs(tel.start);
    const full = tel.full[mac];
    const step = full ? tel.step_min : tel.coarse_step_min;
    const arr = full || tel.coarse[mac] || [];
    const hz = horizon ? toMs(horizon) : -Infinity;
    const out: { t: number; v: number | null }[] = [];
    arr.forEach((v, i) => {
      const t = start + i * step * MIN;
      if (t <= hz) out.push({ t, v: v == null ? null : v / 10 });
    });
    return out;
  }
  latestRx(mac: string, horizon: string | null): { t: number; v: number } | null {
    const s = this.series(mac, horizon);
    const hz = horizon ? toMs(horizon) : 0;
    for (let i = s.length - 1; i >= 0; i--) {
      if (s[i].v != null) return hz - s[i].t <= 15 * MIN ? { t: s[i].t, v: s[i].v as number } : null;
    }
    return null;
  }
  baseline(mac: string, horizon: string | null): number | null {
    const s = this.series(mac, horizon).filter((p) => p.v != null && p.t <= (horizon ? toMs(horizon) : 0) - 60 * MIN).map((p) => p.v as number);
    if (!s.length) return null;
    const sorted = s.slice(-300).sort((a, b) => a - b);
    return sorted[Math.floor(sorted.length / 2)];
  }

  // ---- evidence resolution -------------------------------------------------------------
  resolve(id: string, t: string): { id: string; source: string; row: Row; fetched_by?: string | null; fetched_at?: string } | null {
    const ev = this.b.evidence[id];
    if (ev) return ev;
    const [kind, rest] = [id.split(":")[0], id.slice(id.indexOf(":") + 1)];
    if (kind === "SDAL") {
      const inc = this.incidents(t).get(rest);
      return inc ? { id, source: "incident_registry (platform-owned)", row: { incident_id: inc.incident_id, element: `${inc.element_type} ${inc.element_id}`, state: inc.state, support_score: inc.support_score, proposed_at: inc.proposed_at, snow_refs: inc.snow_refs.join(", ") } } : null;
    }
    if (kind === "WO") {
      const o = this.order(rest.split("@")[0], t);
      return o ? { id, source: "FSM work order (oWFM ALL STATUS)", row: o } : null;
    }
    if (kind === "INC") {
      const s = this.snow(t).find((r) => r.inc_number === rest.split("/")[0]);
      return s ? { id, source: "ServiceNow outage (NAP-expanded)", row: s } : null;
    }
    if (kind === "AUD") {
      const h = this.handyman.find((r) => r.audit_no === rest);
      return h ? { id, source: "Handyman diagnostic log", row: h } : null;
    }
    if (kind === "SUB") {
      const l = this.lines.find((r) => r.subscriber_id === rest);
      return l ? { id, source: "Subscriber base (pseudonymised)", row: l } : null;
    }
    return null;
  }
  runsFor(ref: string): any[] {
    return this.b.trace.filter((r) => r.outputs.some((o: any) => o.ref === ref) || r.trigger.includes(ref));
  }
}

function push<K, V>(m: Map<K, V[]>, k: K, v: V) {
  const a = m.get(k);
  if (a) a.push(v); else m.set(k, [v]);
}

export const fmtScore = (n: number | null | undefined) => (n == null ? "—" : n.toFixed(2));
export const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
