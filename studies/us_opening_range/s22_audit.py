"""One-shot, bounded-memory reproduction of the exposed legacy S22 report.

No network, trades, new candidates, or replacement legacy feature/statistic formulas.
"""
import argparse
import csv
import hashlib
import json
import resource
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from studies.archive.us_preopen_bias.code import picks


ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = "studies/archive/us_preopen_bias"
PLAN = "studies/us_opening_range/notes/S22_AUDIT_PLAN.md"
PLAN_SHA = "daa5315e59fbc37283326920fabdf5ee675bb8b2c64cb9d141267ab4e6a9d1ce"
SYMBOLS = tuple("US." + s for s in (
    "AA AAOI ABVX ACAD AG ALB APLD CDE CLF CRML FSLY HIMS HL IBRX IONQ IOVA "
    "IREN KGC LQDA MP QBTS RARE RGTI RIOT SLS SMCI SVRA TEM TTD U UEC USAR UUUU VKTX"
).split())
DATA_PINS = {
    "data/preopen-s21-select-v1": (
        "9fd9ece38757cfe115512b7c94d78ee7da2930ef3cdbf1448072484587e7f1a0",
        "1f4f324dca3958a5d71e3ae568811ea65fc65ae1148072b3fd8c0433ceee7486"),
    "data/preopen-s21-valid-v1": (
        "42b8a0b53c69cac1152696de25e61660ff79f036b4e1534b343ec2b88c55e677",
        "9f6ed130d7033db039f82d60cd31bedba0f42b601c3b44dffa369e286cd0b44f"),
}
ARCHIVE_PINS = {
    "code/preopen.py": "f95b01702c5a5c3ce699706cab0437dce5ca93b8274a6fa6871c900fd6425f95",
    "code/picks.py": "b3fefbc63dfa2799e3667a9cf33f20c4bbdb6971d90bd80384d3c8bea5c75850",
    "notes/S21_PREREG.md": "5c5112e875323e9ed59f1bfddde4463d3bd756029c7cc0ddcdbaadd97169bb26",
    "notes/S22_PREREG.md": "37f647981b5dd25980b7fe630cd22c355e7aa14ad365e24c5a8ee5dea655d769",
    "notes/universe_smallmid.json": "891277ab17f755938b33eb3251fb700bc42b7a3670124f885f34e8477ac572d0",
    "reports/s22_select_raw.txt": "6cf014b7ec1393040cd8b720058834f4322db3168cb98c7ea2ea958eea1d81e7",
    "reports/s22_validation_raw.txt": "ecb969c245c27e8975d8a8f4443c0264626a7ebd7302cd614ed97c89b883c893",
}
SEGMENTS = (
    ("select", ("data/preopen-s21-select-v1",), "2023-08-01", "2024-12-31"),
    ("validation", tuple(DATA_PINS), "2025-01-02", "2026-09-24"),
)
CANDIDATES = (("M1_gap_inplay", picks.p1_gap_go), ("M2_pm_inplay", picks.p3_pm_volume_go))
FEATURES = ("atr20", "gap", "gap_z", "pm_ratio", "ovol1")
LABELS = ("ret_oc", "up", "down", "hi_oc", "lo_oc")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs(root=ROOT):
    """Check fixed identities and every manifest-covered byte before feature/label work."""
    pins = {PLAN: PLAN_SHA}
    pins.update({ARCHIVE + "/" + rel: value for rel, value in ARCHIVE_PINS.items()})
    for rel, (checksums, manifest) in DATA_PINS.items():
        pins[rel + "/CHECKSUMS.sha256"] = checksums
        pins[rel + "/manifest.json"] = manifest
    for rel, expected in pins.items():
        if sha256(root / rel) != expected:
            raise ValueError("frozen input changed: " + rel)
    counts = {}
    for rel in DATA_PINS:
        directory = root / rel
        seen = set()
        for line in (directory / "CHECKSUMS.sha256").read_text().splitlines():
            expected, name = line.split(maxsplit=1)
            path = directory / name
            if name in seen or Path(name).is_absolute() or ".." in Path(name).parts:
                raise ValueError("unsafe/duplicate checksum path: " + name)
            if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
                raise ValueError("checksum path escapes dataset: " + name)
            if sha256(path) != expected:
                raise ValueError("dataset checksum mismatch: " + str(path))
            seen.add(name)
        observed = {"US." + path.stem for path in (directory / "daily").glob("*.csv")}
        if observed != set(SYMBOLS):
            raise ValueError("fixed daily universe changed: " + rel)
        counts[rel] = len(seen)
    return {"sha256": pins, "checked_files": counts}


