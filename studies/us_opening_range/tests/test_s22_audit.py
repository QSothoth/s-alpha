"""Synthetic-only equivalence and boundary tests for the exposed S22 audit."""
import copy
import io
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from studies.us_opening_range import s22_audit as audit


def row(symbol, day, magnitude, selected=True):
    return {"symbol": symbol, "date": day,
            "f": {"atr20": 1.0, "gap": 1.0, "gap_z": 1.0 if selected else 0.0,
                  "pm_ratio": 3.0 if selected else 1.0, "ovol1": 9000.0},
            "y": {"ret_oc": magnitude, "up": magnitude > 0, "down": magnitude < 0,
                  "hi_oc": abs(magnitude), "lo_oc": -abs(magnitude)}}


def synthetic_source(symbols=("US.AA",), pm_observations=15, exact_option=True):
    days = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(30)]
    tables = {}
    for index, symbol in enumerate(symbols):
        daily = {d: {"date": d, "open": 10.0, "high": 11.0, "low": 9.0,
                     "close": 10.0, "turnover": 20e6, "volume": 2e6} for d in days}
        daily[days[-1]].update(open=12.0 + index, high=15.0 + index, close=13.0 + index)
        option = {"option_volume": 9000, "call_volume": 6000, "put_volume": 3000}
        opt = {days[-3]: dict(option)}
        if exact_option:
            opt[days[-2]] = dict(option)
        ext = {d: {"pm_turn": 0.0, "pm_0830": None, "pm_0930": None,
                   "ah_last": None, "ah_hm": ""} for d in days}
        for d in days[-1 - pm_observations:-1]:
            ext[d]["pm_turn"] = 100.0
        ext[days[-1]]["pm_turn"] = 500.0
        tables[symbol] = {"daily": daily, "opt": opt, "ext": ext, "iv": {}, "sv": {}, "cf": {}}
    return {"symbols": list(symbols), "tables": tables, "market": {}}, days


def nominal(source, symbol):
    return {d: tuple(float(r[k]) for k in ("close", "high", "low", "turnover"))
            for d, r in source["tables"][symbol]["daily"].items()}


