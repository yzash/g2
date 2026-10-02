"""Point-in-time reads of the curated layer.

A Snapshot is the curated layer as it stood at `now`: only rows whose
`_arrived_at` is at or before `now` are visible. Tools read through a
Snapshot, so an agent can never see a row before its feed delivered it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import cached_property

import duckdb
import pandas as pd

OPEN_STATUSES = ("Open", "Unassigned", "Pending", "Delayed", "Ongoing")


class Static:
    """Reference data that does not change inside the demo day."""

    def __init__(self, con: duckdb.DuckDBPyConnection):
        self.con = con
        self.lines = con.execute("SELECT * FROM c_lines").fetchdf()
        self.geo = con.execute("SELECT * FROM ref_nap_geo").fetchdf()
        self.topology_all = con.execute("SELECT * FROM c_topology").fetchdf()
        self.restoration = con.execute("SELECT * FROM c_restoration").fetchdf()
        self.mac_to_line = self.lines.set_index("mac")
        self.acct_to_line = self.lines.set_index("account_no")
        self.svc_to_line = self.lines.set_index("service_id")
        self.nap_geo = self.geo.set_index("NAP")

    def topology_at(self, t: datetime) -> pd.DataFrame:
        tp = self.topology_all
        return tp[(tp.valid_from <= t) & (tp.valid_to > t)].set_index("NAP")


class Snapshot:
    drop_db = 6.0

    def __init__(self, con: duckdb.DuckDBPyConnection, static: Static, now: datetime, cache: dict):
        self.con = con
        self.static = static
        self.now = now
        self._cache = cache

    # -- topology -------------------------------------------------------------
    @cached_property
    def topology(self) -> pd.DataFrame:
        return self.static.topology_at(self.now)

    def lcp_of(self, nap: str, at: datetime | None = None) -> str | None:
        tp = self.topology if at is None else self.static.topology_at(at)
        return tp.LCP.get(nap)

    def olt_of(self, nap: str) -> str | None:
        return self.topology.OLT.get(nap)

    @cached_property
    def _children(self) -> dict:
        tp = self.topology
        out = {}
        for nap, lcp, olt in zip(tp.index, tp.LCP, tp.OLT):
            out.setdefault(("LCP", lcp), []).append(nap)
            out.setdefault(("OLT", olt), []).append(nap)
        return {k: sorted(v) for k, v in out.items()}

    def naps_under(self, element_type: str, element_id: str) -> list[str]:
        if element_type == "NAP":
            return [element_id]
        return list(self._children.get((element_type, element_id), []))

    def chain(self, nap: str) -> list[tuple[str, str]]:
        return [("NAP", nap), ("LCP", self.topology.LCP[nap]), ("OLT", self.topology.OLT[nap])]

    # -- FSM --------------------------------------------------------------------
    @cached_property
    def orders(self) -> pd.DataFrame:
        key = ("orders", self.now)
        if key not in self._cache:
            self._cache[key] = self.con.execute("""
                SELECT * EXCLUDE (_arrived_at), _arrived_at FROM c_order_versions WHERE _arrived_at <= ?
                QUALIFY row_number() OVER (PARTITION BY workordernumber ORDER BY lastupdatedate DESC) = 1
            """, [self.now]).fetchdf()
        return self._cache[key]

    @cached_property
    def open_repairs(self) -> pd.DataFrame:
        o = self.orders
        return o[(o.skillset == "Repair") & (o.status.isin(OPEN_STATUSES))]

    # -- SNOW -------------------------------------------------------------------
    @cached_property
    def snow(self) -> pd.DataFrame:
        return self.con.execute("""
            SELECT * FROM c_snow_versions WHERE _arrived_at <= ?
            QUALIFY row_number() OVER (PARTITION BY inc_number, affected_nap ORDER BY latest_extract_datetime DESC) = 1
        """, [self.now]).fetchdf()

    @cached_property
    def open_snow(self) -> pd.DataFrame:
        s = self.snow
        return s[s.inc_state.isin(["New", "In Progress", "On Hold"])]

    # -- Handyman ---------------------------------------------------------------
    @cached_property
    def handyman(self) -> pd.DataFrame:
        h = self.con.execute("SELECT * FROM c_handyman WHERE _arrived_at <= ?", [self.now]).fetchdf()
        lines = self.static.acct_to_line
        h["nap"] = h.account_number.map(lines.nap)
        h["mac"] = h.account_number.map(lines.mac)
        return h

    # -- Alarms -----------------------------------------------------------------
    @cached_property
    def alarms_open(self) -> pd.DataFrame:
        return self.con.execute("""
            SELECT * FROM c_alarms WHERE _arrived_at <= ? AND (cleared IS NULL OR _cleared_arrived_at > ?)
        """, [self.now, self.now]).fetchdf()

    # -- WMS --------------------------------------------------------------------
    @cached_property
    def wms_horizon(self) -> datetime | None:
        r = self.con.execute("SELECT max(report_time) FROM c_telemetry WHERE _arrived_at <= ?", [self.now]).fetchone()[0]
        return r

    @cached_property
    def gateways(self) -> pd.DataFrame:
        """Per-gateway latest reading, 24-hour baseline and reporting state at the WMS horizon."""
        h = self.wms_horizon
        key = ("gw", h)
        if key in self._cache:
            return self._cache[key]
        df = self.con.execute("""
            WITH a AS (
                SELECT mac, report_time, rx_dbm FROM c_telemetry
                WHERE _arrived_at <= ? AND report_time > ?::TIMESTAMP - INTERVAL 24 HOUR
            ),
            base AS (SELECT mac, median(rx_dbm) AS baseline_dbm, count(*) AS n_base
                     FROM a WHERE report_time <= ?::TIMESTAMP - INTERVAL 60 MINUTE GROUP BY mac),
            lat AS (SELECT mac, arg_max(rx_dbm, report_time) AS rx_latest_dbm, max(report_time) AS last_seen,
                           count(*) FILTER (WHERE report_time > ?::TIMESTAMP - INTERVAL 10 MINUTE) AS n_last2
                    FROM a GROUP BY mac)
            SELECT l.mac, l.nap, l.account_no, base.baseline_dbm, base.n_base, lat.rx_latest_dbm, lat.last_seen,
                   coalesce(lat.n_last2, 0) AS n_last2
            FROM c_lines l LEFT JOIN base USING (mac) LEFT JOIN lat USING (mac)
        """, [self.now, h, h, h]).fetchdf()
        df["known"] = df.n_base.fillna(0) > 0
        df["fresh"] = df.last_seen.notna() & (df.last_seen > pd.Timestamp(h) - pd.Timedelta(minutes=15))
        df["silent2"] = df.known & (df.n_last2 == 0)
        df["drop_db"] = df.baseline_dbm - df.rx_latest_dbm
        df["dropped"] = df.fresh & (df.drop_db > self.drop_db)
        self._cache[key] = df
        return df

    @cached_property
    def nap_stats(self) -> pd.DataFrame:
        g = self.gateways[self.gateways.nap.notna()]
        st = g.groupby("nap").agg(
            n_gw=("mac", "count"), n_known=("known", "sum"), n_fresh=("fresh", "sum"),
            n_drop=("dropped", "sum"), n_silent=("silent2", "sum"),
            rx_median=("rx_latest_dbm", "median"), baseline_median=("baseline_dbm", "median"),
        )
        st["optical_share"] = (st.n_drop / st.n_fresh.where(st.n_fresh > 0)).fillna(0.0)
        st["reach_share"] = (st.n_silent / st.n_known.where(st.n_known > 0)).fillna(0.0)
        return st

    @cached_property
    def _level_stats(self) -> dict:
        cols = ["n_gw", "n_known", "n_fresh", "n_drop", "n_silent"]
        st = self.nap_stats[cols].reindex(self.topology.index).fillna(0).join(self.topology[["LCP", "OLT"]])
        out = {}
        for nap, r in zip(st.index, st[cols].itertuples(index=False)):
            out[("NAP", nap)] = tuple(r)
        for lvl in ("LCP", "OLT"):
            for k, r in zip(*[st.groupby(lvl)[cols].sum().index, st.groupby(lvl)[cols].sum().itertuples(index=False)]):
                out[(lvl, k)] = tuple(r)
        return out

    def element_stats(self, element_type: str, element_id: str) -> dict:
        key = (element_type, element_id)
        n_gw, n_known, n_fresh, n_drop, n_silent = self._level_stats.get(key, (0, 0, 0, 0, 0))
        return {
            "naps": self.naps_under(element_type, element_id),
            "n_gw": int(n_gw),
            "optical_share": float(n_drop / n_fresh) if n_fresh else 0.0,
            "reach_share": float(n_silent / n_known) if n_known else 0.0,
            "n_drop": int(n_drop), "n_silent": int(n_silent),
        }

    def lines_on(self, element_type: str, element_id: str) -> pd.DataFrame:
        naps = self.naps_under(element_type, element_id) if element_type != "LINE" else []
        if element_type == "LINE":
            return self.static.lines[self.static.lines.service_id == element_id]
        return self.static.lines[self.static.lines.nap.isin(naps)]

    def window(self, minutes: int) -> datetime:
        return self.now - timedelta(minutes=minutes)
