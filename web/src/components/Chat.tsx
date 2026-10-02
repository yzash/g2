import React, { useEffect, useRef, useState } from "react";
import { useApp } from "../store";
import { Data, hhmm, toMs } from "../data";
import { EvidenceButton } from "./common";
import { explain, rerank } from "../lib";

interface Answer { text: string; columns?: string[]; rows?: (string | number)[][]; cites: string[]; tools: string[]; abstain?: boolean }

const CANNED = [
  "Which NAPs had three or more repeat orders this week with no SNOW incident?",
  "Why is SDAL-0412 above SDAL-0405?",
  "What breaches in the next two hours?",
  "What should my team in T7 take next?",
];
const MORE = ["What is happening on CAV_118_L004_N07B?", "Which gateways on CAV_118_L004_N07B are below -27 dBm?", "Is any feed late?", "Which recommendations were overridden?", "How many silent customers were notified?"];

function territoryOf(q: string, d: Data): string | null {
  const m = q.match(/\bt([1-8])\b/i);
  if (m) return `T${m[1]}`;
  for (const [code, name, site] of d.b.meta.territories as string[][]) {
    if (q.toLowerCase().includes(name.toLowerCase()) || new RegExp(`\\b${site}\\b`, "i").test(q)) return code;
  }
  if (/cavite|bacoor/i.test(q)) return "T7";
  if (/davao/i.test(q)) return "T5";
  return null;
}

