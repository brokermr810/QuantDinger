"""Import point-in-time fundamental snapshots from a UTF-8 CSV file."""

from __future__ import annotations

import argparse
import csv

from app.services.fundamental_data import FUNDAMENTAL_FIELDS, FundamentalDataService


def _number(value):
    text = str(value or "").strip()
    return float(text) if text else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_file")
    parser.add_argument("--source", default="manual_csv")
    parser.add_argument("--source-version", default="")
    args = parser.parse_args()
    imported = 0
    with open(args.csv_file, "r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            payload = dict(row)
            payload.update({field: _number(row.get(field)) for field in FUNDAMENTAL_FIELDS})
            payload["source"] = args.source
            payload["source_version"] = args.source_version
            FundamentalDataService.upsert(payload)
            imported += 1
    print(f"imported={imported}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
