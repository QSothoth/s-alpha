"""Daily Top-N long / Top-N short among option-active single stocks - the deliverable.  Read-only; no history-kline quota.

Prefilter (point-in-time, all from T-1 and earlier): the 300 option-active stocks of notes/universe_stocks300.json, previous
close >= 3, 20-day mean turnover >= 5M, T-1 option volume >= 2,000 contracts; "unusual" marks T-1 option volume >= 1.5x its
20-day mean.  Ranking: the S26 composite z(Put/Call z) - z(IV - HV) + z(close location), same code as the backtest
(preopen.build + topn.composite_scores; today's bar is a placeholder the composite never reads).

Measured (reports/RESULTS_CN.md, S26, Top 5 / Bottom 5 baskets, open -> close):
  selection 2023-08..2024-12: long-minus-short +63bp/day gross, 55% of days positive;
  validation 2025-01..2026-09 (one shot): +17bp/day gross, 54% of days positive, NOT significant and below a 20bp cost.
The list is a ranking without a validated edge; direction and execution stay with the user's intraday strategy.

    /opt/futu-opend/venv/bin/python studies/us_preopen_bias/code/daily_top.py [--n 3] [--date YYYY-MM-DD]
"""
import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preopen  # noqa: E402
import topn  # noqa: E402

HERE = Path(__file__).resolve().parents[1]
EXCLUDE = ('US.BRK', 'US.SPCX', 'US.B')   # failed the Yahoo cross-check


def with_placeholder(daily, T):
    """Append a placeholder bar for T (open = high = low = close = previous close) so preopen.build emits T's row;
    every feature the composite uses comes from T-1 and earlier."""
    days = sorted(d for d in daily if d < T)
    if not days:
        return daily
    pc = daily[days[-1]]['close']
    out = {d: v for d, v in daily.items() if d < T}
    out[T] = {'date': T, 'open': pc, 'high': pc, 'low': pc, 'close': pc, 'volume': '0', 'turnover': '0'}
    return out


def rank_today(tables, nominal, T, n):
    """tables: {sym: {'daily', 'opt', 'iv'}} in preopen.load shape (dates < T); nominal: {sym: {date: (c, h, l, turnover)}}."""
    data = {'symbols': sorted(tables), 'market': {},
            'tables': {s: {'daily': with_placeholder(t['daily'], T), 'opt': t['opt'], 'iv': t['iv'], 'sv': {}, 'cf': {}, 'ext': {}}
                       for s, t in tables.items()}}
    rows = preopen.build(data, T, T)
    nom = {s: dict(v, **{T: (0.0, 0.0, 0.0, 0.0)}) for s, v in nominal.items()}   # T itself is never read by the gate
    gate = {s: topn.gate_days(v) for s, v in nom.items()}
    pools = topn.active_pools(rows, gate)
    pool = pools.get(T, [])
    sc = topn.composite_scores(pool)
    ranked = sorted((r for r in pool if id(r) in sc), key=lambda r: (sc[id(r)], r['symbol']))
    return pool, sc, ranked[::-1][:n], ranked[:n]


def rank_volatile_half(pool, sc, n):
    """The same composite, restricted to the half of the pool with the higher implied daily move (options-friendly)."""
    half = topn.iv_half({'T': pool})['T']
    xs = sorted((r for r in half if id(r) in sc), key=lambda r: (sc[id(r)], r['symbol']))
    return xs[::-1][:n], xs[:n]


def premarket(ctx, ft, codes):
    """{code: (pre-market price, pre-market volume)} from a snapshot; empty when the fields are missing."""
    out = {}
    for i in range(0, len(codes), 300):
        r = ctx.get_market_snapshot(codes[i:i + 300])
        if r[0] != ft.RET_OK or 'pre_price' not in r[1].columns:
            continue
        for x in r[1].itertuples():
            try:
                out[x.code] = (float(x.pre_price), float(getattr(x, 'pre_volume', 0) or 0))
            except (TypeError, ValueError):
                pass
    return out


