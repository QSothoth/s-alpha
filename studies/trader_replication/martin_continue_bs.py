"""BS: attribute BQ's independent annual account paths by actual trade identity."""
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np

from . import compare, system
from .martin_continue_bq import prepare
from .martin_strong_scan import nl_rules


def summarize(rows, equity_before):
    closed = [t for t in rows if t['why'] != 'end']
    open_ = [t for t in rows if t['why'] == 'end']
    winners = [t['ret'] for t in closed if t['ret'] > 0]
    losers = [t['ret'] for t in closed if t['ret'] < 0]
    capital = [t['executions'][0]['price'] * t['executions'][0]['shares'] for t in closed]
    total_capital = sum(capital)
    widths = [t['risk_pct'] for t in closed]
    weights = [t['executions'][0]['price'] * t['executions'][0]['shares'] / equity_before[t['entry']]
               for t in closed if equity_before[t['entry']] > 0]
    return {'entries': len(rows), 'closed': len(closed), 'open_at_end': len(open_),
            'win': len(winners) / len(closed) if closed else None,
            'avg_win': float(np.mean(winners)) if winners else None,
            'avg_loss': float(np.mean(losers)) if losers else None,
            'mean_ret': float(np.mean([t['ret'] for t in closed])) if closed else None,
            'mean_ret_invested': float(np.mean([t['ret_invested'] for t in closed])) if closed else None,
            'weighted_ret': sum(t['pnl'] for t in closed) / total_capital if total_capital else None,
            'closed_pnl': sum(t['pnl'] for t in closed), 'open_mark_pnl': sum(t['pnl'] for t in open_),
            'initial_capital_sum': total_capital,
            'median_entry_equity_fraction': float(np.median(weights)) if weights else None,
            'median_stop_width': float(np.median(widths)) if widths else None,
            'at_least_30pct': int(sum(t['ret'] >= .30 for t in closed)),
            'reasons': dict(Counter(t['why'] for t in closed))}


def key_trades(trades):
    out = {(t['entry'], t['code'], t['side'], t['kind']): t for t in trades}
    if len(out) != len(trades):
        raise ValueError('trade identity occurs more than once')
    return out


def big_windows(D, rows, year):
    output = []
    for day, j, _, _, date in D.big:
        if not date.startswith(year):
            continue
        peak = day + 1 + int(np.nanargmax(D.h[day + 1:day + 21, j]))
        code = str(D.A['codes'][j])
        item = {'date': date, 'code': code}
        for name, trades in rows.items():
            matched = [t for t in trades if t['code'] == code and t['side'] > 0 and
                       D.di[t['entry']] <= peak and D.di[t['exit']] >= day]
            item[name] = {'held': bool(matched), 'positions': len(matched),
                          'closed_pnl': sum(t['pnl'] for t in matched if t['why'] != 'end'),
                          'open_mark_pnl': sum(t['pnl'] for t in matched if t['why'] == 'end')}
        output.append(item)
    return output


def main():
    D, model, h3, reg, b2, d, ret, labels, score, h, fits, keys = prepare()
    del reg, b2, d, ret, labels, score, h, fits, keys
    rules = nl_rules(D, 6)
    px, em = D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, rules)
    root = Path(__file__).resolve().parents[2]
    previous = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_bq.json').read_text())
    result = {}
    for year, start, end in (('2025', '2025-01-02', '2025-12-31'),
                             ('2026', '2026-01-02', '2026-10-16')):
        keyed, histories, capital = {}, {}, {}
        for name, book in (('MODEL', model), ('H3', h3)):
            curve, dates, trades = system.simulate(px, em, rules, book, start, end, audit=True)
            prior = np.concatenate(([1.0], curve[:-1]))
            capital[name] = dict(zip(map(str, dates), map(float, prior)))
            keyed[name], histories[name] = key_trades(trades), trades
            metric = compare.metrics(curve, dates, trades, book,
                                     int(np.searchsorted(D.A['days'], start)),
                                     int(np.searchsorted(D.A['days'], end, side='right')))
            reference = previous['results'][name]['fresh_' + year]['metrics']
            if abs(metric['by_year'][year] - reference['by_year'][year]) > 1e-12 or len(trades) != reference['entries_by_year'][year]:
                raise AssertionError(f'{name} {year} does not reproduce BQ')
            capital[name]['_net'] = float(curve[-1] - 1)
        m, h = set(keyed['MODEL']), set(keyed['H3'])
        common = m & h
        groups = {}
        for name, which, selection in (('model_common', 'MODEL', common), ('h3_common', 'H3', common),
                                       ('model_only', 'MODEL', m - h), ('h3_only', 'H3', h - m)):
            groups[name] = summarize([keyed[which][k] for k in sorted(selection)], capital[which])
        reconciliation = {}
        for name in ('MODEL', 'H3'):
            total = sum(t['pnl'] for t in histories[name])
            reconciliation[name] = dict(equity_change=capital[name]['_net'], trade_pnl=total,
                                        residual=capital[name]['_net'] - total)
        result[year] = {'common': len(common), 'model_only': len(m - h), 'h3_only': len(h - m),
                        'groups': groups, 'reconciliation': reconciliation,
                        'big_windows': big_windows(D, histories, year)}
        print('year', year, 'entries', len(m), len(h), 'common', len(common), flush=True)
    paths = ('studies/trader_replication/martin_continue_bs.py', 'studies/trader_replication/martin_continue_bq.py',
             'studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_strong.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py')
    out = {'dataset_digest': D.A['digest'], 'years': result,
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_bs.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
