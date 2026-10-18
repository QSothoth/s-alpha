"""Replicated systems frozen out of skills/trader-replication, rebuilt on fresh data with the study's own code.

Each adapter names the research report holding the configuration and the freeze day (the last day of the research
data, so every later day is out of sample).  `today` returns the screen layers the commonality view needs plus the
rule book: positions with next-day exit levels, the record after the freeze day, and the trader's ledger trades
published after it.  Freezing a new configuration is a research decision (trader-replication step 9) and restarts
the forward record.
"""
from __future__ import annotations

import gc
from pathlib import Path

import numpy as np

from studies.trader_replication import ledger as L, system as Y

from . import data

ROOT = data.ROOT
WHY = {'stop': '跌破止损', 'gap_stop': '跳空跌破止损', 'trim': '+10R 卖 30%', 'trail': '收盘跌破 EMA21',
       'signal': '信号离场', 'stop_day0': '当天止损', 'time': '持有到期', 'no_follow': '没有延续'}
STEPS = ('no_signal', 'no_entry', 'market_filter', 'daily_cap', 'no_room', 'traded')


def position_state(trade, close, trail, dates, rules):
    """Exit levels of a position still open on the last day, from its executions (simulate(audit=True)) and the
    engine's rules: the stop moves to the fill after an executed add; partial and add levels are R multiples of the
    initial stop; the close trail is armed once a close after the entry day was beyond the trail line."""
    if rules.breakeven_r or rules.stop_ema_buffer >= 0 or rules.trail_alt or rules.trail_after_trim \
            or rules.trim_signal or rules.exit_signal or rules.nft_days or rules.max_days:
        raise NotImplementedError('position_state covers stops, R partials, adds and one close trail only')
    s = trade['side']
    ex = [e for e in trade['executions'] if e['action'] != 'end']
    fill, stop0 = trade['fill'], trade['stop']
    R = abs(fill - stop0)
    added = any(e['action'] == 'add' for e in ex)
    trims = sum(e['action'] == 'trim' for e in ex)
    shares = sum(e['shares'] * (1 if e['action'] in ('entry', 'add') else -1) for e in ex)
    d0 = int(np.searchsorted(dates, trade['entry']))
    with np.errstate(invalid='ignore'):
        armed = bool(np.any((close[d0 + 1:] - trail[d0 + 1:]) * s > 0)) if trail is not None else False
    stop = (max(stop0, fill) if s > 0 else min(stop0, fill)) if added else stop0
    trim_levels = rules.trims if s > 0 or rules.short_trims is None else rules.short_trims
    add_levels = rules.add_levels or ((rules.add_r,) if rules.add_r else ())
    return dict(code=trade['code'], side=s, entry=trade['entry'], fill=fill, stop0=stop0, stop=stop, shares=shares,
                close=float(close[-1]), r_now=float((close[-1] - fill) * s / R), trims=trims, added=added,
                next_trim=fill + s * trim_levels[trims] * R if trims < len(trim_levels) else None,
                trim_frac=rules.trim_frac,
                next_add=fill + add_levels[trade['add_tries']] * R
                if s > 0 and trade['add_tries'] < len(add_levels) else None,
                trail=float(trail[-1]) if trail is not None else None, armed=armed)


def furthest_step(mask, sets, ours, code, j, a, b, days):
    """How far one of his trades got on any day of its window: signal, entry after the stop rule, market filter,
    daily cap, opened by the rule book (the same ladder as martin_luk.replicate.diagnose)."""
    best, trade = 0, None
    for d in range(a, b + 1):
        k = 0
        if mask[d, j]:
            k = 1
            if j in sets['raw'][d]:
                k = 2
                if j in sets['filtered'][d]:
                    k = 3
                    if j in sets['capped'][d]:
                        k = 4
                        if (code, str(days[d])) in ours:
                            k = 5
                            trade = ours[(code, str(days[d]))]
        best = max(best, k)
    return STEPS[best], trade


