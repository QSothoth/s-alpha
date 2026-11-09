import ast
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from studies.trader_replication import martin_continue_ie15 as m


class IE15Tests(unittest.TestCase):
    def fixture(self):
        days = np.busday_offset('2030-01-01', np.arange(150)).astype(str)
        t = np.arange(len(days), dtype=float)[:, None]
        j = np.arange(9, dtype=float)[None, :]
        close = 30 + t * (.02 + j / 100) + np.sin(t / (2 + j))
        return dict(close=close, opening=close * (1 + .04 * np.sin(t + j)),
                    volume=10000 + 1000 * np.cos(t + j), money=np.full_like(close, 2e8),
                    adr=np.full_like(close, 6.), days=days)

    def test_all_three_scans_ignore_future_rows(self):
        args = self.fixture()
        full = m.scan_ranks(**args)
        for cut in (63, 100, 123):
            prefix = m.scan_ranks(**{k: a[:cut] for k, a in args.items()})
            changed = {k: a.copy() for k, a in args.items()}
            for k, a in changed.items():
                if k != 'days':
                    a[cut:] *= np.arange(1, a.shape[1] + 1) * 50
            future = m.scan_ranks(**changed)
            for k in full:
                np.testing.assert_array_equal(full[k][:cut], prefix[k])
                np.testing.assert_array_equal(full[k][:cut], future[k][:cut])

    def test_grades_and_medium_to_leader_upgrade_are_causal(self):
        close = np.array([10., 10, 12, 12, 12])[:, None]
        e9 = np.array([9., 9, 12, 12, 12])[:, None]
        e21 = np.full_like(close, 10.)
        e50 = np.full_like(close, 9.5)
        weekly = np.full_like(close, 8.)
        grade, upgrade = m.grades(close, e9, e21, e50, weekly)
        self.assertEqual(grade[:, 0].tolist(), [1, 1, 2, 2, 2])
        self.assertEqual(upgrade[:, 0].tolist(), [False, False, True, False, False])
        short = m.grades(*(a[:3] for a in (close, e9, e21, e50, weekly)))
        np.testing.assert_array_equal(short[0], grade[:3])
        np.testing.assert_array_equal(short[1], upgrade[:3])
        grade[0, 0] = 0
        self.assertFalse(m.rolling_any(upgrade, 2)[4, 0])

    def test_weekly_ema_does_not_use_the_unfinished_week(self):
        args = self.fixture()
        full = m.weekly_line(args['close'][:, 0], args['days'])
        for cut in (63, 100, 123):
            np.testing.assert_array_equal(full[:cut], m.weekly_line(args['close'][:cut, 0], args['days'][:cut]))
        self.assertEqual(full[6], full[5])

    def test_recent_list_expires_without_looking_ahead(self):
        hits = np.array([[0, 0], [1, 0], [0, 0], [0, 1], [0, 0]], bool)
        result = m.rolling_any(hits, 2)
        self.assertEqual(result[:, 0].tolist(), [False, True, True, False, False])
        np.testing.assert_array_equal(result[:3], m.rolling_any(hits[:3], 2))

    def test_clusters_use_only_the_supplied_night_and_exclude_self(self):
        t = np.arange(50.)
        history = np.column_stack((np.sin(t), np.sin(t), -np.sin(t), np.cos(t)))
        peers = m.peer_block(history, np.arange(4), np.arange(4))
        self.assertEqual(peers[0, 0], 1)
        self.assertNotIn(0, peers[0])
        scanned = np.array([False, True, False, False])
        upgraded = np.array([False, True, True, False])
        counts = m.cluster_counts(peers, scanned, upgraded)
        self.assertEqual((counts[0][0], counts[1][0]), (1, 1))

    def test_prepared_peer_graphs_ignore_future_prices_and_anchor_changes(self):
        args = self.fixture()
        args['close'][:, 1] = args['close'][:, 0] * 1.02
        load = np.load
        def prepared(a):
            close = a['close']
            fake = SimpleNamespace(days=a['days'], codes=list(range(close.shape[1])),
                    px=dict(close=close, open=a['opening']),
                    f=dict(money=a['money'], adr=a['adr'], e9=close, e21=close * .99, e50=close * .98))
            m.WORK.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=m.WORK) as directory:
                work = Path(directory)
                def cached(path, *args, **kwargs):
                    return a['volume'] if Path(path) == m.old.WORK / 'volume.npy' else load(path, *args, **kwargs)
                with patch.object(m, 'WORK', work), patch.object(m, 'snapshot'), \
                     patch.object(m.old, 'Data', return_value=fake), patch.object(m.old, 'sha', return_value='synthetic'), \
                     patch.object(m.np, 'load', side_effect=cached), patch('builtins.print'):
                    m.prepare()
                return load(work / 'peers.npy').copy()
        full = prepared(args)
        cut = 90
        prefix = prepared({k: a[:cut] for k, a in args.items()})
        changed = {k: a.copy() for k, a in args.items()}
        for k, a in changed.items():
            if k != 'days':
                a[cut:] *= np.arange(1, a.shape[1] + 1) * 50
        future = prepared(changed)
        self.assertTrue((full[:cut] >= 0).any())
        np.testing.assert_array_equal(full[:cut], prefix)
        np.testing.assert_array_equal(full[:cut], future[:cut])

    def test_priority_gives_upgrade_precedence_over_money(self):
        priority = m.priorities(m.REBUILT, np.array([True, False]), np.array([False, False]),
                                np.array([0, 5]), np.array([False, True]),
                                np.array([2e7, 2e9]), np.array([2, 2]))
        self.assertLess(priority[0], priority[1])

    def test_priority_is_identical_when_only_signal_names_are_constructed(self):
        args = (np.array([False, True, False, True]), np.array([True, False, True, False]),
                np.array([1, 3, 0, 5]), np.array([True, False, False, True]),
                np.array([1e8, 2e7, 8e7, 2e8]), np.array([2, 2, 1, 2]))
        indices = np.array([1, 3])
        for name in ('upgrade', 'cluster', 'scan', 'premier', 'leader', 'money'):
            cfg = dict(m.REBUILT, priority=name)
            full = m.priorities(cfg, *args)
            subset = m.priorities(cfg, *(a[indices] for a in args))
            self.assertEqual(subset, [full[j] for j in indices])

    def test_diagnosis_intersects_watch_and_trend_on_the_same_night(self):
        card = dict(rows=[dict(id='synthetic', code='synthetic', bought=False, signal=False, lo=0, hi=1)])
        data = SimpleNamespace(ci={'synthetic': 0})
        built = dict(pool=np.ones((2, 1), bool), watched=np.array([[True], [False]]),
                     trend=np.array([[False], [True]]), signals=dict(long=np.zeros((2, 1), bool)))
        with patch.object(m, 'score', return_value=card), patch.object(m, 'build', return_value=built):
            result = m.diagnosis(data, m.REBUILT, dict(trades=[]), [])
        self.assertEqual(result['card']['rows'][0]['selection_block'], '领涨状态')

    def test_signal_and_order_pipeline_is_unchanged_by_future_prices(self):
        args = self.fixture()
        def data(a):
            close, days = a['close'], a['days']
            px = dict(close=close, open=a['opening'], high=close * 1.06, low=close * .94)
            features = [m.old.features(dict(c=close[:, j], o=px['open'][:, j], h=px['high'][:, j],
                         l=px['low'][:, j], v=a['volume'][:, j], t=a['money'][:, j]), days)
                        for j in range(close.shape[1])]
            f = {key: np.column_stack([r[key] for r in features]) for key in features[0]}
            ranks = m.scan_ranks(**a)
            weekly = np.column_stack([m.weekly_line(close[:, j], days) for j in range(close.shape[1])])
            grade, upgrade = m.grades(close, f['e9'], f['e21'], f['e50'], weekly)
            extra = dict(**ranks, weekly21=weekly, grade=grade, upgrade=upgrade,
                         peers=np.full((*close.shape, 5), -1, np.int16))
            benchmark = dict(close=np.ones(len(days)), e9=np.ones(len(days)), e21=np.ones(len(days)))
            return SimpleNamespace(px=px, f=f, extra=extra, meta=dict(benchmark=[benchmark, benchmark]),
                                   days=days, codes=list(range(close.shape[1])), start=25, end=len(days),
                                   latest=None, built={})
        full = m.build(data(args), m.REBUILT)
        for cut in (90, 120):
            prefix = m.build(data({k: a[:cut] for k, a in args.items()}), m.REBUILT)
            changed = {k: a.copy() for k, a in args.items()}
            for k, a in changed.items():
                if k != 'days':
                    a[cut:] *= 100
            future = m.build(data(changed), m.REBUILT)
            for result in (prefix, future):
                np.testing.assert_array_equal(full['signals']['long'][:cut], result['signals']['long'][:cut])
                self.assertEqual(full['book'][:2 * cut], result['book'][:2 * cut])

    def test_source_contains_no_human_stock_or_entry_date_literals(self):
        labels = m.old.ledger.load(m.old.LEDGER)
        forbidden = {t.ticker for t in labels} | {'US.' + t.ticker for t in labels}
        forbidden |= {t.entry_date for t in labels if t.entry_date}
        for path in (Path(m.__file__), Path(__file__)):
            literals = {n.value for n in ast.walk(ast.parse(path.read_text()))
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            self.assertFalse(literals & forbidden)


if __name__ == '__main__':
    unittest.main()
