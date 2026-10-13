"""TF10 (notes/TF10_PREREG.md): A-share pre-holiday effect on broad indices, existing index data only.

    PY="env PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.trend_breakout.run_tf10 dev          # P1-P3 on 2005-2015, pick the winner
    $PY -m studies.trend_breakout.run_tf10 holdout P?   # the dev winner on 2016-01-01 -> 2026-10-09, once
"""
from __future__ import annotations

from datetime import date
import json
import math
import sys

import numpy as np

from .run_tf1 import REPORTS
from .run_tf9 import INDICES, load

SPANS = {'dev': ('2005-01-01', '2015-12-31'), 'holdout': ('2016-01-01', '2026-10-09')}
DAYS = {'P1': 3, 'P2': 1, 'P3': 5}
COST = 0.001
MAIN = 'SH.000300'


def holidays(d):
    """Rows i whose next trading day starts a long break (prereg section 2): gap >= 5 calendar days, or a
    4-day gap whose next trading day is not a Monday."""
    out = []
    for i in range(len(d) - 1):
        a, b = date.fromisoformat(d[i]), date.fromisoformat(d[i + 1])
        gap = (b - a).days
        if gap >= 5 or (gap == 4 and b.weekday() != 0):
            out.append(i)
    return out


def kind(day):
    m = int(day[5:7])
    return '春节' if m in (1, 2) else '国庆' if m in (9, 10) else '其他'


def window_returns(o, c, k):
    """Open of row t to close of row t + k - 1, for every t."""
    r = np.full(len(c), np.nan)
    r[:len(c) - k + 1] = c[k - 1:] / o[:len(c) - k + 1] - 1
    return r


def evaluate(code, rule, span, base=None):
    d, o, h, l, c = load(code)
    k = DAYS[rule]
    wr = window_returns(o, c, k)
    if base is None:  # the unconditional k-day open-to-close mean, from the development span only
        dev = (d >= SPANS['dev'][0]) & (d <= SPANS['dev'][1])
        base = float(np.nanmean(wr[dev]))
    events = []
    for i in holidays(d):
        s = i - k + 1
        if s < 0 or not (span[0] <= d[s] and d[i] <= span[1]):
            continue
        r = (c[i] * (1 - COST)) / (o[s] * (1 + COST)) - 1
        events.append((d[i], kind(d[i]), r, r - base))
    x = np.array([e[3] for e in events])
    res = {'n': len(x), 'base': base}
    if len(x) > 1:
        res.update({'mean_excess': float(x.mean()), 't': float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))),
                    'win_rate': float(np.mean([e[2] > 0 for e in events])),
                    'mean_raw': float(np.mean([e[2] for e in events])),
                    'by_kind': {t: {'n': sum(e[1] == t for e in events),
                                    'mean_excess': float(np.mean([e[3] for e in events if e[1] == t]))}
                                for t in ('春节', '国庆', '其他') if any(e[1] == t for e in events)},
                    'per_year': float(x.mean() * len(x) / max(1, len({e[0][:4] for e in events}))),
                    'events': [list(e) for e in events]})
    return res


def main():
    mode = sys.argv[1]
    rules = tuple(DAYS) if mode == 'dev' else (sys.argv[2],)
    if mode == 'holdout':
        dev = json.loads((REPORTS / 'tf10_dev.json').read_text(encoding='utf-8'))
        if dev['winner'] != rules[0]:
            raise SystemExit(f'holdout must use the dev winner {dev["winner"]}')
    out = {'span': SPANS[mode], 'results': {}}
    for rule in rules:
        out['results'][rule] = {}
        for code, name in INDICES.items():
            x = evaluate(code, rule, SPANS[mode])
            out['results'][rule][code] = x
            if x['n'] > 1:
                print(f"{rule} {name}: n={x['n']} excess={x['mean_excess']:+.2%} t={x['t']:.2f} "
                      f"win={x['win_rate']:.0%} raw={x['mean_raw']:+.2%} per_year={x['per_year']:+.2%} "
                      f"{ {t: (v['n'], round(100 * v['mean_excess'], 2)) for t, v in x['by_kind'].items()} }",
                      flush=True)
    if mode == 'dev':
        ok = [r for r in rules if out['results'][r][MAIN].get('t', 0) >= 2 and out['results'][r][MAIN]['win_rate'] > 0.5]
        out['winner'] = max(ok, key=lambda r: out['results'][r][MAIN]['mean_excess']) if ok else None
        print('winner:', out['winner'])
    else:
        per = out['results'][rules[0]]
        others = sum(per[c].get('mean_excess', -1) > 0 for c in INDICES if c != MAIN)
        m = per[MAIN]
        out['verdict'] = bool(m.get('mean_excess', -1) > 0 and m.get('t', 0) >= 2 and others >= 3)
        print('others positive', others, 'verdict:', out['verdict'])
    (REPORTS / f'tf10_{mode}.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
