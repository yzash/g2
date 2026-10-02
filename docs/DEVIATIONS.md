# Deviations from PRD v0.1, assumptions, and questions for Gate 0

Everything below is a place where the build had to choose something the PRD left open or where the
PRD's numbers did not hold together on the synthetic day. Each item says what was built and what
needs a decision.

## Deviations

**D1. Queue weights.** With the PRD's bracketed defaults (w_t 0.40, w_l 0.25, w_s 0.20, w_v 0, w_c 0.15),
an OLT incident with ~830 lines always outranks a 14-line NAP incident: the lines and severity
terms add about 0.58 to the OLT side and the crew term only gives the NAP side 0.15. So the PRD's
06:30 beat ("SDAL-0412 above the older OLT incident") cannot happen with those weights. The demo
uses w_t 0.40, w_l 0.10, w_s 0.15, w_v 0, w_c 0.35. That policy reads "unattended work first: an
item with a crew is in hand". The Work queue sandbox has a "PRD v0.1 defaults" button. Pressed at
06:30, it shows the OLT incident on top and the breach exception firing for SDAL-0412. That is
a useful Gate 0 conversation: which of these two is the policy?

**D2. Incident numbers.** The registry is one sequence, and merged duplicate clusters take IDs
(the PRD lists Merged as an incident state). The overnight OLT outage is SDAL-0405. Its six
overnight duplicate clusters are 0406 to 0411. Scenario 1 is SDAL-0412, as in the PRD. The PRD
calls the OLT incident 0398. Here it is 0405, so it is still older and still ranks below 0412.

**D3. Suppress needs a SNOW reference or a crew.** By the PRD's rule, a freshly confirmed incident
with no SNOW ticket and no crew cannot suppress. The demo resolves this the way operations would:
the NOC lead raises the SNOW incident (INC0081207) when confirming at 06:14. That is a human action
outside the platform; the platform's only external write remains NG1, and it is disabled.

**D4. Two small additions to the hold and suppress rules.**
- A line inside a Confirmed incident that is still waiting for a physical signal or a SNOW
  reference gets hold, not dispatch. This happens overnight before the WMS batch lands, and it
  avoids a dispatch → suppress flip.
- A line inside an incident closed in the last 6 hours, whose own gateway is back to baseline,
  gets "suppress: upstream fault restored; close the order after customer confirmation". This
  avoids a 12-minute dispatch flip between restoration and the order being cancelled in FSM.

**D5. Quiet hours and the 06:40 approval.** 06:40 falls inside quiet hours (22:00 to 07:00). So
SDAL-0412's package is approved at 06:40 with an earliest send of 07:00. The "second incident held
by quiet hours" is the OLT incident's update package, built 06:28 when outage management moved the
restoration target to 10:00. The restoration notice for 0412 at 07:15 is held by the frequency cap
until 09:00. That shows the third policy check doing work.

**D6. Alarm sample is corroboration only.** The PRD lists alarm as a candidate signal, but its
non-goals say "no raw-alarm correlation; the alarm sample is corroboration only". An alarm adds
5% weight to the support score and shows as a signal on the map. It never opens an incident on
its own.

## Assumptions (synthetic, to confirm in week 2)

- **WMS cadence.** The demo assumes half-hour batch files landing at :10 and :40. Readings for
  05:30 to 06:00 land at 06:10. That is why the Investigator watches and abstains at 06:07
  (complaints but no optical yet) and proposes at 06:12 once optical lands. With a true 5-minute
  feed, detection would come about 20 minutes earlier.
- **Feed cadences.** FSM every 5 min, SNOW extract every 15 min, Handyman every 5 min, alarms
  every 5 min.
- **NAP naming.** `facilityname` (CAV_118_L004_N07B) is used as canonical. `dpid` is the
  alternate form DP-CAV-118-L004-N07B (open question to Rod).
- **Territory names.** T1–T8 names and sites are placeholders. T5 Davao and T7 Cavite are the
  full clusters, as in the PRD.
- **Product mapping.** prod_id, plan names and MSF are synthetic placeholders, because the real
  `prod_id_mapping` file was not available to the build. MSF is shown only as a band.
- **VIP/B2B** is a synthetic 3% flag kept in a separate platform table, so Globe's base schemas
  stay exact.
- **Severity cut-offs.** OLT ≥500 lines is 1, ≥100 is 2, otherwise 3. LCP is 4. NAP ≥10 lines is
  5.1, otherwise 5.2. A single line is 5.3. These follow the 5.x versus 1–3 framing.
- **Support score weights.** Ticket density 0.28, physical signal 0.42, sibling cleanliness 0.25,
  alarm 0.05. The proposal threshold is 0.60. Scenario 1 scores 0.86 =
  0.28·1 + 0.42·(11/14) + 0.25·1 + 0.05·0.
- **Line-level hold support.** Weights 0.40/0.30/0.15/0.15 across siblings healthy, gateway
  silent, silence after last contact and no fresh complaint. That is multiplied by 0.90 because
  the power check is unavailable, and a silent gateway is exactly what a power cut looks like.
  Scenario 4 scores 0.90.
- **Queue clock.** The clock is the earliest createdate among the item's *open* orders. Overnight
  orders cancelled as "covered by outage" do not start the clock. An incident with no open orders
  has no running clock.
- **Dictionary.** `dictionaries/globe_handoff_columns.json` is transcribed from PRD section 3.
  Replace it with an export of the handoff dictionaries (00_README to 18); the schema diff then
  runs against the real thing.
- **LLM layer.** The four agents follow the PRD's fixed tool-call contracts deterministically.
  Rationales are templated text from the evidence. The conversational panel routes questions to
  registered read-only tools in the browser and abstains when no tool answers. Google ADK on
  Gemini is the pilot plan, and it plugs in at the same tool boundary. No model key ships with the
  demo, and the demo needs no network.

## Open questions from the PRD, with the default the build took

| Question | Default in the build |
| --- | --- |
| Real curated layer instead of synthetic if access lands before 30 Oct? | Synthetic. The loaders take Globe's file shapes, so swapping is a data change. |
| Canonical naming: facilityname or dpid? | facilityname |
| Detector thresholds 10/OLT, 3/NAP, rolling 6 h? | Used as given; all in `config/sdal_config.json` |
| Does outage management publish a restoration target? | Both paths shown: OLT_DAV_207 has a target (10:00); SDAL-0412 gets "next update by …" |
| Show the sandbox weight panel to the Head of Broadband? | Shown, labelled "sandbox, not persisted"; switch role to Head of Broadband to make it read-only |
| Who attends the dry run (Wed 28 Oct)? | Not a build item |

## Not done (outside a static demo)

- Acceptance 7, screen load under 2 s, was measured locally: the bundle loads in about 1.3 s and
  is 7.6 MB raw / 0.8 MB gzipped. The free question answers instantly because routing happens in
  the browser.
- Acceptance 9, a Globe reviewer walking the dry run, is a human step.
