"""One trader system on one market, as of the newest day of the data: the single implementation behind both the
comparison (frozen data) and live running (the trader-screens board on live data).

run(system, market, mode) replays the registered configuration (systems.py) with the research engine from START to
the newest day and returns the account, the last `days` sessions' buys, sells and offered-but-not-taken entries,
and the open positions with their exit levels read straight from the engine (stop, armed trail and its line, next
partial, next add).  `check` compares the replay cut at the freeze day with the comparison report (frozen release,
same code): on live data the part up to the freeze day must not move.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.trader_replication.runner us [live|frozen] [system ...]
"""
from __future__ import annotations

import gc
import json
import sys
from pathlib import Path

import numpy as np

from . import system as Y, systems as SY

OUT = Path(__file__).resolve().parent / 'reports'
WHY = {'stop': '跌破止损', 'gap_stop': '跳空跌破止损', 'trim': '按 R 分批', 'trail': '收盘跌破跟踪线',
       'signal': '信号离场', 'signal_trim': '信号分批', 'signal_trim2': '信号分批', 'day_trim': '到期分批',
       'stop_day0': '当天止损', 'time': '持有到期', 'no_follow': '没有延续'}
WHY_SHORT = {'stop': '涨破止损回补', 'gap_stop': '跳空涨破止损回补', 'trim': '按 R 回补一部分', 'trail': '收盘站上跟踪线回补',
             'stop_day0': '当天止损回补', 'time': '持有到期回补', 'no_follow': '没有延续回补',
             'target': '到达目标线回补'}


def bounded_history(days, values, until, window=60):
    """At most window + 1 observed closes through until; incomplete histories stay unavailable."""
    end = int(np.searchsorted(np.asarray(days, dtype=str), until, side='right'))
    start = max(0, end - window - 1)
    tail = np.asarray(values[start:end], dtype=float)
    if not len(tail) or not np.all(np.isfinite(tail) & (tail > 0)):
        return dict(days=[], values=[])
    return dict(days=[str(d) for d in days[start:end]], values=tail.tolist())


def years_until(curve, dates, until):
    """Calendar-year returns counting only days up to `until` (years the data covers up to then)."""
    out, prev = {}, 1.0
    for y in sorted({str(d)[:4] for d in dates if str(d) <= until}):
        idx = [i for i, d in enumerate(dates) if str(d)[:4] == y and str(d) <= until]
        out[y] = float(curve[idx[-1]] / prev - 1)
        prev = curve[idx[-1]]
    return out


def forward(curve, dates, trades, freeze):
    """After the freeze day: equity change from the freeze-day close, drawdown, trades opened after it."""
    k = int(np.searchsorted(dates, freeze, side='right')) - 1
    new = [t for t in trades if t['entry'] > freeze]
    if k < 0 or k >= len(dates) - 1:
        return dict(since=freeze, days=0, ret=0.0, maxdd=0.0, trades=len(new))
    seg = np.asarray(curve[k:])
    return dict(since=str(dates[k]), days=len(dates) - 1 - k, ret=float(seg[-1] / seg[0] - 1),
                maxdd=float(np.max(1 - seg / np.maximum.accumulate(seg))), trades=len(new))


def reference(system, market):
    """The comparison report's numbers for this system, when they were made with the same configuration and the
    same code (compare.code_digest); otherwise None (no reference: the check is 'missing', never 'passed')."""
    path = OUT / 'compare.json'
    if not path.exists():
        return None
    from .compare import code_digest, config_digest
    r = json.loads(path.read_text(encoding='utf-8')).get(system.id, {}).get('markets', {}).get(market)
    if not r or r['run']['config_digest'] != config_digest(system.config) \
            or r['run'].get('code_digest') != code_digest():
        return None
    return r


def stage(t, e):
    """When an execution happened inside its day: 'open' (gap stop, a trade filled during the day), 'intraday'
    (stop, R partial, target, a same-day stop) or 'close'."""
    a = e['action']
    if a == 'entry':
        return 'intraday' if t.get('intraday') else 'close'
    if a == 'gap_stop':
        return 'open'
    return 'intraday' if a in ('stop', 'trim', 'target', 'stop_day0') else 'close'


