"""Exploratory point-in-time review of crashes and Southbound shareholdings."""

import csv
import datetime
import gzip
import json
from itertools import groupby
from pathlib import Path

START = "2020-06-01"
END = "2026-10-30"


def candidate_peaks(rows, shares):
    """Return each approximate-cap peak that subsequently halves, in date order."""
    peak = None
    reported = False
    found = []
    for index, row in enumerate(rows):
        price = row[2]
        if price <= 0:
            continue
        if peak is None or price > peak[1][2]:
            peak = (index, row)
            reported = False
        if (not reported and index - peak[0] >= 22 and price <= peak[1][2] * 0.5
                and peak[1][2] * shares >= 300_000_000_000):
            found.append({"peak_date": peak[1][0], "peak_price": peak[1][2],
                          "proxy_cap": peak[1][2] * shares, "first_half": row[0]})
            reported = True
    return found


def price_at_date(price, day, actions):
    """Invert later corporate actions, returning the price as visible on day."""
    for ex_date, factor_a, factor_b in reversed(actions):
        if ex_date > day:
            price = (price - factor_b) / factor_a
    return price


def signal(bars, holdings, peak_date, actions=()):
    """First qualifying long-term accumulation, using two-session-old data."""
    start = next(i for i, row in enumerate(bars) if row[0] == peak_date)
    peak_price = bars[start][2]
    missing = 0
    rising_intervals = 0
    for i in range(start + 63, len(bars) - 1):
        day = bars[i][0]
        peak_now = price_at_date(peak_price, day, actions)
        close_now = price_at_date(bars[i][2], day, actions)
        if peak_now <= 0:
            return {"index": None, "missing": missing, "invalid_peak": True,
                    "rising_intervals": rising_intervals}
        if close_now > peak_now:
            break
        if close_now > peak_now * 0.5:
            continue
        dates = [bars[i - offset][0] for offset in (62, 32, 2)]
        if any(dates[0] < ex_date <= dates[-1] and factor_a != 1
               for ex_date, factor_a, _ in actions):
            missing += 1
            continue
        if any(day not in holdings for day in dates):
            missing += 1
            continue
        values = [holdings[day] for day in dates]
        if all(len(v) > 2 for v in values) and len({v[2] for v in values}) != 1:
            missing += 1
            continue
        shares = [v[0] for v in values]
        ratios = [v[1] for v in values]
        if (0 < shares[0] < shares[1] < shares[2] and ratios[2] >= 5
                and ratios[2] - ratios[0] >= 2):
            if bars[i - 2][2] >= bars[i - 62][2]:
                rising_intervals += 1
                continue
            return {"index": i, "similar": shares[2] >= shares[0] * 1.5,
                    "dates": dates, "shares": shares, "ratios": ratios,
                    "missing": missing, "rising_intervals": rising_intervals}
    return {"index": None, "missing": missing, "rising_intervals": rising_intervals}


def accumulation_cadence(bars, holdings, dates):
    """Describe weekly changes without treating absent observations as zero."""
    start, end = dates[0], dates[-1]
    source = holdings[start][2]
    days = [row[0] for row in bars if start <= row[0] <= end]
    weekly = {}
    valid = 0
    for day in days:
        value = holdings.get(day)
        if value is None or len(value) < 3 or value[2] != source:
            continue
        valid += 1
        if day > start:
            week = datetime.date.fromisoformat(day).isocalendar()[:2]
            weekly[week] = value[0]
    weeks = list(dict.fromkeys(datetime.date.fromisoformat(day).isocalendar()[:2]
                               for day in days if day > start))
    previous = holdings[start][0]
    counts = {"positive": 0, "flat": 0, "negative": 0, "missing": 0}
    for week in weeks:
        current = weekly.get(week)
        if current is None:
            counts["missing"] += 1
        elif previous is None:
            counts["missing"] += 1
        elif current > previous:
            counts["positive"] += 1
        elif current < previous:
            counts["negative"] += 1
        else:
            counts["flat"] += 1
        previous = current
    return {"weeks": counts, "observations": valid, "sessions": len(days), "source": source}


