import React from "react";
import { ROLES, useApp, type Screen } from "../store";
import { hhmm, toMs, toStr } from "../data";

export function TopBar() {
  const { d, now, setNow, playing, setPlaying, speed, setSpeed, mode, setMode, role, setRole, go, askChat, setChatOpen } = useApp();
  const meta = d.b.meta;
  const t = toStr(now);
  const span = d.endMs - d.startMs;
  const pct = ((now - d.startMs) / span) * 100;
  const chapters: any[] = meta.chapters;
  const cur = [...chapters].reverse().find((c) => c.t <= t);

  const jump = (c: any) => {
    setPlaying(false);
    setNow(toMs(c.t));
    go(c.screen as Screen, c.target ?? undefined);
    if (c.chat) askChat(c.chat);
  };

  return (
    <header className="topbar">
      <div className="topbar-inner">
        <div className="brand">
          <b>SDAL Control Tower</b>
          <span className="tag">CFS · Broadband</span>
          <span className="synthetic" title={meta.disclaimer}>Synthetic rows on Globe schemas</span>
        </div>
        <div className="clock">
          <div>
            <div className="time" aria-live="off">{t.slice(11, 19)}</div>
            <div className="day">{meta.day_label}</div>
          </div>
          <button className="btn primary" onClick={() => setPlaying(!playing)} style={{ minWidth: 74 }} aria-label={playing ? "Pause replay" : "Play replay"}>
            {playing ? "Pause" : now >= d.endMs ? "Ended" : "Play"}
          </button>
          <div className="seg" role="group" aria-label="Replay speed">
            {[1, 10, 30, 60].map((s) => <button key={s} className={speed === s ? "on" : ""} onClick={() => setSpeed(s)}>{s}x</button>)}
          </div>
          <div className="seg" role="group" aria-label="Decision mode">
            <button className={mode === "guided" ? "on" : ""} onClick={() => setMode("guided")} title="The clock stops at each human decision so the presenter takes it live">Guided</button>
            <button className={mode === "auto" ? "on" : ""} onClick={() => setMode("auto")} title="Scripted human decisions apply on their own; plays end to end without intervention">Autopilot</button>
          </div>
          <select aria-label="Role" value={role} onChange={(e) => setRole(e.target.value as any)}>
            {ROLES.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
          </select>
          <button className="btn" onClick={() => setChatOpen(true)}>Ask</button>
        </div>
      </div>
      <div className="scrub">
        <span className="small faint num">{hhmm(meta.replay_start)}</span>
        <div className="scrub-track">
          <div className="scrub-bar" />
          <div className="scrub-fill" style={{ width: `${pct}%` }} />
          {chapters.map((c) => {
            const p = ((toMs(c.t) - d.startMs) / span) * 100;
            return <div key={c.t} className={`scrub-mark ${c.t <= t ? "hit" : ""}`} style={{ left: `${p}%` }} title={c.label} />;
          })}
          <div className="scrub-head" style={{ left: `${pct}%` }} />
          <input type="range" min={d.startMs} max={d.endMs} step={60000} value={now} aria-label="Replay clock"
            onChange={(e) => { setPlaying(false); setNow(+e.target.value); }} />
        </div>
        <span className="small faint num">{hhmm(meta.replay_end)}</span>
      </div>
      <div className="scrub" style={{ paddingBottom: 10 }}>
        <div className="chapters">
          {chapters.map((c) => (
            <button key={c.t} className={`chapter ${cur === c ? "current" : c.t <= t ? "past" : ""}`} onClick={() => jump(c)} title={c.text}>{c.label}</button>
          ))}
        </div>
      </div>
    </header>
  );
}

export function FeedStrip() {
  const { d, t } = useApp();
  const s = d.snap(t);
  const feeds = Object.values(s.feeds);
  const bad = feeds.filter((f) => f.status !== "on time");
  return (
    <>
      <div className="feeds" aria-label="Feed health">
        {feeds.map((f) => (
          <div key={f.source} className={`feed ${f.status === "on time" ? "" : f.status}`}>
            <div className="name"><span className={`dot ${f.status === "on time" ? "ok" : f.status}`} />{f.label}</div>
            <div className="meta">
              {f.status === "on time" ? "On time" : f.status === "late" ? "LATE" : "STALLED"} · last {hhmm(f.last_arrival)} · every {f.cadence_min} min
              {f.missed > 0 && ` · ${f.missed} missed`}
            </div>
          </div>
        ))}
      </div>
      {bad.map((f) => (
        <div key={f.source} className={`alert ${f.status === "late" ? "warn" : ""}`} role="alert">
          <span className={`dot ${f.status}`} />
          <span>{f.label} {f.status}: no arrival since {hhmm(f.last_arrival)} ({f.missed} expected arrival{f.missed > 1 ? "s" : ""} missed).</span>
          <span className="muted">
            {s.paused.filter((p) => p.source === f.source).map((p) => p.detector).join(", ") || "Dependent detectors"} paused; recommendations that rely on this source fall back to dispatch. This is an alert, not a quiet night.
          </span>
        </div>
      ))}
    </>
  );
}

export function DecisionPrompt() {
  const { pending, pendingCount, acknowledge, go, d } = useApp();
  if (!pending) return null;
  const screen: Screen = pending.object_type === "dispatch" ? "dispatch" : pending.object_type === "package" ? "comms" : "element";
  const inc = pending.object_type === "incident" || pending.object_type === "closure" ? d.incidents("2099").get(pending.object_id) : null;
  return (
    <div className="decision" role="status">
      <div style={{ minWidth: 0 }}>
        <div className="who">{hhmm(pending.at)} · decision for {pending.role}</div>
        <div><b>{pending.actor}</b>: {pending.decision} {pending.object_id} <span style={{ opacity: 0.7 }}>({pending.recommendation})</span></div>
        {pending.reason && <div className="small" style={{ opacity: 0.75 }}>“{pending.reason}”</div>}
        {pendingCount > 1 && <div className="small" style={{ opacity: 0.75 }}>+ {pendingCount - 1} more decision{pendingCount > 2 ? "s" : ""} at the same minute; see Dispatch review</div>}
      </div>
      <button className="btn" onClick={() => go(screen, inc ? inc.element_id : undefined)}>Open</button>
      <button className="btn primary" onClick={acknowledge}>Take scripted decision{pendingCount > 1 ? "s" : ""}</button>
    </div>
  );
}
