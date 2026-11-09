"""Coverage audit of the traders' public dated longs against the shared data and the shared screening floors, before
any one system's rules: is the name in trader-data-v1 (or only v2), was it listed long enough for the 20 / 50 / 252-day
measures the screens read on the day before, and which of the common floors (price, 20-day turnover, ADR, the 50-day)
it fails.  Diagnosis only; reports/gap_review/coverage.json.

    $PY -m studies.trader_replication.coverage
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

import numpy as np

from . import ledger as L, panels

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / 'reports' / 'gap_review'
IDS = ('martin_luk', 'christian_flanders', 'clement_ang', 'qullamaggie', 'oliver_kell', 'mark_minervini',
       'marios_stamatoudis')
SPAN = ('2023-02-01', '2026-10-16')


def v2_names():
    u = json.loads((ROOT / 'data' / 'trader-data-v2' / 'us' / 'universe.json').read_text(encoding='utf-8'))
    return {s['code'] if isinstance(s, dict) else s for s in u['stocks']}


def audit():
    A = panels.arrays('us')
    F, days, has = A['F'], [str(d) for d in A['days']], A['has']
    col = {str(c): j for j, c in enumerate(A['codes'])}
    first = np.where(has.any(0), has.argmax(0), -1)            # first bar of each name in the panel
    v2 = v2_names()
    m = dict(to20=F.to20, adr=F.adr, sma50=F.sma(50), sma200=F.sma(200), hi252=F.hi(252), ret252=F.ret(252),
             raw=F.raw, c=F.c)
    rows, summary = [], {}
    for id_ in IDS:
        trades = [t for t in L.load(ROOT / 'studies' / id_ / 'notes' / 'trades.csv')
                  if t.side == 'long' and t.dated and SPAN[0] <= t.entry_date <= SPAN[1]
                  and L.market(t.ticker) == 'us']
        cnt = collections.Counter()
        for t in trades:
            r = dict(id=id_, trade=t.id, ticker=t.ticker, date=t.entry_date, setup=t.setup, flags=[])
            j = col.get('US.' + t.ticker)
            if j is None:
                r['flags'].append('not_in_v1' + ('_in_v2' if 'US.' + t.ticker in v2 else '_nor_v2'))
            else:
                d = int(np.searchsorted(A['days'], t.entry_date))
                if d >= len(days) or days[d] != t.entry_date or not has[d, j]:
                    r['flags'].append('no_bar_that_day')
                else:
                    age = d - first[j]
                    r['listed_days'] = int(age)
                    r['panel_start'] = bool(first[j] == 0)
                    p = {k: float(v[d - 1, j]) for k, v in m.items()}
                    r.update({k: round(v, 3) for k, v in p.items()})
                    nan = [k for k in ('to20', 'sma50', 'hi252', 'ret252') if not np.isfinite(p[k])]
                    if nan:
                        r['flags'].append(('young_' if first[j] > 0 else 'warmup_') + '+'.join(nan))
                    if np.isfinite(p['raw']) and p['raw'] < 5:
                        r['flags'].append('price<5')
                    if np.isfinite(p['to20']) and p['to20'] < 20e6:
                        r['flags'].append('to20<20M')
                    if np.isfinite(p['adr']) and p['adr'] < 3:
                        r['flags'].append('adr<3')
                    if np.isfinite(p['sma50']) and p['c'] <= p['sma50']:
                        r['flags'].append('below50')
            for f in r['flags'] or ['clear']:
                cnt[f.split('_to20')[0] if f.startswith(('young', 'warmup')) else f] += 1
            rows.append(r)
        summary[id_] = dict(n=len(trades), flags=dict(cnt.most_common()))
        print(id_, len(trades), dict(cnt.most_common()), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'coverage.json').write_text(json.dumps(dict(span=SPAN, summary=summary, rows=rows), indent=1,
                                                  ensure_ascii=False, default=float), encoding='utf-8')
    return rows


if __name__ == '__main__':
    for r in audit():
        if r['flags']:
            print(' ', r['id'][:10], r['trade'], r['ticker'], r['date'], r['setup'], r['flags'],
                  {k: r.get(k) for k in ('listed_days', 'raw', 'to20', 'adr')})
