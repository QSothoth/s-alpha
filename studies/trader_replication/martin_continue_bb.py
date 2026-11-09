"""Continuation BB: audit historical forward-adjustment normalization."""
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np

from studies import trader_data
from studies.trader_data import panel
from . import system, systems
from .martin_continue_a import required_fields
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, name_score, u1_entries


def reanchor(p):
    close, raw = p['close'], p['raw_close']
    scale = np.ones(close.shape[1], dtype=np.float64)
    missing = 0
    for j in range(close.shape[1]):
        valid = np.flatnonzero(np.isfinite(close[:, j]) & np.isfinite(raw[:, j]) & (close[:, j] > 0) & (raw[:, j] > 0))
        if not len(valid):
            missing += 1
            continue
        d = valid[-1]
        scale[j] = float(raw[d, j]) / float(close[d, j])
    for name in ('open', 'high', 'low', 'close'):
        p[name] *= scale[None, :]
    p['volume'] /= scale[None, :]
    return {'missing_anchor': missing, 'changed_anchor': int(np.sum(np.abs(scale - 1) > 1e-6))}


def data_with_system(selected, factory=Data):
    original_get = systems.get
    with patch.object(systems, 'get', side_effect=lambda name: selected if name == 'martin_luk' else original_get(name)):
        return factory()


def main(cut, mode):
    if mode not in ('full', 'normal', 'reanchored'):
        raise ValueError('mode must be full, normal or reanchored')
    selected = systems.get('martin_luk')
    wrapper, _ = selected.load()
    base = getattr(wrapper, 'base', wrapper)
    summary = {}

    def arrays(market):
        p = panel.build(trader_data.frozen(market), upto=None if mode == 'full' else cut, write_cache=False)
        if mode == 'reanchored':
            summary.update(reanchor(p))
        A = base.R.market_arrays(market, p)
        A['digest'] = p['digest']
        return A

    base.arrays = arrays
    D = data_with_system(selected)
    if D.base is not base or (D.days[-1] <= cut if mode == 'full' else D.days[-1] != cut):
        raise AssertionError('actual Data instance has the wrong panel or cutoff')
    if mode == 'reanchored' and not summary:
        raise AssertionError('reanchoring was not executed')
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    entries = u1_entries(D, F, H, score)
    del F, M, score, H
    signals = {}
    for d, row in enumerate(entries):
        if '2024-01-02' <= D.days[d] <= cut:
            signals[D.days[d]] = [[int(e[1]), int(e[2]), e[5], round(float(e[4] / e[3]), 5)]
                                  for e in sorted(row, key=lambda x: x[0])]
    rules = f1_rules(D, 6, (1, 3))
    px, ema = D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, rules)
    track = {}
    curve, dates, trades = system.simulate(px, ema, rules, entries, '2024-01-02', cut, track=track)
    st = system.stats(curve, dates, trades)
    trade_keys = [[t['code'], t['side'], t['kind'], t['entry'], t['exit'], t['why']] for t in trades]
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_bb.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py',
             'studies/trader_data/panel.py', 'studies/trend_breakout/panel.py')
    out = dict(dataset_digest=D.A['digest'], cutoff=cut, mode=mode, reanchor_summary=summary,
               signals=signals, trade_keys=trade_keys, curve=curve.tolist(), dates=[str(x) for x in dates],
               by_year=st['by_year'], maxdd=st['maxdd'], max_close_positions=max(track['open']),
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review' / f'strong_continue_bb_{mode}_{cut}.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    print(mode, cut, summary, st['by_year'], len(trades), flush=True)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
