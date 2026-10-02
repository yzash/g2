"""Append-only trace: every agent run logs its trigger, tool calls with
parameters, evidence returned, outputs and the human decision that followed."""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd


def _jsonable(v, depth=0):
    if depth > 3:
        return str(v)[:120]
    if hasattr(v, "model_dump"):
        d = v.model_dump()
        return {k: d[k] for k in list(d)[:6]} if depth else {"id": d.get("incident_id") or d.get("rec_id") or d.get("package_id")}
    if isinstance(v, dict):
        return {str(k): _jsonable(x, depth + 1) for k, x in list(v.items())[:12]}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x, depth + 1) for x in list(v)[:12]] + ([f"... {len(v) - 12} more"] if len(v) > 12 else [])
    if isinstance(v, (pd.Timestamp, datetime)):
        return pd.Timestamp(v).strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, (str, int, bool)) or v is None:
        return v
    return str(v)[:120]


class Tracer:
    def __init__(self):
        self.runs: list[dict] = []
        self.current: dict | None = None
        self.current_agent: str | None = None
        self._seq = 0
        self._call_seq = 0
        self._last_call: str | None = None
        self.now: datetime | None = None

    def start(self, agent: str, trigger: str, inputs: dict | None = None) -> str:
        self._seq += 1
        run_id = f"RUN-{self._seq:05d}"
        self.current = {"run_id": run_id, "agent": agent, "trigger": trigger, "at": self.now.strftime("%Y-%m-%d %H:%M:%S"),
                        "inputs": _jsonable(inputs or {}), "tool_calls": [], "outputs": [], "notes": []}
        self.current_agent = agent
        return run_id

    def current_call_id(self) -> str | None:
        return self._last_call

    def begin_call(self) -> str:
        self._call_seq += 1
        self._last_call = f"CALL-{self._call_seq:06d}"
        return self._last_call

    def record(self, tool: str, params: dict, result) -> None:
        call_id = self._last_call
        if self.current is None:
            return
        self.current["tool_calls"].append({
            "call_id": call_id, "tool": tool, "params": _jsonable({k: v for k, v in params.items() if k not in ("ctx",)}),
            "summary": result.summary, "evidence_ids": result.evidence_ids[:40], "n_evidence": len(result.evidence_ids),
            "flags": result.flags,
        })

    def refused(self, tool: str, agent: str, params: dict) -> None:
        if self.current is not None:
            self.current["notes"].append(f"REFUSED: {agent} attempted {tool}; not in the registry for this agent")

    def note(self, text: str) -> None:
        if self.current is not None:
            self.current["notes"].append(text)

    def output(self, kind: str, ref: str) -> None:
        if self.current is not None:
            self.current["outputs"].append({"kind": kind, "ref": ref})

    def end(self) -> dict | None:
        run = self.current
        if run is not None and (run["tool_calls"] or run["outputs"] or run["notes"]):
            self.runs.append(run)
        self.current = None
        self.current_agent = None
        return run

    def dump(self, path) -> None:
        with open(path, "w") as f:
            for r in self.runs:
                f.write(json.dumps(r, default=str) + "\n")
