"""Explore previously selected cases with official short-position snapshots."""

import csv
import datetime as dt
import io
import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


WEEKS = (4, 8, 12)


def endpoints(records, cutoff):
    records = sorted((r for r in records if r["timestamp_str"] <= cutoff),
                     key=lambda r: r["timestamp_str"], reverse=True)
    if not records:
        return {}
    latest = records[0]["timestamp_str"]
    result = {0: records[0]}
    for weeks in WEEKS:
        limit = (dt.date.fromisoformat(latest) - dt.timedelta(weeks=weeks)).isoformat()
        result[weeks] = next((r for r in records if r["timestamp_str"] <= limit), None)
    return result


def collect(shorts, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    days = sorted({r["timestamp_str"] for item in shorts
                   for r in endpoints(item.get("records", []), item["cutoff"]).values() if r})
    failures = 0
    for day in days:
        path = directory / f"{day}.csv"
        if path.exists():
            continue
        datepath = day.replace("-", "/")
        url = (f"https://www.sfc.hk/-/media/EN/pdf/spr/{datepath}/"
               f"Short_Position_Reporting_Aggregated_Data_{day.replace('-', '')}.csv")
        try:
            with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=12) as response:
                raw = response.read()
            rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
            expected = dt.date.fromisoformat(day).strftime("%d/%m/%Y")
            if len(rows) < 2 or rows[1][0] != expected:
                raise ValueError("unexpected report date or empty report")
            path.write_bytes(raw)
            failures = 0
            print(day, "saved", flush=True)
            time.sleep(0.2)
        except (OSError, ValueError, UnicodeError) as error:
            print(day, "FAILED", type(error).__name__, flush=True)
            failures += 1
            if (isinstance(error, HTTPError) and error.code == 429) or failures >= 3:
                print("stopping after rate limit or repeated failure", flush=True)
                break


def official_count(directory, day, code):
    path = Path(directory) / f"{day}.csv"
    if not path.exists():
        return None
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            stock_code = row.get("Stock Code", "")
            if stock_code.isdigit() and int(stock_code) == int(code[3:]):
                return int(row["Aggregated Reportable Short Positions (Shares)"])
    return None


def summarize(events, shorts, volumes, directory):
    short_by_code = {x["code"]: x for x in shorts}
    volume_by_code = {x["code"]: x for x in volumes}
    output = []
    for e in events:
        code = e["code"]
        if code not in short_by_code or code not in volume_by_code:
            continue
        cutoff = (dt.date.fromisoformat(e["signal"]) - dt.timedelta(days=14)).isoformat()
        end = endpoints(short_by_code[code].get("records", []), cutoff)
        points = {}
        for weeks, row in end.items():
            if not row:
                points[str(weeks)] = None
                continue
            official = official_count(directory, row["timestamp_str"], code)
            points[str(weeks)] = {"date": row["timestamp_str"], "shares": official,
                                  "vendor_shares": row["aggregated_short"],
                                  "matches_vendor": official == row["aggregated_short"]
                                  if official is not None else None}
        changes = {}
        for weeks in WEEKS:
            before = points.get(str(weeks))
            last = points.get("0")
            if (last and before and last["matches_vendor"] and before["matches_vendor"]
                    and before["shares"]):
                changes[str(weeks)] = last["shares"] / before["shares"] - 1
            else:
                changes[str(weeks)] = None
        rows = sorted((r for r in volume_by_code[code].get("records", [])
                       if r["timestamp_str"] <= e["signal"]),
                      key=lambda r: r["timestamp_str"], reverse=True)[:20]
        valid = [x for x in rows if x.get("turnover") and x.get("short_sell_turnover") is not None]
        short_turnover = (sum(r["short_sell_turnover"] for r in valid) /
                          sum(r["turnover"] for r in valid)) if (
                              len(valid) == 20 and valid[0]["timestamp_str"] == e["signal"]) else None
        output.append({"code": code, "name": e["name"], "signal": e["signal"],
                       "south_pct_start": e["south"]["ratios"][0],
                       "south_pct_end": e["south"]["ratios"][-1],
                       "south_shares_growth": e["south"]["shares"][-1] / e["south"]["shares"][0] - 1,
                       "short_positions": points, "short_change": changes,
                       "short_turnover_20": short_turnover,
                       "short_turnover_last_date": valid[0]["timestamp_str"] if valid else None,
                       "return120": e["o120"]["end_return"]})
    return output


if __name__ == "__main__":
    root = Path("data/hk-southbound-20261101")
    work = root / "multidimensional"
    events = json.loads((root / "current-signals.json").read_text())["events"]
    shorts = json.loads((work / "futu-shortinterest-signals.json").read_text())
    volumes = json.loads((work / "futu-shortvolume-signals.json").read_text())
    if "--collect" in sys.argv:
        collect(shorts, work / "sfc")
    rows = summarize(events, shorts, volumes, work / "sfc")
    (work / "dimension-summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    for row in rows:
        last = row["short_positions"].get("0") or {}
        print(row["code"], row["name"], "south", row["south_pct_start"], row["south_pct_end"],
              "short", last.get("date"), "changes", row["short_change"],
              "turnover20", row["short_turnover_20"], "return120", row["return120"], flush=True)