def years_until(curve, dates, until):
    """Calendar-year returns of an equity curve counting only days up to `until` (the freeze day), for years the
    data covers up to that point; comparable with the research report whatever data came after."""
    out, prev = {}, 1.0
    for y in sorted({str(d)[:4] for d in dates if str(d) <= until}):
        idx = [i for i, d in enumerate(dates) if str(d)[:4] == y and str(d) <= until]
        if str(dates[-1]) >= min(until, f'{y}-12-31'):
            out[y] = float(curve[idx[-1]] / prev - 1)
        prev = curve[idx[-1]]
    return out


def forward(curve, dates, trades, freeze):
    """The part after the freeze day: equity change from the freeze-day close and the trades opened after it."""
    k = int(np.searchsorted(dates, freeze, side='right')) - 1
    new = [t for t in trades if t['entry'] > freeze]
    if k < 0 or k >= len(dates) - 1:
        return dict(since=freeze, days=0, ret=0.0, maxdd=0.0, trades=new)
    seg = np.asarray(curve[k:])
    dd = float(np.max(1 - seg / np.maximum.accumulate(seg)))
    return dict(since=str(dates[k]), days=len(dates) - 1 - k, ret=float(seg[-1] / seg[0] - 1), maxdd=dd, trades=new)


class MartinLuk:
    """R74 carry (= R73 WK1) of studies/martin_luk: US daily momentum swing, close entries, no shorts."""
    id = 'martin_luk'
    name = 'Martin Luk'
    level = 'replicated'
    markets = ('us',)
    summary = '美股动量波段（R74 带入配置）：市况允许时，按成交额买当天信号的前 4 只，收盘买入'
    start = '2024-01-02'                # the rule book starts here, as in the research (replicate.FULL)
    report = 'r74.json'
    freeze = '2026-10-16'               # last day of the research data
    research_years = {'2024': 2.88239, '2025': 2.21191, '2026': 0.94748}   # reports/final_system.json, US by year
    reports = ROOT / 'studies' / 'martin_luk' / 'reports'
    research_folder = ROOT / 'data' / 'martin-luk-universe-us'
    ledger = ROOT / 'studies' / 'martin_luk' / 'notes' / 'trades.csv'

    def config(self):
        import json
        return json.loads((self.reports / self.report).read_text(encoding='utf-8'))['chosen_config']

    def arrays(self, folder):
        """replicate.market_arrays reads selection.broad(); for a scan folder that call is pointed at the folder's
        own panel, built the same way."""
        from studies.martin_luk import replicate as R, selection as S
        if Path(folder).resolve() == self.research_folder.resolve():
            return R.market_arrays('us')
        b = data.panel(folder, 'us')
        keep = S.broad
        S.broad = lambda: b
        try:
            return R.market_arrays('us')
        finally:
            S.broad = keep

    def today(self, folder, days=1, capital=None):
        from studies.martin_luk import replicate as R
        A = self.arrays(folder)
        cfg = self.config()
        trace = {}
        entries, rules, mask, pool = R.build_system(A, cfg, trace)
        px = dict(open=A['open'], high=A['high'], low=A['low'], close=A['close'], dates=A['days'], codes=A['codes'])
        names = (rules.exit_signal, rules.trim_signal, rules.risk_scale, rules.trail_alt_days)
        for k in names:
            if k and (k not in A or k.startswith('idx_')):
                A[k] = R.named_signal(A, pool, k)
        ema = {k: A[k] for k in ('e9', 'e21', 'e50') + names if k and k in A}
        dates, codes = A['days'], A['codes']
        T = len(dates) - 1
        curve, cdates, tr = Y.simulate(px, ema, rules, entries, self.start, str(dates[T]), audit=True)
        equity = float(curve[-1])
        col = {str(c): j for j, c in enumerate(codes)}
        trail = ema.get(rules.trail) if rules.trail else None
        positions = []
        for t in (t for t in tr if t['why'] == 'end'):
            j = col[t['code']]
            p = position_state(t, A['close'][:, j], None if trail is None else trail[:, j], dates, rules)
            p['weight'] = p['shares'] * p['close'] / equity
            p['shares_for_capital'] = capital and p['weight'] * capital / p['close']
            positions.append(p)
        held_today = {(t['code'], t['entry']) for t in tr}
        w = R.system_signals(A, cfg)[1]
        open_ok = R.market_ok(A, pool, w, cfg['filter']) if cfg.get('filter') not in (None, '', 'NONE') \
            else np.ones(len(dates), bool)
        window = {str(dates[d]) for d in range(max(T - days + 1, 0), T + 1)}
        buys, wanted, sells = [], [], []    # what he does: the top 4 by turnover past the market filter
        for d in range(max(T - days + 1, 0), T + 1):
            for e in sorted(trace['capped'][d], key=lambda e: e[0]):
                code = str(codes[e[1]])
                row = dict(code=code, day=str(dates[d]), setup='收盘买入', price=float(e[3]), stop=float(e[4]))
                if (code, str(dates[d])) in held_today:
                    t_ = next(x for x in tr if x['code'] == code and x['entry'] == str(dates[d]))
                    k = int(np.searchsorted(cdates, row['day']))
                    prev_eq = float(curve[k - 1]) if k > 0 else 1.0       # equity at the previous close
                    row['weight'] = t_['executions'][0]['shares'] * t_['fill'] / prev_eq
                    buys.append(row)
                else:
                    wanted.append(dict(row, why='仓位已满或已持有'))
        for t_ in tr:
            for ex in t_['executions']:
                if ex['action'] in ('entry', 'add', 'end') or ex['time'] not in window:
                    continue
                sells.append(dict(code=t_['code'], day=ex['time'], why=WHY.get(ex['action'], ex['action']),
                                  price=ex['price'], ret=ex['price'] / t_['fill'] - 1,
                                  full=ex is t_['executions'][-1]))
        candidates = {str(dates[d]): len(trace['raw'][d]) for d in range(max(T - days + 1, 0), T + 1)}
        closed = [t for t in tr if t['why'] != 'end']
        recent = sum(t['r'] for t in closed[-rules.feedback:]) if rules.feedback else 0.0
        risk = rules.risk
        if rules.feedback and len(closed) >= rules.feedback:
            risk = rules.risk_low if recent < 0 else (rules.risk_high if recent > 0 and rules.risk_high > 0 else risk)
        scale = float(ema[rules.risk_scale][T]) if rules.risk_scale else 1.0
        scale = scale if np.isfinite(scale) else 1.0
        ours = {(t['code'], t['entry']): t for t in tr}
        sets = {k: [{e[1] for e in lst} for lst in trace[k]] for k in ('raw', 'filtered', 'capped')}
        his = []
        after = [t for t in L.load(self.ledger) if t.window_lo > self.freeze]          # wholly out of sample
        for t, j, a, b in R.located_longs(A, after):
            step, ot = furthest_step(mask, sets, ours, str(codes[j]), j, a, b, dates)
            his.append(dict(id=t.id, ticker=t.ticker, window=[t.window_lo, t.window_hi], step=step,
                            our_entry=ot and ot['entry'], our_r=ot and round(ot['r'], 2)))
        years = years_until(curve, cdates, self.freeze)
        out = dict(
            last_day=str(dates[T]), watch=sorted(str(codes[j]) for j in np.flatnonzero(w[T])),
            buys=buys, wanted=wanted, sells=sells,
            book=dict(start=self.start, freeze=self.freeze, report=self.report,
                      check={y: dict(replay=years[y], research=v) for y, v in self.research_years.items() if y in years},
                      buying_open=bool(open_ok[T]), risk_next=float(risk * scale),
                      risk_parts=dict(base=rules.risk, feedback_sum_r=float(recent), feedback=risk, scale=scale),
                      candidates=candidates,
                      positions=positions, equity=equity, gross=float(sum(p['weight'] for p in positions)),
                      forward=forward(curve, cdates, tr, self.freeze), ledger_after_freeze=his))
        del A, trace, entries
        gc.collect()
        return out


REPLICATED = (MartinLuk(),)