def main():
    import logging
    logging.disable(logging.CRITICAL)
    import futu as ft
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=3)
    ap.add_argument('--date', default=None, help='trade date T (ET); default today')
    ap.add_argument('--dump', default=None, help='also write every pool name with its score to this JSON file')
    a = ap.parse_args()
    T = a.date or datetime.now(timezone(timedelta(hours=-4))).date().isoformat()
    uni = [x['code'] for x in json.load(open(HERE / 'notes' / 'universe_stocks300.json', encoding='utf-8'))['symbols']
           if x['code'] not in EXCLUDE]
    t0 = date.fromisoformat(T)
    ctx = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
    tables, nominal, errors = {}, {}, []
    try:
        for i in range(0, len(uni), 100):   # K_DAY subscription in batches, released after each
            part = uni[i:i + 100]
            ctx.subscribe(part, [ft.SubType.K_DAY], subscribe_push=False)
            tb = time.time()
            for s in part:
                bars = {}
                for au, key in ((ft.AuType.QFQ, 'q'), (ft.AuType.NONE, 'n')):
                    time.sleep(0.3)
                    r = ctx.get_cur_kline(s, 60, ft.SubType.K_DAY, au)
                    bars[key] = r[1] if r[0] == ft.RET_OK else None
                if bars['q'] is None or bars['n'] is None:
                    errors.append(s)
                    continue
                tables[s] = {'daily': {str(x.time_key)[:10]: {'date': str(x.time_key)[:10], 'open': x.open, 'high': x.high,
                                                              'low': x.low, 'close': x.close, 'volume': x.volume,
                                                              'turnover': x.turnover}
                                       for x in bars['q'].itertuples() if str(x.time_key)[:10] < T}}
                nominal[s] = {str(x.time_key)[:10]: (x.close, x.high, x.low, x.turnover)
                              for x in bars['n'].itertuples() if str(x.time_key)[:10] < T}
            time.sleep(max(0, 65 - (time.time() - tb)))
            ctx.unsubscribe(part, [ft.SubType.K_DAY])
        for s in list(tables):
            time.sleep(0.55)
            o = ctx.get_option_underlying_his_statistic(s, begin_time=(t0 - timedelta(days=50)).isoformat(), end_time=T)
            time.sleep(0.55)
            v = ctx.get_option_underlying_his_volatility(s, begin_time=(t0 - timedelta(days=10)).isoformat(), end_time=T)
            if o[0] != ft.RET_OK or v[0] != ft.RET_OK:
                errors.append(s)
                tables.pop(s)
                continue
            tables[s]['opt'] = {str(x.time)[:10]: {'option_volume': x.option_volume, 'call_volume': x.call_volume,
                                                  'put_volume': x.put_volume} for x in o[1].itertuples() if str(x.time)[:10] < T}
            tables[s]['iv'] = {str(x.time)[:10]: {'iv': x.iv, 'hv': x.hv} for x in v[1].itertuples() if str(x.time)[:10] < T}
        pool, sc, longs, shorts = rank_today(tables, nominal, T, a.n)
        pre = premarket(ctx, ft, sorted({r['symbol'] for r in pool}))
        if a.dump:
            Path(a.dump).write_text(json.dumps([
                {'symbol': r['symbol'], 'score': sc.get(id(r)), 'prev_close': nominal[r['symbol']][max(nominal[r['symbol']])][0],
                 **{k: r['f'].get(k) for k in ('pcr_z', 'iv', 'hv', 'clv1', 'ovol1', 'ovol20', 'atr20', 'implied_move')}}
                for r in pool], indent=1), encoding='utf-8')
    finally:
        ctx.close()
    print('Top %d long / short for %s (active pool %d of %d; %d request errors)' % (a.n, T, len(pool), len(uni), len(errors)))
    print('Honest record of this ranking (long-minus-short baskets, open -> close): selection 2023-08..2024-12 +63bp/day; '
          'validation 2025-01..2026-09 +17bp/day gross (54% days up); unused names 301-600, 2023-08..2026-09 (S27, Top 3) '
          '+11bp gross (51% days up) - NOT significant and below a 20bp cost. Direction is a lean, not an edge.')

    def gap(r):
        pc = nominal[r['symbol']][max(nominal[r['symbol']])][0]
        p = pre.get(r['symbol'], (0, 0))[0]
        return (p / pc - 1) if p and pc else None

    def show(title, xs):
        print('  ' + title)
        for r in xs:
            f, g = r['f'], gap(r)
            unusual = f.get('ovol20') and f['ovol1'] >= 1.5 * f['ovol20']
            print('    %-8s score %+5.2f  Put/Call z %+5.2f  IV-HV %+6.1f  close location %.2f  options T-1 %7d  '
                  'implied move %4.1f%%  pre-market %s%s' % (
                      r['symbol'], sc.get(id(r), float('nan')), f['pcr_z'], (f['iv'] or 0) - (f['hv'] or 0), f['clv1'] or 0,
                      f['ovol1'], 100 * (f.get('implied_move') or 0),
                      '%+5.1f%% (%+.1f ATR)' % (100 * g, g / f['atr20']) if g is not None and f.get('atr20') else '   -  ',
                      '  UNUSUAL' if unusual else ''))
    show('LONG', longs)
    show('SHORT', shorts)
    pl, ps = rank_volatile_half(pool, sc, a.n)
    print('Volatile half only (implied daily move above the pool median; same composite, untested as a rule):')
    show('LONG', pl)
    show('SHORT', ps)


if __name__ == '__main__':
    main()
