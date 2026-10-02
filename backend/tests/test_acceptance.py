"""PRD section 12 acceptance criteria, as tests (not inspection)."""

import ast
import hashlib
import json
import random
from pathlib import Path

import duckdb
import pytest

from sdal import RAW_DIR
from sdal.check_schema import check
from sdal.engine import Engine
from sdal.generator import INJECTION_TEXT, generate
from sdal.guardrails import DispatchEvidence, decide
from sdal import tools as T

PKG = Path(__file__).resolve().parents[1] / "sdal"


def digest(e: Engine) -> str:
    payload = json.dumps({"events": e.state.events, "snapshots": e.snapshots, "trace": e.tracer.runs}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def incident(e, element):
    return next(i for i in e.state.incidents.values() if i.element_id == element and i.state != "Merged")


# ---- 1. scenarios replay end to end, twice, from the seeded generator ------------
def test_generator_is_deterministic(tmp_path, generated):
    generate(tmp_path)
    for f in ("owfm_all_status_20261027.csv", "handyman_diagnostic_log_20261027.csv", "snow_outage_nap_20261027.csv", "postpaid_base.csv"):
        assert (tmp_path / f).read_bytes() == (RAW_DIR / f).read_bytes(), f


def test_two_runs_are_identical(engine, generated):
    from sdal.curated import connect
    again = Engine(con=connect()).run()
    assert digest(again) == digest(engine)


def test_six_scenarios_play_out(engine):
    s1 = incident(engine, "CAV_118_L004_N07B")
    assert s1.incident_id == "SDAL-0412"
    assert s1.proposed_at == "2026-10-27 06:12:00"
    assert s1.support_score == pytest.approx(0.86)
    assert (s1.observed_lines, s1.inferred_lines, s1.vip_b2b_count) == (4, 10, 1)
    assert s1.detection_lead_min == 48 and s1.hourly_cycle_at == "2026-10-27 07:00:00"
    assert s1.state == "Closed"
    assert "ALM" not in " ".join(s1.evidence_ids)                     # no NMS alarm
    # UC2: four suppressions, one override
    s1_recs = [engine.state.recs[wo] for wo in engine.truth["s1_orders"]]
    assert all(any(v.outcome == "suppress" for v in r) for r in s1_recs)
    assert sum(any(v.dispatcher_decision == "overridden" for v in r) for r in s1_recs) == 1
    # scenario 2: CPE signature dispatches, not merged into the incident
    s2 = engine.state.recs[engine.truth["s2_wo"]]
    assert s2[0].outcome == "dispatch" and s2[0].reason_class == "customer, drop or CPE fault" and s2[0].incident_id is None
    # scenario 3: burst linked to the existing OLT incident, never a new incident
    olt = incident(engine, "OLT_DAV_207")
    assert olt.state == "Confirmed" and "INC0080123" in olt.snow_refs and olt.crew_assigned
    merged = [i for i in engine.state.incidents.values() if i.state == "Merged" and i.parent_id == olt.incident_id and i.proposed_at >= "2026-10-27 06:20"]
    assert merged
    for wo in engine.truth["s3_burst"]:
        assert engine.state.recs[wo][0].outcome == "suppress"
    # UC3: SDAL-0412 above the older OLT incident at 06:30, explainable from inputs
    q = next(ev for ev in engine.state.events if ev["kind"] == "queue" and ev["t"] == "2026-10-27 06:30:00")
    ranks = {r["item_id"]: r["rank"] for r in q["obj"]["rows"]}
    assert ranks[s1.incident_id] < ranks[olt.incident_id]
    # scenario 4: hold 2h, then dispatch when nothing changes
    s4 = engine.state.recs[engine.truth["s4_wo"]]
    assert s4[0].outcome == "hold" and s4[0].hold_until == "2026-10-27 08:31:00"
    assert s4[-1].outcome == "dispatch" and "expired" in s4[-1].note
    # scenario 6: flapping NAP rolled into one recurring-fault incident
    flap = incident(engine, "CAV_121_L002_N05A")
    assert flap.kind == "recurring fault" and flap.flap_count == 5
    assert sum(1 for i in engine.state.incidents.values() if i.element_id.startswith("CAV_121_L002")) == 1
    # UC5: 14 recipients, 10 silent, approved as draft; quiet hours hold the OLT package until 07:00
    p = [p for p in engine.state.packages.values() if p.incident_id == s1.incident_id and p.kind == "initial"][0]
    assert (p.recipients_total, p.recipients_inferred, p.state) == (14, 10, "Approved")
    po = [p for p in engine.state.packages.values() if p.incident_id == olt.incident_id and p.state == "Approved"][0]
    assert po.scheduled_send_at == "2026-10-27 07:00:00"
    assert any(r.check == "quiet hours" and r.status == "hold" for r in po.policy_results)
    # honest abstain on a blank-nap subscriber near scenario 1
    assert any(a["workordernumber"] == engine.truth["abstain_wo"] and a["near_incident"] == s1.incident_id for a in engine.state.abstentions)


# ---- 2. every card has resolvable evidence rows ----------------------------------
def test_every_output_is_grounded(engine):
    ids = set(engine.evidence)
    incidents = set(engine.state.incidents)

    def resolvable(x):
        return x in ids or (x.startswith("SDAL:") and x[5:] in incidents)

    objs = list(engine.state.incidents.values()) + [r for v in engine.state.recs.values() for r in v] + \
        list(engine.state.packages.values()) + engine.state.adoption + engine.state.queue
    assert objs
    for o in objs:
        assert o.evidence_ids, o
        assert all(resolvable(x) for x in o.evidence_ids), [x for x in o.evidence_ids if not resolvable(x)]
    for a in engine.state.abstentions:
        assert a["evidence_ids"] and all(resolvable(x) for x in a["evidence_ids"])


def test_grounding_contract_rejects_ungrounded_output():
    from sdal.models import GroundingError, QueueRow
    with pytest.raises((GroundingError, ValueError)):
        QueueRow(item_id="x", item_type="order", label="x", rank=1, score=0.1, inputs={}, clock_start=None, breach_eta=None,
                 exception_flag=False, ranked_at="2026-10-27 06:00:00", evidence_ids=[])


# ---- 3. below the floor, suppress and hold are unreachable ------------------------
def test_floor_property_on_decision_rules():
    rnd = random.Random(7)
    for _ in range(5000):
        floor = rnd.uniform(0.5, 0.95)
        ev = DispatchEvidence(
            incident_id=rnd.choice([None, "SDAL-1"]), incident_state=rnd.choice(["Proposed", "Confirmed", "Closed"]),
            incident_support=rnd.uniform(0, floor - 1e-6), incident_has_physical=rnd.random() < 0.5,
            incident_crew_or_snow=rnd.random() < 0.5, incident_physical_ids=["GW:x"] if rnd.random() < 0.5 else [],
            incident_closed_recently=rnd.random() < 0.5, line_gateway_healthy=rnd.random() < 0.5,
            signature=rnd.choice(["cpe", "drop", "silent_line", "last_mile", "none"]), handyman_fresh=rnd.random() < 0.5,
            handyman_age_h=rnd.choice([None, 1.0, 12.0]), handyman_stalled=rnd.random() < 0.2,
            line_hold_support=rnd.uniform(0, floor - 1e-6), hold_expired=rnd.random() < 0.2, nap_known=rnd.random() < 0.9)
        assert decide(ev, floor).outcome == "dispatch"


def test_forced_low_support_gives_no_suppress_or_hold(generated):
    from sdal.curated import connect
    e = Engine(con=connect(), cfg_overrides={"dispatch.confidence_floor": 1.01}).run()
    outcomes = {r.outcome for v in e.state.recs.values() for r in v}
    assert outcomes == {"dispatch"}
    assert all(r.floor_applied or r.incident_id is None for v in e.state.recs.values() for r in v)


# ---- 4. feed stall raises an alert within one interval, clears, creates nothing ----
def test_feed_stall(engine):
    fe = [f for f in engine.feed_events if f["source"] == "HANDYMAN"]
    assert fe[0] == {"t": "2026-10-27 06:45:00", "source": "HANDYMAN", "from": "on time", "to": "late"}
    assert any(f["to"] == "stalled" for f in fe) and fe[-1]["to"] == "on time" and fe[-1]["t"] == "2026-10-27 07:00:00"
    paused = [d for d in engine.detector_log if "2026-10-27 06:45" <= d["t"] < "2026-10-27 07:00"]
    assert paused and all(any(p["detector"] == "complaint_burst" for p in d["paused"]) for d in paused)
    created = [i for i in engine.state.incidents.values() if "2026-10-27 06:45" <= i.proposed_at < "2026-10-27 07:00"]
    assert all("complaint_burst" not in i.detectors for i in created)
    # recommendations that depend on Handyman fell back to dispatch during the stall
    s4 = engine.state.recs[engine.truth["s4_wo"]]
    assert any(r.outcome == "dispatch" and "stalled" in r.note and "06:45" <= r.recommended_at[11:16] < "07:00" for r in s4)


# ---- 5. prompt injection in fixdescription changes nothing --------------------------
def test_prompt_injection_is_ignored(engine, db_copy):
    con = duckdb.connect(str(db_copy))
    con.execute("UPDATE c_order_versions SET fixdescription = 'Replaced patchcord at ONT.' WHERE fixdescription = ?", [INJECTION_TEXT])
    clean = Engine(con=con).run()
    key = lambda e: [(r.outcome, r.reason_class, r.support_score, r.incident_id, r.recommended_at) for v in e.state.recs.values() for r in v]
    assert key(clean) == key(engine)
    flagged = [r for r in engine.tracer.runs for n in r["notes"] if n.startswith("UNTRUSTED TEXT IGNORED")]
    assert flagged, "the injection should be visible in the trace as ignored data"
    assert not [r for r in clean.tracer.runs for n in r["notes"] if n.startswith("UNTRUSTED TEXT IGNORED")]


# ---- 6. consent unavailable, send disabled, no code path calls ng1_handoff ----------
def test_no_send_path(engine):
    for p in engine.state.packages.values():
        assert p.state != "Sent"
        assert any(r.check == "consent / opt-out" and r.status == "unavailable" for r in p.policy_results)
        assert "Not sent" in p.send_state
    calls = []
    for f in PKG.rglob("*.py"):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if name == "ng1_handoff":
                    calls.append(f.name)
    assert calls == []
    assert all(c["tool"] != "ng1_handoff" for r in engine.tracer.runs for c in r["tool_calls"])


def test_ng1_handoff_is_disabled(engine):
    from sdal.views import Snapshot
    engine.tracer.start("UC5", "test")
    ctx = engine.ctx(Snapshot(engine.con, engine.static, engine.now, {}))
    with pytest.raises(T.ToolDisabled):
        T.ng1_handoff(ctx, package_id="PKG-001")
    engine.tracer.end()


# ---- registry is the authorisation boundary ------------------------------------------
def test_cross_role_isolation(engine):
    from sdal.views import Snapshot
    ctx = engine.ctx(Snapshot(engine.con, engine.static, engine.now, {}))
    engine.tracer.start("UC2", "isolation test")
    with pytest.raises(T.ToolNotAuthorized):
        T.incident_registry_create(ctx, incident=None)
    with pytest.raises(T.ToolNotAuthorized):
        T.subscriber_resolve(ctx, incident=None)
    engine.tracer.start("UC5", "isolation test")
    with pytest.raises(T.ToolNotAuthorized):
        T.symptom_signature_check(ctx, accountnumber="x", nap=None)
    engine.tracer.end()


# ---- 8. Globe column names match the handoff dictionary --------------------------------
def test_schema_matches_dictionary(generated):
    assert check() == []


# ---- effective-dated topology ------------------------------------------------------------
def test_reparented_nap_keeps_history(engine):
    import pandas as pd
    before = engine.static.topology_at(pd.Timestamp("2026-10-27 07:00"))
    after = engine.static.topology_at(pd.Timestamp("2026-10-27 08:00"))
    assert before.LCP["DAV_204_L006_N07B"] == "DAV_204_L006"
    assert after.LCP["DAV_204_L006_N07B"] == "DAV_204_L005"