export function answer(q: string, d: Data, t: string, weights: any): Answer {
  const s = q.toLowerCase();
  const cfg = d.b.meta.config;
  const elem = q.match(/\b([A-Z]{3}_\d{3}(?:_L\d{3}(?:_N\d{2}[AB])?)?|OLT_[A-Z]{3}_\d{3})\b/);
  const ids = q.toUpperCase().match(/SDAL-\d{4}|WO\d{6,}/g) || [];
  const terr = territoryOf(q, d);

  // 1. repeat orders without a SNOW incident
  if (/repeat|three or more|3 or more|\b3\+/.test(s) && /order/.test(s)) {
    const days = /today/.test(s) ? 1 : +(s.match(/(\d+)\s*days?/)?.[1] || 7);
    const min = /three|3/.test(s) ? 3 : +(s.match(/(\d+) or more/)?.[1] || 3);
    const since = toMs(t) - days * 86_400_000;
    const snowNaps = new Set(d.snow(t).filter((r) => toMs(r.ticket_created_datetime) >= since).map((r) => r.affected_nap));
    const by = new Map<string, any[]>();
    for (const o of d.orders(t)) {
      if (o.skillset !== "Repair" || !o.facilityname || toMs(o.createdate) < since || snowNaps.has(o.facilityname)) continue;
      if (terr && d.naps.get(o.facilityname)?.territory !== terr) continue;
      by.set(o.facilityname, [...(by.get(o.facilityname) || []), o]);
    }
    const hits = [...by.entries()].filter(([, v]) => v.length >= min).sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
    return {
      text: hits.length
        ? `${hits.length} NAP${hits.length > 1 ? "s" : ""} had ${min} or more repair orders in the last ${days} days with no SNOW incident on the NAP${terr ? ` in ${terr}` : ""}. NAPs that did get a SNOW incident (for example the flapping NAP and the NAPs under the OLT_DAV_207 outage) are excluded.`
        : `No NAP had ${min} or more repair orders in the last ${days} days without a SNOW incident.`,
      columns: ["NAP", "orders", "work orders", "statuses"],
      rows: hits.map(([n, v]) => [n, v.length, v.map((o) => o.workordernumber).join(", "), [...new Set(v.map((o) => o.status))].join(", ")]),
      cites: hits.flatMap(([, v]) => v.map((o) => `WO:${o.workordernumber}`)),
      tools: ["curated_query(intent=repeat_orders, days=" + days + ", min_orders=" + min + ")", "ticket_cluster_read", "SNOW affected_nap lookup"],
    };
  }

  const q0 = d.queue(t);
  const ranked = q0 ? rerank(q0.rows, weights, cfg, t) : [];

  // 2. why X above Y
  if (/why/.test(s) && /(above|higher|ahead|before|over)/.test(s)) {
    if (!ranked.length) return { text: "The queue has not been ranked yet at this time.", cites: [], tools: ["queue_read"], abstain: true };
    const pick = (id?: string) => ranked.find((r) => r.row.item_id === id);
    let a = pick(ids[0]), b = pick(ids[1]);
    if (!a || !b) {
      const incs = ranked.filter((r) => r.row.item_type === "incident");
      a = a || incs[0]; b = b || incs.find((r) => r !== a) || ranked[1];
    }
    if (!a || !b) return { text: "I need two items that are in the current queue.", cites: [], tools: ["queue_read"], abstain: true };
    const [hi, lo] = a.rank <= b.rank ? [a, b] : [b, a];
    const ex = explain(hi, lo);
    const top = ex.filter((x) => x.diff > 0).slice(0, 2).map((x) => `${x.term} (+${x.diff.toFixed(3)})`).join(" and ");
    const against = ex.filter((x) => x.diff < 0).slice(0, 2).map((x) => `${x.term} (${x.diff.toFixed(3)})`).join(" and ");
    return {
      text: `${hi.row.item_id} ranks ${hi.rank} with ${hi.score.toFixed(3)}; ${lo.row.item_id} ranks ${lo.rank} with ${lo.score.toFixed(3)}. ${hi.row.item_id} gains on ${top || "no term"}${against ? `, and loses on ${against}` : ""}. ` +
        `Inputs: ${hi.row.item_id} has ${hi.row.inputs.lines} lines, ${hi.row.inputs.element_type}, ${hi.row.inputs.crew ? "crew assigned" : "no crew"}, breach ${hhmm(hi.row.breach_eta)}; ` +
        `${lo.row.item_id} has ${lo.row.inputs.lines} lines, ${lo.row.inputs.element_type}, ${lo.row.inputs.crew ? "crew assigned" : "no crew"}, breach ${hhmm(lo.row.breach_eta)}.` +
        (JSON.stringify(weights) !== JSON.stringify(cfg.queue_weights) ? " (Using sandbox weights.)" : ""),
      columns: ["term", hi.row.item_id, lo.row.item_id, "difference"],
      rows: ex.map((x) => [x.term, x.a.toFixed(3), x.b.toFixed(3), (x.diff > 0 ? "+" : "") + x.diff.toFixed(3)]),
      cites: [...hi.row.evidence_ids, ...lo.row.evidence_ids].slice(0, 12),
      tools: ["queue_read", "sla_clock", "ranking_explain(a=" + hi.row.item_id + ", b=" + lo.row.item_id + ")"],
    };
  }

  // 3. breaches
  if (/breach/.test(s)) {
    const h = /(\d+)\s*h/.test(s) ? +s.match(/(\d+)\s*h/)![1] : /three/.test(s) ? 3 : /one hour|1 hour/.test(s) ? 1 : 2;
    const lim = toMs(t) + h * 3_600_000;
    const hits = ranked.filter((r) => r.row.breach_eta && toMs(r.row.breach_eta) <= lim && (!terr || r.row.territory === terr));
    return {
      text: hits.length ? `${hits.length} item${hits.length > 1 ? "s" : ""} breach the 6-hour window by ${new Date(lim).toISOString().slice(11, 16)}.` : `Nothing breaches the 6-hour window in the next ${h} hour${h > 1 ? "s" : ""}. The earliest breach is ${hhmm(ranked.filter((r) => r.row.breach_eta).sort((a, b) => a.row.breach_eta!.localeCompare(b.row.breach_eta!))[0]?.row.breach_eta)}.`,
      columns: ["item", "rank", "breach", "crew"], rows: hits.map((r) => [r.row.item_id, r.rank, hhmm(r.row.breach_eta), r.row.inputs.crew ? "assigned" : "none"]),
      cites: hits.flatMap((r) => r.row.evidence_ids).slice(0, 12), tools: ["queue_read", `sla_clock(window=${h}h)`],
    };
  }

  // 4. what should my team take next
  if (/take next|next\??$|should (my|our) team|work next|pick up/.test(s)) {
    const pool = ranked.filter((r) => (!terr || r.row.territory === terr) && !r.row.inputs.crew).slice(0, 3);
    return {
      text: pool.length ? `${terr ? terr + ": t" : "T"}op items without a crew, in queue order. ${pool[0].row.item_id} first: ${pool[0].row.label.split(" · ").slice(1).join(", ")}, breach ${hhmm(pool[0].row.breach_eta)}.` : "Nothing in the queue without a crew for that scope.",
      columns: ["rank", "item", "score", "lines", "breach"], rows: pool.map((r) => [r.rank, r.row.item_id, r.score.toFixed(3), r.row.inputs.lines, hhmm(r.row.breach_eta)]),
      cites: pool.flatMap((r) => r.row.evidence_ids).slice(0, 10), tools: ["queue_read", "crew_availability_read"],
    };
  }

  // 5. element questions
  if (elem) {
    const id = elem[1];
    if (!d.naps.has(id) && !d.napsByLcp.has(id) && !d.napsByOlt.has(id)) return { text: `${id} is not in the topology master.`, cites: [], tools: ["topology_lookup"], abstain: true };
    const type = d.elementType(id);
    const naps = d.napsUnder(type, id);
    const horizon = d.snap(t).wms_horizon;
    const lines = naps.flatMap((n) => d.linesByNap.get(n) || []);
    if (/below|gateway|optical|rx|dbm/.test(s)) {
      const thr = +(s.match(/-\s?(\d{2})/)?.[1] || 27);
      const g = lines.map((l) => ({ l, r: d.latestRx(l.mac, horizon) })).filter((x) => x.r && x.r.v < -thr);
      return {
        text: `${g.length} of ${lines.length} gateways on ${id} read below -${thr} dBm at the WMS horizon ${hhmm(horizon)} (raw × 0.0001 mW converted to dBm).`,
        columns: ["gateway MAC", "Rx dBm", "reading at"], rows: g.slice(0, 30).map((x) => [x.l.mac, x.r!.v.toFixed(1), new Date(x.r!.t).toISOString().slice(11, 16)]),
        cites: g.slice(0, 12).map((x) => `SUB:${x.l.subscriber_id}`), tools: [`telemetry_read(element=${id}, hours=2)`],
      };
    }
    const inc = [...d.incidents(t).values()].find((i) => i.state !== "Merged" && (i.element_id === id || i.naps.some((n) => naps.includes(n))) && (i.state === "Proposed" || i.state === "Confirmed")) ||
      [...d.incidents(t).values()].find((i) => i.element_id === id && i.state === "Closed");
    const open = d.orders(t).filter((o) => o.skillset === "Repair" && naps.includes(o.facilityname) && ["Open", "Unassigned", "Pending", "Delayed", "Ongoing"].includes(o.status));
    const snow = [...new Set(d.snow(t).filter((r) => naps.includes(r.affected_nap) && ["New", "In Progress", "On Hold"].includes(r.inc_state)).map((r) => r.inc_number))];
    return {
      text: `${id} (${type}, ${lines.length} lines): ` + (inc ? `${inc.incident_id} is ${inc.state} — ${inc.element_type}-level ${inc.kind}, support ${inc.support_score.toFixed(2)}, ${inc.observed_lines} observed and ${inc.inferred_lines} silent lines. ` : "no SDAL incident. ") +
        `${open.length} open repair orders. ${snow.length ? "Open SNOW: " + snow.join(", ") + "." : "No open SNOW outage."}`,
      columns: ["workordernumber", "created", "status"], rows: open.slice(0, 15).map((o) => [o.workordernumber, hhmm(o.createdate), o.status]),
      cites: [...(inc ? [`SDAL:${inc.incident_id}`] : []), ...open.slice(0, 10).map((o) => `WO:${o.workordernumber}`)],
      tools: ["topology_lookup", "incident_registry_read", "ticket_cluster_read"],
    };
  }

  // 6. feeds
  if (/feed|stall|late|arriv/.test(s)) {
    const f = Object.values(d.snap(t).feeds);
    const bad = f.filter((x) => x.status !== "on time");
    return {
      text: bad.length ? `${bad.map((x) => `${x.label} is ${x.status} (last arrival ${hhmm(x.last_arrival)})`).join("; ")}. Detectors that depend on it are paused; this is an alert, not a quiet night.` : "Every feed arrived on time.",
      columns: ["source", "status", "last arrival", "cadence"], rows: f.map((x) => [x.label, x.status, hhmm(x.last_arrival), `${x.cadence_min} min`]),
      cites: [], tools: ["feed_health_read"],
    };
  }

  // 7. overrides / suppressions
  if (/overrid/.test(s) || /suppress/.test(s)) {
    const recs = [...d.recs(t).values()].filter((r) => (/overrid/.test(s) ? r.dispatcher_decision === "overridden" || d.recVersions(r.workordernumber, t).some((v) => v.dispatcher_decision === "overridden") : r.outcome === "suppress"));
    return {
      text: `${recs.length} ${/overrid/.test(s) ? "orders with a dispatcher override" : "orders currently recommended for suppression"}.`,
      columns: ["order", "recommendation", "decision", "reason"],
      rows: recs.map((r) => { const ov = d.recVersions(r.workordernumber, t).find((v) => v.dispatcher_decision === "overridden"); return [r.workordernumber, r.outcome, ov ? "overridden" : r.dispatcher_decision ?? "pending", ov?.override_reason ?? r.reason_class]; }),
      cites: recs.slice(0, 10).map((r) => `WO:${r.workordernumber}`), tools: ["adoption_record (read)"],
    };
  }

  // 8. notifications
  if (/silent|notif|package|customers.*told|message/.test(s)) {
    const pk = [...d.packages(t).values()].filter((p) => p.state !== "Withheld");
    const silent = pk.reduce((a, p) => a + p.recipients_inferred, 0);
    return {
      text: pk.length ? `${pk.length} packages are draft or approved, covering ${pk.reduce((a, p) => a + p.recipients_total, 0)} recipients of whom ${silent} never called. Nothing has been sent: the NG1 handoff is disabled and consent is unavailable in the pilot.` : "No notification package exists yet.",
      columns: ["package", "incident", "state", "recipients", "silent", "earliest send"], rows: pk.map((p) => [p.package_id, p.incident_id, p.state, p.recipients_total, p.recipients_inferred, hhmm(p.scheduled_send_at)]),
      cites: pk.map((p) => `SDAL:${p.incident_id}`), tools: ["subscriber_resolve", "contact_policy_check (read)"],
    };
  }

  // 9. counts and incidents
  if (/incident/.test(s)) {
    const incs = [...d.incidents(t).values()].filter((i) => (i.state === "Proposed" || i.state === "Confirmed") && (!terr || i.territory === terr));
    return {
      text: `${incs.length} open SDAL incident${incs.length === 1 ? "" : "s"}${terr ? " in " + terr : ""}.`,
      columns: ["incident", "element", "state", "lines", "support"], rows: incs.map((i) => [i.incident_id, `${i.element_type} ${i.element_id}`, i.state, i.observed_lines + i.inferred_lines, i.support_score.toFixed(2)]),
      cites: incs.map((i) => `SDAL:${i.incident_id}`), tools: ["incident_registry_read"],
    };
  }
  if (/how many|count|open orders|orders/.test(s)) {
    const o = d.orders(t).filter((x) => x.skillset === "Repair" && ["Open", "Unassigned", "Pending", "Delayed", "Ongoing"].includes(x.status) && (!terr || d.lineBySvc.get(x.serviceidnumber)?.territory === terr));
    return {
      text: `${o.length} open repair orders${terr ? " in " + terr : ""} at ${hhmm(t)}.`,
      columns: ["status", "orders"], rows: Object.entries(o.reduce((m: any, x) => ((m[x.status] = (m[x.status] || 0) + 1), m), {})).map(([k, v]) => [k, v as number]),
      cites: o.slice(0, 10).map((x) => `WO:${x.workordernumber}`), tools: ["curated_query(intent=open_orders)"],
    };
  }
  return {
    text: "No registered tool answers that, so I will not guess. I can answer questions about repeat orders, queue ranking and breaches, a NAP, LCP or OLT, gateways below a threshold, feed health, overrides, suppressions, notifications and open incidents.",
    cites: [], tools: [], abstain: true,
  };
}

