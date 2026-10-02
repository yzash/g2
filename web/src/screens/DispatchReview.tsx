import React, { useMemo, useState } from "react";
import { useApp } from "../store";
import { hhmm, toMs } from "../data";
import type { Rec } from "../types";
import { Countdown, ElementLink, EvidenceButton, Grounded, Panel, Pill, TraceButton, useRole } from "../components/common";
import { eligible } from "../lib";

function Chips({ r }: { r: Rec }) {
  const { openEvidence } = useApp();
  const inc = r.evidence_ids.find((x) => x.startsWith("SDAL:"));
  const gw = r.evidence_ids.filter((x) => x.startsWith("GW:"));
  const hm = r.evidence_ids.filter((x) => x.startsWith("AUD:"));
  const open = (title: string, ids: string[]) => (e: React.MouseEvent) => { e.stopPropagation(); openEvidence(title, ids); };
  return (
    <div className="row" style={{ gap: 4 }}>
      {inc && <button className="chip" onClick={open("Incident", [inc])}>{inc.slice(5)}</button>}
      {gw.length > 0 && <button className="chip" onClick={open("Optical / reachability", gw)}>optical · {gw.length}</button>}
      {hm.length > 0 && <button className="chip" onClick={open("Handyman", hm)}>Handyman</button>}
      <span className="chip na" title="Planned-works source unavailable in pilot: the check runs and returns unknown, never clear">planned works: n/a</span>
      <span className="chip na" title="Power-footprint source unavailable in pilot: the check runs and returns unknown, never clear">power: n/a</span>
      {r.untrusted_text_flags.length > 0 && <span className="chip flag" title={r.untrusted_text_flags.join("\n")}>untrusted text ignored</span>}
    </div>
  );
}