def load_nominal_symbol(directories, symbol):
    """The legacy merge and fallback, limited to one explicitly pinned symbol."""
    out = {}
    for directory in directories:
        directory = Path(directory)
        sub = "daily_none" if (directory / "daily_none").is_dir() else "daily"
        path = directory / sub / (symbol.split(".")[1] + ".csv")
        if path.is_file():
            with path.open(encoding="utf-8") as stream:
                out.update({r["date"]: tuple(float(r[k]) for k in ("close", "high", "low", "turnover"))
                            for r in csv.DictReader(stream)})
    return out


def compact(row):
    return {"symbol": row["symbol"], "date": row["date"],
            "f": {key: row["f"][key] for key in FEATURES},
            "y": {key: row["y"][key] for key in LABELS}}


def bounded_pool(directories, start, end, symbols=SYMBOLS):
    """Load one symbol's tables, keep only S22 fields, then release the tapes."""
    by_day = defaultdict(list)
    coverage = {}
    source_dates = set()
    for symbol in symbols:
        data = picks.preopen.load(directories, symbols=[symbol])
        dates = sorted(d for d in data["tables"][symbol]["daily"] if start <= d <= end)
        source_dates.update(dates)
        eligible = picks.eligible_days(load_nominal_symbol(directories, symbol))
        rows = picks.preopen.build(data, start, end)
        eligible_pool = picks.pools(rows, {symbol: eligible})
        coverage[symbol] = {"daily_days": len(dates), "daily_first": min(dates, default=None),
                            "daily_last": max(dates, default=None), "built_rows": len(rows),
                            "eligible_rows": sum(len(xs) for xs in eligible_pool.values())}
        for day, day_rows in eligible_pool.items():
            by_day[day].extend(compact(row) for row in day_rows)
        del data, rows, eligible_pool
    # Legacy build globally sorts by date/symbol. Retain its pool ordering exactly.
    for rows in by_day.values():
        rows.sort(key=lambda row: row["symbol"])
    return dict(sorted(by_day.items())), {
        "by_symbol": coverage, "source_daily_days": len(source_dates),
        "source_daily_first": min(source_dates, default=None),
        "source_daily_last": max(source_dates, default=None),
        "eligible_days": len(by_day), "eligible_name_days": sum(map(len, by_day.values())),
        "eligible_first": min(by_day, default=None), "eligible_last": max(by_day, default=None),
    }


def score_candidate(by_day, candidate):
    items = picks.pick_items(by_day, candidate, 3)
    magnitude = picks.score_magnitude(items)
    direction = picks.score(items)
    ratio = picks.range_ratio(by_day, items)
    result = {**magnitude, "range_ratio": ratio,
              "direction_hit": direction.get("hit"), "direction_ci95": direction.get("ci95")}
    result["original_holds"] = bool(magnitude["n"] and magnitude["mag_ratio"] >= 1.2
                                      and ratio >= 1.2 and magnitude["mag_lo90"] > 1.0)
    return result, items


