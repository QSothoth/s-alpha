"""Matrix backtest for TF1 (notes/TF1_PREREG.md): one loop over days, vector operations over every stock.

    trades = backtest.run(p, entry, line, ratchet, eligible, atr22, lo, hi, cost=(0.0005, 0.0005))

Rules, the same in every market (market differences arrive only as ``cost`` and ``limit``):
- signal at row t's close (entry & eligible, not already holding) -> buy at row t+1's open; dropped if t+1 is
  suspended, opens at or below the initial stop, or (with a price limit) opens at the limit-up price;
- exit when close(t) < the stop as of t-1 -> sell at the next traded open; with a price limit a day whose high
  is at or below the limit-down price cannot sell and the exit waits; never sells on the buy day;
- optional failed-breakout exit (TF12): a close back below the signal day's breakout price in the first days;
- optional time exit (TF7): after ``max_hold`` trading days the exit is confirmed at that close;
- the stop starts at the signal day's line and then follows the line (only upward when ``ratchet``);
  suspended days keep it unchanged;
- only buys filled in rows lo..hi count; anything still open after row hi settles at its last close in range.
R = (sell * (1 - sell cost) - buy * (1 + buy cost)) / max(buy - initial stop, ATR(22) of the signal day).
"""
from __future__ import annotations

import numpy as np

TRADE_FIELDS = ('stock', 'signal', 'entry', 'exit', 'buy', 'sell', 'stop0', 'risk', 'r', 'ret', 'at_end')


def limit_price(prev_raw_close, pct, up):
    x = prev_raw_close * (1 + pct if up else 1 - pct)
    return np.floor(x * 100 + 0.5) / 100


