"""Martin Luk through the generic loop (study.py), as its self-check: the study's own replicate.py builds the
system, this module only adapts it.  Reads studies/martin_luk/reports, writes to data/trader-replication-selftest
(never into the Martin study).

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.trader_replication.martin diagnose r74.json
    $PY -m studies.trader_replication.martin final r74.json
    $PY -m studies.trader_replication.martin check            # compare with the committed R74 reports
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from . import study

ROOT = Path(__file__).resolve().parents[2]


class Martin(study.Study):
    id, name = 'martin_luk', 'Martin Luk'
    root = ROOT / 'studies' / 'martin_luk'
    ledger = root / 'notes' / 'trades.csv'
    cutoff = '2026-04-01'
    full = ('2024-01-02', '2026-10-16')

    @property
    def R(self):
        from studies.martin_luk import replicate
        return replicate

    @property
    def his(self):
        return self.R.HIS

    @property
    def out(self):
        return ROOT / 'data' / 'trader-replication-selftest'

    unified = False                 # True: the common data layer (panels) instead of the R74 research panels

    def arrays(self, market, upto=None, mode=None):
        if self.unified or upto is not None or mode is not None:
            from . import panels
            b = panels.load(market, upto, mode)
            A = self.R.market_arrays(market, b)
            A['digest'] = b['digest']
            return A
        return self.R.market_arrays(market)

    def market_gate(self, A, cfg):
        if cfg.get('filter') in (None, '', 'NONE'):
            return None
        pool, w, _ = self.R.system_signals(A, cfg)
        return self.R.market_ok(A, pool, w, cfg['filter'])

    def build(self, A, cfg, trace=None):
        return self.R.build_system(A, cfg, trace)

    daily_cap = 'build'             # build_system keeps the day's first max_new entries before the engine

    def ep_mask(self, A, cfg):
        """His pre-market gapper EP as build_system makes it (on the liquidity pool, not the leader list)."""
        return self.R.ep_signal(A, self.R.pool_for(A, cfg.get('pool')), **cfg.get('ep_opts', {}))

    def own_floor(self, cfg, turnover, price):
        """His pool is a POOLS entry (price, turnover, ADR): the same ADR with the lower floors."""
        R = self.R
        p, t, a = R.POOLS[cfg.get('pool') or R.chosen('r20_pool.json', 'U0')]
        spec = (min(p, price), min(t, turnover), a)
        name = next((k for k, v in R.POOLS.items() if v == spec), None)
        if name is None:
            name = f'C{spec[0]:g}_{spec[1]:g}_{spec[2]:g}'
            R.POOLS[name] = spec
        return dict(cfg, pool=name)

    def own_stop_off(self, cfg, mode):
        """His min(5%, 0.5 ADR) is built into his entries: the common rule's mode picks 'cap' (move up) or 'skip';
        a tighter common limit then applies on top."""
        return dict(cfg, stop='skip' if mode == 'skip' else 'cap')

    def short_setups(self, A, sc):
        return self.R.short_setups(A, sc)

    def named(self, A, pool, name):
        if name == 'w9':
            return self.R.weekly_ema(A['close'], A['days'], 9)
        return self.R.named_signal(A, pool, name)

    def pool_dependent(self, name):
        return name.startswith('idx_')

    def robust_variants(self, cfg):
        """The neighbours replicate.robust uses."""
        return {'base': {}, 'max_new 3': {'max_new': 3}, 'max_new 5': {'max_new': 5},
                'risk x0.8': {'risk': cfg['risk'] * .8, 'risk_high': cfg.get('risk_high', 0) * .8},
                'risk x1.2': {'risk': cfg['risk'] * 1.2, 'risk_high': cfg.get('risk_high', 0) * 1.2},
                'max_position .4': {'max_position': .4}, 'max_position .6': {'max_position': .6},
                'gross 2.4': {'gross': 2.4}, 'gross 3.2': {'gross': 3.2},
                'stop_min .008': {'stop_min': .008}, 'stop_min .012': {'stop_min': .012},
                'no adds': {'rule_opts': {'add_r': 0.0, 'add_levels': []}},
                'no risk scale': {'rule_opts': {'risk_scale': ''}},
                'no climax exit': {'rule_opts': {'exit_signal': ''}},
                'costs x2': {'rule_opts': {'buy_cost': .001, 'sell_cost': .001}}}

    def his_entry(self, A, d, j, cfg):
        """His ticker on his day through the system's own stop rule (close fill, day-low stop capped at
        min(5%, half ADR), at least 1%)."""
        mask = np.zeros(A['close'].shape, bool)
        mask[d, j] = True
        e = self.R.entries_close_stop(A, mask, cfg['stop'], kind='his', cap_max=cfg.get('stop_cap_max', .05),
                                      stop_min=cfg.get('stop_min', 0.0))[d]
        return e[0] if e else None


def compare(a, b, path='', tol=1e-9, out=None):
    """Differences between two JSON trees (numbers within tol); keys only in `b` (the generic output) are extras."""
    out = [] if out is None else out
    if isinstance(a, dict):
        for k in a:
            if k not in b:
                out.append(f'{path}.{k}: missing')
            else:
                compare(a[k], b[k], f'{path}.{k}', tol, out)
    elif isinstance(a, list):
        if not isinstance(b, list) or len(a) != len(b):
            out.append(f'{path}: list length {len(a)} vs {len(b) if isinstance(b, list) else type(b)}')
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                compare(x, y, f'{path}[{i}]', tol, out)
    elif isinstance(a, float) or isinstance(b, float):
        if a is None or b is None or not np.isclose(a, b, rtol=tol, atol=tol, equal_nan=True):
            out.append(f'{path}: {a} vs {b}')
    elif a != b:
        out.append(f'{path}: {a!r} vs {b!r}')
    return out


def check():
    s = Martin()
    res = {}
    pairs = [('diagnose_r74.json', 'diagnose_r74.json'), ('final_r74.json', 'final_system_r74.json'),
             ('robust_r74.json', 'robust_r74.json')]
    for mine, theirs in pairs:
        if not (s.out / mine).exists():
            continue
        a = json.loads((s.reports / theirs).read_text())
        b = json.loads((s.out / mine).read_text())
        diff = compare(a, b)
        res[theirs] = diff
        print(theirs, 'identical' if not diff else f'{len(diff)} differences', *diff[:20], sep='\n  ')
    return res


if __name__ == '__main__':
    if sys.argv[1] == 'check':
        check()
    else:
        study.main(Martin(), sys.argv)
