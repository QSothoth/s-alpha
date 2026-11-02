"""Re-evaluate six cases with historical CCASS and available share counts."""

import bisect
import csv
import gzip
import json
import re
from collections import defaultdict
from pathlib import Path

from studies.opportunity_events.hk_southbound import accumulation_cadence, outcomes, signal
from studies.opportunity_events.hk_southbound_dimensions import official_count


ROOT = Path("data/hk-southbound-20261101")
WORK = ROOT / "multidimensional"
ISSUED_COMPONENTS = {
    30520: (30520, 30758),  # Kuaishou: class B plus class A
    33377: (33377,),        # China Tourism Group: H shares
    24979: (24979,),        # WuXi Biologics: ordinary shares
    3606: (3606,),          # Ping An: H shares
    26823: (26823, 26824),  # Meituan: class B plus class A
    11742: (11742,),        # Alibaba: ordinary shares
}
SHORT_ENDPOINTS = {
    "HK.01024": ("2021-11-05", "2021-12-31"),
    "HK.01880": ("2023-11-17", "2024-01-12"),
    "HK.02269": ("2022-01-21", "2022-03-18"),
    "HK.02318": ("2024-10-18", "2024-12-13"),
    "HK.03690": ("2021-12-31", "2022-02-25"),
    "HK.09988": ("2025-03-07", "2025-05-02"),
}


def issued_history(path, ids=None):
    if ids is None:
        ids = {v for components in ISSUED_COMPONENTS.values() for v in components}
    alternatives = b"|".join(str(v).encode() for v in sorted(ids))
    pattern = re.compile(rb"\((" + alternatives + rb"),'(\d{4}-\d\d-\d\d)',"
                         rb"([0-9.eE+-]+),'([^']+)',\d+\)")
    result = defaultdict(list)
    tail = b""
    with gzip.open(path, "rb") as file:
        while True:
            block = file.read(1024 * 1024)
            data = tail + block
            cutoff = max(0, len(data) - 256) if block else len(data)
            for match in pattern.finditer(data):
                if match.start() >= cutoff:
                    break
                issue, date, amount, modified = match.groups()
                result[int(issue)].append((date.decode(), float(amount), modified.decode()))
            tail = data[cutoff:]
            if not block:
                break
    return result


def latest_available(rows, day):
    candidates = [r for r in rows if r[0] <= day and r[2][:10] <= day]
    return max(candidates, key=lambda r: r[0]) if candidates else None


def main():
    archive = json.loads((WORK / "webb-snapshots.json").read_text())
    stocks = {s["code"]: s for s in json.loads((ROOT / "candidates.json").read_text())["stocks"]}
    events = {e["code"]: e for e in json.loads((ROOT / "current-signals.json").read_text())["events"]}
    issued = issued_history(WORK / "issuedshares.sql.gz")
    actions = defaultdict(set)
    for path in (Path("data/trader-data-v2/hk/actions.csv.gz"),
                 Path("data/trader-live/trader-data-v1/hk/actions.csv.gz")):
        with gzip.open(path, "rt", newline="") as file:
            for row in csv.DictReader(file):
                actions[row["code"]].add((row["ex_date"], float(row["factor_a"]), float(row["factor_b"])))
    result = []
    for issue, components in ISSUED_COMPONENTS.items():
        code = archive["issues"][str(issue)][0]
        stock, old = stocks[code], events[code]
        south = []
        for participant in (1323, 1456):
            history = archive["south_history"].get(f"{issue}:{participant}", [])
            south.append(([row[0] for row in history], [row[1] for row in history]))
        holdings = {}
        for bar in stock["bars"]:
            day = bar[0]
            if day > "2025-10-10":
                continue
            amount = 0
            for dates, amounts in south:
                index = bisect.bisect_right(dates, day) - 1
                amount += amounts[index] if index >= 0 else 0
            denominators = [latest_available(issued[c], day) for c in components]
            if amount and all(denominators):
                holdings[day] = (amount, amount / sum(x[1] for x in denominators) * 100, "webb")
        acts = sorted(actions[code])
        found = signal(stock["bars"], holdings, old["peak"]["peak_date"], acts)
        if found["index"] is None:
            result.append({"code": code, "name": stock["name"], "signal": None,
                           "missing": found["missing"]})
            continue
        first, last = SHORT_ENDPOINTS[code]
        short_first = official_count(WORK / "sfc", first, code)
        short_last = official_count(WORK / "sfc", last, code)
        result.append({
            "code": code, "name": stock["name"], "old_signal": old["signal"],
            "signal": stock["bars"][found["index"]][0], "south": found,
            "cadence": accumulation_cadence(stock["bars"], holdings, found["dates"]),
            "outcome120": outcomes(stock["bars"], found["index"], 120, acts),
            "short_first": [first, short_first], "short_last": [last, short_last],
            "short_change": short_last / short_first - 1 if short_first and short_last else None,
        })
    (WORK / "corrected-signals.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    for row in result:
        print(row["code"], row["name"], row["signal"],
              "short8w", row.get("short_change"), "120d", row.get("outcome120", {}).get("end_return"))


if __name__ == "__main__":
    main()
