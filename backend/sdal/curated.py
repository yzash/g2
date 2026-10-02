"""Curated layer on DuckDB.

Loads the generated files exactly as Globe delivers them, keeps Globe's column
names, applies unit conversion (Rx raw x 0.0001 mW, then dBm), and stamps every
row with `_arrived_at` from the feed arrival model so that no tool can read a
row before its source would have delivered it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import duckdb

from . import DB_PATH, RAW_DIR
from .config import load_config, ts


def ceil_to(t: datetime, minutes: int) -> datetime:
    base = t.replace(second=0, microsecond=0)
    if t.second or t.microsecond:
        base += timedelta(minutes=1)
    r = base.minute % minutes
    return base if r == 0 else base + timedelta(minutes=minutes - r)


class FeedModel:
    """Expected-arrival model per source, including the seeded Handyman stall."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.feeds = cfg["feeds"]
        self.stalls = [(s["source"], ts(s["from"]), ts(s["to"])) for s in cfg.get("feed_stalls", [])]

    def slots(self, source: str, start: datetime, end: datetime) -> list[datetime]:
        f = self.feeds[source]
        out = []
        if source == "WMS":
            t = start.replace(minute=0, second=0) - timedelta(hours=1)
            while t <= end:
                for m in (10, 40):
                    s = t.replace(minute=m)
                    if start <= s <= end:
                        out.append(s)
                t += timedelta(hours=1)
            return sorted(out)
        step = f["cadence_min"]
        t = ceil_to(start, step)
        while t <= end:
            out.append(t)
            t += timedelta(minutes=step)
        return out

    def delivered(self, source: str, slot: datetime) -> bool:
        return not any(src == source and a < slot < b for src, a, b in self.stalls)

    def arrival_for(self, source: str, event_time: datetime) -> datetime:
        """First delivered slot at or after the row's event time (WMS: batch landing)."""
        if source == "WMS":
            f = self.feeds["WMS"]
            win = f["batch_window_min"]
            start = event_time.replace(minute=(event_time.minute // win) * win, second=0, microsecond=0)
            return start + timedelta(minutes=win + f["landing_lag_min"])
        t = ceil_to(event_time, self.feeds[source]["cadence_min"])
        while not self.delivered(source, t):
            t += timedelta(minutes=self.feeds[source]["cadence_min"])
        return t

    def health(self, source: str, now: datetime) -> dict:
        """Last arrival, lag and status at `now` (on time / late / stalled)."""
        window_start = now - timedelta(hours=3)
        slots = self.slots(source, window_start, now)
        if not slots:
            return {"source": source, "status": "on time", "last_arrival": None, "expected": None, "lag_min": 0, "missed": 0}
        expected = slots[-1]
        delivered = [s for s in slots if self.delivered(source, s)]
        last = delivered[-1] if delivered else None
        missed = sum(1 for s in slots if last is None or s > last)
        status = "on time" if missed == 0 else ("late" if missed == 1 else "stalled")
        lag = int((now - last).total_seconds() // 60) if last else None
        return {"source": source, "label": self.feeds[source]["label"], "status": status,
                "last_arrival": last.strftime("%Y-%m-%d %H:%M:%S") if last else None,
                "expected": expected.strftime("%Y-%m-%d %H:%M:%S"), "lag_min": lag, "missed": missed,
                "cadence_min": self.feeds[source]["cadence_min"]}


def build_curated(db_path=DB_PATH, raw=RAW_DIR) -> duckdb.DuckDBPyConnection:
    cfg = load_config()
    feeds = FeedModel(cfg)
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))

    def csv(name):
        return f"read_csv_auto('{raw / name}', header=true, all_varchar=false, sample_size=-1)"

    # ---- raw landing tables (Globe column names untouched) --------------------
    con.execute(f"CREATE TABLE raw_owfm_all_status AS SELECT * FROM {csv('owfm_all_status_20261027.csv')}")
    con.execute(f"CREATE TABLE raw_snow_outage_nap AS SELECT * FROM {csv('snow_outage_nap_20261027.csv')}")
    con.execute(f"CREATE TABLE raw_handyman AS SELECT * FROM {csv('handyman_diagnostic_log_20261027.csv')}")
    con.execute(f"CREATE TABLE raw_alarms AS SELECT * FROM {csv('nms_alarm_sample.csv')}")
    con.execute(f"CREATE TABLE raw_postpaid AS SELECT * FROM {csv('postpaid_base.csv')}")
    con.execute(f"CREATE TABLE raw_prepaid AS SELECT * FROM {csv('prepaid_base.csv')}")
    con.execute(f"CREATE TABLE raw_prod AS SELECT * FROM {csv('prod_id_mapping.csv')}")
    con.execute(f"CREATE TABLE raw_vip AS SELECT * FROM {csv('synthetic_vip_b2b_flag.csv')}")
    con.execute(f"CREATE TABLE raw_wms_keys AS SELECT * FROM {csv('wms_subscriber_keys.csv')}")
    con.execute(f"CREATE TABLE raw_restoration AS SELECT * FROM {csv('seeded_outage_restoration_target.csv')}")
    con.execute(f"CREATE TABLE ref_nap_geo AS SELECT * FROM {csv('ref_nap_geography.csv')}")
    con.execute(f"CREATE TABLE raw_telemetry AS SELECT * FROM read_parquet('{raw / 'wms_gateway_telemetry_20261027.parquet'}')")
    con.execute(f"CREATE TABLE raw_master_0000 AS SELECT * FROM {csv('master_olt_lcp_nap_20261027T0000.csv')}")
    con.execute(f"CREATE TABLE raw_master_0730 AS SELECT * FROM {csv('master_olt_lcp_nap_20261027T0730.csv')}")

    # ---- arrival stamps from the feed model ------------------------------------
    def stamp(table: str, source: str, time_col: str):
        rows = con.execute(f'SELECT DISTINCT "{time_col}" FROM {table} WHERE "{time_col}" IS NOT NULL').fetchall()
        m = [(r[0], feeds.arrival_for(source, r[0] if isinstance(r[0], datetime) else ts(str(r[0])))) for r in rows]
        con.execute(f"CREATE TEMP TABLE _arr_{table} (k TIMESTAMP, a TIMESTAMP)")
        con.executemany(f"INSERT INTO _arr_{table} VALUES (?, ?)", m)
        return f"_arr_{table}"

    a = stamp("raw_owfm_all_status", "FSM", "lastupdatedate")
    con.execute(f"""CREATE TABLE c_order_versions AS
        SELECT o.*, x.a AS _arrived_at FROM raw_owfm_all_status o JOIN {a} x ON o.lastupdatedate = x.k""")
    con.execute("""CREATE TABLE c_snow_versions AS
        SELECT *, latest_extract_datetime AS _arrived_at FROM raw_snow_outage_nap""")
    a = stamp("raw_handyman", "HANDYMAN", "date_time")
    con.execute(f"""CREATE TABLE c_handyman AS SELECT h.*, x.a AS _arrived_at FROM raw_handyman h JOIN {a} x ON h.date_time = x.k""")
    con.execute("""CREATE TABLE c_alarms AS SELECT *,
        CAST(time_bucket(INTERVAL 5 MINUTE, raised + INTERVAL 299 SECOND) AS TIMESTAMP) AS _arrived_at,
        CAST(time_bucket(INTERVAL 5 MINUTE, cleared + INTERVAL 299 SECOND) AS TIMESTAMP) AS _cleared_arrived_at FROM raw_alarms""")

    win = cfg["feeds"]["WMS"]["batch_window_min"]
    lag = cfg["feeds"]["WMS"]["landing_lag_min"]
    con.execute(f"""CREATE TABLE c_telemetry AS SELECT
            "Gateway MAC Address" AS mac,
            "Report Time" AS report_time,
            "Rx Optical Power" AS rx_raw,
            10 * log10("Rx Optical Power" * 0.0001) AS rx_dbm,
            10 * log10("Tx Optical Power" * 0.0001) AS tx_dbm,
            "Optical Module Bias Current" * 0.002 AS bias_ma,
            "Voltage" * 0.0001 AS voltage_v,
            "Temperature" / 256.0 AS temperature_c,
            "Subnet Name Path" AS subnet_path,
            time_bucket(INTERVAL {win} MINUTE, "Report Time") + INTERVAL {win + lag} MINUTE AS _arrived_at
        FROM raw_telemetry""")
    con.execute("CREATE INDEX idx_tel ON c_telemetry(mac, report_time)")

    # ---- effective-dated topology ------------------------------------------------
    re_at = ts("2026-10-27T07:30:00")
    con.execute("""CREATE TABLE c_topology AS
        SELECT a.NAP, a.LCP, a.OLT, TIMESTAMP '2025-03-01 00:00:00' AS valid_from,
               CASE WHEN a.LCP <> b.LCP THEN ?::TIMESTAMP ELSE TIMESTAMP '2099-01-01 00:00:00' END AS valid_to,
               a.GRID_ID
        FROM raw_master_0000 a JOIN raw_master_0730 b USING (NAP)
        UNION ALL
        SELECT b.NAP, b.LCP, b.OLT, ?::TIMESTAMP, TIMESTAMP '2099-01-01 00:00:00', b.GRID_ID
        FROM raw_master_0000 a JOIN raw_master_0730 b USING (NAP) WHERE a.LCP <> b.LCP""", [re_at, re_at])

    # ---- subscribers (pseudonymised; no contact fields exist) -----------------
    con.execute("""CREATE TABLE c_subscribers AS
        SELECT s.*, 'postpaid' AS base FROM raw_postpaid s UNION ALL SELECT s.*, 'prepaid' FROM raw_prepaid s""")
    con.execute("""CREATE TABLE c_lines AS
        SELECT s.subscriber_id, s.service_id, s.account_no, s.prod_id, s.prod_desc, s.base, s.nap,
               p.msf, v.vip_b2b_flag AS vip,
               k."Gateway MAC Address" AS mac, k."Gateway SN" AS sn, k."Territory Code" AS territory,
               k."Town Name" AS town, k."Barangay PSGC" AS psgc,
               split_part(k."Gateway MAC Address", ':', 1) AS _x
        FROM c_subscribers s
        JOIN raw_prod p USING (prod_id)
        JOIN raw_vip v USING (subscriber_id)
        JOIN raw_wms_keys k ON k."Account Number" = s.account_no""")
    con.execute("""CREATE TABLE c_restoration AS SELECT *, published_at AS _arrived_at FROM raw_restoration""")
    return con


def connect(db_path=DB_PATH) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path), read_only=False)
