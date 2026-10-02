"""Acceptance criterion 8: the generated files carry Globe's column names exactly.

Diffs the header of every generated Globe-shaped file against the handoff
dictionary (dictionaries/globe_handoff_columns.json) and checks the value
vocabularies the dictionary lists.
"""

from __future__ import annotations

import json

import pandas as pd

from . import DICTIONARY_PATH, RAW_DIR

FILES = {
    "fsm_repair_workorders": "owfm_all_status_20261027.csv",
    "snow_outage_nap": "snow_outage_nap_20261027.csv",
    "master_olt_lcp_nap": "master_olt_lcp_nap_20261027T0000.csv",
    "postpaid_base": "postpaid_base.csv",
    "prepaid_base": "prepaid_base.csv",
    "prod_id_mapping": "prod_id_mapping.csv",
    "wms_gateway_telemetry": "wms_gateway_telemetry_20261027.parquet",
    "wms_subscriber_keys": "wms_subscriber_keys.csv",
    "handyman_diagnostic_log": "handyman_diagnostic_log_20261027.csv",
    "nms_alarm_sample": "nms_alarm_sample.csv",
    "outage_reason_mapping": "outage_reason_mapping.csv",
    "repair_segment_mapping": "repair_segment_mapping.csv",
    "repair_cohort_mapping": "repair_cohort_mapping.csv",
}


def check(raw=RAW_DIR) -> list[str]:
    spec = json.load(open(DICTIONARY_PATH))["tables"]
    problems = []
    for table, fname in FILES.items():
        path = raw / fname
        df = pd.read_parquet(path) if fname.endswith(".parquet") else pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])
        want, got = spec[table]["columns"], list(df.columns)
        if want != got:
            missing = [c for c in want if c not in got]
            extra = [c for c in got if c not in want]
            problems.append(f"{table}: columns differ (missing {missing}, extra {extra}, order {'same' if not missing and not extra else 'n/a'})")
        for col, vocab in spec[table].get("vocab", {}).items():
            allowed = {v for v in vocab if v is not None}
            vals = set(df[col].dropna().unique()) if col in df else set()
            bad = vals - allowed
            if bad:
                problems.append(f"{table}.{col}: values outside the dictionary vocabulary: {sorted(bad)[:5]}")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("SCHEMA DIFF FAILED")
        for p in problems:
            print("  -", p)
        return 1
    print(f"Schema diff OK: {len(FILES)} generated files match the handoff dictionary column names and vocabularies.")
    return 0
