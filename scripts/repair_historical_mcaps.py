"""Repair archived valuations from exact-session J-Quants responses.

No current-price fallback and no reconstruction of historical rankings. The
original selection, factors and price data are preserved; revisions are audited.
"""
import argparse
from copy import deepcopy
from datetime import date
import json
import math
from pathlib import Path

LEGACY_FIELDS = ("mcap_flag", "shoutfy_jq", "cur_end", "corr",
                 "shares_kabutan", "mcap_kabutan_oku")


def repair(data, valuations, revised_on):
    day = data["session_date"]
    date.fromisoformat(day)
    date.fromisoformat(revised_on)
    lookup = {}
    for record in valuations:
        if record.get("Date") != day:
            raise ValueError(f"valuation date differs from {day}")
        code = record["Code"]
        if code in lookup:
            raise ValueError(f"duplicate valuation: {code}")
        lookup[code] = record.get("MktCap")
    if not lookup:
        raise ValueError(f"no valuations for {day}")
    result = deepcopy(data)
    audit = []
    for group in ("rows", "dropped_mcap", "dropped_turnover"):
        for row in result.get(group, []):
            if "mcap_oku" not in row:
                continue
            value = lookup.get(row["code"] + "0")
            if value is not None and (not math.isfinite(float(value)) or float(value) <= 0):
                raise ValueError(f"invalid valuation: {day} {row['code']}")
            # Same conversion as the daily pipeline (million yen -> oku).
            new = None if value is None else round(round(float(value) / 100, 1))
            old = {key: row[key] for key in ("mcap_oku", "mcap_source", *LEGACY_FIELDS)
                   if key in row}
            for key in LEGACY_FIELDS:
                row.pop(key, None)
            row.update(mcap_oku=new, mcap_source="jquants" if new is not None else "unavailable")
            audit.append({"session_date": day, "group": group, "code": row["code"],
                          "before": old, "mktcap_million_yen": value,
                          "after_mcap_oku": new})
    result.setdefault("criteria", {})["mcap_method"] = "jquants_valuation"
    result["mcap_revision"] = {"revised_on": revised_on,
                               "valuation_date": day,
                               "original_selection_preserved": True}
    return result, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("docs/data"))
    parser.add_argument("--valuation-dir", type=Path, required=True)
    parser.add_argument("--revised-on", required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    pending, audit = [], []
    # Validate every archive before making any changes.
    for path in sorted(args.data_dir.glob("????-??-??.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        values = json.loads((args.valuation_dir / path.name).read_text(encoding="utf-8"))
        fixed, entries = repair(data, values, args.revised_on)
        pending.append((path, fixed))
        audit.extend(entries)
    if not pending:
        raise ValueError("no archives found")
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.write:
        for path, fixed in pending:
            path.write_text(json.dumps(fixed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{'Repaired' if args.write else 'Validated'} {len(pending)} archives, {len(audit)} valuations")


if __name__ == "__main__":
    main()
