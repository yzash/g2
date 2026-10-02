import React, { useMemo, useState } from "react";
import { useApp } from "../store";
import { hhmm, toMs } from "../data";
import type { Incident, Row } from "../types";
import { Bar, ElementLink, EvidenceButton, Grounded, Panel, Pill, StatePill, TraceButton, useRole } from "../components/common";
import { OpticalChart } from "../components/OpticalChart";

const COMP_LABEL: Record<string, string> = { ticket_density: "Ticket density", physical_signal: "Physical signal", sibling_cleanliness: "Sibling cleanliness", alarm_presence: "Alarm presence" };

export function IncidentCard({ inc }: { inc: Incident }) {
  const { d, t, overlays, decide } = useApp();
  const role = useRole("incident");
  const [mode, setMode] = useState<"none" | "reject" | "merge">("none");
  const [reason, setReason] = useState("");
  const [target, setTarget] = useState("");
  const w = d.b.meta.config.support_weights;
  const ov = overlays[inc.incident_id];
  const others = [...d.incidents(t).values()].filter((i) => i.incident_id !== inc.incident_id && (i.state === "Confirmed" || i.state === "Proposed"));
  const state = ov && ov.kind === "incident" ? (ov.decision === "rejected" ? "Rejected" : ov.decision === "merged" ? "Merged" : "Confirmed") : inc.state;
  const c = inc.score_components;
  return (
    <Grounded ids={inc.evidence_ids} what={inc.incident_id}>
      <article className={`inc ${state === "Proposed" ? "proposed" : ""}`}>
        <div className="inc-h">
          <div style={{ minWidth: 0 }}>
            <div className="row">
              <h2 className="mono">{inc.incident_id}</h2>
              <StatePill state={state} />
              {ov && <Pill kind="live">live decision</Pill>}
              {inc.kind !== "outage" && <Pill kind="exc">recurring fault · flap count {inc.flap_count}</Pill>}
              {inc.closure_proposed_at && inc.state === "Confirmed" && <Pill kind="ok">closure proposed {hhmm(inc.closure_proposed_at)}</Pill>}
            </div>
            <div className="muted" style={{ marginTop: 2 }}>
              {inc.element_type}-level {inc.kind} on <ElementLink id={inc.element_id} /> · severity {inc.severity} · proposed {hhmm(inc.proposed_at)}
              {inc.first_signal_at && inc.first_signal_at !== inc.proposed_at ? ` · first signal ${hhmm(inc.first_signal_at)}` : ""}
            </div>
          </div>
          <div className="score">
            <div className="eyebrow">Support score</div>
            <b>{inc.support_score.toFixed(2)}</b>
            <div className="small faint">not a probability until calibrated</div>
          </div>
        </div>
        <div className="inc-b">
          <dl className="kv">
            <dt>Lines affected</dt><dd className="num"><b>{inc.observed_lines + inc.inferred_lines}</b> · {inc.observed_lines} observed (called or ran Handyman), <b>{inc.inferred_lines} silent</b> · {inc.vip_b2b_count} VIP/B2B</dd>
            <dt>SNOW</dt><dd>{inc.snow_refs.length ? inc.snow_refs.join(", ") : "none"}</dd>
            <dt>Crew</dt><dd>{inc.crew_assigned ? "assigned (static team / assignment group)" : "none assigned"} · live crew availability unavailable in pilot</dd>
            {inc.decided_by && <><dt>Decision</dt><dd>{inc.state} by {inc.decided_by} at {hhmm(inc.decided_at)}{inc.decision_reason ? ` · “${inc.decision_reason}”` : ""}</dd></>}
            {inc.detection_lead_min != null && <><dt>Lead time</dt><dd>{inc.detection_lead_min} min ahead of the hourly manual cycle ({hhmm(inc.hourly_cycle_at)})</dd></>}
            {ov && <><dt>Live decision</dt><dd>{ov.decision} by {ov.actor} at {hhmm(ov.at)}{ov.reason ? ` · “${ov.reason}”` : ""}. The replay continues on the scripted branch; in the pilot the agents re-run on this decision.</dd></>}
          </dl>
          <p className="rationale">{inc.rationale}</p>
          <div className="cols-2e grid" style={{ gap: 18 }}>
            <div className="bars">
              <div className="eyebrow">Score components (weights from config)</div>
              {Object.keys(w).map((k) => <Bar key={k} label={COMP_LABEL[k]} value={c[k] ?? 0} weight={w[k]} />)}
              <div className="small faint">= {Object.keys(w).map((k) => `${w[k]}×${(c[k] ?? 0).toFixed(2)}`).join(" + ")} = {inc.support_score.toFixed(2)}</div>
            </div>
            <div className="bars">
              <div className="eyebrow">Isolation hypotheses</div>
              {inc.hypothesis_rank.map((h) => <Bar key={h.element_id} label={`${h.element_type} ${h.element_id.split("_").slice(-1)[0]}`} value={h.score} />)}
              <div className="small faint">Siblings clean: NAP-level. Most siblings on the LCP degraded: LCP-level. Most LCPs on the OLT degraded: OLT-level.</div>
            </div>
          </div>
          <div className="actions">
            <EvidenceButton ids={inc.evidence_ids} title={`${inc.incident_id} evidence`} />
            <TraceButton refId={inc.incident_id} label="Full trace" />
            <span style={{ flex: 1 }} />
            {inc.state === "Proposed" && !ov && (
              <>
                <button className="btn primary" disabled={!role.allowed} title={role.why} onClick={() => decide({ objectId: inc.incident_id, kind: "incident", decision: "confirmed" })}>Confirm</button>
                <button className="btn" disabled={!role.allowed} title={role.why} onClick={() => setMode(mode === "merge" ? "none" : "merge")}>Merge…</button>
                <button className="btn danger" disabled={!role.allowed} title={role.why} onClick={() => setMode(mode === "reject" ? "none" : "reject")}>Reject…</button>
              </>
            )}
          </div>
          {mode === "reject" && (
            <div className="stack">
              <label className="small" htmlFor={`rej-${inc.incident_id}`}>Rejection reason (required; becomes an evaluation case)</label>
              <textarea id={`rej-${inc.incident_id}`} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Known planned maintenance on this LCP" />
              <div><button className="btn danger" disabled={!reason.trim()} onClick={() => { decide({ objectId: inc.incident_id, kind: "incident", decision: "rejected", reason }); setMode("none"); }}>Reject with reason</button></div>
            </div>
          )}
          {mode === "merge" && (
            <div className="row">
              <select value={target} onChange={(e) => setTarget(e.target.value)} aria-label="Merge into">
                <option value="">Merge into…</option>
                {others.map((o) => <option key={o.incident_id} value={o.incident_id}>{o.incident_id} · {o.element_id}</option>)}
              </select>
              <button className="btn" disabled={!target} onClick={() => { decide({ objectId: inc.incident_id, kind: "incident", decision: "merged", reason: `into ${target}` }); setMode("none"); }}>Merge</button>
            </div>
          )}
        </div>
      </article>
    </Grounded>
  );
}