def run(system, market, mode=None, days=1, A=None):
    st, cfg = system.study, system.config
    A = A if A is not None else st.arrays(market, mode=mode)
    trace = {}
    entries, rules, mask, pool = st.build(A, cfg, trace)
    skipped = trace.get('limit_up') or []
    del trace
    ema = st.ema_inputs(A, pool, rules)
    dates, codes = A['days'], [str(c) for c in A['codes']]
    T = len(dates) - 1
    curve, cdates, tr = Y.simulate(st.px(A), ema, rules, entries, SY.START, str(dates[T]), audit=True)
    equity = float(curve[-1])
    di = {str(d): i for i, d in enumerate(cdates)}
    window = [str(d) for d in dates[max(T - days + 1, 0):T + 1]]
    col = {c: j for j, c in enumerate(codes)}

    def prev_eq(day):
        k = di[day]
        return float(curve[k - 1]) if k > 0 else 1.0

    buys, sells, opened = [], [], set()
    for t in tr:
        opened.add((t['code'], t['entry']))
        ex = t['executions']
        d0 = int(np.searchsorted(dates, t['entry']))
        t['intraday'] = t['kind'] in rules.intraday_kinds or not t['fill'] == A['close'][d0, col[t['code']]]
        if t['entry'] in window:
            buys.append(dict(code=t['code'], day=t['entry'], setup=t['kind'], side=t['side'], price=t['fill'],
                             stop=t['stop'], weight=ex[0]['shares'] * ex[0]['price'] / prev_eq(t['entry']),
                             stage=stage(t, ex[0])))
        for e in ex:
            if e['action'] in ('entry', 'end') or e['time'][:10] not in window:
                continue
            if e['action'] == 'add':
                buys.append(dict(code=t['code'], day=e['time'][:10], setup='加码', side=t['side'], price=e['price'],
                                 stop=None, stage='close',
                                 weight=e['shares'] * e['price'] / prev_eq(e['time'][:10])))
                continue
            why = (WHY if t['side'] > 0 else WHY_SHORT).get(e['action'], e['action'])
            sells.append(dict(code=t['code'], day=e['time'][:10], why=why, side=t['side'], stage=stage(t, e),
                              price=e['price'], ret=t['side'] * (e['price'] / t['fill'] - 1),
                              full=e is [x for x in ex if x['action'] != 'end'][-1] and t['why'] != 'end'))
    wanted = []
    for day in window:
        d = int(np.searchsorted(dates, day))
        for e in sorted(entries[d], key=lambda e: e[0]):
            c = codes[e[1]]
            if (c, day) not in opened:
                wanted.append(dict(code=c, day=day, setup=e[5], side=int(e[2]), price=float(e[3]), stop=float(e[4])))
        for e in (skipped[d] if d < len(skipped) else []):      # A-share limit-up closes: not bought (shorts.py)
            wanted.append(dict(code=codes[e[1]], day=day, setup=e[5], side=int(e[2]), price=float(e[3]),
                               stop=float(e[4]), limit_up=True))
    holdings = []
    for t in (t for t in tr if t['why'] == 'end'):
        s, j = t['state'], col[t['code']]
        seen = np.flatnonzero(np.isfinite(A['close'][:T + 1, j]))   # the engine's valuation: the last close it has
        close = float(A['close'][seen[-1], j]) if len(seen) else t['fill']
        line = ema.get(s['trail']) if s['trail'] else None
        R = abs(t['fill'] - t['stop'])
        sd = t['side']
        holdings.append(dict(code=t['code'], entry_day=t['entry'], setup=t['kind'], side=sd, fill=t['fill'],
                             close=close, close_day=str(dates[seen[-1]]) if len(seen) else t['entry'],
                             tradable=bool(np.isfinite(A['close'][T, j])), ret=sd * (close / t['fill'] - 1),
                             r_now=sd * (close - t['fill']) / R if R else None,
                             stop=s['stop'], trail=float(line[T, j]) if line is not None and s['armed'] else None,
                             trail_name=s['trail'], next_trim=s['next_trim'], trim_frac=s['trim_frac'],
                             next_add=s['next_add'], day_trim_pending=s['day_trim_pending'] and sd > 0,
                             trim_day=s['trim_day'], trim_day_frac=s['trim_day_frac'],
                             trim_day_profit=s['trim_day_profit'], next_target=s.get('next_target'),
                             target_name=s.get('target_name', ''), max_days=s.get('max_days', 0),
                             short_trim_day_pending=s.get('short_trim_day_pending', False),
                             short_trim_day=s.get('short_trim_day', 0), short_trim_day_frac=s.get('short_trim_day_frac', 0),
                             trim_signal=s.get('trim_signal', ''), trim_signal_frac=s.get('trim_signal_frac', 0),
                             breakeven=s.get('breakeven'),
                             weight=s['shares'] * close / equity, days=int(T - int(np.searchsorted(dates, t['entry'])))))
    gate = st.market_gate(A, cfg)
    closed = [t for t in tr if t['why'] != 'end']
    wins = [t for t in closed if t['ret'] > 0]
    peak = np.maximum.accumulate(np.concatenate([[1.0], curve]))[1:]
    out = dict(id=system.id, name=system.name, version=system.version, status=system.status, label=system.label,
               market=market, data=A.get('digest'), last_day=str(dates[T]), days=days,
               equity_history=bounded_history(cdates, curve, str(dates[T])),
               strategy=system.strategy, buys=buys, sells=sells, wanted=wanted, holdings=holdings,
               gate_today=None if gate is None else bool(gate[T]),
               account=dict(since=SY.START, ret=equity - 1, maxdd=float(np.max(1 - curve / peak)),
                            trades=len(closed), win=len(wins) / len(closed) if closed else None,
                            exposure=float(sum(h['weight'] for h in holdings)),
                            short_exposure=float(sum(h['weight'] for h in holdings if h['side'] < 0))),
               freeze=system.freeze, registered=getattr(system, 'registered', ''),
               forward=forward(curve, cdates, tr, system.freeze))
    ref = reference(system, market)
    if ref is None:
        out['check'] = dict(ok=None, status='missing')
    else:
        mine = years_until(curve, cdates, system.freeze)
        ok = all(abs(mine.get(y, np.nan) - v) < 1e-9 for y, v in ref['by_year'].items())
        out['check'] = dict(ok=ok, status='passed' if ok else 'failed', replay=mine, research=ref['by_year'])
    del entries, mask, pool
    gc.collect()
    return out


def main(argv):
    market = argv[1]
    mode = argv[2] if len(argv) > 2 else None
    names = argv[3:]
    for x in SY.all_():
        if names and x.id not in names:
            continue
        r = run(x, market, mode)
        print(r['name'], r['label'], r['last_day'], f"account {r['account']['ret']:+.3f}",
              'buys', [b['code'] for b in r['buys']], 'sells', [s['code'] for s in r['sells']],
              'holdings', len(r['holdings']), 'check', r.get('check', {}).get('ok'), flush=True)


if __name__ == '__main__':
    main(sys.argv)
