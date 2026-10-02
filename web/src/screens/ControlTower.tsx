import React, { useMemo, useState } from "react";
import { useApp } from "../store";
import { hhmm, toMs } from "../data";
import { ClusterMap, Legend, NationalMap } from "../components/MapView";
import { ElementLink, EvidenceButton, Panel, Pill, StatePill } from "../components/common";

const STATUSES = ["ALL", "Open", "Unassigned", "Pending", "Delayed", "Ongoing"];

export function ControlTower() {
  const { d, t, go } = useApp();
  const snap = d.snap(t);
  const [territory, setTerritory] = useState("ALL");
  const [site, setSite] = useState("CAV");
  const [barangay, setBarangay] = useState("ALL");
  const [status, setStatus] = useState("ALL");
  const [window6h, setWindow6h] = useState(true);

  const incidents = [...d.incidents(t).values()];
  const open = incidents.filter((i) => i.state === "Proposed" || i.state === "Confirmed").sort((a, b) => (a.state === "Proposed" ? -1 : 1) - (b.state === "Proposed" ? -1 : 1) || b.proposed_at.localeCompare(a.proposed_at));
  const recs = d.recs(t);
  const territories: [string, string, string][] = d.b.meta.territories;
  const sitesFor = territory === "ALL" ? [...d.oltsBySite.keys()] : territories.filter((x) => x[0] === territory).map((x) => x[2]);
  const brgys = [...new Set(d.napsUnder("SITE", site).map((n) => d.naps.get(n)!.barangay))];

  const orders = useMemo(() => {
    const cut = window6h ? toMs(t) - 6 * 3_600_000 : 0;
    return d.orders(t)
      .filter((o) => o.skillset === "Repair" && ["Open", "Unassigned", "Pending", "Delayed", "Ongoing"].includes(o.status))
      .filter((o) => status === "ALL" || o.status === status)
      .filter((o) => toMs(o.createdate) >= cut)
      .filter((o) => {
        const line = d.lineBySvc.get(o.serviceidnumber);
        if (territory !== "ALL" && line?.territory !== territory) return false;
        if (barangay !== "ALL") return o.facilityname && d.naps.get(o.facilityname)?.barangay === barangay;
        return true;
      })
      .sort((a, b) => b.createdate.localeCompare(a.createdate));
  }, [d, t, status, window6h, territory, barangay]);

  const signals = Object.entries(snap.nap_states).filter(([, s]) => s === "signal").map(([n]) => n);
  const snowOnly = Object.entries(snap.nap_states).filter(([, s]) => s === "snow").map(([n]) => n);
  const abst = d.abstentions(t).filter((a) => toMs(a.at) >= toMs(t) - 6 * 3_600_000);
  const q = d.queue(t);
  const exc = q?.rows.filter((r) => r.exception_flag).slice(0, 3) || [];
  const c = snap.counts;

  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="kpis">
        <Kpi v={c.open_orders} l="Open repair orders" />
        <Kpi v={c.open_incidents} l="Open SDAL incidents" />
        <Kpi v={c.proposed} l="Awaiting NOC decision" hot={c.proposed > 0} />
        <Kpi v={c.pending_reviews} l="Dispatch reviews pending" hot={c.pending_reviews > 0} />
        <Kpi v={c.open_snow} l="Open SNOW outages" />
        <Kpi v={c.drafts} l="Draft notification packages" />
      </div>

      <div className="row" style={{ gap: 12 }}>
        <span className="eyebrow">Filters</span>
        <label className="small">Territory{" "}
          <select value={territory} onChange={(e) => { setTerritory(e.target.value); const s = territories.find((x) => x[0] === e.target.value); if (s) setSite(s[2]); setBarangay("ALL"); }}>
            <option value="ALL">All eight</option>
            {territories.map(([code, name]) => <option key={code} value={code}>{code} · {name}</option>)}
          </select>
        </label>
        <label className="small">Cluster{" "}
          <select value={site} onChange={(e) => { setSite(e.target.value); setBarangay("ALL"); }}>
            {sitesFor.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label className="small">Barangay{" "}
          <select value={barangay} onChange={(e) => setBarangay(e.target.value)}>
            <option value="ALL">All</option>
            {brgys.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
        </label>
        <label className="small">Repair status{" "}
          <select value={status} onChange={(e) => setStatus(e.target.value)}>{STATUSES.map((s) => <option key={s}>{s}</option>)}</select>
        </label>
        <label className="small row" style={{ gap: 5 }}><input type="checkbox" checked={window6h} onChange={(e) => setWindow6h(e.target.checked)} /> 6-hour window</label>
        <span style={{ flex: 1 }} />
        <Legend />
      </div>

      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 330px) minmax(0, 1fr) minmax(0, 360px)" }}>
        <Panel title="All eight territories" eyebrow="National">
          <NationalMap site={site} setSite={(s) => { setSite(s); setBarangay("ALL"); }} territory={territory} />
          <div className="small faint">Click a cluster to open it. Territory names are synthetic placeholders.</div>
        </Panel>
        <Panel title={`${site} cluster · OLT → LCP → NAP`} eyebrow={`WMS horizon ${hhmm(snap.wms_horizon)}`}>
          <ClusterMap site={site} barangay={barangay} onPick={(id) => go("element", id)} />
        </Panel>
        <Panel title="Needs attention" eyebrow={`At ${hhmm(t)}`}>
          <div className="stack">
            {open.length === 0 && <div className="faint small">No open incidents.</div>}
            {open.map((i) => (
              <button key={i.incident_id} onClick={() => go("element", i.element_id)} className="panel" style={{ textAlign: "left", padding: "9px 11px", borderColor: i.state === "Proposed" ? "var(--accent)" : undefined, background: "var(--surface)" }}>
                <div className="row between">
                  <b className="mono">{i.incident_id}</b>
                  <StatePill state={i.state} />
                </div>
                <div className="small">{i.element_type} {i.element_id}{i.kind !== "outage" ? " · recurring fault" : ""}</div>
                <div className="small muted num">
                  {i.observed_lines + i.inferred_lines} lines ({i.inferred_lines} silent) · support {i.support_score.toFixed(2)} · {i.crew_assigned ? "crew assigned" : "no crew"}
                  {i.closure_proposed_at && i.state === "Confirmed" ? " · closure proposed" : ""}
                </div>
                {i.state === "Proposed" && <div className="small" style={{ color: "var(--accent)", fontWeight: 600, marginTop: 3 }}>NOC decision needed: confirm, reject or merge</div>}
              </button>
            ))}
            {signals.length > 0 && (
              <div className="small">
                <div className="eyebrow" style={{ marginBottom: 4 }}>Detector signals, not yet an incident</div>
                {signals.map((n) => <div key={n}><ElementLink id={n} /> <span className="faint">watching; support below proposal threshold {d.b.meta.config.propose_min_support}</span></div>)}
              </div>
            )}
            {snap.paused.length > 0 && (
              <div className="small">
                <div className="eyebrow" style={{ marginBottom: 4 }}>Paused detectors</div>
                {snap.paused.map((p) => <div key={p.detector} style={{ color: "var(--crit)" }}>{p.note}</div>)}
              </div>
            )}
            {exc.length > 0 && (
              <div className="small">
                <div className="eyebrow" style={{ marginBottom: 4 }}>Queue exceptions</div>
                {exc.map((r) => <div key={r.item_id}><b className="mono">{r.item_id}</b> <span className="muted">{r.exception_text}</span></div>)}
              </div>
            )}
            {abst.length > 0 && (
              <div className="small">
                <div className="eyebrow" style={{ marginBottom: 4 }}>Honest abstentions</div>
                {abst.map((a) => <div key={a.abstention_id} className="muted">{a.text} <EvidenceButton ids={a.evidence_ids} title={a.abstention_id} label="Row" /></div>)}
              </div>
            )}
            {snowOnly.length > 0 && (
              <div className="small">
                <div className="eyebrow" style={{ marginBottom: 4 }}>SNOW outages without an SDAL signal</div>
                <div className="row">{snowOnly.map((n) => <ElementLink key={n} id={n} />)}</div>
              </div>
            )}
          </div>
        </Panel>
      </div>

      <Panel title={`Open repair orders · ${orders.length}`} eyebrow="FSM / oWFM, as arrived" tight
        right={<span className="small faint">Column names as in Globe's ALL STATUS file</span>}>
        <div className="tablewrap scrollbox">
          <table className="t">
            <thead><tr><th>workordernumber</th><th>createdate</th><th>status</th><th>faultcode</th><th>facilityname</th><th>cabinetid</th><th>team</th><th>appointmentdate</th><th>SDAL recommendation</th><th></th></tr></thead>
            <tbody>
              {orders.map((o) => {
                const r = recs.get(o.workordernumber);
                return (
                  <tr key={o.workordernumber} className="click" onClick={() => o.facilityname ? go("element", o.facilityname) : go("dispatch")}>
                    <td className="mono">{o.workordernumber}</td>
                    <td className="num">{hhmm(o.createdate)} <span className="faint">{o.createdate.slice(5, 10)}</span></td>
                    <td>{o.status}</td>
                    <td className="mono">{o.faultcode}</td>
                    <td className="mono">{o.facilityname || <span className="faint">blank</span>}</td>
                    <td className="mono">{o.cabinetid}</td>
                    <td className="mono">{o.team || <span className="faint">—</span>}</td>
                    <td className="num">{hhmm(o.appointmentdate)}</td>
                    <td>{r ? <Pill kind={r.outcome}>{r.outcome}</Pill> : <span className="faint small">not eligible</span>}</td>
                    <td><EvidenceButton ids={[`WO:${o.workordernumber}`]} title={o.workordernumber} label="Row" /></td>
                  </tr>
                );
              })}
              {orders.length === 0 && <tr><td colSpan={10} className="empty">No open repair orders match the filters.</td></tr>}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

function Kpi({ v, l, hot }: { v: number; l: string; hot?: boolean }) {
  return <div className={`kpi ${hot ? "hot" : ""}`}><div className="v">{v ?? 0}</div><div className="l">{l}</div></div>;
}