class S22AuditTests(unittest.TestCase):
    def test_original_statistics_exact_and_event_weighted_self_inclusive_denominator(self):
        pool = {"2024-01-01": [row("US.A", "2024-01-01", 4), row("US.B", "2024-01-01", 2, False)],
                "2024-01-02": [row("US.A", "2024-01-02", 8), row("US.B", "2024-01-02", 4),
                               row("US.C", "2024-01-02", 2)]}
        metrics, items = audit.score_candidate(pool, audit.picks.p1_gap_go)
        original = audit.picks.score_magnitude(items)
        for key, value in original.items():
            self.assertEqual(metrics[key], value)
        self.assertEqual(metrics["direction_ci95"], audit.picks.score(items)["ci95"])
        self.assertEqual(items[0][4], 3.0)  # (4 + 2) / 2 includes the selected name itself.
        self.assertAlmostEqual(metrics["mag_ratio"], 18 / 17)  # Three picks weight day two three times.
        self.assertAlmostEqual(metrics["range_ratio"], 18 / 17)
        output = io.StringIO()
        audit.write_events(output, "synthetic", "M1_gap_inplay", pool, items)
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(events), 4)
        self.assertEqual(events[0]["pool_mean_abs_atr"], 3.0)
        self.assertEqual(events[-1]["pool_count"], 3)

    def test_missing_exact_previous_option_is_not_backfilled(self):
        source, days = synthetic_source(exact_option=False)
        result = audit.picks.preopen.build(source, days[-1], days[-1])
        self.assertIsNone(result[0]["f"]["ovol1"])
        eligible = {"US.AA": audit.picks.eligible_days(nominal(source, "US.AA"))}
        self.assertIn(days[-1], eligible["US.AA"])
        self.assertFalse(audit.picks.pools(result, eligible))
        source["tables"]["US.AA"]["opt"][days[-2]] = source["tables"]["US.AA"]["opt"][days[-3]].copy()
        result = audit.picks.preopen.build(source, days[-1], days[-1])
        self.assertEqual(len(audit.picks.pools(result, eligible)[days[-1]]), 1)

    def test_pm_15_positive_observations_not_20_complete_observations(self):
        for observations, expected in ((14, None), (15, 5.0), (20, 5.0)):
            with self.subTest(observations=observations):
                source, days = synthetic_source(pm_observations=observations)
                result = audit.picks.preopen.build(source, days[-1], days[-1])
                self.assertEqual(result[0]["f"]["pm_ratio"], expected)
        # A missing and a zero observation are both absent from the positive-history denominator.
        source, days = synthetic_source(pm_observations=15)
        del source["tables"]["US.AA"]["ext"][days[-21]]
        result = audit.picks.preopen.build(source, days[-1], days[-1])
        self.assertEqual(result[0]["f"]["pm_ratio"], 5.0)

    def test_partitioned_build_matches_full_legacy_pool_on_synthetic_input(self):
        symbols = ("US.BB", "US.AA")
        source, days = synthetic_source(symbols)
        full = audit.picks.preopen.build(source, days[-1], days[-1])
        eligible = {s: audit.picks.eligible_days(nominal(source, s)) for s in symbols}
        expected = {d: [audit.compact(r) for r in rows] for d, rows in audit.picks.pools(full, eligible).items()}
        calls = []

        def load(directories, symbols):
            calls.append(tuple(symbols))
            self.assertEqual(len(symbols), 1)
            return {"symbols": symbols, "tables": {symbols[0]: copy.deepcopy(source["tables"][symbols[0]])}, "market": {}}

        with patch.object(audit.picks.preopen, "load", side_effect=load), \
                patch.object(audit, "load_nominal_symbol", side_effect=lambda dirs, s: nominal(source, s)):
            actual, coverage = audit.bounded_pool([], days[-1], days[-1], symbols=symbols)
        self.assertEqual(actual, expected)
        self.assertEqual(calls, [(s,) for s in symbols])
        self.assertEqual(coverage["eligible_name_days"], 2)
        for name, fn in audit.CANDIDATES:
            self.assertEqual(audit.score_candidate(actual, fn)[0], audit.score_candidate(expected, fn)[0])

    def test_original_tie_order_is_preserved(self):
        pool = [row("US.A", "2024-01-01", 1), row("US.B", "2024-01-01", 1)]
        self.assertEqual(audit.picks.p1_gap_go(pool, 1)[0][0]["symbol"], "US.B")
        for r in pool:
            r["f"].update(gap=-1.0, gap_z=-1.0)
        self.assertEqual(audit.picks.p1_gap_go(pool, 1)[1][0]["symbol"], "US.A")
        self.assertEqual(audit.picks.p3_pm_volume_go(pool, 1)[1][0]["symbol"], "US.B")

    def test_current_label_availability_gate_is_retained_and_disclosed(self):
        source, days = synthetic_source()
        source["tables"]["US.AA"]["daily"][days[-1]]["close"] = ""
        self.assertEqual(audit.picks.preopen.build(source, days[-1], days[-1]), [])
        r = row("US.A", days[-1], 1)
        r["y"]["hi_oc"] = None
        self.assertFalse(audit.picks.pools([r], {"US.A": {days[-1]}}))

    def test_existing_output_rejected_before_reading_inputs_or_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, events = Path(tmp) / "out.json", Path(tmp) / "events.jsonl"
            out.touch()
            with patch.object(audit, "verify_inputs") as verify, patch.object(audit, "bounded_pool") as pool:
                with self.assertRaises(FileExistsError):
                    audit.run(out, events)
            verify.assert_not_called()
            pool.assert_not_called()
            self.assertFalse(events.exists())

    def test_low_memory_rejected_before_labels(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(audit, "memory_available_kib", return_value=100), \
                patch.object(audit, "verify_inputs") as verify:
            with self.assertRaises(RuntimeError):
                audit.run(Path(tmp) / "out", Path(tmp) / "events")
            verify.assert_not_called()

    def test_mismatch_preserves_audit_and_does_not_run_second_segment(self):
        pool = {"2024-01-01": [row("US.A", "2024-01-01", 1)]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / audit.ARCHIVE / "reports" / "s22_select_raw.txt"
            original.parent.mkdir(parents=True)
            original.write_text("intentionally unequal synthetic reference\n")
            out, events = root / "out.json", root / "events.jsonl"
            with patch.object(audit, "verify_inputs", return_value={}), \
                    patch.object(audit, "memory_available_kib", return_value=1024 * 1024), \
                    patch.object(audit, "bounded_pool", return_value=(pool, {})) as build, \
                    patch("builtins.print"):
                result = audit.run(out, events, root=root)
            self.assertEqual(build.call_count, 1)
            self.assertEqual(result["status"], "AUDIT_MISMATCH_STOPPED")
            self.assertEqual(list(result["segments"]), ["select"])
            self.assertEqual(result["events"]["count"], 2)
            self.assertEqual(result["events"]["sha256"], audit.sha256(events))
            self.assertEqual(json.loads(out.read_text())["status"], result["status"])


if __name__ == "__main__":
    unittest.main()
