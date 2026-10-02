import React from "react";
import { useApp } from "../store";
import { MIN, toMs, toStr } from "../data";

/** Optical Rx per gateway (dBm, converted from WMS raw units) over the 24 hours before the WMS horizon. */
export function OpticalChart({ macs, highlight }: { macs: string[]; highlight?: Set<string> }) {
  const { d, t } = useApp();
  const horizon = d.snap(t).wms_horizon;
  const W = 760, H = 230, L = 38, R = 12, T = 12, B = 24;
  if (!horizon) return <div className="empty">No WMS batch has landed yet.</div>;
  const end = toMs(horizon);
  const start = end - 24 * 60 * MIN;
  const yMin = -32, yMax = -15;
  const x = (ms: number) => L + ((ms - start) / (end - start)) * (W - L - R);
  const y = (v: number) => T + ((yMax - v) / (yMax - yMin)) * (H - T - B);
  const ticks = [];
  for (let ms = Math.ceil(start / (4 * 60 * MIN)) * 4 * 60 * MIN; ms <= end; ms += 4 * 60 * MIN) ticks.push(ms);
  const shown = macs.slice(0, 40);
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Optical receive power per gateway, last 24 hours">
      <g className="grid">
        {[-30, -27, -24, -21, -18, -15].map((v) => <line key={v} x1={L} x2={W - R} y1={y(v)} y2={y(v)} />)}
      </g>
      {[-30, -27, -24, -21, -18, -15].map((v) => <text key={v} x={L - 6} y={y(v) + 3} textAnchor="end">{v}</text>)}
      {ticks.map((ms) => <text key={ms} x={x(ms)} y={H - 6} textAnchor="middle">{toStr(ms).slice(11, 16)}</text>)}
      <line x1={L} x2={W - R} y1={y(-27)} y2={y(-27)} stroke="var(--crit)" strokeDasharray="4 3" strokeWidth={1} />
      <text x={W - R} y={y(-27) - 4} textAnchor="end" style={{ fill: "var(--crit)" }}>-27 dBm</text>
      {shown.map((mac) => {
        const s = d.series(mac, horizon).filter((p) => p.t >= start);
        const hot = highlight?.has(mac);
        let path = "", pen = false;
        for (const p of s) {
          if (p.v == null) { pen = false; continue; }
          path += `${pen ? "L" : "M"}${x(p.t).toFixed(1)},${y(Math.max(yMin, Math.min(yMax, p.v))).toFixed(1)}`;
          pen = true;
        }
        return <path key={mac} d={path} fill="none" stroke={hot ? "var(--crit)" : "var(--ink-3)"} strokeOpacity={hot ? 0.85 : 0.45} strokeWidth={hot ? 1.3 : 1} />;
      })}
      <line x1={x(end)} x2={x(end)} y1={T} y2={H - B} stroke="var(--ink)" strokeWidth={1} />
      <text x={x(end) - 4} y={T + 9} textAnchor="end" style={{ fill: "var(--ink)" }}>WMS horizon {horizon.slice(11, 16)}</text>
    </svg>
  );
}

export function Spark({ values, w = 90, h = 22, color = "var(--ink-2)" }: { values: (number | null)[]; w?: number; h?: number; color?: string }) {
  const v = values.filter((x): x is number => x != null);
  if (v.length < 2) return <span className="faint small">no data</span>;
  const lo = Math.min(...v, -28), hi = Math.max(...v, -18);
  let p = "", pen = false;
  values.forEach((val, i) => {
    if (val == null) { pen = false; return; }
    p += `${pen ? "L" : "M"}${((i / (values.length - 1)) * w).toFixed(1)},${(h - ((val - lo) / (hi - lo)) * h).toFixed(1)}`;
    pen = true;
  });
  return <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true"><path d={p} fill="none" stroke={color} strokeWidth={1.2} /></svg>;
}
