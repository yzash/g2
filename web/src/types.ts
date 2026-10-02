// Shapes of the replay bundle written by backend/sdal/bundle.py.

export type Row = Record<string, any>;
export interface Table { columns: string[]; rows: any[][] }

export interface Hypothesis { element_type: string; element_id: string; score: number; components: Record<string, number> }

export interface Incident {
  incident_id: string; element_type: "NAP" | "LCP" | "OLT" | "LINE"; element_id: string; kind: string;
  hypothesis_rank: Hypothesis[]; observed_lines: number; inferred_lines: number; vip_b2b_count: number;
  msf_band_total: Record<string, number>; severity: string; support_score: number; score_components: Record<string, number>;
  rationale: string; state: "Proposed" | "Confirmed" | "Rejected" | "Merged" | "Closed"; proposed_at: string;
  decided_by?: string | null; decided_at?: string | null; decision_reason?: string | null; parent_id?: string | null;
  snow_refs: string[]; crew_assigned: boolean; has_physical_signal: boolean; closure_proposed_at?: string | null;
  closed_at?: string | null; flap_count: number; detectors: string[]; olt?: string; lcp?: string | null; naps: string[];
  territory?: string; hourly_cycle_at?: string | null; detection_lead_min?: number | null; first_signal_at?: string | null;
  run_id?: string; evidence_ids: string[]; version: number; updated_at?: string;
}

export interface Check { question: string; tool: string; status: "available" | "unavailable"; result: string; evidence_ids: string[] }

export interface Rec {
  rec_id: string; workordernumber: string; review_seq: number; outcome: "dispatch" | "suppress" | "hold";
  reason_class: string; note: string; support_score: number | null; floor: number; floor_applied: boolean;
  incident_id: string | null; checks: Check[]; estimated_avoidable_cost: string; hold_until: string | null;
  recommended_at: string; territory: string; trigger: string; dispatcher_decision: "accepted" | "overridden" | null;
  decided_by: string | null; decided_at: string | null; override_reason: string | null; override_outcome: string | null;
  outcome_observed: string | null; untrusted_text_flags: string[]; run_id: string; evidence_ids: string[];
}

export interface QueueRow {
  item_id: string; item_type: "incident" | "order"; label: string; rank: number; score: number;
  inputs: { t_elapsed_h: number; lines: number; sev: number; sev_class: string; element_type: string; vip: number; crew: number; state: string; open_orders: number };
  clock_start: string | null; breach_eta: string | null; exception_flag: boolean; exception_text: string | null;
  ranked_at: string; territory: string | null; evidence_ids: string[];
}

export interface PolicyResult { check: string; status: "pass" | "hold" | "blocked" | "unavailable"; detail: string; affected: number }

export interface Pkg {
  package_id: string; incident_id: string; kind: "initial" | "update" | "restoration"; recipients_total: number;
  recipients_observed: number; recipients_inferred: number; recipients_vip: number; recipients_mass: number;
  recipient_tokens_sample: string[]; text: string; restoration_target: string | null; next_update_at: string | null;
  scheduled_send_at: string | null; policy_results: PolicyResult[]; state: "Draft" | "Approved" | "Withheld" | "Sent";
  send_state: string; approver: string | null; decided_at: string | null; decision_note: string | null; built_at: string;
  trigger: string; ng1_payload_preview: Row; run_id: string; evidence_ids: string[];
}

export interface Adoption {
  record_id: string; at: string; actor: string; role: string; object_type: string; object_id: string;
  recommendation: string; decision: string; reason: string | null; outcome_observed: string | null;
  scripted: boolean; batch?: boolean; evidence_ids: string[]; live?: boolean;
}

export interface Abstention { abstention_id: string; at: string; workordernumber: string; cabinetid: string; town: string; near_incident: string | null; text: string; evidence_ids: string[] }

export interface Ev { t: string; kind: string; change: string; id: string; obj: any }

export interface FeedHealth { source: string; label: string; status: "on time" | "late" | "stalled"; last_arrival: string | null; expected: string | null; lag_min: number | null; missed: number; cadence_min: number }

export interface Snap {
  t: string; feeds: Record<string, FeedHealth>; nap_states: Record<string, string>; alarm_elements: string[];
  paused: { detector: string; source: string; status: string; note: string }[]; wms_horizon: string | null;
  counts: Record<string, number>;
}

export interface ToolCall { call_id: string; tool: string; params: Row; summary: string; evidence_ids: string[]; n_evidence: number; flags: string[] }
export interface Run { run_id: string; agent: string; trigger: string; at: string; inputs: Row; tool_calls: ToolCall[]; outputs: { kind: string; ref: string }[]; notes: string[] }

export interface EvidenceRow { id: string; source: string; row: Row; fetched_by: string | null; fetched_at: string }

export interface NapRef { NAP: string; LCP: string; OLT: string; site: string; territory: string; territory_name: string; barangay: string; town: string; province: string; lat: number; lon: number; subs: number }

export interface Bundle {
  meta: any;
  geo: { outline: number[][][]; source: string };
  naps: NapRef[];
  lines: Table;
  tables: { orders: Table; snow: Table; handyman: Table; alarms: Table; restoration: Table };
  telemetry: { start: string; step_min: number; coarse_step_min: number; n_slots: number; full: Record<string, (number | null)[]>; coarse: Record<string, (number | null)[]>; unit: string };
  events: Ev[];
  snapshots: Snap[];
  trace: Run[];
  evidence: Record<string, EvidenceRow>;
  answers: Record<string, any>;
}
