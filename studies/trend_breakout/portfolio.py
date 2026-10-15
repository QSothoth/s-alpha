"""Cash/position accounting for the existing daily execution engine; PB1 historical diagnostics."""
from __future__ import annotations

from datetime import date

import numpy as np


class Account:
    def __init__(self, p, priority, cost, *, slots=10, risk_fraction=0.005, position_cap=0.10):
        if slots < 1 or not 0 < risk_fraction <= 1 or not 0 < position_cap <= 1:
            raise ValueError('invalid position budget')
        self.p, self.priority, self.cost = p, priority, cost
        self.slots, self.risk_fraction, self.position_cap = slots, risk_fraction, position_cap
        self.cash = self.previous_nav = 1.0
        self.positions, self.trades, self.curve = {}, [], []
        self.skipped = {'slots': 0, 'cash': 0, 'invalid': 0}

    def allocate(self, t, fill, prices, stops, atr, signal):
        accepted = np.zeros_like(fill)
        candidates = np.flatnonzero(fill)
        # Ranking is known at the signal close; never use the next day's volume or return.
        candidates = sorted(candidates, key=lambda j: (-self.priority[signal[j], j], str(self.p['codes'][j])))
        for j in candidates:
            if not self.has_room():
                self.skipped['slots'] += 1
                continue
            risk = max(prices[j] - stops[j], atr[j])
            if not np.isfinite([prices[j], risk]).all() or prices[j] <= 0 or risk <= 0:
                self.skipped['invalid'] += 1
                continue
            qty = min(self.previous_nav * self.risk_fraction / risk,
                      self.previous_nav * self.position_cap / prices[j],
                      self.cash / (prices[j] * (1 + self.cost[0])))
            if qty * prices[j] < 1e-12:
                self.skipped['cash'] += 1
                continue
            paid = qty * prices[j] * (1 + self.cost[0])
            self.cash -= paid
            self.positions[int(j)] = {'qty': qty, 'paid': paid, 'last': float(prices[j]),
                                      'peak': float(prices[j]), 'stale': 0}
            accepted[j] = True
        return accepted

    def has_room(self):
        return len(self.positions) < self.slots

    def close(self, trade):
        j = int(trade['stock'])
        pos = self.positions[j]
        proceeds = pos['qty'] * trade['sell'] * (1 - self.cost[1])
        peak = max(pos['peak'], trade['sell'])
        peak_pnl = pos['qty'] * peak * (1 - self.cost[1]) - pos['paid']
        row = {k: (bool(v) if k == 'at_end' else int(v) if k in ('stock', 'signal', 'entry', 'exit') else float(v))
               for k, v in trade.items()}
        row.update(code=str(self.p['codes'][j]), pnl=float(proceeds - pos['paid']), paid=float(pos['paid']),
                   peak_pnl=float(peak_pnl), giveback=float(peak_pnl - (proceeds - pos['paid'])),
                   held_sessions=int(trade['exit'] - trade['entry']), stale_sessions=pos['stale'])
        self.trades.append(row)
        if not trade['at_end']:
            self.cash += proceeds
            del self.positions[j]

    def mark(self, t):
        values = []
        stale = 0
        for j, pos in self.positions.items():
            price = self.p['close'][t, j]
            if np.isfinite(price):
                pos['last'], pos['stale'] = float(price), 0
                pos['peak'] = max(pos['peak'], float(self.p['high'][t, j]))
            else:
                pos['stale'] += 1
                stale += 1
            values.append(pos['qty'] * pos['last'])
        value = sum(values)
        nav = self.cash + value
        if self.cash < -1e-10 or not np.isfinite(nav) or nav <= 0:
            raise ValueError('invalid cash ledger')
        self.curve.append({'date': str(self.p['dates'][t]), 'nav': float(nav), 'cash': float(self.cash),
                           'exposure': float(value / nav), 'positions': len(values),
                           'largest_weight': float(max(values, default=0) / nav), 'stale_positions': stale})
        self.previous_nav = nav

    def summary(self, start_date):
        result = nav_summary(self.curve, start_date)
        r = np.array([x['r'] for x in self.trades])
        pnl = np.array([x['pnl'] for x in self.trades])
        win, loss = r[r > 0], r[r < 0]
        closed = [x for x in self.trades if not x['at_end']]
        open_ = [x for x in self.trades if x['at_end']]
        held = [x['held_sessions'] for x in closed]
        positive = sorted((x for x in self.trades if x['pnl'] > 0), key=lambda x: x['pnl'], reverse=True)
        top = positive[:max(1, int(np.ceil(len(self.trades) * .05)))]
        codes = {x['code'] for x in self.trades}
        end_value = sum(x['qty'] * x['last'] for x in self.positions.values())
        result.update(
            trades=len(r), closed_trades=len(closed), open_at_end=len(open_),
            mean_r=float(r.mean()) if len(r) else None, win_rate=float((r > 0).mean()) if len(r) else None,
            payoff=float(win.mean() / -loss.mean()) if len(win) and len(loss) else None,
            profit_factor=float(pnl[pnl > 0].sum() / -pnl[pnl < 0].sum()) if (pnl < 0).any() else None,
            p5r=float((r >= 5).mean()) if len(r) else None, p10r=float((r >= 10).mean()) if len(r) else None,
            realized_pnl=sum(x['pnl'] for x in closed), open_liquidation_pnl=sum(x['pnl'] for x in open_),
            liquidation_nav=float(self.cash + end_value * (1 - self.cost[1])),
            closed_hold_median=float(np.median(held)) if held else None,
            closed_hold_p90=float(np.percentile(held, 90)) if held else None,
            closed_hold_max=max(held, default=0),
            held_60_sessions=sum(x['held_sessions'] >= 60 for x in self.trades),
            top5pct_pnl=sum(x['pnl'] for x in top), top5pct_trades=len(top),
            total_giveback=sum(x['giveback'] for x in self.trades),
            total_positive_peak=sum(max(0, x['peak_pnl']) for x in self.trades),
            distinct_stocks=len(codes), repeat_entries=len(r) - len(codes),
            skipped=self.skipped,
            top_contributors=[{k: x[k] for k in ('code', 'pnl', 'r', 'held_sessions', 'at_end')}
                              for x in positive[:5]],
        )
        # Realized and estimated unrealized P&L must explain liquidation NAV exactly.
        if not np.isclose(result['liquidation_nav'], 1 + pnl.sum(), atol=1e-10, rtol=1e-10):
            raise ValueError('trade P&L does not reconcile with cash and holdings')
        return result


