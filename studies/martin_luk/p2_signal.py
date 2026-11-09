"""P2 market-only signal facade; evaluation labels are never inputs here."""
from __future__ import annotations

import csv
import hashlib
import json
from itertools import zip_longest
from pathlib import Path

import numpy as np

from studies.trader_replication import regime
from studies.trader_replication.study import Study

ROOT = Path(__file__).resolve().parents[2]
HOME = Path(__file__).resolve().parent


def benchmarks():
    series = {}
    for code in ('US.QQQ', 'US.IWM'):
        path = ROOT/'data/martin-luk-benchmarks-v1'/f'{code}.csv'
        with path.open() as stream:
            rows = list(csv.DictReader(stream))
        days = np.array([r['time_key'][:10] for r in rows])
        if series and not np.array_equal(days, calendar):
            raise ValueError('benchmark calendars differ')
        calendar = days
        series[code] = {k: np.array([float(r[k]) for r in rows]) for k in ('close', 'high', 'low')}
        if any(not np.all(np.isfinite(v) & (v > 0)) for v in series[code].values()):
            raise ValueError('benchmark contains missing prices')
    return dict(days=calendar, indices=series)


def confirm(raw, length=3):
    """Publish only after length consecutive observations; never backfill."""
    out = np.full(len(raw), regime.PULLBACK, np.int8)
    current, pending, count = regime.PULLBACK, None, 0
    for t, state in enumerate(raw):
        if state == pending:
            count += 1
        else:
            pending, count = state, 1
        if count >= length:
            current = state
        out[t] = current
    return out


def market_states(A, producer='idx_ema', confirmation=3, **changes):
    options = regime.spec(dict(producer=producer, source='US.QQQ', **changes))
    # states() already lags raw observations once; confirmation commutes with
    # that lag because the initial unknown state is pullback in both stages.
    labels = confirm(regime.states(A, options)['label'], confirmation)
    spec = dict(options, confirmation=confirmation, auxiliary='lag1(IWM/QQQ > (IWM/QQQ)[-21])',
                data='martin-luk-benchmarks-v1', version=2)
    fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    q, i = (A['indices'][c]['close'] for c in ('US.QQQ', 'US.IWM'))
    ratio = i/q
    strong = np.zeros(len(ratio), bool)
    strong[22:] = ratio[21:-1] > ratio[:-22]
    return dict(label=labels, episodes=regime.episodes(labels, A['days']), spec=spec,
                spec_sha=fingerprint, iwm_strong=strong)


class P2Signals(Study):
    """Signal-only research. Never call build/allocate/trade for this task."""
    id, name, root = 'martin_luk_p2', 'Martin Luk P2', HOME

    def arrays(self, market='us', upto=None, mode='frozen'):
        if market != 'us' or mode != 'frozen':
            raise ValueError('P2 uses only local frozen US signals')
        panel = HOME/'reports/u1_work/panel'
        days, codes = (np.load(panel/f'{name}.npy', mmap_mode='r') for name in ('days', 'codes'))
        stop = len(days) if upto is None else int(np.searchsorted(days, upto, side='right'))
        A = dict(days=days[:stop], codes=codes, market=market, mode=mode,
                 close=np.load(panel/'close.npy', mmap_mode='r')[:stop])
        paths = dict(ie9=HOME/'reports/s0_work/picks/IE9.json',
                     h1=HOME/'reports/s0_work/picks/H1A_signals.json',
                     raw_ie9=HOME/'reports/p2a_work/market/IE9_order.json',
                     h1_pool=HOME/'reports/p2a_work/market/H1A_pool.json')
        A.update({key: json.loads(path.read_text()) for key, path in paths.items()})
        ci = {str(c): j for j, c in enumerate(codes)}
        eligible = np.zeros(A['close'].shape, bool)
        for t, day in enumerate(A['days'][:-1]):
            names = set(A['raw_ie9'].get(str(day), [])) | set(A['h1_pool'].get(str(day), []))
            for code in names:
                if code in ci:
                    eligible[t+1, ci[code]] = True
        A['eligible'] = eligible
        A['unknown_source_names'] = sorted({code for key in ('ie9', 'h1', 'raw_ie9')
            for row in A[key].values() for code in row if code not in ci})
        return A

    def universe(self, A, cfg):
        return A['eligible']

    def signal(self, A, pool, cfg):
        options = cfg['signal']
        ci = {str(c): j for j, c in enumerate(A['codes'])}
        result = {}
        for t, day in enumerate(A['days']):
            day = str(day)
            merged = merge_night(A['ie9'].get(day, []), A['raw_ie9'].get(day, []), A['h1'].get(day, []),
                                 options['merge'])
            # pool[d] is known before session d. Tonight t's pool is therefore
            # pool[t+1], formed with observations available at this close.
            result[t] = [c for c in merged if c in ci and t+1 < len(pool) and pool[t+1, ci[c]]][:options['native_max']]
        return result


def merge_night(native, raw, theme, mode):
    def zipper(left, right):
        return [c for pair in zip_longest(left, right) for c in pair if c is not None]
    if mode == 'native_zip':
        ordered = zipper(native, theme)
    elif mode == 'raw_ie9':
        ordered = list(raw)
    elif mode == 'raw_zip':
        ordered = zipper(raw, theme)
    elif mode == 'theme_first':
        ordered = zipper(theme, raw)
    elif mode == 'agreement':
        scope = set(raw)
        ordered = [c for c in theme if c in scope]+zipper(raw, theme)
    else:
        raise ValueError('unknown frozen merge mode: '+mode)
    return list(dict.fromkeys(ordered))
