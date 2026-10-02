import React from "react";
import { useApp } from "../store";
import { hhmm, toMs, MIN } from "../data";

export function Pill({ kind, children }: { kind: string; children: React.ReactNode }) {
  return <span className={`pill ${kind.toLowerCase()}`}>{children}</span>;
}

export function StatePill({ state }: { state: string }) {
  return <Pill kind={state}>{state}</Pill>;
}

/** Grounding contract in the UI: a card without evidence rows renders as an abstention, never as an answer. */
export function Grounded({ ids, children, what }: { ids: string[] | undefined; children: React.ReactNode; what: string }) {
  if (!ids || ids.length === 0) return <div className="empty">Abstained: {what} has no evidence rows, so it cannot be shown.</div>;
  return <>{children}</>;
}

export function EvidenceButton({ ids, title, note, label }: { ids: string[]; title: string; note?: string; label?: string }) {
  const { openEvidence } = useApp();
  return (
    <button className="evid" onClick={(e) => { e.stopPropagation(); openEvidence(title, ids, note); }} title="Open the evidence rows">
      <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M2 1.5h5l3 3v6H2z" fill="none" stroke="currentColor" strokeWidth="1.2" /><path d="M4 6.5h4M4 8.5h4" stroke="currentColor" strokeWidth="1.2" /></svg>
      {label ?? `Evidence (${ids.length})`}
    </button>
  );
}

export function TraceButton({ refId, label = "Trace" }: { refId: string; label?: string }) {
  const { openTrace } = useApp();
  return <button className="evid" onClick={(e) => { e.stopPropagation(); openTrace(refId); }}>{label}</button>;
}

export function Countdown({ until }: { until: string }) {
  const { now } = useApp();
  const left = toMs(until) - now;
  if (left <= 0) return <span className="pill exc">recheck due {hhmm(until)}</span>;
  const h = Math.floor(left / (60 * MIN));
  const m = Math.floor((left % (60 * MIN)) / MIN);
  return <span className="pill hold num">recheck in {h}h {String(m).padStart(2, "0")}m · {hhmm(until)}</span>;
}

export function Panel({ title, right, children, tight, eyebrow }: { title: React.ReactNode; right?: React.ReactNode; children: React.ReactNode; tight?: boolean; eyebrow?: string }) {
  return (
    <section className="panel">
      <div className="panel-h">
        <div className="grow">
          {eyebrow && <div className="eyebrow">{eyebrow}</div>}
          <h3>{title}</h3>
        </div>
        {right}
      </div>
      <div className={`panel-b ${tight ? "tight" : ""}`}>{children}</div>
    </section>
  );
}

export function ElementLink({ id, children }: { id: string; children?: React.ReactNode }) {
  const { go } = useApp();
  return <button className="evid mono" style={{ fontWeight: 500 }} onClick={(e) => { e.stopPropagation(); go("element", id); }}>{children ?? id}</button>;
}

export function Bar({ label, value, max = 1, weight, fmt }: { label: string; value: number; max?: number; weight?: number; fmt?: (v: number) => string }) {
  const pct = Math.max(0, Math.min(1, value / max)) * 100;
  return (
    <div className="bar">
      <span className="muted">{label}</span>
      <span className="track"><span className="fill" style={{ width: `${pct}%` }} /></span>
      <span className="val">{fmt ? fmt(value) : value.toFixed(2)}{weight != null ? ` × ${weight}` : ""}</span>
    </div>
  );
}

export function useRole(what: string) {
  const { can, role } = useApp();
  return { allowed: can(what), why: can(what) ? "" : `Your role (${role}) cannot take this decision` };
}