def nav_summary(curve, start_date):
    dates = [start_date] + [x['date'] for x in curve]
    nav = np.array([1.] + [x['nav'] for x in curve])
    peaks = np.maximum.accumulate(nav)
    dd = nav / peaks - 1
    trough = int(np.argmin(dd))
    peak = int(np.flatnonzero(nav[:trough + 1] == peaks[trough])[-1])
    recovered = np.flatnonzero(nav[trough + 1:] >= peaks[trough])
    recovery = int(trough + 1 + recovered[0]) if len(recovered) else None
    if dd[trough] == 0:
        recovery = trough
    run = longest = 0
    for value in dd:
        run = run + 1 if value < -1e-12 else 0
        longest = max(longest, run)
    years, prev = {}, 1.
    for year in sorted({d[:4] for d in dates[1:]}):
        rows = [i for i in range(1, len(dates)) if dates[i].startswith(year)]
        end = nav[rows[-1]]
        local = np.r_[prev, nav[rows]]
        years[year] = {'return': float(end / prev - 1), 'sessions': len(rows),
                       'max_drawdown': float((local / np.maximum.accumulate(local) - 1).min())}
        prev = end
    elapsed = (date.fromisoformat(dates[-1]) - date.fromisoformat(start_date)).days / 365.25
    return {'total_return': float(nav[-1] - 1), 'cagr': float(nav[-1] ** (1 / elapsed) - 1) if elapsed else 0.,
            'max_drawdown': float(dd[trough]), 'drawdown_peak': dates[peak], 'drawdown_trough': dates[trough],
            'drawdown_recovery': dates[recovery] if recovery is not None else None,
            'drawdown_recovery_sessions': recovery - peak if recovery is not None else None,
            'longest_underwater_sessions': longest, 'current_underwater_sessions': run,
            'mean_exposure': float(np.mean([x['exposure'] for x in curve])),
            'mean_positions': float(np.mean([x['positions'] for x in curve])),
            'max_positions': max(x['positions'] for x in curve),
            'max_single_weight': max(x['largest_weight'] for x in curve),
            'stale_valuation_days': sum(x['stale_positions'] > 0 for x in curve), 'years': years}