export function Chat() {
  const { chatOpen, setChatOpen, chatSeed, d, t, weights } = useApp();
  const [log, setLog] = useState<{ q: string; a: Answer; at: string }[]>([]);
  const [input, setInput] = useState("");
  const body = useRef<HTMLDivElement>(null);
  const ask = (q: string) => {
    if (!q.trim()) return;
    setLog((l) => [...l, { q, a: answer(q, d, t, weights), at: t }]);
    setInput("");
  };
  useEffect(() => { if (chatSeed) ask(chatSeed.split("​")[0]); }, [chatSeed]);
  useEffect(() => { body.current?.scrollTo({ top: body.current.scrollHeight }); }, [log]);
  if (!chatOpen) return <button className="btn primary chatfab" onClick={() => setChatOpen(true)}>Ask the control tower</button>;
  return (
    <aside className="chat" aria-label="Conversational panel">
      <div className="chat-h">
        <div style={{ flex: 1 }}><b>Ask the control tower</b><div className="small faint">Answers only through registered tools over the curated layer, as of {hhmm(t)}</div></div>
        <button className="btn sm" onClick={() => setChatOpen(false)}>Close</button>
      </div>
      <div className="chat-b" ref={body}>
        {log.length === 0 && <div className="small muted">Ask in plain language. Every answer lists the tool calls it made and cites the rows behind it; with no evidence rows, it abstains.</div>}
        {log.map((m, i) => (
          <React.Fragment key={i}>
            <div className="msg-q">{m.q}</div>
            <div className="msg-a">
              <div>{m.a.text}</div>
              {m.a.rows && m.a.rows.length > 0 && (
                <div className="tablewrap"><table className="t"><thead><tr>{m.a.columns!.map((c) => <th key={c}>{c}</th>)}</tr></thead>
                  <tbody>{m.a.rows.map((r, j) => <tr key={j}>{r.map((v, k) => <td key={k} className={typeof v === "number" ? "r num" : k === 0 ? "mono" : "small"}>{v}</td>)}</tr>)}</tbody></table></div>
              )}
              <div className="row between">
                <span className="tools">{m.a.tools.length ? m.a.tools.join(" → ") : "no tool call"} · {hhmm(m.at)}</span>
                {m.a.cites.length > 0 && <EvidenceButton ids={m.a.cites} title={m.q} label={`Cites ${m.a.cites.length} rows`} />}
              </div>
            </div>
          </React.Fragment>
        ))}
      </div>
      <div className="chat-f">
        <div className="suggest">{(log.length ? MORE : CANNED).map((c) => <button key={c} onClick={() => ask(c)}>{c}</button>)}</div>
        <form className="row" onSubmit={(e) => { e.preventDefault(); ask(input); }}>
          <input type="text" id="chat-input" value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask a question" style={{ flex: 1 }} aria-label="Question" />
          <button className="btn primary" type="submit">Ask</button>
        </form>
      </div>
    </aside>
  );
}