def run(p, entry, line, ratchet, eligible, atr22, lo, hi, cost=(0.0, 0.0), limit=None, max_hold=None, use_stop=True,
        fail_level=None, fail_days=0):
    """Return (trades as a dict of arrays, skipped-signal counts). ``limit``: per-stock fraction, NaN = none.
    ``max_hold``: also exit once the position has been held that many trading days (the buy day is day 1),
    confirmed at that day's close; ``use_stop=False`` keeps the line only for the R unit (time exit only).
    ``fail_level`` (dates x stocks, e.g. the breakout price known at the signal close) with ``fail_days``: within
    the first ``fail_days`` held days (buy day = 1), a close below the signal day's level exits (failed breakout)."""
    T, N = p['close'].shape
    o, c = p['open'], p['close']
    lim = np.full(N, np.nan) if limit is None else np.asarray(limit, float)
    has_lim = ~np.isnan(lim)
    hold = np.zeros(N, bool)
    want_out = np.zeros(N, bool)
    pend = np.zeros(N, bool)
    pend_sig = np.zeros(N, int)
    pend_stop = np.zeros(N)
    pend_atr = np.zeros(N)
    pend_fail = np.full(N, -np.inf)
    fail_at = np.full(N, -np.inf)
    buy = np.zeros(N)
    stop = np.zeros(N)
    stop0 = np.zeros(N)
    risk = np.zeros(N)
    sig_row = np.zeros(N, int)
    in_row = np.zeros(N, int)
    last_close = np.full(N, np.nan)
    prev_raw = np.full(N, np.nan)
    for t in range(max(lo - 1, 0)):  # the last raw close before the loop, for the first day's price limits
        seen = ~np.isnan(p['raw_close'][t])
        prev_raw[seen] = p['raw_close'][t][seen]
    rows = []
    skipped = {'suspended': 0, 'below_stop': 0, 'limit_up': 0}
    buy_cost, sell_cost = cost

    def close_out(idx, t, px, at_end):
        for j in np.flatnonzero(idx):
            net = px[j] * (1 - sell_cost) - buy[j] * (1 + buy_cost)
            rows.append((j, sig_row[j], in_row[j], t, buy[j], px[j], stop0[j], risk[j], net / risk[j],
                         net / (buy[j] * (1 + buy_cost)), at_end))

    for t in range(max(lo - 1, 0), hi + 1):
        traded = ~np.isnan(c[t])
        if t >= lo:
            with np.errstate(invalid='ignore'):
                up_px = limit_price(prev_raw, lim, True)
                dn_px = limit_price(prev_raw, lim, False)
                stuck_up = has_lim & (p['raw_open'][t] >= up_px - 1e-9)
                stuck_dn = has_lim & (p['raw_high'][t] <= dn_px + 1e-9)
            # exits at the open
            go = hold & want_out & traded & ~stuck_dn & (in_row < t)
            close_out(go, t, o[t], False)
            hold &= ~go
            want_out &= ~go
            # entries at the open
            if pend.any():
                susp = pend & ~traded
                below = pend & traded & (o[t] <= pend_stop)
                capped = pend & traded & ~below & stuck_up
                fill = pend & traded & ~below & ~capped
                skipped['suspended'] += int(susp.sum())
                skipped['below_stop'] += int(below.sum())
                skipped['limit_up'] += int(capped.sum())
                buy[fill], stop[fill], stop0[fill] = o[t][fill], pend_stop[fill], pend_stop[fill]
                risk[fill] = np.fmax(o[t][fill] - pend_stop[fill], pend_atr[fill])
                sig_row[fill], in_row[fill] = pend_sig[fill], t
                fail_at[fill] = pend_fail[fill]
                hold |= fill
            pend[:] = False
            # exits decided at the close, then the stop moves with today's line
            with np.errstate(invalid='ignore'):
                if use_stop:
                    want_out |= hold & traded & (c[t] < stop)
                if max_hold is not None:
                    want_out |= hold & traded & (t - in_row + 1 >= max_hold)
                if fail_days:
                    want_out |= hold & traded & (t - in_row + 1 <= fail_days) & (c[t] < fail_at)
            move = hold & traded & ~np.isnan(line[t])
            stop[move] = np.fmax(stop[move], line[t][move]) if ratchet else line[t][move]
        last_close[traded] = c[t][traded]
        prev_raw[traded] = p['raw_close'][t][traded]
        # new signals at the close, filled at the next open
        if t < hi:
            new = entry[t] & eligible[t] & traded & ~hold & ~np.isnan(line[t])
            pend[new] = True
            pend_sig[new], pend_stop[new], pend_atr[new] = t, line[t][new], atr22[t][new]
            if fail_level is not None:
                pend_fail[new] = np.nan_to_num(fail_level[t][new], nan=-np.inf)
    close_out(hold, hi, last_close, True)
    trades = {k: np.array([r[i] for r in rows]) for i, k in enumerate(TRADE_FIELDS)}
    if not rows:
        trades = {k: np.array([], int if k in ('stock', 'signal', 'entry', 'exit') else float) for k in TRADE_FIELDS}
    return trades, skipped


def random_entries(entry, eligible, pool, rng):
    """Same number of signals per day as ``entry & eligible``, drawn uniformly from ``pool``."""
    out = np.zeros_like(entry, bool)
    counts = (entry & eligible).sum(axis=1)
    for t in np.flatnonzero(counts):
        cand = np.flatnonzero(pool[t])
        if len(cand):
            out[t, rng.choice(cand, min(counts[t], len(cand)), replace=False)] = True
    return out


def ew_benchmark(p, eligible, trades):
    """Equal-weight return of the signal day's eligible pool over each trade's own holding window."""
    o, c = p['open'], p['close']
    cache, out = {}, np.zeros(len(trades['r']))
    for k, (s, a, b, end) in enumerate(zip(trades['signal'], trades['entry'], trades['exit'], trades['at_end'])):
        key = (s, a, b, end)
        if key not in cache:
            last = c[b] if end else o[b]
            with np.errstate(invalid='ignore', divide='ignore'):
                r = last / o[a] - 1
            r = r[eligible[s] & ~np.isnan(r)]
            cache[key] = r.mean() if len(r) else 0.0
        out[k] = cache[key]
    return out
