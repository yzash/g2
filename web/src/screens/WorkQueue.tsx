import React, { useMemo, useState } from "react";
import { useApp, type Weights } from "../store";
import { hhmm, toMs } from "../data";
import { ElementLink, EvidenceButton, Panel, Pill, TraceButton, useRole } from "../components/common";
import { explain, inputText, rerank } from "../lib";

const TERM_COLOR: Record<string, string> = { time: "var(--ink)", lines: "var(--accent)", severity: "#7d8cf0", vip: "var(--warn)", "no crew": "var(--crit)" };

export function WorkQueue() {
  const { d, t, now, weights, setWeights, go, overlays } = useApp();
  const role = useRole("weights");
  const cfg = d.b.meta.config;
  const locked: Weights = cfg.queue_weights;
  const q = d.queue(t);
  const [a, setA] = useState<string>("");
  const [b, setB] = useState<string>("");
  const sandbox = JSON.stringify(weights) !== JSON.stringify(locked);
  const ranked = useMemo(() => (q ? rerank(q.rows, weights, cfg, t) : []), [q, weights, t]);
  const lockedRank = useMemo(() => (q ? rerank(q.rows, locked, cfg, t) : []), [q, t]);
  const prevRank = new Map(lockedRank.map((r) => [r.row.item_id, r.rank]));
  const maxScore = Math.max(0.01, ...ranked.map((r) => r.score));
  const ia = ranked.find((r) => r.row.item_id === (a || ranked[0]?.row.item_id));
  const ib = ranked.find((r) => r.row.item_id === (b || ranked.find((x) => x.row.item_type === "incident" && x.row.item_id !== ia?.row.item_id)?.row.item_id || ranked[1]?.row.item_id));

  const setW = (k: keyof Weights, v: number) => setWeights({ ...weights, [k]: Math.round(v * 100) / 100 });

  return (
    <div className="stack" style={{ gap: 16 }}>
      <div>
        <div className="eyebrow">Work queue · UC3 · re-ranked {q ? hhmm(q.t) : "—"} ({q?.reason})</div>
        <h1>Ranked by arithmetic the operations lead can inspect</h1>
        <div className="muted small mono" style={{ marginTop: 4 }}>
          S = w_t·min(t/6h, 1.5) + w_l·log10(1+lines) + w_s·sev + w_v·vip + w_c·(1−crew)
        </div>
        <div className="small faint">No language model ranks anything. Re-ranks on incident create, confirm and close, on crew change, and every 15 minutes. Clock: earliest createdate among the item's open orders (a Gate 0 item).</div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(0, 330px)" }}>
        <Panel title={`Queue · ${ranked.length} items`} right={sandbox ? <Pill kind="exc">sandbox weights: not persisted</Pill> : <Pill kind="ok">locked policy weights</Pill>} tight>
          <div className="tablewrap scrollbox" style={{ maxHeight: 620 }}>
            <table className="t">
              <thead><tr><th className="r">#</th><th>item</th><th>score, by term</th><th className="r">score</th><th>inputs</th><th>breach</th><th></th></tr></thead>
              <tbody>{ranked.map((r) => {
                const moved = sandbox ? (prevRank.get(r.row.item_id) || 0) - r.rank : 0;
                const isInc = r.row.item_type === "incident";
                const inc = isInc ? d.incidents(t).get(r.row.item_id) : null;
                return (
                  <tr key={r.row.item_id} className={isInc ? "click" : ""} onClick={() => inc && go("element", inc.element_id)}>
                    <td className="r num"><b>{r.rank}</b>{moved !== 0 && <div className="small" style={{ color: moved > 0 ? "var(--ok)" : "var(--crit)" }}>{moved > 0 ? "▲" : "▼"}{Math.abs(moved)}</div>}</td>
                    <td style={{ minWidth: 220 }}>
                      <div className="row" style={{ gap: 6 }}><b className="mono">{r.row.item_id}</b>{isInc ? <Pill kind={inc?.state === "Proposed" ? "proposed" : "confirmed"}>{inc?.state}</Pill> : <span className="small faint">single line</span>}</div>
                      <div className="small muted">{r.row.label.split(" · ").slice(1).join(" · ")}</div>
                      {r.exception && <div className="small" style={{ color: "var(--warn)" }}>⚑ {r.exception}</div>}
                    </td>
                    <td style={{ width: 200 }}>
                      <div style={{ display: "flex", height: 10, background: "var(--sunk)", borderRadius: 3, overflow: "hidden", width: `${(r.score / maxScore) * 100}%`, minWidth: 4 }}>
                        {Object.entries(r.terms).map(([k, v]) => v > 0 && <span key={k} title={`${k}: ${v.toFixed(3)}`} style={{ width: `${(v / r.score) * 100}%`, background: TERM_COLOR[k] }} />)}
                      </div>
                    </td>
                    <td className="r num"><b>{r.score.toFixed(3)}</b></td>
                    <td className="small muted">{inputText(r.row, r.tElapsed)}</td>
                    <td className="num small">{r.row.breach_eta ? hhmm(r.row.breach_eta) : <span className="faint">clock not running</span>}</td>
                    <td><EvidenceButton ids={r.row.evidence_ids} title={r.row.item_id} label="Rows" /></td>
                  </tr>
                );
              })}</tbody>
            </table>
          </div>
          <div className="legend" style={{ padding: "8px 12px", borderTop: "1px solid var(--rule)" }}>
            {Object.entries(TERM_COLOR).map(([k, c]) => <span key={k}><i style={{ background: c, borderRadius: 2 }} />{k}</span>)}
          </div>
        </Panel>

        <div className="stack" style={{ gap: 16 }}>
          <Panel title="Why is one item above another?" eyebrow="ranking_explain">
            <div className="stack">
              <div className="row">
                <select value={ia?.row.item_id || ""} onChange={(e) => setA(e.target.value)} aria-label="First item">{ranked.map((r) => <option key={r.row.item_id}>{r.row.item_id}</option>)}</select>
                <span className="faint">vs</span>
                <select value={ib?.row.item_id || ""} onChange={(e) => setB(e.target.value)} aria-label="Second item">{ranked.map((r) => <option key={r.row.item_id}>{r.row.item_id}</option>)}</select>
              </div>
              {ia && ib && (
                <>
                  <div className="small"><b className="mono">{(ia.rank < ib.rank ? ia : ib).row.item_id}</b> ranks {Math.min(ia.rank, ib.rank)}, <b className="mono">{(ia.rank < ib.rank ? ib : ia).row.item_id}</b> ranks {Math.max(ia.rank, ib.rank)}; scores {ia.score.toFixed(3)} vs {ib.score.toFixed(3)}.</div>
                  <table className="t">
                    <thead><tr><th>term</th><th className="r">{ia.row.item_id}</th><th className="r">{ib.row.item_id}</th><th className="r">Δ</th></tr></thead>
                    <tbody>{explain(ia, ib).map((x) => <tr key={x.term}><td>{x.term}</td><td className="r">{x.a.toFixed(3)}</td><td className="r">{x.b.toFixed(3)}</td><td className="r" style={{ color: x.diff > 0 ? "var(--ok)" : x.diff < 0 ? "var(--crit)" : undefined }}>{x.diff > 0 ? "+" : ""}{x.diff.toFixed(3)}</td></tr>)}</tbody>
                  </table>
                  <div className="small muted">{ia.row.item_id}: {inputText(ia.row, ia.tElapsed)}.<br />{ib.row.item_id}: {inputText(ib.row, ib.tElapsed)}.</div>
                  <div className="small faint">Cites queue_rank rows from the re-rank at {q ? hhmm(q.t) : "—"}. {q && <TraceButton refId={q.run_id} label="Trace" />}</div>
                </>
              )}
            </div>
          </Panel>

          <Panel title="Sandbox weights" eyebrow="Operations lead · change control in production" right={<button className="btn sm" onClick={() => setWeights({ ...locked })} disabled={!sandbox}>Reset to locked</button>}>
            <div className="stack">
              {(["w_t", "w_l", "w_s", "w_v", "w_c"] as (keyof Weights)[]).map((k) => (
                <label key={k} className="small" style={{ display: "grid", gridTemplateColumns: "92px minmax(0,1fr) 40px", gap: 8, alignItems: "center" }}>
                  <span className="mono">{k} <span className="faint">{{ w_t: "time", w_l: "lines", w_s: "severity", w_v: "VIP", w_c: "no crew" }[k]}</span></span>
                  <input type="range" min={0} max={0.6} step={0.01} value={weights[k]} disabled={!role.allowed} onChange={(e) => setW(k, +e.target.value)} />
                  <span className="num r">{weights[k].toFixed(2)}</span>
                </label>
              ))}
              <div className="row">
                <button className="btn sm" disabled={!role.allowed} onClick={() => setWeights({ ...cfg.prd_v01_weights })}>PRD v0.1 defaults</button>
                <button className="btn sm" disabled={!role.allowed} onClick={() => setWeights({ ...weights, w_v: cfg.vip_weight_if_enabled })}>VIP rule on ({cfg.vip_weight_if_enabled})</button>
              </div>
              <div className="small faint">Production weights are locked and change only through change control. The sandbox is not persisted. With the PRD v0.1 defaults the older OLT incident outranks SDAL-0412 and the breach exception fires instead; this is a Gate 0 decision.</div>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
