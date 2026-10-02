import React, { useMemo } from "react";
import { useApp } from "../store";

const RANK: Record<string, number> = { confirmed: 4, proposed: 3, signal: 2, snow: 1, clean: 0 };
export const STATE_COLOR: Record<string, string> = {
  confirmed: "var(--crit)", proposed: "var(--accent)", signal: "var(--warn)", snow: "var(--ink)", clean: "var(--rule-strong)",
};
const LABEL: Record<string, string> = { confirmed: "Confirmed incident", proposed: "Proposed incident", signal: "Detector signal", snow: "SNOW outage only", clean: "Clean" };

export function Legend() {
  return (
    <div className="legend">
      {Object.keys(LABEL).reverse().map((k) => (
        <span key={k}><i style={{ background: k === "snow" ? "var(--surface)" : STATE_COLOR[k], border: k === "snow" ? "2px solid var(--ink)" : undefined }} />{LABEL[k]}</span>
      ))}
    </div>
  );
}

// Metro Manila clusters sit within a few kilometres of each other; fan their labels out.
const LABEL_POS: Record<string, [string, number, number]> = {
  PAM: ["end", 0, -14], QZN: ["start", 0, -16], PSG: ["start", 0, 10], CAV: ["end", 0, 18], NAG: ["start", 0, 0], LAO: ["start", 0, 0],
};

export function worst(states: string[]): string {
  return states.reduce((a, b) => (RANK[b] > RANK[a] ? b : a), "clean");
}

/** National view: one marker per cluster, coloured by its worst NAP state. */
export function NationalMap({ site, setSite, territory }: { site: string; setSite: (s: string) => void; territory: string }) {
  const { d, t } = useApp();
  const snap = d.snap(t);
  const W = 360, H = 560;
  const lon0 = 116.6, lon1 = 127.0, lat0 = 4.4, lat1 = 21.0;
  const x = (lon: number) => ((lon - lon0) / (lon1 - lon0)) * W;
  const y = (lat: number) => H - ((lat - lat0) / (lat1 - lat0)) * H;
  const outline = useMemo(() => d.b.geo.outline.map((p) => "M" + p.map(([lo, la]) => `${x(lo).toFixed(1)},${y(la).toFixed(1)}`).join("L") + "Z").join(""), [d]);
  const sites = useMemo(() => {
    const m = new Map<string, { site: string; territory: string; name: string; lat: number; lon: number; naps: string[] }>();
    for (const n of d.b.naps) {
      const s = m.get(n.site) || { site: n.site, territory: n.territory, name: n.territory_name, lat: 0, lon: 0, naps: [] };
      s.naps.push(n.NAP); s.lat += n.lat; s.lon += n.lon;
      m.set(n.site, s);
    }
    return [...m.values()].map((s) => ({ ...s, lat: s.lat / s.naps.length, lon: s.lon / s.naps.length })).sort((a, b) => a.territory.localeCompare(b.territory));
  }, [d]);
  return (
    <svg className="map" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="National map of the eight territories">
      <path className="land" d={outline} />
      {sites.map((s) => {
        const st = s.naps.map((n) => snap.nap_states[n] || "clean");
        const w = worst(st);
        const hot = st.filter((v) => v !== "clean").length;
        const r = 5 + Math.sqrt(s.naps.length) * 0.9;
        const dim = territory !== "ALL" && s.territory !== territory;
        const pos = LABEL_POS[s.site] || [s.lon > 124.5 ? "end" : "start", 0, 0];
        const left = pos[0] === "end";
        const dy = pos[2];
        return (
          <g key={s.site} transform={`translate(${x(s.lon)},${y(s.lat)})`} style={{ cursor: "pointer", opacity: dim ? 0.3 : 1 }} onClick={() => setSite(s.site)}>
            {site === s.site && <circle r={r + 6} fill="none" stroke="var(--ink)" strokeWidth={1} strokeDasharray="2 2" />}
            <circle r={r} fill={w === "snow" ? "var(--surface)" : STATE_COLOR[w]} stroke={w === "snow" ? "var(--ink)" : "var(--surface)"} strokeWidth={w === "snow" ? 2.5 : 1.5} />
            <text x={left ? -(r + 5) : r + 5} y={dy - 1} textAnchor={left ? "end" : "start"} style={{ fontSize: 11, fontWeight: 600, fill: "var(--ink)" }}>{s.territory} · {s.site}</text>
            <text x={left ? -(r + 5) : r + 5} y={dy + 11} textAnchor={left ? "end" : "start"} style={{ fontSize: 10 }}>{s.name}{hot ? ` · ${hot} flagged` : ""}</text>
          </g>
        );
      })}
    </svg>
  );
}

/** Cluster view: schematic OLT → LCP → NAP, one dot per NAP. */
export function ClusterMap({ site, barangay, onPick }: { site: string; barangay: string; onPick: (nap: string) => void }) {
  const { d, t } = useApp();
  const snap = d.snap(t);
  const olts = d.oltsBySite.get(site) || [];
  const alarms = new Set(snap.alarm_elements);
  return (
    <div className="stack" style={{ gap: 14 }}>
      {olts.map((olt) => {
        const naps = d.napsByOlt.get(olt) || [];
        const lcps = [...new Set(naps.map((n) => d.naps.get(n)!.LCP))].sort();
        const oState = worst(naps.map((n) => snap.nap_states[n] || "clean"));
        return (
          <div key={olt}>
            <div className="row" style={{ marginBottom: 6 }}>
              <button className="evid mono" onClick={() => onPick(olt)} style={{ fontWeight: 650, color: "var(--ink)" }}>{olt}</button>
              <span className="faint small">{naps.length} NAPs · {naps.reduce((a, n) => a + (d.naps.get(n)!.subs || 0), 0)} lines</span>
              {oState !== "clean" && <span className="pill" style={{ background: "var(--sunk)", color: STATE_COLOR[oState] }}>{LABEL[oState]}</span>}
              {alarms.has(olt) && <span className="chip flag">NMS alarm</span>}
            </div>
            <div style={{ display: "grid", gap: 4 }}>
              {lcps.map((lcp) => {
                const ln = naps.filter((n) => d.naps.get(n)!.LCP === lcp);
                return (
                  <div key={lcp} style={{ display: "grid", gridTemplateColumns: "190px minmax(0,1fr)", alignItems: "center", gap: 8 }}>
                    <button className="evid mono" style={{ fontWeight: 500, color: "var(--ink-2)", justifySelf: "start" }} onClick={() => onPick(lcp)}>{lcp.split("_").slice(-1)[0]} <span className="faint">· {d.naps.get(ln[0])!.barangay}</span></button>
                    <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                      {ln.map((n) => {
                        const s = snap.nap_states[n] || "clean";
                        const dim = barangay !== "ALL" && d.naps.get(n)!.barangay !== barangay;
                        return (
                          <button key={n} onClick={() => onPick(n)} title={`${n} · ${LABEL[s]}`} aria-label={`${n}, ${LABEL[s]}`}
                            style={{
                              width: 30, height: 22, borderRadius: 4, fontSize: 9.5, fontFamily: "var(--mono)", padding: 0,
                              border: s === "snow" ? "2px solid var(--ink)" : "1px solid " + (s === "clean" ? "var(--rule)" : STATE_COLOR[s]),
                              background: s === "clean" || s === "snow" ? "var(--surface)" : STATE_COLOR[s],
                              color: s === "clean" || s === "snow" ? "var(--ink-2)" : "#fff", opacity: dim ? 0.3 : 1,
                            }}>{n.slice(-3)}</button>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
