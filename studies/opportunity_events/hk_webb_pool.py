"""Select candidate-pool CCASS histories without expanding the full dump."""

import gzip
import json
import re
from collections import defaultdict
from pathlib import Path

from studies.opportunity_events.hk_webb_ccass import MARKER, read_archive


ROOT = Path("data/hk-southbound-20261101")
WORK = ROOT / "multidimensional"
PARTICIPANTS = (1323, 1456, 454, 460, 30, 1243)


def matches(path, pattern):
    tail = b""
    with gzip.open(path, "rb") as file:
        while True:
            block = file.read(1024 * 1024)
            data = tail + block
            cutoff = max(0, len(data) - 512) if block else len(data)
            for match in pattern.finditer(data):
                if match.start() >= cutoff:
                    break
                yield match.groups()
            tail = data[cutoff:]
            if not block:
                break


def pool_metadata():
    listings = defaultdict(list)
    listing_pattern = re.compile(rb"\((\d+),'(\d+)',(\d+),"
                                 rb"(NULL|'\d{4}-\d\d-\d\d'),"
                                 rb"(NULL|'\d{4}-\d\d-\d\d'),"
                                 rb"(NULL|'\d{4}-\d\d-\d\d'),")
    for fields in matches(WORK / "stocklistings.sql.gz", listing_pattern):
        issue, stock, exchange, first, last, delisted = [x.decode().strip("'") for x in fields]
        if exchange in {"1", "20", "22", "23"}:
            listings[int(stock)].append((int(issue), first, last, delisted))
    issue_pattern = re.compile(rb"\((\d+),(\d+),[^,]*,(\d+),")
    issues = {int(issue): (int(issuer), int(kind))
              for issue, issuer, kind in matches(WORK / "issue.sql.gz", issue_pattern)}
    siblings = defaultdict(list)
    for issue, (issuer, kind) in issues.items():
        if kind == 7:
            siblings[issuer].append(issue)
    verified_peaks = set()
    for path in (ROOT / "mx").glob("cap-*.json"):
        try:
            response = json.loads(path.read_text())
            tables = response["data"]["data"]["searchDataResultDTO"]["dataTableDTOList"]
            for table in tables:
                raw = table["rawTable"]
                field = next(k for k in raw if k != "headName")
                if float(raw[field][0]) >= 500_000_000_000:
                    verified_peaks.add(("HK." + table["code"].split(".")[0], raw["headName"][0][:10]))
        except (KeyError, TypeError, ValueError, IndexError, StopIteration):
            continue
    selected, missing = {}, []
    for stock in json.loads((ROOT / "candidates.json").read_text())["stocks"]:
        peaks = [p for p in stock["peaks"] if p["proxy_cap"] >= 500_000_000_000
                 or (stock["code"], p["peak_date"]) in verified_peaks]
        if not peaks or int(stock["code"][3:]) >= 80000:
            continue
        date = peaks[0]["peak_date"]
        rows = [row for row in listings[int(stock["code"][3:])]
                if (row[1] == "NULL" or row[1] <= date)
                and (row[2] == "NULL" or row[2] >= date)
                and (row[3] == "NULL" or row[3] >= date)]
        if len(rows) != 1 or rows[0][0] not in issues:
            missing.append({"code": stock["code"], "name": stock["name"], "mapping_candidates": rows})
            continue
        issue = rows[0][0]
        issuer, kind = issues[issue]
        components = [issue] + (siblings[issuer] if kind == 8 else [])
        selected[str(issue)] = {"code": stock["code"], "name": stock["name"],
                                "components": components, "peaks": peaks}
    return selected, missing


class PoolSelector:
    def __init__(self, issues):
        choices = b"|".join(k.encode() for k in issues)
        parts = b"|".join(str(x).encode() for x in PARTICIPANTS)
        self.daily_pattern = re.compile(rb"\('(\d{4}-\d\d-\d\d)',(" + choices + rb"),([0-9,]+)\)")
        self.holding_pattern = re.compile(rb"\((" + parts + rb"),(" + choices +
                                          rb"),(\d+),'(\d{4}-\d\d-\d\d)'\)")
        self.table = b""
        self.tail = b""
        self.daily = {}
        self.history = {}
        self.before = {}
        self.seen = set()

    def scan(self, data, limit):
        if self.table == b"dailylog":
            for match in self.daily_pattern.finditer(data):
                if match.start() >= limit:
                    break
                day, issue, values = match.groups()
                day, issue = day.decode(), issue.decode()
                if "2020-01-01" <= day <= "2025-10-10":
                    row = [int(x) for x in values.split(b",")]
                    if len(row) != 10:
                        raise ValueError("Unexpected dailylog fields")
                    self.daily.setdefault(issue, {})[day] = row
        elif self.table == b"holdings":
            for match in self.holding_pattern.finditer(data):
                if match.start() >= limit:
                    break
                participant, issue, amount, day = match.groups()
                day = day.decode()
                if day > "2025-10-10":
                    continue
                key = f"{issue.decode()}:{participant.decode()}"
                value = [day, int(amount)]
                if day < "2020-01-01":
                    previous = self.before.get(key)
                    if previous is None or previous[0] < day:
                        self.before[key] = value
                else:
                    self.history.setdefault(key, []).append(value)

    def feed(self, block, final=False):
        data = self.tail + block
        cutoff = len(data) if final else max(0, len(data) - 512)
        cursor = 0
        for marker in MARKER.finditer(data):
            if marker.start() >= cutoff:
                break
            self.scan(data[cursor:marker.start()], marker.start() - cursor)
            self.table = marker[1]
            self.seen.add(self.table.decode())
            cursor = marker.end()
        self.scan(data[cursor:], max(0, cutoff - cursor))
        self.tail = data[cutoff:]


def main():
    import sys

    selected, missing = pool_metadata()
    if not selected:
        raise ValueError("No mapped candidate issues")
    path = WORK / "webb-pool.json"
    prior = json.loads(path.read_text()) if "--only-new" in sys.argv and path.exists() else None
    target = {issue: item for issue, item in selected.items()
              if prior is None or issue not in prior["issues"]}
    if not target:
        print("No new mapped issues")
        return
    selector = PoolSelector(target)
    size = 0
    for block in read_archive(WORK / "ccass-sparse-header.7z"):
        selector.feed(block)
        size += len(block)
        if size % (1024**3) == 0:
            print(f"Decoded {size // 1024**3} GiB; table {selector.table.decode()}", flush=True)
        if selector.table == b"parthold":
            break
    if not {"dailylog", "holdings", "parthold"}.issubset(selector.seen):
        raise ValueError("CCASS table extraction incomplete")
    for key, value in selector.before.items():
        selector.history.setdefault(key, []).insert(0, value)
    result = {"issues": selected, "unmapped": missing,
              "dailylog": selector.daily, "history": selector.history}
    if prior is not None:
        result["dailylog"] = {**prior["dailylog"], **result["dailylog"]}
        result["history"] = {**prior["history"], **result["history"]}
    path.write_text(json.dumps(result, separators=(",", ":")))
    print(f"Wrote {path}; mapped {len(selected)}, unmapped {len(missing)}", flush=True)


if __name__ == "__main__":
    main()
