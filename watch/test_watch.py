#!/usr/bin/env python3
"""Self-check for the watcher. Runs without futu: `python3 watch/test_watch.py`."""
import importlib.util
import re
import sys
import types
import unittest
from pathlib import Path
from contextlib import ExitStack
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

_futu = types.ModuleType('futu')
_futu.AuType = _futu.KLType = _futu.SubType = type('X', (), {'K_1M': None, 'K_DAY': None, 'NONE': None, 'QFQ': None})
_futu.OpenQuoteContext = object
_futu.RET_OK = 0
sys.modules.setdefault('futu', _futu)
sys.path.insert(0, str(Path(__file__).resolve().parent))

_spec = importlib.util.spec_from_file_location(
    'watcher', __file__.replace('test_watch.py', 'smc_watch.py'))
w = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(w)

NAN = float('nan')


class Frame:
    def __init__(self, rows, name='腾讯控股', last_close=None):
        self.rows = [(name,) + r + (() if last_close is None else (last_close,)) for r in rows]
        self.columns = ['name', 'time_key', 'open', 'high', 'low', 'close', 'volume']
        if last_close is not None:
            self.columns.append('last_close')

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, col):
        return [r[self.columns.index(col)] for r in self.rows]


def stamp(i):
    return '2026-09-21 %02d:%02d:00' % (9 + (30 + i) // 60, (30 + i) % 60)


def fake_bars():
    """Hand-built day: an opening wick sets the high (closes untouched, so the
    EMAs stay low), then a quiet base, then one volume-expansion break of
    structure that lands in the lower part of the range."""
    rows = [(stamp(0), 96.0, 103.0, 95.5, 96.0, 5000.0)]
    closes = ([96.0] * 4 + [95.7, 95.5, 95.6, 95.8, 96.1, 95.9, 95.6, 95.5]
              + [95.6, 95.7, 95.8, 95.9, 96.0, 96.05, 96.1, 96.05]
              + [95.9, 95.8, 95.85, 95.95, 96.05, 96.15, 96.2, 96.25]
              + [96.3, 96.35, 96.4, 96.45])
    for c in closes:
        o = rows[-1][4]
        rows.append((stamp(len(rows)), o, max(o, c) + 0.05, min(o, c) - 0.05, c, 200000.0))
    rows.append((stamp(len(rows)), rows[-1][4], 97.5, rows[-1][4] - 0.05, 97.4, 900000.0))
    for k in range(10):
        o, c = rows[-1][4], 97.4 + 0.01 * k
        rows.append((stamp(len(rows)), o, max(o, c) + 0.05, min(o, c) - 0.05, c, 200000.0))
    return rows


def hot(**kw):
    """An indicator snapshot that already clears the volume gate."""
    d = {'vol_ratio': w.VOL_MULT, 'atr': 1.0, 'close': 100.0,
         'swing_high': None, 'swing_low': None}
    d.update(kw)
    return d


def test_rsi_matches_wilder_on_a_known_series():
    closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
              45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
    assert abs(w.rsi_last(closes) - 70.46) < 0.5, w.rsi_last(closes)


def test_swing_needs_both_sides_confirmed():
    # pullback to 10.9, then a breakout close above it -> BOS must be reachable
    highs = [10, 10.2, 10.1, 10.3, 10.25, 10.9, 10.6, 10.5, 10.4, 10.45, 10.55, 10.95]
    lows = [h - 0.2 for h in highs]
    sh, _sl = w.last_swing(highs, lows)
    assert sh == 10.9, sh
    assert 10.92 > sh  # the original bug returned 10.95 and BOS could never fire


def test_swing_ignores_unconfirmed_right_edge():
    highs = [10, 10.2, 10.1, 10.3, 10.25, 10.4, 10.35, 10.5, 10.45, 10.6, 10.55, 11.0]
    lows = [h - 0.2 for h in highs]
    assert w.last_swing(highs, lows)[0] != 11.0, 'last bar must not be its own swing high'


def test_volume_only_decides_the_tier_not_the_trigger():
    """structure() must stay volume-blind; marks() is what splits vol/plain."""
    bars = [(stamp(i), 100, 101, 99, 100, 1.0) for i in range(5)]
    quiet = hot(vol_ratio=0.1, close=110.0, swing_high=100.0)
    assert 'BOS' in w.structure(bars, quiet)[0]
    assert w.structure(bars, hot(atr=0.0, close=110.0, swing_high=100.0)) == ([], [])


def test_structure_detects_bos_fvg_and_sweep():
    flat = [(stamp(i), 100, 101, 99, 100, 1.0) for i in range(3)]
    assert 'BOS' in w.structure(flat, hot(close=105.0, swing_high=100.0))[0]
    assert 'BOS' in w.structure(flat, hot(close=95.0, swing_low=100.0))[1]
    gap = [(stamp(0), 100, 101, 99, 100, 1.0), (stamp(1), 101, 104, 101, 103, 1.0),
           (stamp(2), 103, 105, 102, 104, 1.0)]          # low[-1] 102 > high[-3] 101
    assert 'FVG' in w.structure(gap, hot(close=104.0))[0]
    wick = [(stamp(i), 100, 101, 99, 100, 1.0) for i in range(2)]
    wick.append((stamp(2), 100, 101, 94.0, 99.0, 1.0))   # pierces 95 then closes back
    assert 'SWEEP' in w.structure(wick, hot(close=99.0, swing_low=95.0))[0]


def test_frame_bars_drops_nan():
    f = Frame([
        ('2026-09-21 09:30:00', 1.0, 1.5, 0.9, 1.2, 100.0),
        ('2026-09-21 09:31:00', 1.2, NAN, 1.1, 1.3, 100.0),
        ('2026-09-21 09:32:00', 1.3, 1.6, 1.2, 1.4, NAN),
    ])
    assert [b[0][-8:] for b in w.frame_bars(f)] == ['09:30:00']


def test_session_bars_keeps_today_and_drops_the_auction():
    now = datetime(2026, 9, 28, 16, 1, tzinfo=w.HKT)
    day = now.strftime('%Y-%m-%d')
    f = Frame([
        ('2026-09-18 15:00:00', 1, 1, 1, 1, 10),   # previous session
        (day + ' 09:30:00', 1, 1, 1, 1, 10),
        (day + ' 15:59:00', 1, 1, 1, 1, 10),
        (day + ' 16:00:00', 1, 1, 1, 1, 10),       # closing auction
    ], last_close=0.9)
    ctx = types.SimpleNamespace(get_cur_kline=lambda *a: (0, f))
    with patch.object(w, 'now_hkt', return_value=now):
        bars, name, previous = w.session_bars(ctx, 'X')
    assert [b[0] for b in bars] == [day + ' 09:30:00', day + ' 15:59:00']
    assert name == '腾讯控股', name
    assert previous == 0.9
    assert w.session_bars(types.SimpleNamespace(get_cur_kline=lambda *a: (-1, 'x')), 'X')[0] is None


def test_session_bars_drops_the_minute_still_forming():
    """OpenD hands back the in-progress bar; a mark fired on it would be emitted
    and then stop being true once the minute completes."""
    now = datetime(2026, 9, 28, 10, 30, 20, tzinfo=w.HKT)
    day = now.strftime('%Y-%m-%d')
    live = now.strftime('%Y-%m-%d %H:%M:00')
    f = Frame([(day + ' 09:30:00', 1, 1, 1, 1, 10), (live, 1, 1, 1, 1, 10)])
    ctx = types.SimpleNamespace(get_cur_kline=lambda *a: (0, f))
    with patch.object(w, 'now_hkt', return_value=now):
        assert [b[0] for b in w.session_bars(ctx, 'X')[0]] == [day + ' 09:30:00']


def test_tencent_m1_maps_ohlc_and_a_share_codes():
    assert w.tencent_symbol('SZ.300795') == 'sz300795'
    assert w.tencent_symbol('300795.SZ') == 'sz300795'
    assert w.tencent_symbol('300795') == 'sz300795'
    assert w.tencent_symbol('SH.600519') == 'sh600519'
    assert w.tencent_symbol('HK.02513') is None
    assert w.canonical_code('HK.02208\udcef\udcbf') == 'HK.02208'
    assert w.canonical_code('sz300795') == 'SZ.300795'
    payload = {'code': 0, 'data': {'sz300795': {
        'qt': {'sz300795': ['51', '米奥会展', '300795']},
        'm1': [['202609221110', '14.09', '14.20', '14.25', '14.08', '896.00', {}, '5.14']],
    }}}
    bars, name = w.parse_tencent_m1(payload, 'sz300795')
    assert name == '米奥会展'
    assert bars == [('2026-09-22 11:10:00', 14.09, 14.25, 14.08, 14.20, 896.0)]


def test_closed_session_drops_yesterday_and_the_live_minute():
    now = datetime(2026, 9, 28, 10, 30, 20, tzinfo=w.HKT)
    day = now.strftime('%Y-%m-%d')
    live = now.strftime('%Y-%m-%d %H:%M:00')
    bars = [
        ('2020-01-01 10:00:00', 1, 1, 1, 1, 1),
        (day + ' 09:30:00', 1, 1, 1, 1, 1),
        (live, 2, 2, 2, 2, 2),
    ]
    with patch.object(w, 'now_hkt', return_value=now):
        assert [b[0] for b in w.closed_session(bars)] == [day + ' 09:30:00']


def test_watch_never_touches_the_trade_api():
    """watch/ is quote-only; custody's own scan does not reach this directory."""
    import ast as _ast
    import pathlib
    forbidden = {'OpenSecTradeContext', 'place_order', 'unlock_trade', 'modify_order'}
    for path in sorted(pathlib.Path(__file__).resolve().parent.glob('*.py')):
        used = set()
        for node in _ast.walk(_ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, _ast.Attribute):
                used.add(node.attr)
            elif isinstance(node, _ast.Name):
                used.add(node.id)
            elif isinstance(node, (_ast.Import, _ast.ImportFrom)):
                used.update(a.name for a in node.names)
        assert not (used & forbidden), (path.name, used & forbidden)


def test_the_fixture_breakout_is_marked_as_volume_confirmed():
    """Guards the whole chain: without this a silent regression (the original
    BOS bug) would pass every other test."""
    ms, _d = w.marks(fake_bars())
    vol = [m for m in ms if m['tier'] == 'vol']
    assert len(vol) == 1, ms
    m = vol[0]
    assert m['side'] == 'BUY' and m['trigger'] == 'BOS', m
    assert m['vol_ratio'] >= w.VOL_MULT and m['pos'] <= w.PREMIUM, m
    assert m['stop'] is not None and m['stop'] < m['close'], m


def turn_bars(new_high_before_break=False):
    """Price stays above VWAP throughout: heavy volume at 90 early, light above.
    Swing high 101 at bar 30, pullback low 99.1, bar 35 wicks to 101.3 and
    closes back under 101, then closes slide until bar 39 closes at 99.0."""
    rows = []
    for k in range(30):
        c = 90 + 0.3 * k
        rows.append((stamp(k), c, c + 0.5, c - 0.5, c, 1e6 if k < 25 else 1e5))
    rows.append((stamp(30), 98.7, 101.0, 98.5, 100.3, 1e5))
    for h, l, c in ((100.4, 99.1, 100.0), (100.2, 99.7, 99.8), (100.0, 99.5, 99.9), (100.1, 99.8, 100.0)):
        rows.append((stamp(len(rows)), rows[-1][4], h, l, c, 1e5))
    rows.append((stamp(35), 100.0, 101.3, 99.9, 100.8, 1e5))
    for c in (100.5, 100.2, 99.9):
        o = rows[-1][4]
        h = 101.5 if new_high_before_break and len(rows) == 37 else max(o, c) + 0.1
        rows.append((stamp(len(rows)), o, h, min(o, c) - 0.1, c, 1e5))
    rows.append((stamp(39), 99.9, 100.0, 98.9, 99.0, 1e5))
    return rows


def test_turn_sells_the_first_break_while_still_above_vwap():
    bars = turn_bars()
    with patch.object(w, 'turn', return_value=None):
        assert not [m for m in w.marks(bars)[0] if m['side'] == 'SELL']
    sells = [m for m in w.marks(bars)[0] if m['side'] == 'SELL']
    assert len(sells) == 1, sells
    m = sells[0]
    assert m['i'] == 39 and m['trigger'] == 'TURN' and m['stop'] == 101.3, m
    assert m['close'] > m['vwap'], m


def test_turn_is_cancelled_by_a_new_high_before_the_break():
    sells = [m for m in w.marks(turn_bars(new_high_before_break=True))[0] if m['side'] == 'SELL']
    assert not sells, sells


def test_bias_and_structure_marks_are_unchanged_by_turn():
    bars = fake_bars()
    full = w.marks(bars)[0]
    with patch.object(w, 'turn', return_value=None):
        old = w.marks(bars)[0]
    assert [m for m in full if 'TURN' not in m['trigger']] == old, (full, old)


def test_flat_volume_leaves_only_plain_marks():
    bars = [(t, o, h, l, c, 10000.0) for t, o, h, l, c, _v in fake_bars()]
    ms = w.marks(bars)[0]
    assert ms, 'plain marks must survive without volume expansion'
    assert {m['tier'] for m in ms} == {'plain'}, ms


def test_volume_ratio_uses_only_the_previous_twenty_bars():
    rows = [(stamp(i), 100, 101, 99, 100, 100.0) for i in range(21)]
    rows[-1] = rows[-1][:-1] + (150.0,)
    assert w.read(rows)['vol_ratio'] == 1.5
    rows[-1] = rows[-1][:-1] + (1000.0,)
    assert w.read(rows)['vol_ratio'] == 10.0
    assert w.read(rows[:1])['vol_ratio'] is None
    zero = [b[:-1] + (0.0,) for b in rows[:-1]] + [rows[-1]]
    assert w.read(zero)['vol_ratio'] is None
    # A zero-volume bar is a real observation when the baseline exists.
    assert w.read(rows[:-1] + [rows[-1][:-1] + (0.0,)])['vol_ratio'] == 0.0
    # No preceding volume must not crash or invent a volume-confirmed mark.
    bars = [b[:-1] + (0.0,) for b in fake_bars()[:34]]
    bars[-1] = bars[-1][:-1] + (900000.0,)
    ms, _ = w.marks(bars)
    assert ms and ms[-1]['vol_ratio'] is None and ms[-1]['tier'] == 'plain'
    assert '0.0x' not in w.mark_text(ms[-1], 100)


def test_same_side_same_tier_waits_fifteen_bars():
    """A steady decline keeps reprinting the same sell. The shipped rule
    drops the reprints inside 15 bars and allows the next one after the gap."""
    def stamp(i):
        return '2026-09-21 %02d:%02d:00' % (9 + (30 + i) // 60, (30 + i) % 60)

    px = 100.0
    bars = []
    for i in range(90):
        px -= 0.15
        bars.append((stamp(i), px + 0.05, px + 0.1, px - 0.1, px, 1000.0))
    ms, _d = w.marks(bars)
    idxs = [m['i'] for m in ms if m['side'] == 'SELL' and m['tier'] == 'plain']
    assert idxs[0] == 25 and 40 in idxs, idxs
    assert all(b - a >= 15 for a, b in zip(idxs, idxs[1:]))
    assert not any(i in idxs for i in range(26, 40))


def test_no_marks_during_the_opening_warmup():
    ms, _d = w.marks(fake_bars())
    assert min(m['i'] for m in ms) >= w.WARMUP_BARS


def test_restart_midday_reproduces_the_same_list():
    """Stateless by construction: marks() must be a pure function of the bars."""
    bars = fake_bars()
    full, _d = w.marks(bars)
    for cut in (30, 36, 40):
        part, _d = w.marks(bars[:cut])
        assert part == [m for m in full if m['i'] < cut], 'cut=%d diverges' % cut


def test_no_bold_marks_only_tick_bound_ones_are_dim():
    """The grade replaced bold (D2): sides are plain capitals; only `~` dims."""
    base = {'t': '10:47', 'side': 'BUY', 'trigger': 'BOS+FVG', 'close': 78.95,
            'vol_ratio': 3.8, 'stop': 77.1, 'tier': 'plain', 'grade': 4}
    for m in (dict(base, daily=True, coarse=False), dict(base, daily=False, coarse=False),
              dict(base, daily=None, coarse=False)):
        line = w.mark_text(m, 100)
        assert w.BOLD not in line and not line.startswith(w.DIM) and w.GREEN + 'B' in line, m
    dim = w.mark_text(dict(base, daily=True, coarse=True), 100)
    assert dim.startswith(w.DIM) and w.BOLD not in dim
    assert ' B4~' in re.sub(r'\x1b\[[0-9;]*m', '', dim)


def test_hk_tick_table_and_a_share_tick():
    for day in ('2025-08-03', '2025-08-04', '2026-08-02', '2026-08-03'):
        assert w.hk_tick(0.25, day) == 0.001 and w.hk_tick(0.5, day) == 0.005
        assert w.hk_tick(100, day) == 0.05 and w.hk_tick(200, day) == 0.1
        assert w.hk_tick(500, day) == 0.2 and w.hk_tick(1000, day) == 0.5
        assert w.hk_tick(2000, day) == 1.0 and w.hk_tick(9000, day) == 5.0
        assert w.hk_tick(10, day) == (0.005 if day >= '2026-08-03' else 0.01)
        assert w.hk_tick(20, day) == (0.01 if day >= '2025-08-04' else 0.02)
        assert w.hk_tick(30, day) == (0.02 if day >= '2025-08-04' else 0.05)
        assert w.hk_tick(50, day) == (0.02 if day >= '2025-08-04' else 0.05)
        assert w.hk_tick(50.05, day) == 0.05
    assert w.a_tick(13.2) == 0.01


def test_tick_density_uses_the_bar_date_not_the_replay_date():
    for day, expected in (('2025-08-03', 1.2), ('2025-08-04', 3.0)):
        bars = [(day + ' 09:30:00', 30, 30, 30, 30, 100),
                (day + ' 09:31:00', 30, 30.06, 30, 30, 100)]
        assert abs(w.ticks_per_bar(bars)[-1] - expected) < 1e-9
        assert abs(w.ticks_per_bar(bars, w.a_tick)[-1] - 6.0) < 1e-9


def test_ticks_per_bar_skips_the_auction_print_and_is_causal():
    bars = [(stamp(0), 96.0, 103.0, 95.5, 96.0, 1.0),          # auction: ignored
            (stamp(1), 96.0, 96.10, 96.0, 96.05, 1.0),          # 2 ticks of 0.05
            (stamp(2), 96.0, 96.20, 96.0, 96.10, 1.0)]          # 4 ticks
    tpb = w.ticks_per_bar(bars)
    assert tpb[0] == 0.0 and abs(tpb[1] - 2.0) < 1e-9 and abs(tpb[2] - 3.0) < 1e-9, tpb
    assert w.ticks_per_bar(bars[:2]) == tpb[:2]


def test_tick_bound_tape_is_shown_but_tagged():
    """Same shape as the fixture, but every bar spans under one tick: the
    marks stay on the board, dimmed and tagged `~`, never hidden."""
    rows = fake_bars()
    squeezed = [rows[0]] + [(t, c, c + 0.01, c - 0.01, c, v) for t, o, h, l, c, v in rows[1:]]
    ms, d = w.marks(squeezed)
    assert ms and all(m['coarse'] and not m['fine'] for m in ms), ms
    assert d['tpb'] < w.GATE_TPB
    line = w.mark_text(ms[0], 100)
    assert line.startswith(w.DIM) and '~' in line
    plain = re.sub(r'\x1b\[[0-9;]*m', '', w.board(
        {'HK.00001': {'bars': squeezed, 'marks': ms, 'read': d}}, w.now_hkt(), 100))
    assert 'muted' not in plain and ms[0]['t'] in plain


def _daily(closes, last_high=11.0, last_low=9.0, today='2026-09-24'):
    rows = [('2026-09-%02d' % (10 + k), c, c + 0.5, c - 0.5, c, 1000.0) for k, c in enumerate(closes)]
    rows[-1] = rows[-1][:2] + (last_high, last_low) + rows[-1][4:]
    rows.append((today, 99.0, 99.0, 99.0, 99.0, 1.0))           # today's forming bar: must be ignored
    return rows


def test_daily_context_uses_only_closed_sessions():
    ctx = w.daily_context(_daily([10, 10, 10, 10, 10, 9.5]), '2026-09-24')
    assert abs(ctx['ret5d'] - (9.5 / 10 - 1)) < 1e-12
    assert ctx['pdh'] == 11.0 and ctx['pdl'] == 9.0 and ctx['day'] == '2026-09-15'
    assert w.daily_context(_daily([10, 10, 10, 10, 9.5]), '2026-09-24') is None   # five closed sessions only


def test_daily_support_is_w6_k5():
    down = w.daily_context(_daily([10, 10, 10, 10, 10, 9.5]), '2026-09-24')   # fell over five sessions
    up = w.daily_context(_daily([10, 10, 10, 10, 10, 10.5]), '2026-09-24')
    buy = {'side': 'BUY', 'close': 10.0}
    sell = {'side': 'SELL', 'close': 10.0}
    assert w.daily_support(buy, down) is True                    # against the week, below yesterday's high
    assert w.daily_support(dict(buy, close=11.5), down) is False  # broke yesterday's high
    assert w.daily_support(buy, up) is False                     # with the week
    assert w.daily_support(sell, up) is True
    assert w.daily_support(dict(sell, close=8.5), up) is False    # broke yesterday's low
    assert w.daily_support(sell, None) is None


def test_daily_context_rejects_bad_prices_without_shifting_the_window():
    good = _daily([10, 10, 10, 10, 10, 9.5])
    for index in (0, 5):
        for column in (2, 3, 4):
            for value in (0.0, -1.0, NAN, float('inf')):
                rows = list(good)
                bad = list(rows[index])
                bad[column] = value
                rows[index] = tuple(bad)
                rows.insert(0, ('2026-09-01', 10, 11, 9, 10, 100))
                assert w.daily_context(rows, '2026-09-24') is None


def test_daily_tag_is_optional_and_shown():
    bars = fake_bars()
    ms, _d = w.marks(bars)
    assert [m['i'] for m in w.with_daily(ms, None)] == [m['i'] for m in ms]
    assert all(m['daily'] is None for m in w.with_daily(ms, None))
    base = {'t': '10:47', 'side': 'BUY', 'trigger': 'BOS', 'close': 10.0, 'vol_ratio': 1.0,
            'stop': 9.9, 'tier': 'plain'}
    assert 'D+' in w.mark_text(dict(base, daily=True), 100)
    assert 'D-' in w.mark_text(dict(base, daily=False), 100)
    none = re.sub(r'\x1b\[[0-9;]*m', '', w.mark_text(dict(base, daily=None), 100))
    assert 'D+' not in none and 'D-' not in none
    broken = types.SimpleNamespace(get_cur_kline=lambda *a: 1 / 0)
    assert w.hk_daily(broken, 'HK.00001') is None


def test_signal_strength_is_joint_and_missing_safe():
    marks = [{'t': '10:47', 'side': 'BUY'}, {'t': '10:47', 'side': 'SELL'}]
    marks[0]['close'] = marks[1]['close'] = 102.0
    scored = w.with_strength(marks, ({'10:47': 102.0}, 100.0), 100.0)
    assert scored[0]['strength'] >= 90
    assert scored[1]['strength'] <= 10
    assert w.with_strength(marks, None, 100.0)[0]['strength'] is None
    assert w.with_strength(marks, ({'10:47': 102.0}, 100.0), None)[0]['strength'] is None
    assert scored[0]['stock_pct'] == 2.0 and scored[0]['hsi_pct'] == 2.0
    assert w.with_strength(marks, None, 100.0)[0]['hsi_pct'] is None
    assert w.with_strength(marks, ({'10:47': 102.0}, 100.0), None)[0]['stock_pct'] is None
    text = re.sub(r'\x1b\[[0-9;]*m', '', w.mark_text(dict(
        scored[0], trigger='BOS', vol_ratio=1, stop=100.0), 100))
    assert '+2.0' not in text and 'S98' not in text      # moves stay in JSON only
    missing = re.sub(r'\x1b\[[0-9;]*m', '', w.mark_text(dict(
        marks[0], trigger='BOS', vol_ratio=1, stop=100.0), 100))
    assert '-/-' not in missing


def test_swing_reference_on_the_wrong_side_is_flagged_not_hidden():
    base = {'t': '10:21', 'trigger': 'FVG', 'close': 599.0, 'vol_ratio': 0.6,
            'daily': True, 'coarse': False}
    def plain(m):
        return re.sub(r'\x1b\[[0-9;]*m', '', w.mark_text(m, 100))
    assert 'ref crossed' in plain(dict(base, side='BUY', stop=599.5))
    assert 'ref crossed' in plain(dict(base, side='BUY', stop=599.0))
    assert 'ref 580.00 -3.2%' in plain(dict(base, side='BUY', stop=580.0))
    assert 'ref crossed' in plain(dict(base, side='SELL', stop=598.0))
    assert 'ref 605.00 +1.0%' in plain(dict(base, side='SELL', stop=605.0))
    assert 'ref -' in plain(dict(base, side='BUY', stop=None))


def test_hsi_session_uses_closed_minutes_and_previous_close():
    rows = [('2026-09-28 10:29:00', 100, 102, 99, 102, 100),
            ('2026-09-28 10:30:00', 102, 103, 101, 103, 100)]
    ctx = types.SimpleNamespace(get_cur_kline=lambda *a: (w.RET_OK, Frame(rows, last_close=100)))
    with patch.object(w, 'now_hkt', return_value=datetime(2026, 9, 28, 10, 30, 20, tzinfo=w.HKT)):
        assert w.hsi_session(ctx) == ({'10:29': 102.0}, 100.0)
    broken = types.SimpleNamespace(get_cur_kline=lambda *a: (w.RET_OK, Frame(rows)))
    assert w.hsi_session(broken) is None


def test_tencent_daily_maps_close_high_low():
    payload = {'data': {'sz300795': {'qfqday': [['2026-09-23', '14.040', '13.500', '14.190', '13.440', '270449.000']]}}}
    assert w.parse_tencent_day(payload, 'sz300795') == [('2026-09-23', 14.04, 14.19, 13.44, 13.5, 270449.0)]


def test_marks_carry_their_tick_density():
    ms, d = w.marks(fake_bars())
    assert ms and all(m['coarse'] == (m['tpb'] < w.GATE_TPB) for m in ms), ms
    assert all(m['fine'] == (m['tpb'] >= w.FINE_TPB) for m in ms)
    assert d['tpb'] >= w.GATE_TPB


def test_board_renders_without_crashing():
    bars = fake_bars()
    ms, d = w.marks(bars)
    out = w.board({'HK.00001': {'bars': bars, 'marks': ms, 'read': d},
                   'HK.00002': {'error': 'no data'}}, w.now_hkt(), 100)
    plain = re.sub(r'\x1b\[[0-9;]*m', '', out)
    assert 'HK.00001' in plain and 'no data' in plain
    assert 'earlier' not in plain
    for m in ms:
        assert m['t'] in plain
    assert 'kline.1m' in plain and 'evt.log' not in plain and 'x' in plain
    assert '盯盘' not in plain and 'BUY' not in plain and 'SELL' not in plain
    assert '┌' not in plain and '█' not in plain
    both = w.board({'HK.00001': {'bars': bars, 'marks': ms, 'read': d, 'name': '甲'},
                    'HK.00002': {'bars': bars, 'marks': ms, 'read': d, 'name': '乙'}},
                   w.now_hkt(), 100)
    both = re.sub(r'\x1b\[[0-9;]*m', '', both)
    head, tail = both.split('HK.00002', 1)
    assert 'HK.00001' in head and re.search(r'\d\d:\d\d', head)
    assert re.search(r'\d\d:\d\d', tail)
    assert '\033[32m' in out and '\033[31m' in out
    for wide in (80, 100):
        rendered = re.sub(r'\x1b\[[0-9;]*m', '', w.board(
            {'HK.00001': {'bars': bars, 'marks': ms, 'read': d, 'name': '腾讯控股'}},
            w.now_hkt(), wide))
        for line in rendered.splitlines():
            assert w.disp_width(line) <= wide, (wide, w.disp_width(line), line)


def test_range_left_uses_latest_checkpoint_and_is_gated():
    import math
    day = '2026-09-28'
    times = ['09:%02d' % m for m in range(30, 60)] + ['10:%02d' % m for m in range(60)] + ['11:00']
    bars, price = [], 100.0
    for k, hm in enumerate(times):
        price += 0.3 if k % 2 else -0.2
        bars.append(('%s %s:00' % (day, hm), price, price + 0.25, price - 0.25, price, 1000.0))
    dctx = {'pdh': 103.0, 'pdl': 99.0, 'pdo': 100.0, 'ret5d': 0.0}
    assert w.range_left(bars[:30], dctx) is None                 # before 10:00
    assert w.range_left(bars, None) is None
    assert w.range_left(bars, dict(dctx, pdo=None)) is None
    r = w.range_left(bars, dctx)
    assert r['cp'] == '11:00'
    cp, minutes, a, b, c, lo, hi = w.RANGE_MODEL[2]
    rv = sum(abs(math.log(bars[k][4] / bars[k - 1][4])) for k in range(1, 91))
    mid = a + b * math.log(rv / minutes) + c * math.log(0.04)
    assert abs(r['half'] - math.exp(mid) * 50) < 1e-9 and r['lo'] < r['half'] < r['hi']
    flat = [(t0, o, o + 0.01, o - 0.01, o, v) for t0, o, h, l, c0, v in bars]
    assert w.range_left(flat, dctx) is None                      # tick-bound tape
    assert w.daily_context([('2026-09-%02d' % d, 10.0 + d, 11.0 + d, 9.0 + d, 10.0 + d, 1.0)
                            for d in range(18, 25)], day)['pdo'] == 34.0
    st = {'bars': bars, 'marks': [], 'read': {'vol_ratio': 1.0}, 'range': r}
    text = re.sub(r'\x1b\[[0-9;]*m', '', '\n'.join(w.symbol_lines('HK.00700', st, 100)))
    assert 'left \u00b1%.2f%%' % r['half'] in text and '@11:00' in text
    text = re.sub(r'\x1b\[[0-9;]*m', '', '\n'.join(w.symbol_lines('HK.00700', dict(st, range=None), 100)))
    assert 'left -' in text


def test_grade_is_one_fixed_scale_and_missing_safe():
    """W27: parts normalized by daily ATR20, so any market reads the same."""
    dctx = {'pdh': 103.0, 'pdl': 97.0, 'pdo': 100.0, 'ret5d': 0.0, 'atr20': 0.02}
    base = {'t': '10:47', 'side': 'BUY', 'trigger': 'BOS', 'close': 102.0, 'stop': 101.0,
            'vol_ratio': 4.0, 'stock_pct': 2.0, 'hsi_pct': 1.0, 'daily': True, 'coarse': False}
    assert w.with_grade([base], dctx, 0.01)[0]['grade'] == 5      # 4x volume, one ATR each
    weak = dict(base, vol_ratio=0.5, stock_pct=-2.0, hsi_pct=-1.0)
    assert w.with_grade([weak], dctx, 0.01)[0]['grade'] == 1
    flat = dict(base, vol_ratio=1.0, stock_pct=0.0, hsi_pct=0.0)    # 1/3, 1/2, 1/2 -> 0.44
    assert w.with_grade([flat], dctx, 0.01)[0]['grade'] == 2
    assert w.with_grade([dict(base, side='SELL')], dctx, 0.01)[0]['grade'] == 1   # volume only; tape against
    # W31 cuts: 3x volume and half an ATR each way is a 4, not yet a 5.
    assert w.with_grade([dict(base, vol_ratio=3.0, stock_pct=1.0, hsi_pct=0.5)], dctx, 0.01)[0]['grade'] == 4
    # Same moves in ATR units grade the same whatever the price or market.
    assert (w.with_grade([dict(base, stock_pct=6.0, hsi_pct=3.0)], dict(dctx, atr20=0.06), 0.03)[0]['grade']
            == w.with_grade([base], dctx, 0.01)[0]['grade'])
    for missing in (dict(base, hsi_pct=None), dict(base, stock_pct=None), dict(base, vol_ratio=None)):
        assert w.with_grade([missing], dctx, 0.01)[0]['grade'] is None
    assert w.with_grade([base], None, 0.01)[0]['grade'] is None
    assert w.with_grade([base], dctx, None)[0]['grade'] is None
    plain = re.sub(r'\x1b\[[0-9;]*m', '', w.mark_text(dict(base, grade=5), 100))
    assert re.search(r' B5 +BOS', plain)
    plain = re.sub(r'\x1b\[[0-9;]*m', '', w.mark_text(dict(base, grade=None, coarse=True), 100))
    assert re.search(r' B\?~ +BOS', plain)


def test_atr20_and_market_routing():
    rows = [('2026-09-%02d' % d, 100.0, 102.0, 98.0, 100.0, 1.0) for d in range(1, 23)]
    assert abs(w.atr20(rows) - 0.04) < 1e-12
    assert w.atr20(rows[:20]) is None
    assert w.daily_context(rows, '2026-09-23')['atr20'] == w.atr20(rows)
    assert w.market('HK.00700') == 'HK' and w.market('US.AAPL') == 'US'
    assert w.market('SZ.300795') == 'A' and w.market(w.INDEX['A']) == 'A'
    assert w.us_tick(150.0) == 0.01 and w.us_tick(0.5) == 0.0001
    payload = {'data': {'sh000300': {'qt': {'sh000300': ['1', 'x', '000300', '4275.68', '4287.98']}}}}
    assert w.tencent_previous(payload, 'sh000300') == 4287.98
    assert w.tencent_previous({}, 'sh000300') is None


def test_us_session_uses_new_york_clock():
    at = datetime(2026, 10, 13, 22, 0, tzinfo=w.HKT)          # 10:00 New York (EDT)
    assert w.bar_stale('US.AAPL', '2026-10-13 09:59:00', at) is False
    assert w.bar_stale('US.AAPL', '2026-10-13 09:50:00', at) is True
    assert w.bar_stale('HK.00700', '2026-10-13 09:50:00', at) is None   # HK is closed then
    with patch.object(w, 'now_hkt', return_value=at):
        bars = [('2026-10-13 09:31:00', 1, 1, 1, 1, 1), ('2026-10-13 09:59:00', 1, 1, 1, 1, 1),
                ('2026-10-13 10:00:00', 1, 1, 1, 1, 1)]
        assert [b[0][11:16] for b in w.closed_session(bars, 'US')] == ['09:31', '09:59']
    late = datetime(2026, 10, 14, 4, 20, tzinfo=w.HKT)          # 16:20 New York
    with patch.object(w, 'now_hkt', return_value=late):
        assert w.closed_session([('2026-10-13 16:00:00', 1, 1, 1, 1, 1)], 'US')


def test_run_counter_marks_repeats_on_one_side():
    base = {'trigger': 'BOS', 'close': 10.0, 'vol_ratio': 1.0, 'stop': 9.9, 'coarse': False, 'grade': 3}
    ms = [dict(base, t='10:00', side='BUY'), dict(base, t='10:20', side='BUY'),
          dict(base, t='10:40', side='BUY'), dict(base, t='11:00', side='SELL', stop=10.1),
          dict(base, t='11:20', side='BUY')]
    bars = [('2026-09-28 11:20:00', 10, 10, 10, 10, 1)]
    text = re.sub(r'\x1b\[[0-9;]*m', '', '\n'.join(
        w.symbol_lines('HK.00700', {'bars': bars, 'marks': ms, 'read': {}}, 100)))
    rows = [line for line in text.splitlines() if line.startswith('  1')]
    assert [bool(re.search(r'#\d', line)) for line in rows] == [False, True, True, False, False]
    assert '#2' in rows[1] and '#3' in rows[2]
    assert text.splitlines()[1].startswith('  left')     # left leads the second line


def test_two_column_rows_fit_their_column():
    bars = fake_bars()
    ms, d = w.marks(bars)
    st = {'bars': bars, 'marks': ms, 'read': d, 'name': '腾讯控股'}
    for line in w.symbol_lines('HK.00700', st, 69):
        assert w._plain_width(line) <= 69, line
    plain = re.sub(r'\x1b\[[0-9;]*m', '', '\n'.join(w.symbol_lines('HK.00700', st, 69)))
    assert 'tpb' in plain and 'n%d' % len(bars) in plain


class PollingTests(unittest.TestCase):
    def run_watch(self, *, seconds=90, codes=('SZ.300795',), quote=None, daily=None):
        elapsed = [0.0]
        base = datetime(2026, 9, 28, 10, 0, tzinfo=w.HKT)
        calls, events, frames = [], [], []
        bars = fake_bars()
        bars[-1] = ('2026-09-28 09:59:00',) + bars[-1][1:]

        def get_quote(code):
            calls.append(('quote', code, elapsed[0]))
            return (quote(code, elapsed[0]) if quote else bars), 'test', None

        def get_daily(code):
            calls.append(('daily', code, elapsed[0]))
            delay, rows = daily(code, elapsed[0]) if daily else (0, None)
            elapsed[0] += delay
            return rows

        def emit(kind, payload):
            calls.append((kind, payload.get('code'), elapsed[0]))
            events.append((kind, payload))

        def frame(state, at, width, rows):
            frames.append({code: dict(st) for code, st in state.items()})
            calls.append(('paint', None, elapsed[0]))
            return ['frame']

        with ExitStack() as stack:
            replacements = {
                'now_hkt': lambda: base + timedelta(seconds=elapsed[0]),
                'close_hkt': lambda: base + timedelta(seconds=seconds),
                'tencent_session': get_quote,
                'index_session': lambda ctx, mkt: None,
                'index_daily': lambda ctx, mkt: None,
                'tencent_daily': get_daily,
                'marks': lambda bars, **kw: ([{'t': '09:59', 'side': 'BUY', 'close': 100}], {}),
                'read': lambda bars: {},
                'emit': emit,
                'log_path': lambda: '/tmp/polling-test-not-written.log',
                'frame_lines': frame,
                'paint': lambda lines, prev, rows: lines,
            }
            for name, value in replacements.items():
                stack.enter_context(patch.object(w, name, value))
            stack.enter_context(patch.object(w.sys, 'argv', ['smc_watch.py', *codes]))
            stack.enter_context(patch.object(w.sys.stdout, 'isatty', return_value=True))
            stack.enter_context(patch.object(w.time, 'monotonic', lambda: elapsed[0]))
            stack.enter_context(patch.object(w.time, 'sleep',
                                            lambda delay: elapsed.__setitem__(0, elapsed[0] + delay)))
            self.assertEqual(w.main(), 0)
        return calls, events, frames

    def test_daily_timeout_follows_output_and_does_not_extend_poll_period(self):
        calls, events, _ = self.run_watch(seconds=360, daily=lambda code, now: (12, None))
        quote_times = [at for kind, code, at in calls if kind == 'quote']
        daily_times = [at for kind, code, at in calls if kind == 'daily']
        self.assertEqual(quote_times, list(range(0, 361, 30)))
        self.assertEqual(daily_times, [0, 330])
        kinds = [kind for kind, _, _ in calls]
        self.assertLess(kinds.index('MARK'), kinds.index('daily'))
        self.assertLess(kinds.index('paint'), kinds.index('daily'))

    def test_only_one_optional_daily_request_per_poll(self):
        calls, _, _ = self.run_watch(codes=('SZ.300795', 'SH.600519'),
                                    daily=lambda code, now: (12, None))
        self.assertEqual([(code, at) for kind, code, at in calls if kind == 'daily'],
                         [('SZ.300795', 0), ('SH.600519', 30)])

    def test_opend_daily_fills_every_symbol_in_one_poll(self):
        ctx = Mock()
        ctx.subscribe.return_value = (w.RET_OK, '')
        rows = [('2026-09-%02d' % day, 100, 101, 99, 100, 100) for day in range(1, 28)]
        asked = []
        def daily(_ctx, code):
            asked.append((code, w.time.monotonic()))
            return rows
        with patch.object(w, 'OpenQuoteContext', return_value=ctx), \
                patch.object(w, 'session_bars', return_value=(fake_bars(), 'test', 99.0)), \
                patch.object(w, 'hk_daily', daily):
            _, events, _ = self.run_watch(seconds=60, codes=('HK.00700', 'HK.01810', 'HK.09988'))
        self.assertEqual([code for code, _ in asked], ['HK.00700', 'HK.01810', 'HK.09988'])
        self.assertEqual(len({at for _, at in asked}), 1)
        self.assertEqual(sum(kind == 'DAILY_CONTEXT' for kind, _ in events), 3)

    def test_daily_retries_do_not_starve_later_symbols(self):
        codes = tuple('SZ.%06d' % i for i in range(1, 13))
        calls, _, _ = self.run_watch(seconds=390, codes=codes)
        first_requests = [(code, at) for kind, code, at in calls if kind == 'daily'][:12]
        self.assertEqual(first_requests, list(zip(codes, range(0, 360, 30))))

    def test_optional_daily_subscription_exception_keeps_quotes_running(self):
        ctx = Mock()
        ctx.subscribe.side_effect = [(w.RET_OK, ''), RuntimeError('daily unavailable')]
        with patch.object(w, 'OpenQuoteContext', return_value=ctx), \
                patch.object(w, 'session_bars', return_value=(fake_bars(), 'test', 99.0)), \
                patch.object(w, 'hk_daily', return_value=None):
            _, events, _ = self.run_watch(seconds=0, codes=('HK.00700',))
        self.assertTrue(any(kind == 'MARK' for kind, _ in events))
        self.assertFalse(any(kind == 'FAILED' for kind, _ in events))
        ctx.close.assert_called_once()

    def test_stale_is_per_symbol_and_recovers_when_bars_resume(self):
        def quote(code, elapsed):
            if code == 'SZ.300795' and elapsed < 60:
                stamp = '2026-09-28 09:40:00'
            else:
                stamp = (datetime(2026, 9, 28, 9, 59) + timedelta(seconds=elapsed)).isoformat(' ')
            return [(stamp, 100, 101, 99, 100, 100)]

        _, events, frames = self.run_watch(codes=('SZ.300795', 'SH.600519'), quote=quote)
        health = [(kind, payload['code']) for kind, payload in events
                  if kind in ('STALE', 'RECOVERED')]
        self.assertEqual(health, [('STALE', 'SZ.300795'), ('RECOVERED', 'SZ.300795')])
        self.assertTrue(frames[0]['SZ.300795']['stale'])
        self.assertFalse(frames[0]['SH.600519']['stale'])
        self.assertFalse(frames[-1]['SZ.300795']['stale'])

    def test_daily_context_arrives_after_initial_mark(self):
        rows = [('2026-09-%02d' % day, 100, 101, 99, 100, 100) for day in range(18, 24)]
        calls, events, frames = self.run_watch(daily=lambda code, now: (12, rows))
        mark = next(payload for kind, payload in events if kind == 'MARK')
        self.assertIsNone(mark['daily'])
        context = [payload for kind, payload in events if kind == 'DAILY_CONTEXT']
        self.assertEqual(len(context), 1)
        self.assertEqual(context[0]['code'], 'SZ.300795')
        self.assertTrue(frames[1]['SZ.300795']['marks'][0]['daily'])
        self.assertEqual([at for kind, _, at in calls if kind == 'paint'][:2], [0, 12])

    def test_starting_at_deadline_still_adds_daily_context_for_every_symbol(self):
        codes = ('SZ.300795', 'SH.600519')
        rows = [('2026-09-%02d' % day, 100, 101, 99, 100, 100) for day in range(18, 24)]
        calls, events, frames = self.run_watch(seconds=0, codes=codes,
                                               daily=lambda code, now: (12, rows))
        self.assertEqual([code for kind, code, _ in calls if kind == 'daily'], list(codes))
        self.assertEqual([payload['code'] for kind, payload in events if kind == 'DAILY_CONTEXT'],
                         list(codes))
        self.assertTrue(all(frames[-1][code]['marks'][0]['daily'] for code in codes))
        self.assertEqual([at for kind, _, at in calls if kind == 'paint'], [0, 24])

    def test_closed_session_excludes_current_and_future_end_labels(self):
        at = datetime(2026, 9, 28, 10, 30, 20, tzinfo=w.HKT)
        bars = [(stamp, 1, 1, 1, 1, 1) for stamp in (
            '2026-09-27 10:29:00', '2026-09-28 10:29:00',
            '2026-09-28 10:30:00', '2026-09-28 10:31:00')]
        with patch.object(w, 'now_hkt', return_value=at):
            self.assertEqual(w.closed_session(bars), [bars[1]])

    def test_stale_checks_pause_outside_trading_and_after_reopening(self):
        for code, day, hour, minute in (
            ('HK.00700', 28, 9, 0), ('HK.00700', 28, 12, 15),
            ('HK.00700', 28, 13, 1), ('HK.00700', 28, 16, 0),
            ('SZ.300795', 28, 11, 30), ('SZ.300795', 28, 15, 0),
            ('HK.00700', 27, 10, 0),
        ):
            at = datetime(2026, 9, day, hour, minute, tzinfo=w.HKT)
            self.assertIsNone(w.bar_stale(code, '2026-09-28 09:30:00', at))
        at = datetime(2026, 9, 28, 13, 3, tzinfo=w.HKT)
        self.assertTrue(w.bar_stale('HK.00700', '2026-09-28 12:00:00', at))
        self.assertFalse(w.bar_stale('HK.00700', '2026-09-28 13:02:00', at))

    def test_board_shows_data_time_and_stale_with_unknown_volume_ratio(self):
        bars = [('2026-09-28 10:29:00', 100, 101, 99, 100, 100)]
        lines = w.symbol_lines('HK.00700', {'bars': bars, 'marks': [],
                               'read': {'vol_ratio': None}, 'stale': True}, 80)
        text = re.sub(r'\x1b\[[0-9;]*m', '', '\n'.join(lines))
        self.assertIn('data 10:29', text)
        self.assertIn('STALE', text)
        self.assertNotIn('0.0x', text)


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for t in tests:
        t()
        print('ok', t.__name__)
    print('%d passed' % len(tests))
    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(PollingTests))
    if not result.wasSuccessful():
        sys.exit(1)