def render_lines(by_day, candidates):
    lines = ["eligible name-days %d over %d days (mean pool %.1f)" % (
        sum(map(len, by_day.values())), len(by_day), mean(map(len, by_day.values())))]
    for name, _ in CANDIDATES:
        m = candidates[name]
        lines.append("%-16s n=%d days=%d  |move| ratio %.2fx [%.2f, %.2f] lo90 %.2f  range ratio %.2fx  => %s" % (
            name, m["n"], m["days"], m["mag_ratio"], *m["mag_ci95"], m["mag_lo90"], m["range_ratio"],
            "HOLDS" if m["original_holds"] else "FAILS"))
        lines.append("      (descriptive) gap-direction hit %.1f%% [%.1f, %.1f]" % (
            100 * m["direction_hit"], *(100 * x for x in m["direction_ci95"])))
    return lines


def write_events(stream, segment, name, by_day, items):
    for day, side, row, base, pool_mag, pool_mfe in items:
        pool = by_day[day]
        event = {"segment": segment, "candidate": name, "date": day, "symbol": row["symbol"],
                 "side": side, "f": row["f"], "y": row["y"], "pool_count": len(pool),
                 "pool_same_side_rate": base, "pool_mean_abs_atr": pool_mag,
                 "pool_mean_mfe_side": pool_mfe,
                 "pool_mean_range_atr": mean((r["y"]["hi_oc"] - r["y"]["lo_oc"]) / r["f"]["atr20"] for r in pool)}
        stream.write(json.dumps(event, sort_keys=True, allow_nan=False) + "\n")


def memory_available_kib():
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1])
    raise RuntimeError("cannot establish memory availability")


def run(out, events_out, root=ROOT):
    out, events_out = Path(out), Path(events_out)
    if out.resolve() == events_out.resolve() or any(p.exists() or p.is_symlink() for p in (out, events_out)):
        raise FileExistsError("audit outputs must be two distinct, fresh files")
    available = memory_available_kib()
    if available < 512 * 1024:
        raise RuntimeError("less than 512 MiB available; do not begin labels")
    started = time.monotonic()
    report = {"purpose": "EXPOSED_LEGACY_AUDIT_NOT_NEW_VALIDATION", "status": "AUDIT_MATCH",
              "started_utc": datetime.now(timezone.utc).isoformat(), "symbols": list(SYMBOLS),
              "input_pins": verify_inputs(root), "code_sha256": sha256(Path(__file__)),
              "preflight_available_kib": available, "segments": {}}
    event_count = 0
    with events_out.open("x", encoding="utf-8") as stream:
        for segment, rels, start, end in SEGMENTS:
            segment_started = time.monotonic()
            by_day, coverage = bounded_pool([root / rel for rel in rels], start, end)
            candidates = {}
            for name, fn in CANDIDATES:
                metrics, items = score_candidate(by_day, fn)
                candidates[name] = metrics
                write_events(stream, segment, name, by_day, items)
                event_count += len(items)
            lines = render_lines(by_day, candidates)
            original_path = root / ARCHIVE / "reports" / ("s22_" + segment + "_raw.txt")
            expected = original_path.read_text().splitlines()
            matches = lines == expected
            report["segments"][segment] = {
                "requested_start": start, "requested_end": end, "datasets": list(rels),
                "coverage": coverage, "candidates": candidates, "rendered_lines": lines,
                "original_lines": expected, "exact_display_match": matches,
                "elapsed_seconds": time.monotonic() - segment_started,
            }
            print(segment + ": " + ("MATCH" if matches else "MISMATCH"), flush=True)
            print("\n".join(lines), flush=True)
            del by_day, items
            if not matches:
                report["status"] = "AUDIT_MISMATCH_STOPPED"
                break
    report.update({"ended_utc": datetime.now(timezone.utc).isoformat(),
                   "elapsed_seconds": time.monotonic() - started,
                   "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                   "events": {"path": str(events_out), "count": event_count, "sha256": sha256(events_out)}})
    with out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--events-out", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.out, args.events_out)
    return 0 if result["status"] == "AUDIT_MATCH" else 1


if __name__ == "__main__":
    raise SystemExit(main())
