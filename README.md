# SDAL Control Tower: MVP demo

The demo built from *PRD: SDAL Control Tower MVP demo* (DevX Labs for Globe Telecom, draft v0.1). It
shows one synthetic morning in the CFS control tower with four SDAL agents on Globe's schemas:

- **UC1 Incident Investigator** finds a non-alarm NAP fault 48 minutes before the hourly cycle, with evidence rows.
- **UC2 Dispatch Reviewer** recommends dispatch, suppress or hold-and-recheck. Below the 0.80 floor, suppress and hold are unreachable.
- **UC3 Queue Prioritizer** ranks with inspectable arithmetic, explains any position, and has a sandbox for the weights.
- **UC5 Customer Notification** builds draft, policy-checked packages for the silent majority. Nothing is sent.

The data is synthetic rows on Globe's column names and vocabularies, so nothing on screen is a Globe figure.

```
backend/sdal/            Python: generator, DuckDB curated layer, detectors, tool registry, agents, guardrails, replay engine
  generator.py           seeded synthetic day (CSV + parquet in Globe's shapes); the six scenarios of PRD §10
  curated.py             DuckDB curated layer; unit conversion; feed-arrival stamps (no tool sees a row early)
  detectors.py           ticket-burst, optical-drop, reachability, complaint-burst, flap, alarm (corroboration)
  tools.py               the tool registry: the complete authorisation boundary; every call traced
  scoring.py             deterministic support score and isolation hypotheses
  guardrails.py          UC2 decision rules; the confidence floor is checked first
  agents/                investigator.py, dispatch.py, prioritizer.py, notifier.py
  engine.py, script.py   minute-by-minute replay with scripted human decisions
  bundle.py              writes web/public/bundle.json for the surface
backend/tests/           PRD §12 acceptance criteria as tests
web/                     React operator surface: Control Tower, Element, Dispatch review, Work queue,
                         Communications, Adoption record, evidence drawer, trace, conversational panel
config/sdal_config.json  every threshold, weight and policy value (all Gate 0 items)
dictionaries/            Globe handoff column dictionary used by the schema diff
docs/RUNBOOK.md          the 20-minute click-through
docs/DEVIATIONS.md       deviations from the PRD, assumptions, open questions
```

## Run it

```bash
pip install -r backend/requirements.txt
cd backend && python -m sdal all          # generate → schema diff → DuckDB → engine → web/public/bundle.json (~1 min)
python -m pytest -q tests                 # acceptance tests (~3 min)
cd ../web && npm install && npm run dev   # http://localhost:5173
npm run build                             # static site in web/dist, deployable to any static host
```

`web/public/bundle.json` is committed, so the surface builds and deploys without Python.

## Acceptance criteria (PRD §12)

| # | Criterion | Where it is proven |
| --- | --- | --- |
| 1 | Six scenarios play end to end, twice, from the seeded generator | `test_generator_is_deterministic`, `test_two_runs_are_identical`, `test_six_scenarios_play_out`; Autopilot mode in the surface |
| 2 | Every card opens an evidence drawer with real row identifiers; no ungrounded answer renders | `test_every_output_is_grounded`, `test_grounding_contract_rejects_ungrounded_output`; `Grounded` wrapper in the UI |
| 3 | Below 0.80, no suppress or hold anywhere, by test | `test_floor_property_on_decision_rules` (5,000 random cases), `test_forced_low_support_gives_no_suppress_or_hold` |
| 4 | Feed stall alerts within one interval, clears, creates nothing | `test_feed_stall` |
| 5 | Prompt injection in fixdescription changes nothing and shows as ignored | `test_prompt_injection_is_ignored` |
| 6 | Consent unavailable, send disabled, no code path calls ng1_handoff | `test_no_send_path` (AST scan), `test_ng1_handoff_is_disabled` |
| 7 | Screens under 2 s; free question under 15 s | Measured: about 1.3 s to load the bundle locally; answers are instant |
| 8 | Column names match the handoff dictionaries; diff is part of the build | `python -m sdal check-schema` runs in `all`; `test_schema_matches_dictionary` |
| 9 | Globe reviewer walks the dry run | Human step (Wed 28 Oct) |

Also tested: cross-role isolation at the tool registry (`test_cross_role_isolation`) and effective-dated topology (`test_reparented_nap_keeps_history`).

## Demo stack versus pilot

DuckDB stands in for BigQuery. The replay clock (10x, pause, scrub, chapters) stands in for the
live clock. A static React app stands in for the Gemini Enterprise surface. The agents run their
PRD tool-call contracts deterministically, so the morning replays identically. The conversational
panel answers only through registered read-only tools and abstains otherwise. What carries over
unchanged: schemas, tool registry, output objects, guardrail code, adoption record and trace shape.