export function DispatchReview() {
  const { d, t, overlays, decide } = useApp();
  const role = useRole("dispatch");
  const cfg = d.b.meta.config;
  const [territory, setTerritory] = useState("ALL");
  const [view, setView] = useState<"sdal" | "today">("sdal");
  const [showClosed, setShowClosed] = useState(false);
  const [sel, setSel] = useState<string | null>(null);
  const [ovr, setOvr] = useState<{ outcome: string; reason: string }>({ outcome: "dispatch", reason: "" });

  const recs = d.recs(t);
  const items = useMemo(() => {
    return [...recs.values()].map((r) => ({ r, o: d.order(r.workordernumber, t)! }))
      .filter(({ o }) => o && (showClosed || eligible(o, t)))
      .filter(({ r }) => territory === "ALL" || r.territory === territory)
      .sort((a, b) => {
        const pa = a.r.dispatcher_decision ? 1 : 0, pb = b.r.dispatcher_decision ? 1 : 0;
        return pa - pb || b.r.recommended_at.localeCompare(a.r.recommended_at);
      });
  }, [recs, t, territory, showClosed, d]);
  const counts = { suppress: 0, hold: 0, dispatch: 0 } as Record<string, number>;
  items.forEach(({ r }) => counts[r.outcome]++);
  const selected = sel ? items.find((x) => x.r.workordernumber === sel) || null : items[0] || null;
  const breakEven = cfg.wrong_suppression_cost_ratio / (cfg.wrong_suppression_cost_ratio + 1);

  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="row between">
        <div>
          <div className="eyebrow">Dispatch review · UC2</div>
          <h1>Every dispatch-eligible order, reviewed before it rolls</h1>
          <div className="muted small">Repair orders with status Open, Unassigned or Pending and an appointment in the next 24 hours. The agent recommends; the dispatcher decides; the agent cannot cancel anything.</div>
        </div>
        <div className="seg">
          <button className={view === "sdal" ? "on" : ""} onClick={() => setView("sdal")}>SDAL review</button>
          <button className={view === "today" ? "on" : ""} onClick={() => setView("today")}>Today's process</button>
        </div>
      </div>

      <div className="kpis" style={{ gridTemplateColumns: "repeat(5, minmax(0,1fr))" }}>
        <div className="kpi"><div className="v">{counts.suppress}</div><div className="l">Suppress (upstream fault)</div></div>
        <div className="kpi"><div className="v">{counts.hold}</div><div className="l">Hold and recheck</div></div>
        <div className="kpi"><div className="v">{counts.dispatch}</div><div className="l">Dispatch</div></div>
        <div className="kpi"><div className="v num">{cfg.floor.toFixed(2)}</div><div className="l">Confidence floor: below it, suppress and hold are unreachable</div></div>
        <div className="kpi"><div className="v num">{cfg.wrong_suppression_cost_ratio}:1</div><div className="l">Wrong suppression vs wrong dispatch. Calibrated break-even {breakEven.toFixed(2)}; the demo floor sits on an uncalibrated score</div></div>
      </div>

      <div className="row">
        <label className="small">Territory{" "}
          <select value={territory} onChange={(e) => setTerritory(e.target.value)}>
            <option value="ALL">All</option>
            {(d.b.meta.territories as string[][]).map(([c, n]) => <option key={c} value={c}>{c} · {n}</option>)}
          </select>
        </label>
        <label className="small row" style={{ gap: 5 }}><input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} /> Include orders no longer eligible</label>
        <span className="small faint" style={{ marginLeft: "auto" }}>Estimated avoidable cost: {cfg.truck_roll_unit_cost_note.toLowerCase()}. INVALID, Cancelled and WithoutVisit are never counted as avoided rolls.</span>
      </div>

      {view === "today" ? (
        <Panel title="The same orders under today's process" eyebrow="Comparison" tight>
          <table className="t">
            <thead><tr><th>workordernumber</th><th>created</th><th>facilityname</th><th>today</th><th>appointment</th><th>SDAL instead</th></tr></thead>
            <tbody>{items.map(({ r, o }) => (
              <tr key={r.workordernumber}><td className="mono">{r.workordernumber}</td><td className="num">{hhmm(o.createdate)}</td><td className="mono">{o.facilityname || "blank"}</td>
                <td><Pill kind="dispatch">dispatched within 24h</Pill></td><td className="num">{hhmm(o.appointmentdate)}</td><td><Pill kind={r.outcome}>{r.outcome}</Pill></td></tr>
            ))}</tbody>
          </table>
          <div className="empty">Under today's process every order rolls a truck at its appointment. No check for an upstream fault, planned works, power or a customer-side signature is recorded.</div>
        </Panel>
      ) : (
        <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1.35fr) minmax(0, 1fr)" }}>
          <Panel title={`Review queue · ${items.length}`} tight>
            <div className="tablewrap scrollbox" style={{ maxHeight: 640 }}>
              <table className="t">
                <thead><tr><th>order</th><th>terr.</th><th>recommendation</th><th>reason</th><th className="r">support</th><th>evidence</th><th>decision</th></tr></thead>
                <tbody>{items.map(({ r, o }) => {
                  const ov = overlays[r.rec_id];
                  return (
                    <tr key={r.workordernumber} className={`click ${selected?.r.workordernumber === r.workordernumber ? "sel" : ""}`} onClick={() => setSel(r.workordernumber)}>
                      <td><div className="mono">{r.workordernumber}</div><div className="small faint mono">{o.facilityname || `${o.cabinetid} (no NAP)`} · {hhmm(o.createdate)}</div></td>
                      <td>{r.territory}</td>
                      <td><div className="stack" style={{ gap: 3 }}><Pill kind={r.outcome}>{r.outcome}</Pill>{r.outcome === "hold" && r.hold_until && <Countdown until={r.hold_until} />}</div></td>
                      <td className="small">{r.reason_class}{r.floor_applied && <div style={{ color: "var(--warn)" }}>floor applied</div>}</td>
                      <td className="r num">{r.support_score == null ? "—" : r.support_score.toFixed(2)}</td>
                      <td><Chips r={r} /></td>
                      <td>{ov ? <Pill kind="live">{ov.decision}{ov.outcome ? ` → ${ov.outcome}` : ""}</Pill> : r.dispatcher_decision ? <Pill kind={r.dispatcher_decision === "accepted" ? "approved" : "exc"}>{r.dispatcher_decision}</Pill> : <span className="small" style={{ color: "var(--accent)", fontWeight: 600 }}>pending</span>}</td>
                    </tr>
                  );
                })}
                {items.length === 0 && <tr><td colSpan={7} className="empty">No dispatch-eligible orders at {hhmm(t)}.</td></tr>}
                </tbody>
              </table>
            </div>
          </Panel>

          {selected ? (
            <Grounded ids={selected.r.evidence_ids} what={selected.r.rec_id}>
              <section className="panel">
                <div className="panel-h">
                  <div className="grow">
                    <div className="eyebrow">Recommendation {selected.r.rec_id} · review {selected.r.review_seq} · {hhmm(selected.r.recommended_at)}</div>
                    <h2 className="row"><span className="mono">{selected.r.workordernumber}</span><Pill kind={selected.r.outcome}>{selected.r.outcome}</Pill></h2>
                    <div className="small muted">Trigger: {selected.r.trigger}{selected.o.facilityname ? <> · line on <ElementLink id={selected.o.facilityname} /></> : ""}</div>
                  </div>
                </div>
                <div className="panel-b stack">
                  <p className="rationale" style={{ margin: 0 }}>{selected.r.note}</p>
                  <table className="t">
                    <thead><tr><th>question</th><th>tool</th><th>result</th></tr></thead>
                    <tbody>{selected.r.checks.map((c) => (
                      <tr key={c.tool}><td className="small">{c.question}</td><td className="mono small">{c.tool}</td>
                        <td className="small">{c.status === "unavailable" ? <span className="chip na" style={{ height: "auto", whiteSpace: "normal" }}>UNAVAILABLE IN PILOT · unknown, never clear</span> : c.result}</td></tr>
                    ))}</tbody>
                  </table>
                  {selected.r.untrusted_text_flags.map((f) => <div key={f} className="chip flag" style={{ height: "auto", whiteSpace: "normal", padding: "4px 8px" }}>{f}</div>)}
                  <dl className="kv">
                    <dt>Support / floor</dt><dd className="num">{selected.r.support_score == null ? "n/a (dispatch)" : selected.r.support_score.toFixed(2)} / {selected.r.floor.toFixed(2)}{selected.r.floor_applied ? " · floor applied: suppress and hold unreachable" : ""}</dd>
                    <dt>Avoidable cost</dt><dd>{selected.r.estimated_avoidable_cost}</dd>
                    {selected.r.dispatcher_decision && <><dt>Dispatcher</dt><dd>{selected.r.dispatcher_decision} by {selected.r.decided_by} at {hhmm(selected.r.decided_at)}{selected.r.override_reason ? ` · “${selected.r.override_reason}” → ${selected.r.override_outcome}` : ""}</dd></>}
                    {selected.r.outcome_observed && toMs(t) >= d.endMs - 60000 && <><dt>Observed outcome</dt><dd>{selected.r.outcome_observed}</dd></>}
                  </dl>
                  <div className="actions">
                    <EvidenceButton ids={selected.r.evidence_ids} title={selected.r.rec_id} />
                    <TraceButton refId={selected.r.run_id} label="Trace" />
                  </div>
                  {!selected.r.dispatcher_decision && !overlays[selected.r.rec_id] && (
                    <div className="stack" style={{ borderTop: "1px solid var(--rule)", paddingTop: 10 }}>
                      <div className="row">
                        <button className="btn primary" disabled={!role.allowed} title={role.why} onClick={() => decide({ objectId: selected.r.rec_id, kind: "dispatch", decision: "accepted", outcome: selected.r.outcome })}>Accept {selected.r.outcome}</button>
                        <select value={ovr.outcome} onChange={(e) => setOvr({ ...ovr, outcome: e.target.value })} aria-label="Override outcome">
                          {["dispatch", "suppress", "hold"].filter((o) => o !== selected.r.outcome).map((o) => <option key={o}>{o}</option>)}
                        </select>
                        <input type="text" id="override-reason" placeholder="Override reason (required)" value={ovr.reason} onChange={(e) => setOvr({ ...ovr, reason: e.target.value })} style={{ flex: 1, minWidth: 160 }} />
                        <button className="btn" disabled={!role.allowed || !ovr.reason.trim()} onClick={() => { decide({ objectId: selected.r.rec_id, kind: "dispatch", decision: "overridden", reason: ovr.reason, outcome: ovr.outcome }); setOvr({ outcome: "dispatch", reason: "" }); }}>Override</button>
                      </div>
                      <div className="small faint">Every decision, including accepts, lands in the adoption record.</div>
                    </div>
                  )}
                  <div>
                    <div className="eyebrow" style={{ marginBottom: 4 }}>Review history</div>
                    <table className="t"><tbody>
                      {d.recVersions(selected.r.workordernumber, t).map((v) => (
                        <tr key={v.rec_id}><td className="num">{hhmm(v.recommended_at)}</td><td><Pill kind={v.outcome}>{v.outcome}</Pill></td><td className="small">{v.trigger}</td><td className="small">{v.dispatcher_decision ?? ""}</td></tr>
                      ))}
                    </tbody></table>
                  </div>
                </div>
              </section>
            </Grounded>
          ) : <div className="panel empty">Select an order.</div>}
        </div>
      )}
    </div>
  );
}
