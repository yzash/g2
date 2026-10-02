import React, { useMemo } from "react";
import { useApp } from "../store";
import { hhmm, toMs, toStr } from "../data";
import type { Adoption as A } from "../types";
import { EvidenceButton, Panel, Pill, TraceButton } from "../components/common";
import { csv } from "../lib";

export function Adoption() {
  const { d, t, overlays, say, openTrace } = useApp();
  const meta = d.b.meta;
  const scripted = d.adoption(t);
  const live: A[] = Object.values(overlays).map((o, i) => ({
    record_id: `LIVE-${i + 1}`, at: o.at, actor: o.actor, role: "presenter", object_type: o.kind, object_id: o.objectId,
    recommendation: "", decision: o.decision, reason: o.reason ?? (o.outcome ? `→ ${o.outcome}` : null), outcome_observed: null, scripted: false, evidence_ids: [], live: true,
  }));
  const all = [...scripted, ...live].sort((a, b) => a.at.localeCompare(b.at));
  const morning = all.filter((a) => a.at >= meta.replay_start);

  const incs = [...d.incidents(t).values()].filter((i) => i.state !== "Merged");
  const recs = [...d.latest<any>("rec", t).values()];
  const s1 = incs.find((i) => i.element_id === "CAV_118_L004_N07B");
  const s1Recs = s1 ? recs.filter((r) => r.incident_id === s1.incident_id) : [];
  const s1Supp = new Set(s1Recs.filter((r) => r.outcome === "suppress").map((r) => r.workordernumber));
  const overrides = all.filter((a) => a.decision === "overridden");
  const pk = [...d.packages(t).values()];
  const atEnd = toMs(t) >= d.endMs - 60000;
  const safety = meta.summary.safety_critical as any[];
  const byReason = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of d.recs(t).values()) m.set(`${r.outcome} · ${r.reason_class}`, (m.get(`${r.outcome} · ${r.reason_class}`) || 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [d, t]);

  const exportRows = () => all.map((a) => ({ at: a.at, actor: a.actor, role: a.role, object_type: a.object_type, object_id: a.object_id, recommendation: a.recommendation, decision: a.decision, reason: a.reason ?? "", outcome_observed: atEnd ? a.outcome_observed ?? "" : "", live: a.live ? "yes" : "no" }));
  const download = () => {
    const blob = new Blob([csv(exportRows())], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `sdal_adoption_record_${t.slice(0, 16).replace(/[ :]/g, "")}.csv`;
    a.click();
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(csv(exportRows())); say("Adoption record copied as CSV"); } catch { say("Copy is blocked here; use Download CSV"); }
  };

  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="row between">
        <div>
          <div className="eyebrow">Adoption record · all roles, read</div>
          <h1>The morning, as recommendations and human decisions</h1>
          <div className="muted small">Every recommendation and what a person did with it: accepted, overridden with a reason, rejected, approved. Observed outcomes fill in from FSM as the morning plays out; this record feeds the evaluation harness.</div>
        </div>
        <div className="row"><button className="btn" onClick={copy}>Copy CSV</button><button className="btn primary" onClick={download}>Download CSV</button></div>
      </div>

      {s1 && (
        <div className="kpis">
          <div className="kpi"><div className="v">{incs.filter((i) => i.proposed_at >= meta.replay_start).length}</div><div className="l">New incidents this morning</div></div>
          <div className="kpi"><div className="v">{s1Supp.size}</div><div className="l">Suppressions on {s1.incident_id}</div></div>
          <div className="kpi"><div className="v">{overrides.length}</div><div className="l">Overrides, each with a reason</div></div>
          <div className="kpi"><div className="v">{pk.filter((p) => p.state === "Approved" || overlays[p.package_id]?.decision === "approved").length}</div><div className="l">Approved draft packages (none sent)</div></div>
          <div className="kpi hot"><div className="v num">{s1.detection_lead_min != null ? `${s1.detection_lead_min} min` : "—"}</div><div className="l">{s1.incident_id} ahead of the hourly cycle</div></div>
          <div className="kpi"><div className="v">{atEnd ? safety.length : "…"}</div><div className="l">Wrong suppressions {atEnd ? "(suppressed or held, field repair needed)" : "(known at end of replay)"}</div></div>
        </div>
      )}

      {s1 && <Comparison />}

      <div className="grid cols-2">
        <Panel title={`Timeline · ${morning.length} decisions since ${hhmm(meta.replay_start)}`} tight right={<span className="small faint">{all.length - morning.length} overnight</span>}>
          <div className="tablewrap scrollbox" style={{ maxHeight: 560 }}>
            <table className="t">
              <thead><tr><th>time</th><th>who</th><th>object</th><th>recommendation</th><th>decision</th><th>observed outcome</th><th></th></tr></thead>
              <tbody>{[...all].reverse().map((a) => (
                <tr key={a.record_id}>
                  <td className="num">{hhmm(a.at)}{a.at < meta.replay_start && <div className="small faint">{a.at.slice(5, 10)}</div>}</td>
                  <td className="small">{a.actor}{a.batch && <div className="faint">batch accept</div>}</td>
                  <td className="mono small">{a.object_id}</td>
                  <td className="small">{a.recommendation}</td>
                  <td><Pill kind={a.live ? "live" : a.decision === "overridden" || a.decision === "rejected" ? "exc" : "approved"}>{a.decision}</Pill>{a.reason && <div className="small muted">“{a.reason}”</div>}</td>
                  <td className="small">{atEnd ? a.outcome_observed ?? "" : <span className="faint">pending</span>}</td>
                  <td>{a.evidence_ids.length > 0 && <EvidenceButton ids={a.evidence_ids} title={a.record_id} label="Rows" />}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </Panel>
        <div className="stack" style={{ gap: 16 }}>
          <Panel title="Detection lead time per incident" tight>
            <table className="t">
              <thead><tr><th>incident</th><th>proposed</th><th>hourly cycle</th><th className="r">lead</th><th></th></tr></thead>
              <tbody>{incs.map((i) => (
                <tr key={i.incident_id}>
                  <td><b className="mono">{i.incident_id}</b><div className="small faint">{i.element_type} {i.element_id}</div></td>
                  <td className="num">{hhmm(i.proposed_at)}</td>
                  <td className="num small">{i.hourly_cycle_at ? hhmm(i.hourly_cycle_at) : "already in SNOW"}</td>
                  <td className="r num">{i.detection_lead_min != null ? `${i.detection_lead_min} min` : "—"}</td>
                  <td><button className="evid" onClick={() => openTrace(i.incident_id)}>Trace</button></td>
                </tr>
              ))}</tbody>
            </table>
          </Panel>
          <Panel title="Recommendations by reason class" tight>
            <table className="t"><tbody>{byReason.map(([k, v]) => <tr key={k}><td className="small">{k}</td><td className="r num">{v}</td></tr>)}</tbody></table>
          </Panel>
          <Panel title="Authorisation boundary" eyebrow="Tool registry: everything the system can do">
            <div className="tablewrap scrollbox" style={{ maxHeight: 300 }}>
              <table className="t">
                <thead><tr><th>tool</th><th>writes</th><th>used by</th></tr></thead>
                <tbody>{(meta.tool_registry as any[]).map((r) => <tr key={r.name}><td className="mono small">{r.name}</td><td className="small" style={{ color: r.name === "ng1_handoff" ? "var(--crit)" : undefined }}>{r.writes}</td><td className="small">{r.used_by.join(", ")}</td></tr>)}</tbody>
              </table>
            </div>
            <div className="small faint" style={{ marginTop: 6 }}>{meta.summary.tool_calls.toLocaleString()} tool calls in {meta.summary.trace_runs} agent runs; ng1_handoff calls: {meta.summary.ng1_calls}.</div>
          </Panel>
        </div>
      </div>
    </div>
  );
}

function Comparison() {
  const { d, t } = useApp();
  const c = d.b.meta.comparison;
  const start = toMs("2026-10-27 05:30:00"), end = toMs("2026-10-27 13:30:00");
  const pos = (s: string) => `${Math.max(0, Math.min(100, ((toMs(s) - start) / (end - start)) * 100))}%`;
  const vis = (s: string | null) => s && s <= t;
  const ticks = [0, 1, 2, 3, 4, 5, 6, 7, 8].map((h) => toStr(start + h * 3_600_000));
  return (
    <Panel title={`${c.incident_id}: today's process vs the SDAL morning`} eyebrow="Comparison on the synthetic day only">
      <div className="compare">
        <div className="lane"><span className="small faint" /><div style={{ position: "relative", height: 14 }}>{ticks.map((tk) => <span key={tk} className="small faint num" style={{ position: "absolute", left: pos(tk), transform: "translateX(-50%)" }}>{tk.slice(11, 16)}</span>)}</div></div>
        <div className="lane">
          <div><b>Today</b><div className="small faint">{c.today.process}</div></div>
          <div className="lane-track">
            <Ev at={c.first_fault} label="fault 05:48" color="var(--crit)" pos={pos} />
            {c.orders.map((o: any) => <Ev key={o.workordernumber} at={o.createdate} label="" color="var(--ink-3)" pos={pos} />)}
            <Ev at={c.today.first_detection} label={`hourly cycle ${hhmm(c.today.first_detection)}`} color="var(--ink)" pos={pos} />
            {c.orders.map((o: any) => <Ev key={o.workordernumber + "a"} at={o.appointmentdate} label="" color="var(--warn)" pos={pos} />)}
            <Ev at="2026-10-27 11:30:00" label={`${c.today.dispatched} trucks roll 10:00–13:00`} color="var(--warn)" pos={pos} />
          </div>
        </div>
        <div className="lane">
          <div><b>SDAL</b><div className="small faint">Customer-side signals and optical evidence, every 5 minutes</div></div>
          <div className="lane-track">
            <Ev at={c.first_fault} label="fault 05:48" color="var(--crit)" pos={pos} />
            {vis(c.sdal.first_detection) && <Ev at={c.sdal.first_detection} label={`detected ${hhmm(c.sdal.first_detection)}`} color="var(--accent)" pos={pos} />}
            {vis(c.sdal.confirmed) && <Ev at={c.sdal.confirmed} label="" color="var(--accent)" pos={pos} />}
            {vis("2026-10-27 06:40:00") && <Ev at="2026-10-27 06:40:00" label="14 told (draft)" color="var(--accent)" pos={pos} />}
            {vis(c.sdal.closed) && <Ev at={c.sdal.closed} label={`restored ${hhmm(c.sdal.closed)}`} color="var(--ok)" pos={pos} />}
          </div>
        </div>
        <div className="small muted">First detection {hhmm(c.sdal.first_detection)} against {hhmm(c.today.first_detection)}: {c.sdal.lead_min} minutes earlier. {c.today.note} With SDAL, three of the four orders close without a visit and the fourth rolls only because the dispatcher overrode it for a B2B SLA.</div>
      </div>
    </Panel>
  );
}

function Ev({ at, label, color, pos }: { at: string; label: string; color: string; pos: (s: string) => string }) {
  return <div className="lane-ev" style={{ left: pos(at) }}><i style={{ background: color }} />{label && <span className="small">{label}</span>}</div>;
}
