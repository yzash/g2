import React from "react";
import type { Run } from "../types";
import { useApp } from "../store";
import { hhmm } from "../data";

const HIDE = new Set(["_arrived_at", "_cleared_arrived_at"]);

function fmtV(v: any) {
  if (v === null || v === undefined || v === "") return <span className="faint">null</span>;
  if (typeof v === "boolean") return String(v);
  return String(v);
}

export function EvidenceDrawer() {
  const { drawer, closeDrawer, d, t, openTrace } = useApp();
  if (!drawer) return null;
  const resolved = drawer.ids.map((id) => ({ id, r: d.resolve(id, t) }));
  const calls = new Set(resolved.map((x) => x.r?.fetched_by).filter(Boolean));
  return (
    <>
      <div className="drawer-bg" onClick={closeDrawer} />
      <aside className="drawer" role="dialog" aria-label="Evidence rows">
        <div className="drawer-h">
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="eyebrow">Evidence rows</div>
            <h2>{drawer.title}</h2>
            <div className="small muted">
              {resolved.length} rows the tools returned{calls.size ? `, fetched by ${calls.size} tool call${calls.size > 1 ? "s" : ""}` : ""}. Rows are shown exactly as the curated layer holds them; free text is data, never instructions.
            </div>
            {drawer.note && <div className="small" style={{ marginTop: 6 }}>{drawer.note}</div>}
          </div>
          <button className="btn" onClick={closeDrawer} autoFocus>Close</button>
        </div>
        <div className="drawer-b">
          {resolved.map(({ id, r }) => (
            <div className="evrow" key={id}>
              <div className="evrow-h">
                <code>{id}</code>
                {r ? <span className="faint small">{r.source}</span> : <span className="unres small">not resolvable at {hhmm(t)}</span>}
                {r?.fetched_by && <button className="chip" onClick={() => { closeDrawer(); openTrace(r.fetched_by!); }}>{r.fetched_by}</button>}
              </div>
              {r && (
                <table>
                  <tbody>
                    {Object.entries(r.row).filter(([k]) => !HIDE.has(k)).map(([k, v]) => (
                      <tr key={k}><td>{k}</td><td style={{ overflowWrap: "anywhere" }}>{fmtV(v)}</td></tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ))}
        </div>
      </aside>
    </>
  );
}

export function TraceDrawer() {
  const { traceRef, openTrace, d, t, openEvidence } = useApp();
  if (!traceRef) return null;
  let runs: Run[] = traceRef.startsWith("CALL-")
    ? d.b.trace.filter((r) => r.tool_calls.some((c) => c.call_id === traceRef))
    : traceRef.startsWith("RUN-") ? d.b.trace.filter((r) => r.run_id === traceRef) : d.runsFor(traceRef);
  runs = runs.filter((r) => r.at <= t);
  return (
    <>
      <div className="drawer-bg" onClick={() => openTrace(null)} />
      <aside className="drawer" role="dialog" aria-label="Agent trace" style={{ width: "min(760px, 100vw)" }}>
        <div className="drawer-h">
          <div style={{ flex: 1 }}>
            <div className="eyebrow">Append-only trace</div>
            <h2>{traceRef}</h2>
            <div className="small muted">Every agent run: trigger, tool calls in order with parameters, the evidence each call returned, notes and outputs. Agents act only through the registered tools.</div>
          </div>
          <button className="btn" onClick={() => openTrace(null)} autoFocus>Close</button>
        </div>
        <div className="drawer-b">
          {runs.length === 0 && <div className="empty">No runs for this reference up to {hhmm(t)}.</div>}
          {runs.map((r) => (
            <div className="evrow" key={r.run_id}>
              <div className="evrow-h">
                <b className="num">{hhmm(r.at)}</b>
                <span className="pill dispatch">{r.agent}</span>
                <code>{r.run_id}</code>
                <span className="small muted" style={{ flex: 1 }}>{r.trigger}</span>
              </div>
              <ol style={{ margin: 0, padding: "6px 10px 6px 30px", display: "grid", gap: 6 }}>
                {r.tool_calls.map((c) => (
                  <li key={c.call_id} className="small" style={{ background: c.call_id === traceRef ? "var(--accent-soft)" : undefined }}>
                    <code style={{ fontWeight: 600 }}>{c.tool}</code> <span className="faint mono">({Object.entries(c.params).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v).slice(0, 60) : v}`).join(", ")})</span>
                    <div className="muted">→ {c.summary}{c.n_evidence ? " · " : ""}{c.n_evidence > 0 && <button className="evid" onClick={() => openEvidence(`${c.tool} · ${c.call_id}`, c.evidence_ids)}>{c.n_evidence} rows</button>}</div>
                    {c.flags.map((f) => <div key={f} className="chip flag" style={{ height: "auto", whiteSpace: "normal" }}>{f}</div>)}
                  </li>
                ))}
              </ol>
              {(r.notes.length > 0 || r.outputs.length > 0) && (
                <div style={{ padding: "4px 10px 8px", display: "grid", gap: 4 }} className="small">
                  {r.notes.map((n, i) => <div key={i} className={n.startsWith("UNTRUSTED") || n.startsWith("REFUSED") ? "chip flag" : "muted"} style={{ height: "auto", whiteSpace: "normal" }}>{n}</div>)}
                  {r.outputs.map((o, i) => <div key={i}>Output: <code>{o.kind}</code> {o.ref}</div>)}
                </div>
              )}
            </div>
          ))}
        </div>
      </aside>
    </>
  );
}
