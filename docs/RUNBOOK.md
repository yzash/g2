# Presenter runbook: 20 minutes, one synthetic morning

Open the app, leave **Guided** on, role **Presenter (all roles)**, speed **10x**. The clock starts
at 05:30 on Tuesday 27 Oct 2026 (synthetic). The chapter chips under the scrubber jump to each beat.
In Guided mode the clock stops at every human decision. Click **Take scripted decision**, or open
the screen and decide live. A live decision lands in the adoption record marked "live".

| Clock | Screen | Say | Click |
| --- | --- | --- | --- |
| 05:30 | Control Tower | One map, eight territories. FSM, SNOW, Handyman, WMS and alarms are correlated on NAP. The feed strip says every source is on time. SDAL-0405 (OLT_DAV_207 fibre cut) has been open since 23:42 with a crew. | Play |
| 06:07 | Control Tower | Three customers on CAV_118_L004_N07B and no alarm. The NAP turns amber: the Investigator is watching but abstains. Support is 0.53, because the WMS batch with the optical readings has not landed. | Chapter "06:07" |
| 06:12 | Element view | SDAL-0412 is proposed: 11 of 14 gateways below -27 dBm since 05:48, 11 of 11 sibling NAPs clean, so NAP-level. Support 0.86 is arithmetic you can read. 14 lines: 4 called, 10 silent. Open **Evidence** and **Full trace**. | Chapter "06:12" |
| 06:14 | (prompt) | The NOC lead confirms and raises INC0081207. | Take scripted decision, or Confirm on the card |
| 06:15 | Dispatch review | Three suppressions on the incident (the fourth order arrives 06:32). WO on N07A gets **dispatch** with a CPE signature: healthy optical, modem not found. Planned works and power are drawn as unavailable, never clear. Switch to **Today's process** to show all rolling. | Chapter "06:15" |
| 06:18 | (prompt) | The dispatcher accepts three and overrides the B2B line with a reason. | Take scripted decision |
| 06:30 | Work queue | SDAL-0412 is above SDAL-0405: no crew yet, and it breaches first. Use **Why is one item above another?** Then press **PRD v0.1 defaults** to show the policy question for Gate 0, and **Reset to locked**. | Chapter "06:30" |
| 06:31 | Dispatch review | An order whose only evidence is a 12-hour-old Handyman check, with the gateway silent since 18:35: **hold-and-recheck** with a countdown to 08:31. | Six scenarios → 4 |
| 06:40 | Communications | 14 recipients, 10 of them never called. The policy checks show consent unavailable, so the package is draft-only. NG1 send is disabled, with the reason. The OLT package is held by quiet hours until 07:00. | Chapter "06:40" |
| 06:45 | Control Tower | Handyman goes late, then stalled. The alert explains it; the complaint detector pauses; the hold falls back to dispatch. At 07:00 the feed recovers and the hold returns. | Chapter "06:45" |
| 07:13 | Element view | Rx is back to -20 dBm. Closure is proposed and confirmed. The orders close without a visit; the overridden B2B visit finds no fault. | Chapter "07:10" |
| 07:30 | Ask panel | "Which NAPs had three or more repeat orders this week with no SNOW incident?" The answer cites rows. Then take a question from the room. | Chapter "07:30" |
| 07:32 | Work queue | The flapping NAP: five short SNOW auto-tickets become one recurring-fault incident, scored on 12 lines, not on ticket count. | Chapter "07:32" |
| 08:32 | Adoption record | The morning: one incident, four suppressions, one override, approved drafts, 48 minutes ahead of the hourly cycle, zero wrong suppressions, all with evidence IDs. Show the comparison lane and **Download CSV**. | Chapter "08:30", then the Adoption tab |

**Questions the panel answers** (examples): "What is happening on OLT_DAV_207?", "Which gateways on
CAV_118_L004_N07B are below -27 dBm?", "What breaches in the next two hours?", "What should my team
in T5 take next?", "Is any feed late?", "Which recommendations were overridden?", "How many silent
customers were notified?". If no registered tool answers a question, the panel says so and does
not guess.

**Autopilot** plays all six scenarios end to end with no clicks (acceptance criterion 1).
