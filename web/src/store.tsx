import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { Data, MIN, toMs, toStr } from "./data";
import type { Adoption } from "./types";

export type Screen = "tower" | "element" | "dispatch" | "queue" | "comms" | "adoption";
export type Role = "presenter" | "noc" | "dispatcher" | "ops" | "comms" | "hob";

export const ROLES: { id: Role; label: string; can: string[] }[] = [
  { id: "presenter", label: "Presenter (all roles)", can: ["incident", "dispatch", "weights", "package"] },
  { id: "noc", label: "NOC lead", can: ["incident"] },
  { id: "dispatcher", label: "Dispatcher", can: ["dispatch"] },
  { id: "ops", label: "Operations lead", can: ["weights"] },
  { id: "comms", label: "Communications approver", can: ["package"] },
  { id: "hob", label: "Head of Broadband (read)", can: [] },
];

export interface Overlay { objectId: string; kind: string; decision: string; reason?: string; at: string; actor: string; text?: string; outcome?: string }

export interface Weights { w_t: number; w_l: number; w_s: number; w_v: number; w_c: number }

interface Ctx {
  d: Data;
  now: number; t: string; setNow: (ms: number) => void;
  playing: boolean; setPlaying: (p: boolean) => void;
  speed: number; setSpeed: (s: number) => void;
  mode: "auto" | "guided"; setMode: (m: "auto" | "guided") => void;
  screen: Screen; go: (s: Screen, element?: string | null) => void;
  element: string | null;
  role: Role; setRole: (r: Role) => void; can: (what: string) => boolean;
  overlays: Record<string, Overlay>; decide: (o: Omit<Overlay, "at" | "actor">) => void;
  pending: Adoption | null; pendingCount: number; acknowledge: () => void;
  drawer: { title: string; ids: string[]; note?: string } | null; openEvidence: (title: string, ids: string[], note?: string) => void; closeDrawer: () => void;
  traceRef: string | null; openTrace: (ref: string | null) => void;
  chatOpen: boolean; setChatOpen: (b: boolean) => void; chatSeed: string | null; askChat: (q: string) => void;
  weights: Weights; setWeights: (w: Weights) => void;
  toast: string | null; say: (s: string) => void;
}

const C = createContext<Ctx>(null as any);
export const useApp = () => useContext(C);

export function AppProvider({ d, children }: { d: Data; children: React.ReactNode }) {
  const [now, setNowRaw] = useState(d.startMs);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<number>(d.b.meta.config ? 10 : 10);
  const [mode, setMode] = useState<"auto" | "guided">("guided");
  const [screen, setScreen] = useState<Screen>("tower");
  const [element, setElement] = useState<string | null>(null);
  const [role, setRole] = useState<Role>("presenter");
  const [overlays, setOverlays] = useState<Record<string, Overlay>>({});
  const [acked, setAcked] = useState<Set<string>>(new Set());
  const [pending, setPending] = useState<Adoption | null>(null);
  const [drawer, setDrawer] = useState<Ctx["drawer"]>(null);
  const [traceRef, setTraceRef] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatSeed, setChatSeed] = useState<string | null>(null);
  const [weights, setWeights] = useState<Weights>({ ...d.b.meta.config.queue_weights });
  const [toast, setToast] = useState<string | null>(null);

  // Decision moments the presenter takes live in guided mode (not the bulk accepts)
  const moments = useMemo(() => {
    const all = [...(d.byKind.get("adoption")?.values() || [])].map((e) => e[0].obj as Adoption);
    return all.filter((a) => !a.batch && toMs(a.at) >= d.startMs).sort((a, b) => a.at.localeCompare(b.at));
  }, [d]);

  const nowRef = useRef(now);
  nowRef.current = now;
  const setNow = useCallback((ms: number) => {
    const c = Math.max(d.startMs, Math.min(d.endMs, ms));
    setNowRaw(c);
    setPending(null);
  }, [d]);

  useEffect(() => {
    if (!playing) return;
    let last = performance.now();
    const id = window.setInterval(() => {
      const p = performance.now();
      const dt = (p - last) * speed;
      last = p;
      const prev = nowRef.current;
      let next = prev + dt;
      if (mode === "guided") {
        const m = moments.find((a) => !acked.has(a.record_id) && toMs(a.at) > prev && toMs(a.at) <= next);
        if (m) {
          next = toMs(m.at) - 1000;
          setNowRaw(next);
          setPlaying(false);
          setPending(m);
          return;
        }
      }
      if (next >= d.endMs) { next = d.endMs; setPlaying(false); }
      setNowRaw(next);
    }, 200);
    return () => window.clearInterval(id);
  }, [playing, speed, mode, moments, acked, d]);

  const t = useMemo(() => toStr(Math.floor(now / MIN) * MIN), [now]);

  const say = useCallback((s: string) => {
    setToast(s);
    window.setTimeout(() => setToast((cur) => (cur === s ? null : cur)), 3200);
  }, []);

  const acknowledge = useCallback(() => {
    if (!pending) return;
    // decisions taken at the same minute are acknowledged together
    setAcked((a) => { const n = new Set(a); moments.filter((m) => m.at === pending.at).forEach((m) => n.add(m.record_id)); return n; });
    setNowRaw(toMs(pending.at));
    setPending(null);
    setPlaying(true);
  }, [pending, moments]);

  const decide = useCallback((o: Omit<Overlay, "at" | "actor">) => {
    const r = ROLES.find((x) => x.id === role)!;
    setOverlays((cur) => ({ ...cur, [o.objectId]: { ...o, at: toStr(nowRef.current), actor: r.label + " (live)" } }));
    // a live decision on the moment the clock is waiting for releases the clock
    if (pending && (pending.object_id === o.objectId || pending.object_id.includes(o.objectId))) {
      setAcked((a) => new Set(a).add(pending.record_id));
      setPending(null);
    }
    say("Decision recorded in the adoption record");
  }, [role, pending, say]);

  const value: Ctx = {
    d, now, t, setNow, playing, setPlaying, speed, setSpeed, mode, setMode,
    screen, element,
    go: (s, el) => { setScreen(s); if (el !== undefined) setElement(el); window.scrollTo({ top: 0 }); },
    role, setRole, can: (w) => ROLES.find((r) => r.id === role)!.can.includes(w),
    overlays, decide, pending, acknowledge, pendingCount: pending ? moments.filter((m) => m.at === pending.at).length : 0,
    drawer, openEvidence: (title, ids, note) => setDrawer({ title, ids, note }), closeDrawer: () => setDrawer(null),
    traceRef, openTrace: setTraceRef,
    chatOpen, setChatOpen, chatSeed, askChat: (q) => { setChatOpen(true); setChatSeed(q + "​" + Date.now()); },
    weights, setWeights, toast, say,
  };
  return <C.Provider value={value}>{children}</C.Provider>;
}
