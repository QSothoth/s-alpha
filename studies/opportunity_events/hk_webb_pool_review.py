"""Review approximate-cap candidates against available historical CCASS data."""

import bisect
import csv
import gzip
import json
from collections import defaultdict

from studies.opportunity_events.hk_southbound import accumulation_cadence, outcomes, signal
from studies.opportunity_events.hk_webb_corrected_signals import WORK, issued_history, latest_available
from studies.opportunity_events.hk_webb_pool import ROOT


def main():
    source = json.loads((WORK / "webb-pool.json").read_text())
    stocks = {s["code"]: s for s in json.loads((ROOT / "candidates.json").read_text())["stocks"]}
    component_ids = {i for item in source["issues"].values() for i in item["components"]}
    issued = issued_history(WORK / "issuedshares.sql.gz", component_ids)
    actions = defaultdict(set)
    for path in ("data/trader-data-v2/hk/actions.csv.gz", "data/trader-live/trader-data-v1/hk/actions.csv.gz"):
        with gzip.open(path, "rt", newline="") as file:
            for row in csv.DictReader(file):
                actions[row["code"]].add((row["ex_date"], float(row["factor_a"]), float(row["factor_b"])))
    events, no_signal = [], []
    for issue, item in source["issues"].items():
        stock = stocks[item["code"]]
        daily = source["dailylog"].get(issue, {})
        histories = {}
        for participant in (1323, 1456, 454, 460, 30, 1243):
            rows = source["history"].get(f"{issue}:{participant}", [])
            histories[participant] = ([r[0] for r in rows], [r[1] for r in rows])

        def at(participant, day):
            dates, amounts = histories[participant]
            index = bisect.bisect_right(dates, day) - 1
            return amounts[index] if index >= 0 else 0

        holdings = {}
        for bar in stock["bars"]:
            day = bar[0]
            if day not in daily:
                continue
            south = at(1323, day) + at(1456, day)
            counts = [latest_available(issued[component], day) for component in item["components"]]
            if south and all(counts):
                holdings[day] = (south, south / sum(c[1] for c in counts) * 100, "webb")
        acts = sorted(actions[item["code"]])
        found = None
        for peak in item["peaks"]:
            if peak["peak_date"] > "2025-10-10":
                continue
            found = signal(stock["bars"], holdings, peak["peak_date"], acts)
            if found["index"] is not None:
                start, _, end = found["dates"]
                concentration = []
                for day in (start, end):
                    row = daily[day]
                    named = row[0] + row[4]
                    concentration.append(100 * row[6] / named if named else None)
                groups = {}
                for label, members in {"south": (1323, 1456),
                                       "three_custodians": (454, 460, 30),
                                       "futu": (1243,)}.items():
                    groups[label] = [sum(at(p, day) for p in members) for day in (start, end)]
                events.append({
                    "code": item["code"], "name": item["name"], "issue": issue,
                    "peak": peak, "signal": stock["bars"][found["index"]][0],
                    "south": found, "cadence": accumulation_cadence(stock["bars"], holdings, found["dates"]),
                    "ccass_top5_pct": concentration, "group_holdings": groups,
                    "outcome120": outcomes(stock["bars"], found["index"], 120, acts),
                })
                break
        if found is None or found["index"] is None:
            no_signal.append({"code": item["code"], "name": item["name"],
                              "ccass_days": len(daily), "missing_eligible_days": found["missing"] if found else None})
    result = {"events": sorted(events, key=lambda x: x["signal"]), "no_signal": no_signal,
              "unmapped": source["unmapped"], "coverage_end": "2025-10-10"}
    (WORK / "webb-pool-events.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    for e in result["events"]:
        outcome = e["outcome120"]["end_return"]
        print(e["code"], e["name"], e["signal"],
              "south", [round(r, 2) for r in e["south"]["ratios"]],
              "120d", round(outcome * 100, 1) if outcome is not None else None)
    print("events", len(events), "no_signal", len(no_signal), "unmapped", len(source["unmapped"]))


if __name__ == "__main__":
    main()
