"""SDAL Control Tower MVP demo engine.

Synthetic rows on Globe's schemas, deterministic detectors, a registered tool
boundary, four agents with code-enforced guardrails, and a replay engine that
emits the bundle the operator surface plays back.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "sdal_config.json"
DICTIONARY_PATH = ROOT / "dictionaries" / "globe_handoff_columns.json"
RAW_DIR = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "sdal_curated.duckdb"
BUNDLE_PATH = ROOT / "web" / "public" / "bundle.json"
TRACE_PATH = ROOT / "data" / "trace.jsonl"