def outcomes(bars, index, horizon=120, actions=()):
    """Price returns and first 10% pullback, excluding cash dividends and costs."""
    entry_day = bars[index + 1][0]
    entry = price_at_date(bars[index + 1][1], entry_day, actions)
    if entry <= 0:
        return None
    future = bars[index + 1:index + 1 + horizon]
    high = entry
    high_day = entry_day
    high_raw = entry
    first_pullback = None
    values = []
    for row in future:
        raw_close = price_at_date(row[2], row[0], actions)
        units = 1.0
        for ex_date, factor_a, _ in actions:
            if entry_day < ex_date <= row[0]:
                units /= factor_a
        equivalent = raw_close * units
        values.append(equivalent)
        if equivalent > high:
            high, high_day, high_raw = equivalent, row[0], raw_close
        if first_pullback is None and equivalent <= high * 0.9:
            first_pullback = {"peak_date": high_day, "peak_return": high / entry - 1,
                              "peak_raw_close": high_raw, "date": row[0],
                              "raw_close": raw_close, "return": equivalent / entry - 1}
    return {"entry_date": entry_day, "entry": entry, "observed": len(future),
            "end_return": values[-1] / entry - 1 if len(future) == horizon else None,
            "max_close_return": max(values) / entry - 1,
            "min_close_return": min(values) / entry - 1,
            "first_pullback": first_pullback}


def rebound_path(bars, index, horizon=120, actions=()):
    """First 20% rebound from a running low, followed by a 10% pullback."""
    entry_day = bars[index + 1][0]
    low = price_at_date(bars[index + 1][1], entry_day, actions)
    low_day = entry_day
    peak = None
    peak_day = None
    peak_raw = None
    future = bars[index + 1:index + 1 + horizon]
    for row in future:
        raw = price_at_date(row[2], row[0], actions)
        units = 1.0
        for ex_date, factor_a, _ in actions:
            if entry_day < ex_date <= row[0]:
                units /= factor_a
        close = raw * units
        if peak is None:
            if close < low:
                low, low_day = close, row[0]
            if close >= low * 1.2:
                peak, peak_day, peak_raw = close, row[0], raw
        else:
            if close > peak:
                peak, peak_day, peak_raw = close, row[0], raw
            if close <= peak * 0.9:
                return {"low_date": low_day, "low_equivalent": low,
                        "peak_date": peak_day, "peak_raw_close": peak_raw,
                        "rebound": peak / low - 1, "pullback_date": row[0],
                        "pullback_raw_close": raw, "observed": len(future)}
    return {"low_date": low_day, "low_equivalent": low,
            "peak_date": peak_day, "peak_raw_close": peak_raw,
            "rebound": peak / low - 1 if peak is not None else None,
            "pullback_date": None, "pullback_raw_close": None, "observed": len(future)}


def load_universe(original_path, v2_root):
    original = json.loads(Path(original_path).read_text())
    stocks = {x["code"]: x["name"] for x in json.loads(
        (Path(v2_root) / "universe.json").read_text())["stocks"]}
    v2_codes = set(stocks)
    stocks.update(original["nm"])
    snap = original["snap"]
    seen = set()
    for code, values in original["K"].items():
        rows = sorted({r[0]: r for r in values if START <= r[0] <= END}.values())
        if len(rows) < 23 and code in v2_codes:
            continue
        seen.add(code)
        yield code, stocks.get(code, code), snap.get(code, [None])[0], rows, "original"
    with gzip.open(Path(v2_root) / "bars_qfq.csv.gz", "rt", newline="") as handle:
        for code, grouped in groupby(csv.DictReader(handle), key=lambda r: r["code"]):
            if code in seen:
                continue
            seen.add(code)
            rows = [[r["date"], float(r["open"]), float(r["close"]),
                     float(r["high"]), float(r["low"]), float(r["volume"])]
                    for r in grouped if START <= r["date"] <= END]
            yield code, stocks.get(code, code), snap.get(code, [None])[0], rows, "v2"


def candidates(original_path, v2_root, output_path):
    counts = {"stocks": 0, "missing_shares": 0, "short_bars": 0}
    selected = []
    for code, name, shares, rows, source in load_universe(original_path, v2_root):
        counts["stocks"] += 1
        if not shares:
            counts["missing_shares"] += 1
            continue
        if len(rows) < 23:
            counts["short_bars"] += 1
            continue
        peaks = candidate_peaks(rows, shares)
        if peaks:
            selected.append({"code": code, "name": name, "shares": shares,
                             "source": source, "peaks": peaks, "bars": rows})
    Path(output_path).write_text(json.dumps({"counts": counts, "stocks": selected},
                                           ensure_ascii=False))
    return counts, [(x["code"], x["name"], x["peaks"]) for x in selected]


if __name__ == "__main__":
    import sys
    counts, stocks = candidates(sys.argv[1], sys.argv[2], sys.argv[3])
    print("coverage", counts, "candidate stocks", len(stocks), flush=True)
    for code, name, peaks in stocks:
        for peak in peaks:
            print(code, name, peak, flush=True)
