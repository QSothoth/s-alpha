"""Recompute the registered exploratory screen against locally captured data."""

import csv
import glob
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

from studies.opportunity_events.hk_southbound import (accumulation_cadence, outcomes,
                                                       price_at_date, rebound_path, signal)


def review(candidate_path, rank_dir, action_paths, raw_paths, destination):
    candidates = json.loads(Path(candidate_path).read_text())
    listing_path = Path(candidate_path).parent / "listings.json"
    listings = {x["code"]: x["listing_date"] for x in json.loads(listing_path.read_text())} if listing_path.exists() else {}
    holdings = defaultdict(dict)
    for page in sorted(glob.glob(str(Path(rank_dir) / "*.json"))):
        for row in json.loads(Path(page).read_text())["data"]:
            if row["HOLD_SHARES"] is not None and row["HOLD_SHARES_RATIO"] is not None:
                holdings["HK." + row["SECURITY_CODE"]][row["HOLD_DATE"][:10]] = (
                    float(row["HOLD_SHARES"]), float(row["HOLD_SHARES_RATIO"]), "rank")

    mx_dir = Path(rank_dir).parent / "mx"
    for path in sorted(mx_dir.glob("history-*.json")):
        try:
            body = json.loads(path.read_text())
            tables = body["data"]["data"]["searchDataResultDTO"]["dataTableDTOList"]
            for table in tables:
                names = table["nameMap"]
                raw = table["rawTable"]
                share_key = next(k for k, value in names.items() if value == "南向持股数量")
                ratio_key = next(k for k, value in names.items() if value == "南向持股占比")
                code = "HK." + table["code"].split(".")[0]
                for day, shares, ratio in zip(raw["headName"], raw[share_key], raw[ratio_key]):
                    try:
                        value = (float(shares), float(ratio), "mx")
                    except (TypeError, ValueError):
                        continue
                    holdings[code].setdefault(day[:10], value)
        except (KeyError, TypeError, StopIteration, ValueError):
            continue

    actions = defaultdict(set)
    for path in action_paths:
        with gzip.open(path, "rt", newline="") as handle:
            for row in csv.DictReader(handle):
                actions[row["code"]].add((row["ex_date"], float(row["factor_a"]),
                                           float(row["factor_b"])))

    found = []
    for stock in candidates["stocks"]:
        if int(stock["code"][3:]) >= 80000:
            continue
        bars = stock["bars"]
        acts = sorted(a for a in actions[stock["code"]] if a[0] <= bars[-1][0])
        for peak in stock["peaks"]:
            result = signal(bars, holdings[stock["code"]], peak["peak_date"], acts)
            if result["index"] is None:
                continue
            index = result["index"]
            event = {"code": stock["code"], "name": stock["name"], "source": stock["source"],
                     "peak": peak, "signal": bars[index][0], "south": result,
                     "listed": listings.get(stock["code"]),
                     "sessions_since_peak": index - next(i for i, b in enumerate(bars)
                                                         if b[0] == peak["peak_date"]),
                     "cadence": accumulation_cadence(bars, holdings[stock["code"]], result["dates"]),
                     "signal_close": price_at_date(bars[index][2], bars[index][0], acts),
                     "o60": outcomes(bars, index, 60, acts),
                     "o120": outcomes(bars, index, 120, acts),
                     "o250": outcomes(bars, index, 250, acts),
                     "rebound": rebound_path(bars, index, 120, acts),
                     "last_date": bars[-1][0],
                     "last_close": price_at_date(bars[-1][2], bars[-1][0], acts),
                     "price_checks": []}
            found.append(event)
            break

    checks = defaultdict(list)
    for event in found:
        checks[(event["code"], event["signal"])].append((event, "close", event["signal_close"]))
        checks[(event["code"], event["o120"]["entry_date"])].append(
            (event, "open", event["o120"]["entry"]))
    calendar = {row[0] for stock in candidates["stocks"] if stock["code"] == "HK.00700"
                for row in stock["bars"]}
    for path in raw_paths:
        with gzip.open(path, "rt", newline="") as handle:
            for row in csv.DictReader(handle):
                if row["code"] == "HK.00700":
                    calendar.add(row["date"])
                for event, field, reconstructed in checks.get((row["code"], row["date"]), []):
                    raw = float(row[field])
                    event["price_checks"].append({"date": row["date"], "field": field,
                        "raw": raw, "reconstructed": reconstructed,
                        "ok": abs(raw - reconstructed) <= max(0.05, raw * 0.01)})

    stock_bars = {x["code"]: x["bars"] for x in candidates["stocks"]}
    for event in found:
        days = {row[0] for row in stock_bars[event["code"]]}
        expected = sorted(day for day in calendar
                          if event["signal"] < day <= event["last_date"])[:120]
        event["missing_market_days"] = [day for day in expected if day not in days]

    Path(destination).write_text(json.dumps({"coverage": candidates["counts"],
        "events": found}, ensure_ascii=False, indent=2))
    return found


if __name__ == "__main__":
    root = Path("data/trader-data-v2/hk")
    live = Path("data/trader-live/trader-data-v1/hk")
    independent_raw = Path(sys.argv[1]).parent / "independent-raw.csv.gz"
    raw_paths = [root / "bars_raw.csv.gz", live / "bars_raw.csv.gz"]
    if independent_raw.exists():
        raw_paths.append(independent_raw)
    events = review(sys.argv[1], sys.argv[2], [root / "actions.csv.gz", live / "actions.csv.gz"],
                    raw_paths, sys.argv[3])
    for e in events:
        o = e["o120"]
        print(e["code"], e["name"], "peak", e["peak"]["peak_date"],
              "cap_proxy_100m", round(e["peak"]["proxy_cap"] / 1e8), "signal", e["signal"],
              "entry", round(o["entry"], 3), "observed", o["observed"],
              "end120", round(o["end_return"] * 100, 1) if o["end_return"] is not None else None,
              "first_pullback", o["first_pullback"], "missing_prior", e["south"]["missing"],
              "price_checks", e["price_checks"], flush=True)
