"""Check selected raw closing prices against Webb-site's HKEX DQS archive."""

import csv
import gzip
import json
import re
from collections import defaultdict

from studies.opportunity_events.hk_southbound import price_at_date
from studies.opportunity_events.hk_webb_ccass import MARKER, read_archive
from studies.opportunity_events.hk_webb_corrected_signals import ROOT, WORK


def main():
    events = json.loads((WORK / "webb-pool-events.json").read_text())["events"]
    stocks = {s["code"]: s for s in json.loads((ROOT / "candidates.json").read_text())["stocks"]}
    actions = defaultdict(set)
    for path in ("data/trader-data-v2/hk/actions.csv.gz", "data/trader-live/trader-data-v1/hk/actions.csv.gz"):
        with gzip.open(path, "rt", newline="") as file:
            for row in csv.DictReader(file):
                actions[row["code"]].add((row["ex_date"], float(row["factor_a"]), float(row["factor_b"])))
    expected = {}
    for event in events:
        stock = stocks[event["code"]]
        bars = stock["bars"]
        index = next(i for i, bar in enumerate(bars) if bar[0] == event["signal"])
        days = {event["signal"], bars[index + 120][0]}
        pullback = event["outcome120"]["first_pullback"]
        if pullback:
            days.add(pullback["peak_date"])
        for bar in bars:
            if bar[0] in days and bar[0] <= "2025-10-10":
                expected[(event["issue"], bar[0])] = (event["code"],
                    price_at_date(bar[2], bar[0], sorted(actions[event["code"]])))
    choices = b"|".join(sorted({key[0].encode() for key in expected}))
    quote = re.compile(rb"\((" + choices + rb"),'(\d{4}-\d\d-\d\d)',"
                       rb"([0-9.eE+-]+),([0-9.eE+-]+),")
    table, tail, seen, actual, count = b"", b"", set(), {}, 0
    for block in read_archive(WORK / "ccass-sparse-header.7z"):
        data = tail + block
        cutoff, cursor = max(0, len(data) - 512), 0

        def scan(chunk, limit):
            if table == b"quotes":
                for match in quote.finditer(chunk):
                    if match.start() >= limit:
                        break
                    issue, day = match[1].decode(), match[2].decode()
                    if (issue, day) in expected:
                        actual[(issue, day)] = float(match[4])

        for marker in MARKER.finditer(data):
            if marker.start() >= cutoff:
                break
            scan(data[cursor:marker.start()], marker.start() - cursor)
            table = marker[1]
            seen.add(table)
            cursor = marker.end()
        scan(data[cursor:], max(0, cutoff - cursor))
        tail = data[cutoff:]
        count += len(block)
        if count % (1024**3) == 0:
            print(f"Decoded {count // 1024**3} GiB; table {table.decode()}", flush=True)
        if b"quotes" in seen and table != b"quotes":
            break
    if b"quotes" not in seen:
        raise ValueError("Quotes table was not reached")
    checks = []
    for key, (code, recorded) in sorted(expected.items()):
        original = actual.get(key)
        checks.append({"code": code, "date": key[1], "reconstructed": recorded, "archive": original,
                       "ok": None if original is None else abs(recorded - original) <= max(0.05, original * 0.01)})
    (WORK / "webb-quote-check.json").write_text(json.dumps(checks, indent=2))
    print("Price checks", len(checks), "missing", sum(x["ok"] is None for x in checks),
          "mismatched", sum(x["ok"] is False for x in checks), flush=True)


if __name__ == "__main__":
    main()
