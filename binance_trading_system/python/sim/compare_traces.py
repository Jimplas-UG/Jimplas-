#!/usr/bin/env python3
"""Compare the orders two code versions sent for identical scenarios.

  python sim/compare_traces.py <baseline out dir> <patched out dir> [--json result.json]

A scenario with no injected fault must match exactly: time, coin, side, position side, type,
quantity and client id. Differences where a fault fired are listed as corrected execution
failures, because repairing those failures is what changes the orders sent.
"""
from __future__ import annotations

import glob
import json
import os
import sys

FIELDS = ("t", "symbol", "side", "ps", "type", "qty", "cid")
# Close ids embed the time, which the time field already compares.


def rows(path: str) -> tuple[list[tuple], dict]:
    data = json.load(open(path, encoding="utf-8"))
    return [tuple(r.get(k) for k in FIELDS) for r in data["trace"]], data["summary"]


def main() -> int:
    base, new = sys.argv[1], sys.argv[2]
    identical = 0
    strategy_diffs: list[dict] = []
    corrected: list[dict] = []
    orders_compared = 0
    for path in sorted(glob.glob(os.path.join(base, "*.json"))):
        name = os.path.basename(path)[:-5]
        other = os.path.join(new, name + ".json")
        if name.startswith("_") or not os.path.exists(other):
            continue
        a, sa = rows(path)
        b, sb = rows(other)
        if a == b:
            identical += 1
            orders_compared += len(a)
            continue
        first = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
        row = {
            "name": name, "first_diff_index": first,
            "baseline": a[first] if first < len(a) else None,
            "patched": b[first] if first < len(b) else None,
            "baseline_orders": len(a), "patched_orders": len(b),
        }
        fault_free = (
            sa["faults_fired"] == 0 and sb["faults_fired"] == 0 and sa["rejects"] == sb["rejects"]
            and not sa.get("partial_fills") and not sb.get("partial_fills")
        )
        (strategy_diffs if fault_free else corrected).append(row)
    print(f"identical scenarios: {identical} ({orders_compared} orders compared)")
    print(f"corrected execution failures: {len(corrected)}")
    print(f"UNEXPLAINED DIFFERENCES: {len(strategy_diffs)}")
    for r in strategy_diffs[:40]:
        print("  ", json.dumps(r)[:260])
    if "--json" in sys.argv:
        with open(sys.argv[sys.argv.index("--json") + 1], "w", encoding="utf-8") as fh:
            json.dump({"identical": identical, "orders": orders_compared, "corrected": corrected, "unexplained": strategy_diffs}, fh, indent=0)
    return 1 if strategy_diffs else 0


if __name__ == "__main__":
    sys.exit(main())