export function ElementView() {
  const { d, t, element, go } = useApp();
  const id = element || "CAV_118_L004_N07B";
  const type = d.elementType(id);
  const naps = d.napsUnder(type, id);
  const ref = d.naps.get(naps[0])!;
  const snap = d.snap(t);
  const horizon = snap.wms_horizon;
  const chain = { NAP: type === "NAP" ? id : null, LCP: type === "OLT" ? null : ref.LCP, OLT: ref.OLT };
  const incs = [...d.incidents(t).values()];
  const ancestors = new Set([id, chain.LCP, chain.OLT].filter(Boolean) as string[]);
  const nset = new Set(naps);
  const related = incs.filter((i) => i.state !== "Merged" && (ancestors.has(i.element_id) || i.naps.some((n) => nset.has(n))))
    .sort((a, b) => (a.state === "Proposed" || a.state === "Confirmed" ? -1 : 1) - (b.state === "Proposed" || b.state === "Confirmed" ? -1 : 1) || b.proposed_at.localeCompare(a.proposed_at));
  const merges = incs.filter((i) => i.state === "Merged" && related.some((r) => r.incident_id === i.parent_id));

  const lines = useMemo(() => naps.flatMap((n) => d.linesByNap.get(n) || []), [id]);
  const accts = new Set(lines.map((l) => l.account_no));
  const orders = d.orders(t).filter((o) => o.skillset === "Repair" && nset.has(o.facilityname)).sort((a, b) => b.createdate.localeCompare(a.createdate));
  const recentOrders = orders.filter((o) => toMs(o.createdate) >= toMs(t) - 24 * 3_600_000 || ["Open", "Unassigned", "Pending", "Delayed", "Ongoing"].includes(o.status));
  const hm = d.handymanAt(t).filter((h) => accts.has(h.account_number) && toMs(h.date_time) >= toMs(t) - 24 * 3_600_000).sort((a, b) => b.date_time.localeCompare(a.date_time));
  const recs = d.recs(t);
  const snow = d.snow(t).filter((s) => nset.has(s.affected_nap)).sort((a, b) => b.ticket_created_datetime.localeCompare(a.ticket_created_datetime));
  const reported = new Set([...recentOrders.map((o) => o.accountnumber), ...hm.filter((h) => h.LineStatus === "Account has a last mile issue" || h.Result === "FAILED").map((h) => h.account_number)]);

  const gw = useMemo(() => lines.map((l): Row => {
    const last = d.latestRx(l.mac, horizon);
    const base = d.baseline(l.mac, horizon);
    const dropped = last && base != null ? base - last.v > 6 : false;
    return { ...l, rx: last?.v ?? null, base, dropped, silent: !last };
  }), [lines, horizon]);
  const hot = new Set(gw.filter((g) => g.dropped).map((g) => g.mac));

  const siblings = type === "NAP" ? (d.napsByLcp.get(ref.LCP) || []).filter((n) => n !== id) : type === "LCP" ? [...new Set((d.napsByOlt.get(ref.OLT) || []).map((n) => d.naps.get(n)!.LCP))].filter((l) => l !== id) : (d.oltsBySite.get(ref.site) || []).filter((o) => o !== id);
  const sibRows = useMemo(() => siblings.map((s) => {
    const sn = d.napsUnder(type === "NAP" ? "NAP" : type, s);
    const g = sn.flatMap((n) => d.linesByNap.get(n) || []);
    const rx = g.map((l) => d.latestRx(l.mac, horizon)?.v).filter((v): v is number => v != null).sort((a, b) => a - b);
    const oo = d.orders(t).filter((o) => o.skillset === "Repair" && sn.includes(o.facilityname) && ["Open", "Unassigned", "Pending", "Delayed", "Ongoing"].includes(o.status)).length;
    const state = sn.map((n) => snap.nap_states[n] || "clean").reduce((a, b) => (b === "clean" ? a : b), "clean");
    return { id: s, median: rx.length ? rx[Math.floor(rx.length / 2)] : null, reporting: rx.length, total: g.length, orders: oo, state };
  }), [id, horizon, t]);
  const changes = (d.b.meta.topology_changes as any[]).filter((c) => nset.has(c.NAP));

  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="row between">
        <div>
          <div className="eyebrow">Element view · {type}</div>
          <h1 className="mono">{id}</h1>
          <div className="muted small row" style={{ gap: 6 }}>
            {chain.OLT && <ElementLink id={chain.OLT} />}{chain.LCP && <>›<ElementLink id={chain.LCP} /></>}{chain.NAP && <>›<span className="mono">{chain.NAP}</span></>}
            <span>· {ref.territory} {ref.territory_name} · {ref.town}, {ref.province}{type === "NAP" ? ` · Brgy. ${ref.barangay}` : ""} · {lines.length} lines on {naps.length} NAP{naps.length > 1 ? "s" : ""}</span>
          </div>
        </div>
        <button className="btn" onClick={() => go("tower")}>Back to Control Tower</button>
      </div>
      {changes.length > 0 && (
        <div className="alert warn">Effective-dated topology: {changes[0].NAP} moves from {changes[0].LCP} to {changes[1]?.LCP} at {hhmm(changes[0].valid_to)}. Orders before that time stay attributed to the old parent.</div>
      )}

      {related.length === 0 && <div className="panel empty">No SDAL incident on this element or its parents at {hhmm(t)}.</div>}
      {related.map((i) => <IncidentCard key={i.incident_id} inc={i} />)}
      {merges.length > 0 && (
        <Panel title={`Duplicate clusters linked, not duplicated · ${merges.length}`} eyebrow="Merged into the incident above" tight>
          <table className="t"><tbody>
            {merges.map((m) => <tr key={m.incident_id}><td className="mono">{m.incident_id}</td><td className="num">{hhmm(m.proposed_at)}</td><td>{m.rationale}</td><td><EvidenceButton ids={m.evidence_ids} title={m.incident_id} /></td></tr>)}
          </tbody></table>
        </Panel>
      )}

      <Panel title="Optical Rx per gateway, last 24 hours" eyebrow="WMS telemetry · raw × 0.0001 mW → dBm"
        right={<span className="small muted">{hot.size} of {gw.length} gateways more than 6 dB below baseline · {gw.filter((g) => g.silent).length} not reporting</span>}>
        <OpticalChart macs={gw.map((g) => g.mac)} highlight={hot} />
      </Panel>

      <div className="grid cols-2e">
        <Panel title={`Open and recent repair orders · ${recentOrders.length}`} tight>
          <div className="tablewrap"><table className="t">
            <thead><tr><th>workordernumber</th><th>created</th><th>status</th><th>faultcode</th><th>SDAL</th><th></th></tr></thead>
            <tbody>
              {recentOrders.map((o) => {
                const r = recs.get(o.workordernumber);
                return <tr key={o.workordernumber}><td className="mono">{o.workordernumber}</td><td className="num">{hhmm(o.createdate)}</td><td>{o.status}</td><td className="mono">{o.faultcode}</td><td>{r ? <Pill kind={r.outcome}>{r.outcome}</Pill> : <span className="faint">—</span>}</td><td><EvidenceButton ids={[`WO:${o.workordernumber}`]} title={o.workordernumber} label="Row" /></td></tr>;
              })}
              {recentOrders.length === 0 && <tr><td colSpan={6} className="empty">No orders in the last 24 hours.</td></tr>}
            </tbody>
          </table></div>
        </Panel>
        <Panel title={`Handyman results, last 24 hours · ${hm.length}`} tight>
          <div className="tablewrap scrollbox" style={{ maxHeight: 280 }}><table className="t">
            <thead><tr><th>audit_no</th><th>time</th><th>template</th><th>LineStatus</th><th>ModemStatus</th><th>Last Mile Status</th></tr></thead>
            <tbody>
              {hm.slice(0, 60).map((h) => <tr key={h.audit_no}><td className="mono">{h.audit_no}</td><td className="num">{hhmm(h.date_time)}</td><td className="small">{h.diagnosis_template}</td><td className="small">{h.LineStatus || "—"}</td><td className="small">{h.ModemStatus}</td><td className="mono">{h["Last Mile Status"] || "—"}</td></tr>)}
              {hm.length === 0 && <tr><td colSpan={6} className="empty">No Handyman results that have arrived.</td></tr>}
            </tbody>
          </table></div>
        </Panel>
      </div>

      <div className="grid cols-2e">
        <Panel title={`Sibling ${type === "NAP" ? "NAPs on " + ref.LCP : type === "LCP" ? "LCPs on " + ref.OLT : "OLTs in " + ref.site}`} tight>
          <div className="tablewrap scrollbox" style={{ maxHeight: 320 }}><table className="t">
            <thead><tr><th>element</th><th className="r">median Rx</th><th className="r">reporting</th><th className="r">open orders</th><th>state</th></tr></thead>
            <tbody>{sibRows.map((s) => <tr key={s.id}><td><ElementLink id={s.id} /></td><td className="r">{s.median?.toFixed(1) ?? "—"}</td><td className="r">{s.reporting}/{s.total}</td><td className="r">{s.orders}</td><td>{s.state === "clean" ? <span className="faint">clean</span> : <Pill kind={s.state === "confirmed" ? "confirmed" : s.state === "proposed" ? "proposed" : "hold"}>{s.state}</Pill>}</td></tr>)}</tbody>
          </table></div>
        </Panel>
        <Panel title={`ServiceNow outages on this element · ${snow.length}`} tight>
          <div className="tablewrap scrollbox" style={{ maxHeight: 320 }}><table className="t">
            <thead><tr><th>inc_number</th><th>created</th><th>inc_state</th><th>outage_reason</th><th>assignment group</th><th className="r">res. h</th></tr></thead>
            <tbody>
              {[...new Map(snow.map((s) => [s.inc_number, s])).values()].map((s) => <tr key={s.inc_number}><td className="mono">{s.inc_number}</td><td className="num">{hhmm(s.ticket_created_datetime)}</td><td>{s.inc_state}</td><td className="small">{s.outage_reason}</td><td className="mono small">{s.inc_assignment_group}</td><td className="r">{s.resolution_hours ?? "—"}</td></tr>)}
              {snow.length === 0 && <tr><td colSpan={6} className="empty">No SNOW incident covers this element.</td></tr>}
            </tbody>
          </table></div>
        </Panel>
      </div>

      <Panel title={`Subscribers · ${lines.length}`} eyebrow="Pseudonymised tokens; no names or phone numbers exist in the demo data" tight>
        <div className="tablewrap scrollbox"><table className="t">
          <thead><tr><th>subscriber</th><th>plan</th><th>segment</th><th>gateway MAC</th><th className="r">Rx dBm</th><th className="r">baseline</th><th>optical</th><th>contact</th></tr></thead>
          <tbody>{gw.slice(0, 200).map((g) => (
            <tr key={g.subscriber_id}>
              <td className="mono">{g.subscriber_id}</td><td className="small">{g.prod_desc}</td>
              <td>{g.vip ? <Pill kind="proposed">VIP/B2B</Pill> : <span className="faint small">mass</span>}</td>
              <td className="mono">{g.mac}</td><td className="r">{g.rx?.toFixed(1) ?? "—"}</td><td className="r">{g.base?.toFixed(1) ?? "—"}</td>
              <td>{g.silent ? <Pill kind="hold">not reporting</Pill> : g.dropped ? <Pill kind="confirmed">&gt;6 dB drop</Pill> : <span className="faint small">ok</span>}</td>
              <td>{reported.has(g.account_no) ? <span className="small">reported</span> : <span className="faint small">silent</span>}</td>
            </tr>
          ))}</tbody>
        </table></div>
        {gw.length > 200 && <div className="empty">Showing 200 of {gw.length} lines.</div>}
      </Panel>
    </div>
  );
}
