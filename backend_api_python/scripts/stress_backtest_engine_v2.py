from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.helpers.backtest_stress_cases import heavy_stress_scenarios, run_scenario


def main() -> int:
    parser = argparse.ArgumentParser(description="Run QuantDinger backtest engine v2 stress scenarios.")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args()

    rows = []
    for scenario in heavy_stress_scenarios():
        summary = run_scenario(scenario)
        summary["passSeconds"] = summary["seconds"] <= scenario.max_seconds
        rows.append(summary)

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            print(
                f"{row['name']}: bars={row['bars']} seconds={row['seconds']} "
                f"orders={row['orders']} fills={row['fills']} trades={row['trades']} "
                f"return={row['returnPct']}% maxDD={row['maxDrawdownPct']}% "
                f"intrabar={row['intrabarMode']} passSeconds={row['passSeconds']}"
            )

    return 0 if all(row["passSeconds"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
