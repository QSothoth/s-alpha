"""R17 (notes/PREREG_R17.md): whole-market daily system, W2 watchlist + close-confirmed entries, three markets.

    nice -n 19 /opt/opend-us-options/.venv/bin/python -m studies.martin_luk.r17
"""
from __future__ import annotations

from dataclasses import replace
import json

import numpy as np

from . import intraday as I, luk, selection as S

CANDS = {'G1': dict(g='G1'), 'G2': dict(g='G2'), 'G3': dict(g='G3', adr_cap_mult=1.0),
         'G4': dict(g='G1', trail='e21'), 'G5': dict(g='G1', market_filter=True)}
SEL, VAL = ('2024-01-02', '2024-12-31'), ('2025-01-02', '2026-10-16')


def panel_for(market):
    if market == 'us':
        b = S.broad()
        return {'dates': b['days'], 'codes': b['codes'], **{k: b[k].astype(float) for k in
                ('open', 'high', 'low', 'close', 'turnover', 'raw_close')}}
    return luk.load(market)


def watch(p, ind, market):
    c = p['close']
    to20 = luk.rolling_mean(p['turnover'], 20)
    with np.errstate(invalid='ignore', divide='ignore'):
        pool = ((p['raw_close'] >= 1) & (to20 >= 2e6)) if market == 'us' else np.isfinite(c)
        n = np.zeros(c.shape, np.int8)
        for hz in (21, 63, 126):
            r = np.where(pool, c / luk.lag(c, hz) - 1, np.nan)
            n += (pool & (r >= np.nanquantile(r, .98, axis=1)[:, None])).astype(np.int8)
        return S._past_any(n >= 2, 20) & (ind['adr'] >= 4)


def run(p, ind, market, cand, seg, placebo=0):
    cfg = replace(luk.Config(market=market), **CANDS[cand])
    orders, closes = luk.signals(p, ind, cfg)
    curve, dates, tr = luk.simulate(p, ind, cfg, *seg, orders, closes)
    st = luk.stats(curve, dates, tr)
    r = np.array([t['r'] for t in tr]) if tr else np.zeros(1)
    res = dict(total=float(st['total']), cagr=float(st['cagr']), maxdd=float(st['maxdd']), trades=len(tr),
               win=float(st['win']), avg_win=float(st['avg_win']), avg_loss=float(st['avg_loss']), exp_r=float(r.mean()),
               days_win=float(st['days_win']), bench=luk.benchmark(ind, p['dates'], *seg),
               by_year={k: float(v) for k, v in st['by_year'].items()})
    if placebo:
        boots = np.random.default_rng(0).choice(r, (2000, len(r))).mean(axis=1)
        rng = np.random.default_rng(1)
        pl = np.array([luk.simulate(p, ind, cfg, *seg, orders, closes, placebo=rng)[0][-1] - 1 for _ in range(placebo)])
        res.update(ci=[float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
                   placebo_median=float(np.median(pl)), placebo_p90=float(np.percentile(pl, 90)),
                   placebo_rank=float((pl < st['total']).mean()))
    return res


def main():
    out = {}
    chosen = None
    for market in ('us', 'hk', 'cn'):
        p = panel_for(market)
        ind = luk.indicators(p, replace(luk.Config(market=market), adr_min=4.0))
        ind['_close'] = p['close']
        ind['leader'] = watch(p, ind, market)
        out[market] = {'select': {}, 'validate': {}}
        for cand in CANDS:
            out[market]['select'][cand] = run(p, ind, market, cand, SEL)
            print(market, 'select', cand, {k: (round(v, 3) if isinstance(v, float) else v)
                                           for k, v in out[market]['select'][cand].items()}, flush=True)
        if chosen is None:
            chosen = max(CANDS, key=lambda c: out['us']['select'][c]['total'])
        out[market]['validate'][chosen] = run(p, ind, market, chosen, VAL, placebo=100)
        print(market, 'validate', chosen, {k: (round(v, 3) if isinstance(v, float) else v)
                                           for k, v in out[market]['validate'][chosen].items()}, flush=True)
        del p, ind
    v = out['us']['validate'][chosen]
    out['chosen'] = chosen
    out['passed_us'] = bool(v['total'] > v['bench'] and v['ci'][0] > 0 and v['total'] > v['placebo_p90'])
    print('chosen', chosen, 'passed (US)', out['passed_us'])
    (I.OUT / 'r17_daily_system.json').write_text(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
