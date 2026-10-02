"""python -m sdal [generate|curate|run|bundle|check-schema|all]"""

import sys
import time


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "all"
    t0 = time.time()
    if cmd in ("generate", "all"):
        from .generator import generate
        s = generate()
        print(f"generated: {s['naps']} NAPs, {s['subscribers']} subscribers, {s['telemetry_rows']:,} telemetry rows, "
              f"{s['orders']} orders, {s['handyman_rows']} Handyman rows, {s['snow_rows']} SNOW rows")
    if cmd in ("check-schema", "all"):
        from .check_schema import main as check
        if check():
            return 1
    if cmd in ("curate", "all"):
        from .curated import build_curated
        build_curated().close()
        print("curated layer built (DuckDB)")
    if cmd in ("run", "bundle", "all"):
        from .bundle import build_bundle
        from .curated import connect
        from .engine import Engine
        from . import BUNDLE_PATH
        e = Engine(con=connect()).run()
        b = build_bundle(e)
        m = b["meta"]["summary"]
        print(f"engine: {m['incidents']} incidents, {m['merges']} merges, {m['recommendations']} recommendations, "
              f"{m['trace_runs']} agent runs, {m['tool_calls']} tool calls, {m['evidence_rows']} evidence rows, "
              f"safety-critical {len(m['safety_critical'])}")
        print(f"bundle: {BUNDLE_PATH} ({BUNDLE_PATH.stat().st_size / 1e6:.1f} MB)")
    print(f"done in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
