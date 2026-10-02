import React, { useState } from "react";
import { useApp } from "../store";
import { hhmm } from "../data";
import { EvidenceButton, Grounded, Panel, Pill, TraceButton, useRole } from "../components/common";

export function Communications() {
  const { d, t, overlays, decide } = useApp();
  const role = useRole("package");
  const pkgs = [...d.packages(t).values()].sort((a, b) => b.built_at.localeCompare(a.built_at));
  const [sel, setSel] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const lastChange = (id: string) => d.history("package", id, t).slice(-1)[0]?.t || "";
  const recent = [...pkgs].sort((a, b) => lastChange(b.package_id).localeCompare(lastChange(a.package_id)))[0];
  const p = pkgs.find((x) => x.package_id === sel) || recent;
  const inc = p ? d.incidents(t).get(p.incident_id) : null;
  const ov = p ? overlays[p.package_id] : undefined;
  const state = ov ? (ov.decision === "approved" ? "Approved" : ov.decision === "withheld" ? "Withheld" : p!.state) : p?.state;
  const text = ov?.text ?? p?.text;

  return (
    <div className="stack" style={{ gap: 16 }}>
      <div>
        <div className="eyebrow">Communications · UC5</div>
        <h1>The silent majority hears first, after a human approves</h1>
        <div className="muted small">Draft, policy-checked packages for confirmed incidents. Identifiers stay pseudonymised; re-identification happens inside Globe at the point of contact. No approval, no send. There is no bypass path.</div>
      </div>
      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 340px) minmax(0, 1fr)" }}>
        <Panel title={`Packages · ${pkgs.length}`} tight>
          {pkgs.length === 0 && <div className="empty">No packages yet at {hhmm(t)}. A package is built when an incident is confirmed.</div>}
          <table className="t"><tbody>
            {pkgs.map((x) => {
              const o = overlays[x.package_id];
              const s = o ? (o.decision === "approved" ? "Approved" : "Withheld") : x.state;
              return (
                <tr key={x.package_id} className={`click ${p?.package_id === x.package_id ? "sel" : ""}`} onClick={() => setSel(x.package_id)}>
                  <td><div className="row" style={{ gap: 6 }}><b className="mono">{x.package_id}</b><Pill kind={s}>{s}</Pill>{o && <Pill kind="live">live</Pill>}</div>
                    <div className="small muted">{x.kind} · {x.incident_id} · {x.recipients_total} recipients · built {hhmm(x.built_at)}</div>
                    {x.decision_note && <div className="small faint">{x.decision_note}</div>}</td>
                </tr>
              );
            })}
          </tbody></table>
        </Panel>

        {p && (
          <Grounded ids={p.evidence_ids} what={p.package_id}>
            <section className="panel">
              <div className="panel-h">
                <div className="grow">
                  <div className="eyebrow">{p.kind} notice · {p.incident_id} {inc ? `· ${inc.element_type} ${inc.element_id}` : ""} · trigger: {p.trigger}</div>
                  <h2 className="row"><span className="mono">{p.package_id}</span><Pill kind={state!}>{state}</Pill>{ov && <Pill kind="live">live decision</Pill>}</h2>
                </div>
                <EvidenceButton ids={p.evidence_ids} title={p.package_id} />
                <TraceButton refId={p.run_id} />
              </div>
              <div className="panel-b stack" style={{ gap: 14 }}>
                <div className="grid cols-3">
                  <div><div className="eyebrow">Recipients</div><div style={{ fontSize: 26, fontWeight: 650 }} className="num">{p.recipients_total}</div><div className="small muted">{p.recipients_vip} VIP/B2B · {p.recipients_mass} mass (synthetic flag)</div></div>
                  <div><div className="eyebrow">Silent (inferred)</div><div style={{ fontSize: 26, fontWeight: 650, color: "var(--accent)" }} className="num">{p.recipients_inferred}</div><div className="small muted">never called; {p.recipients_observed} observed</div></div>
                  <div><div className="eyebrow">Earliest send</div><div style={{ fontSize: 26, fontWeight: 650 }} className="num">{hhmm(p.scheduled_send_at)}</div><div className="small muted">{p.restoration_target ? `restoration target ${hhmm(p.restoration_target)} (from outage management)` : `no published target; next update by ${hhmm(p.next_update_at)}`}</div></div>
                </div>
                <div style={{ display: "flex", height: 10, borderRadius: 99, overflow: "hidden", background: "var(--sunk)" }} aria-label="Observed versus silent recipients">
                  <span style={{ width: `${(p.recipients_observed / p.recipients_total) * 100}%`, background: "var(--ink-3)" }} />
                  <span style={{ width: `${(p.recipients_inferred / p.recipients_total) * 100}%`, background: "var(--accent)" }} />
                </div>

                <div>
                  <div className="eyebrow" style={{ marginBottom: 4 }}>Message (English template; non-English out of scope)</div>
                  {editing === p.package_id ? (
                    <div className="stack">
                      <textarea id="pkg-text" rows={4} value={draft} onChange={(e) => setDraft(e.target.value)} />
                      <div className="row"><button className="btn primary" onClick={() => { decide({ objectId: p.package_id, kind: "package", decision: "edited", text: draft }); setEditing(null); }}>Save edit</button><button className="btn" onClick={() => setEditing(null)}>Cancel</button></div>
                    </div>
                  ) : <blockquote style={{ margin: 0, padding: "10px 12px", background: "var(--sunk)", borderRadius: 6, maxWidth: "72ch" }}>{text}</blockquote>}
                </div>

                <table className="t">
                  <thead><tr><th>contact policy check</th><th>result</th><th>detail</th><th className="r">affected</th></tr></thead>
                  <tbody>{p.policy_results.map((r) => (
                    <tr key={r.check}><td>{r.check}</td><td><Pill kind={r.status === "pass" ? "ok" : r.status === "hold" ? "hold" : r.status === "unavailable" ? "na" : "confirmed"}>{r.status}</Pill></td><td className="small">{r.detail}</td><td className="r num">{r.affected}</td></tr>
                  ))}</tbody>
                </table>
                <div className="small faint">Policy is enforced by the contact_policy_check tool, not by agent judgement.</div>

                <div className="actions">
                  {state === "Draft" && (
                    <>
                      <button className="btn primary" disabled={!role.allowed} title={role.why} onClick={() => decide({ objectId: p.package_id, kind: "package", decision: "approved" })}>Approve draft</button>
                      <button className="btn" disabled={!role.allowed} onClick={() => { setDraft(text || ""); setEditing(p.package_id); }}>Edit text</button>
                      <button className="btn danger" disabled={!role.allowed} onClick={() => decide({ objectId: p.package_id, kind: "package", decision: "withheld", reason: "Withheld by approver" })}>Withhold</button>
                    </>
                  )}
                  {p.approver && <span className="small muted">Approved by {p.approver} at {hhmm(p.decided_at)}{p.decision_note ? ` · “${p.decision_note}”` : ""}</span>}
                </div>

                <div className="grid cols-2e">
                  <div className="panel" style={{ padding: 12, background: "var(--sunk)" }}>
                    <div className="row between"><b>NG1 handoff</b><button className="btn" disabled title="Disabled in the demo">Send via NG1</button></div>
                    <div className="small muted" style={{ margin: "6px 0" }}>The single governed write in the design. Disabled: no consent source in the pilot, so every package is draft-only by rule, and no code path in the demo calls ng1_handoff.</div>
                    <pre className="mono" style={{ margin: 0, whiteSpace: "pre-wrap", fontSize: 11 }}>{JSON.stringify(p.ng1_payload_preview, null, 2)}</pre>
                  </div>
                  <div className="panel" style={{ padding: 12, background: "var(--sunk)" }}>
                    <b>Delivery and replies</b>
                    <div className="small muted" style={{ marginTop: 6 }}>reply_capture_read: placeholder for the m360 delivery and reply signal, pending the m360/ISDP decision. Send state: {p.send_state}</div>
                    <div className="small" style={{ marginTop: 8 }}>Sample recipient tokens: <span className="mono">{p.recipient_tokens_sample.slice(0, 3).join(", ")}…</span></div>
                  </div>
                </div>
              </div>
            </section>
          </Grounded>
        )}
      </div>
    </div>
  );
}
