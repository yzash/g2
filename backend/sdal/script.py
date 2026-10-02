"""Scripted human decisions for the synthetic morning.

These are the presenter's decisions in autopilot. In the operator surface the
presenter can take them live instead (guided mode); anything off-script is
recorded in the adoption record as a live decision. Every entry is a human
action, never an agent action.
"""

SCRIPT = [
    # ---- overnight ----------------------------------------------------------
    {"at": "2026-10-26 23:50", "actor": "NOC lead (night)", "role": "NOC / network-operations lead", "action": "confirm_incident",
     "target": {"element": "OLT_DAV_207"}, "snow_ref": "INC0080123",
     "reason": "Matches NMS PON LOS on OLT_DAV_207 and SNOW INC0080123 raised by NMS."},
    {"at": "2026-10-26 23:58", "actor": "Dispatcher T5 (night)", "role": "Dispatcher", "action": "accept_pending", "target": {"territory": "T5"}},
    {"at": "2026-10-27 00:30", "actor": "Dispatcher T5 (night)", "role": "Dispatcher", "action": "accept_pending", "target": {"territory": "T5"}},
    {"at": "2026-10-27 05:45", "actor": "Dispatcher T7", "role": "Dispatcher", "action": "accept_pending", "target": {"territory": "*"}},
    # ---- 06:14 NOC lead confirms SDAL incident on CAV_118_L004_N07B and raises SNOW ----
    {"at": "2026-10-27 06:14", "actor": "NOC lead (T7)", "role": "NOC / network-operations lead", "action": "confirm_incident",
     "target": {"element": "CAV_118_L004_N07B"}, "snow_ref": "INC0081207",
     "reason": "Evidence rows check out: 11 of 14 gateways below -27 dBm, siblings clean, no alarm. Raised INC0081207."},
    # ---- 06:18 dispatcher reviews the reacted queue -----------------------------
    {"at": "2026-10-27 06:18", "actor": "Dispatcher T7", "role": "Dispatcher", "action": "decide_rec", "target": {"truth": "s1_orders", "index": 0}, "decision": "accepted"},
    {"at": "2026-10-27 06:18", "actor": "Dispatcher T7", "role": "Dispatcher", "action": "decide_rec", "target": {"truth": "s1_orders", "index": 2}, "decision": "accepted"},
    {"at": "2026-10-27 06:18", "actor": "Dispatcher T7", "role": "Dispatcher", "action": "decide_rec", "target": {"truth": "s1_orders", "index": 1}, "decision": "overridden",
     "override_outcome": "dispatch", "reason": "B2B account under SLA: send a technician to site regardless, alongside the fibre crew."},
    {"at": "2026-10-27 06:18", "actor": "Dispatcher T7", "role": "Dispatcher", "action": "decide_rec", "target": {"truth": "s2_wo"}, "decision": "accepted"},
    {"at": "2026-10-27 06:26", "actor": "Dispatcher T5", "role": "Dispatcher", "action": "accept_pending", "target": {"territory": "T5"}},
    {"at": "2026-10-27 06:35", "actor": "Dispatcher T5", "role": "Dispatcher", "action": "decide_rec", "target": {"truth": "s4_wo"}, "decision": "accepted"},
    {"at": "2026-10-27 06:38", "actor": "Dispatcher T7", "role": "Dispatcher", "action": "decide_rec", "target": {"truth": "s1_orders", "index": 3}, "decision": "accepted"},
    # ---- 06:40 communications approver -------------------------------------------
    {"at": "2026-10-27 06:40", "actor": "Comms approver", "role": "Communications approver", "action": "approve_package",
     "target": {"element": "CAV_118_L004_N07B", "kind": "initial"}, "reason": "Recipients, text and evidence reviewed. Approve draft."},
    {"at": "2026-10-27 06:44", "actor": "Dispatcher T5", "role": "Dispatcher", "action": "accept_pending", "target": {"territory": "T5"}},
    {"at": "2026-10-27 06:52", "actor": "Comms approver", "role": "Communications approver", "action": "approve_package",
     "target": {"element": "OLT_DAV_207", "kind": "update"}, "reason": "Restoration target 10:00 confirmed with outage management."},
    {"at": "2026-10-27 07:05", "actor": "Dispatcher T5", "role": "Dispatcher", "action": "accept_pending", "target": {"territory": "*"}},
    # ---- 07:13 restoration ---------------------------------------------------------
    {"at": "2026-10-27 07:13", "actor": "NOC lead (T7)", "role": "NOC / network-operations lead", "action": "confirm_closure",
     "target": {"element": "CAV_118_L004_N07B"}, "reason": "Crew reports NAP connector re-terminated; Rx back to -20 dBm."},
    {"at": "2026-10-27 07:20", "actor": "Dispatcher T5", "role": "Dispatcher", "action": "accept_pending", "target": {"territory": "*"}},
    {"at": "2026-10-27 07:40", "actor": "NOC lead (T7)", "role": "NOC / network-operations lead", "action": "confirm_incident",
     "target": {"element": "CAV_121_L002_N05A"}, "reason": "Known flapping NAP; one recurring-fault ticket for field inspection."},
    {"at": "2026-10-27 07:50", "actor": "Dispatcher T7", "role": "Dispatcher", "action": "accept_pending", "target": {"territory": "*"}},
    {"at": "2026-10-27 08:20", "actor": "Dispatcher T5", "role": "Dispatcher", "action": "accept_pending", "target": {"territory": "*"}},
    {"at": "2026-10-27 08:34", "actor": "Dispatcher T5", "role": "Dispatcher", "action": "decide_rec", "target": {"truth": "s4_wo"}, "decision": "accepted"},
]
