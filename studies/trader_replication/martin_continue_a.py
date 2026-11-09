"""D1 opportunity and capacity accounting; see PREREG_STRONG.md, continuation A."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from . import panels
from . import watchlist as WL
from .martin_list import ema
from .martin_strong import Data, bench, lag, roll_ext
from .martin_strong_scan import HOLD, active, hold_sim, name_score, nl_rules, pool_book3


def rolling_float32(x, n):
    out = np.empty(x.shape, dtype=np.float32)
    for start in range(0, x.shape[1], 64):
        out[:, start:start + 64] = WL.roll_mean(x[:, start:start + 64].astype(np.float32), n)
    return out


def required_fields(D):
    """Recompute only H3 and D1 inputs; the wide exploratory cache is optional."""
    import datetime as dt
    c, h, l, o, t, adr = D.c, D.h, D.l, D.o, D.t, D.adr
    with np.errstate(all='ignore'):
        e9, e21, e50 = (ema(c.astype(float), n).astype(np.float32) for n in (9, 21, 50))
        D.e9 = e9
        F = {'act20': np.log(D.to20 * adr), 'g21': c / lag(c, 21) - 1,
             'stack': (e9 > e21).astype(np.float32) + (e21 > e50).astype(np.float32),
             'lowe9': (l / e9 - 1) / adr, 'ext21': (c / e21 - 1) / adr,
             'cpos': (c - l) / (h - l)}
        del e21, e50
        q = bench(D.days, 'QQQ').astype(np.float32)
        rs = np.log(c) - np.log(q)[:, None]
        hi = roll_ext(rs, 60, np.nanmax)
        lo = roll_ext(rs, 60, np.nanmin)
        F['rs_pos60'] = (rs - lo) / (hi - lo)
        del q, rs, hi, lo
        F['stay250'] = rolling_float32(D.rk < 100, 250)
        r = c / lag(c) - 1
        F['fast250'] = rolling_float32(np.abs(r) >= .05, 250)

        # words() returns a one-day lag, and name_score() applies a second lag.
        weeks = [dt.date.fromisoformat(d).isocalendar()[:2] for d in D.days]
        ends = [i for i in range(len(weeks)) if i + 1 == len(weeks) or weeks[i + 1] != weeks[i]]
        idx = np.searchsorted(np.asarray(ends), np.arange(len(weeks)), side='left') - 1
        wc = D.A['close'][ends].astype(float)
        w9, w21 = ema(wc, 9), ema(wc, 21)
        weekly = np.zeros(c.shape, dtype=np.float32)
        for day, week in enumerate(idx):
            if week >= 0:
                weekly[day] = ((D.A['close'][day] > w9[week]).astype(np.float32)
                               + (D.A['close'][day] > w21[week]).astype(np.float32))
        F['w_wk_above'] = lag(weekly).astype(np.float32)
        del wc, w9, w21, weekly

        ok = (D.to20 >= 5e7) & (WL.roll_mean(h / l - 1, 5) >= .035)
        pot, led = np.zeros(c.shape, bool), np.zeros(c.shape, bool)
        for d in range(len(c)):
            ix = np.flatnonzero(ok[d] & np.isfinite(r[d]))
            if len(ix) > 60:
                pot[d, ix[np.argsort(-r[d, ix])[:50]]] = True
            ix = np.flatnonzero(ok[d] & np.isfinite(F['g21'][d]))
            if len(ix) > 120:
                led[d, ix[np.argsort(-F['g21'][d, ix])[:100]]] = True
        F['led20'] = rolling_float32(led, 20)
        rr = np.empty_like(r, dtype=np.float32)
        for day in range(len(r)):
            median = np.nanmedian(np.where(D.rk[day] < 300, r[day], np.nan))
            rr[day] = np.nan_to_num(r[day] - median)
        del r, ok, led
        peer_rank, peer_pot = (np.full(c.shape, np.nan, dtype=np.float32) for _ in range(2))
        near = names = None
        for d in range(60, len(c)):
            cur = np.flatnonzero(D.rk[d] < 300)
            if len(cur) < 30:
                continue
            if near is None or d % 5 == 0:
                w = rr[d - 39:d + 1][:, cur]
                w = w - w.mean(0)
                sd = w.std(0) + 1e-6
                near = ((w.T @ w) / len(w) / np.outer(sd, sd)) >= .5
                names = cur
            g = F['g21'][d, names]
            g = np.where(np.isfinite(g), g, -9)
            n = near.sum(1)
            peer_rank[d, names] = ((g[None, :] <= g[:, None]) & near).sum(1) / n
            pot5 = pot[d - 4:d + 1][:, names].sum(axis=0) / 5.0
            peer_pot[d, names] = (near * pot5).sum(1) / n
        F['peer_rank'], F['peer_pot'] = peer_rank, peer_pot
    return {k: v.astype(np.float32, copy=False) for k, v in F.items()}


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    holding = hold_sim(score, 12, 36)
    book = pool_book3(D, F, holding, score, 8.0, False, .03)
    rules = nl_rules(D, 6, trail='e9')
    stats, trades = D.base.run(D.A, book, panels.WINDOW, D.pool, rules, placebo=0, audit=True)
    years = {}
    for year in ('2024', '2025', '2026'):
        dates = [d for d, date in enumerate(D.days) if date.startswith(year) and panels.WINDOW[0] <= date <= panels.WINDOW[1]]
        pool_counts, setup_counts, qualified = [], [], []
        for d in dates:
            pool = holding[d]
            touch = (F['lowe9'][d] <= .1) & (D.c[d] > D.e9[d])
            breakout = (D.c[d] > D.h[d - 1]) & (F['cpos'][d] >= .5)
            valid = np.isfinite(D.c[d]) & np.isfinite(D.l[d])
            setup = pool & (touch | breakout) & (np.nan_to_num(F['ext21'][d], nan=99) <= 8) & valid
            pool_counts.append(int(pool.sum()))
            setup_counts.append(int(setup.sum()))
            qualified.append(len(book[d]))
        closed = [t for t in trades if t['entry'].startswith(year) and t['why'] != 'end']
        opened = [t for t in trades if t['entry'].startswith(year)]
        winners = [t for t in closed if t['ret'] > 0]
        losers = [t for t in closed if t['ret'] < 0]
        reasons = {}
        for t in losers:
            reasons[t['why']] = reasons.get(t['why'], 0) + 1
        years[year] = dict(days=len(dates), pool_name_days=sum(pool_counts), setup_name_days=sum(setup_counts),
                           qualified_name_days=sum(qualified), qualified_zero_days=sum(n == 0 for n in qualified),
                           qualified_median=float(np.median(qualified)),
                           max_six_per_day=sum(min(6, n) for n in qualified),
                           actual_entries=len(opened), closed=len(closed), open_at_end=len(opened)-len(closed),
                           wins=len(winners), losses=len(losers), loss_exit_reasons=reasons,
                           mean_win=float(np.mean([t['ret'] for t in winners])) if winners else None,
                           mean_loss=float(np.mean([t['ret'] for t in losers])) if losers else None,
                           mean_winner_days=float(np.mean([t['days'] for t in winners])) if winners else None,
                           mean_loser_days=float(np.mean([t['days'] for t in losers])) if losers else None)
    root = Path(__file__).resolve().parents[2]
    files = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_strong.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/trader_replication/system.py', 'studies/martin_luk/notes/trades.csv')
    hashes = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in files}
    out = dict(window=list(panels.WINDOW), actual_digest=D.A.get('digest'), data_pin=json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text()),
               code_sha256=hashes, year=years, by_year=stats['by_year'])
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_a.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
