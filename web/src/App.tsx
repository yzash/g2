import React, { useEffect, useState } from "react";
import { Data, hhmm, toMs } from "./data";
import type { Bundle } from "./types";
import { AppProvider, useApp, type Screen } from "./store";
import { DecisionPrompt, FeedStrip, TopBar } from "./components/TopBar";
import { EvidenceDrawer, TraceDrawer } from "./components/Drawer";
import { Chat } from "./components/Chat";
import { ControlTower } from "./screens/ControlTower";
import { ElementView } from "./screens/ElementView";
import { DispatchReview } from "./screens/DispatchReview";
import { WorkQueue } from "./screens/WorkQueue";
import { Communications } from "./screens/Communications";
import { Adoption } from "./screens/Adoption";

export default function App() {
  const [d, setD] = useState<Data | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    fetch("bundle.json")
      .then((r) => { if (!r.ok) throw new Error(`bundle.json returned ${r.status}`); return r.json(); })
      .then((b: Bundle) => setD(new Data(b)))
      .catch((e) => setErr(String(e)));
  }, []);
  if (err) return <div className="shell" style={{ paddingTop: 40 }}><h1>The replay bundle did not load</h1><p className="muted">{err}. Run <code>python -m sdal all</code> in backend/ to write web/public/bundle.json, then reload.</p></div>;
  if (!d) return <div className="shell" style={{ paddingTop: 40 }}><div className="eyebrow">SDAL Control Tower</div><h1>Loading the synthetic morning…</h1></div>;
  return <AppProvider d={d}><Shell /></AppProvider>;
}

function Shell() {
  const { screen, go, d, t, toast } = useApp();
  const snap = d.snap(t);
  const recs = d.recs(t);
  const pendingRecs = snap.counts.pending_reviews;
  const drafts = snap.counts.drafts;
  const tabs: { id: Screen; label: string; count?: number; hot?: boolean }[] = [
    { id: "tower", label: "Control Tower", count: snap.counts.proposed || undefined, hot: snap.counts.proposed > 0 },
    { id: "element", label: "Element view" },
    { id: "dispatch", label: "Dispatch review", count: pendingRecs || undefined, hot: pendingRecs > 0 },
    { id: "queue", label: "Work queue", count: d.queue(t)?.rows.length },
    { id: "comms", label: "Communications", count: drafts || undefined, hot: drafts > 0 },
    { id: "adoption", label: "Adoption record" },
  ];
  void recs;
  return (
    <>
      <TopBar />
      <main className="shell">
        <FeedStrip />
        <nav className="nav" aria-label="Screens">
          {tabs.map((x) => (
            <button key={x.id} className={screen === x.id ? "on" : ""} onClick={() => go(x.id)}>
              {x.label}{x.count != null && <span className={`count ${x.hot ? "hot" : ""}`}>{x.count}</span>}
            </button>
          ))}
          <span className="spacer" />
          <Scenarios />
        </nav>
        {screen === "tower" && <ControlTower />}
        {screen === "element" && <ElementView />}
        {screen === "dispatch" && <DispatchReview />}
        {screen === "queue" && <WorkQueue />}
        {screen === "comms" && <Communications />}
        {screen === "adoption" && <Adoption />}
        <footer className="small faint" style={{ marginTop: 32, borderTop: "1px solid var(--rule)", paddingTop: 12 }}>
          {d.b.meta.disclaimer} Seed {d.b.meta.seed}. Every number on screen is generated; every column name is Globe's. DevX Labs for Globe Telecom · SDAL MVP demo for Gate 1.
        </footer>
      </main>
      <DecisionPrompt />
      <Chat />
      <EvidenceDrawer />
      <TraceDrawer />
      {toast && <div className="toast" role="status">{toast}</div>}
    </>
  );
}

function Scenarios() {
  const { d, setNow, setPlaying, go, t } = useApp();
  const [open, setOpen] = useState(false);
  const sc: any[] = d.b.meta.scenarios;
  return (
    <div style={{ position: "relative" }}>
      <button className="btn sm" onClick={() => setOpen(!open)} aria-expanded={open}>Six scenarios</button>
      {open && (
        <div className="panel" style={{ position: "absolute", right: 0, top: 34, width: 440, zIndex: 35, boxShadow: "0 10px 30px rgba(18,21,31,.15)" }}>
          {sc.map((s) => (
            <button key={s.n} onClick={() => { setPlaying(false); setNow(toMs(s.jump)); go(s.screen, s.element ?? undefined); setOpen(false); }}
              style={{ display: "grid", gridTemplateColumns: "26px minmax(0,1fr)", gap: 8, textAlign: "left", width: "100%", border: 0, borderBottom: "1px solid var(--rule)", background: s.jump <= t ? "var(--surface)" : "var(--surface)", padding: "9px 12px" }}>
              <b className="num">{s.n}</b>
              <span><b>{s.clock} · {s.title}</b><div className="small muted">{s.takeaway}</div><div className="small faint">Jump to {hhmm(s.jump)}</div></span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
