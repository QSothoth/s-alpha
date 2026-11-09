"""W1: the names he talks about on his streams as labels of what he chooses.  notes/PREREG_W1.md

    $PY -m studies.trader_replication.martin_w1
"""
import collections
import csv
import re
from pathlib import Path

import numpy as np

from . import review as RV, systems as SY, ticket_t4 as T4
from .martin_words import FOLDS, WORDS, words
from .pick_model import K, NAMES, day_matrix, features, fit

ROOT = Path(__file__).resolve().parents[2]
SUBS = ROOT / 'data' / 'martin-luk-subs'
FIX = dict(SNTK='SNDK', BMR='BMNR', AOI='AAOI', OMDS='ONDS', SKH='SKHY')
DROP = set('THE AND FOR ARE BUT NOT YOU ALL CAN HAS ONE OUT NOW NEW GOOD VERY EMA VWAP ADR USD AI US EP RS IPO ETF FOMO VCP SMA MA IT ON OR SO GO BE AT IN IS AS TV HP PS CK DK SK VW IQ EV CEO CPI FOMC UK AM PM OK WAY REAL SEE KEY LOW HIGH BIG'.split()) | {'QQQ', 'SPY', 'IWM', 'IGV', 'TQQQ', 'SQQQ', 'SOXL', 'SOXS', 'USIC'}


LONG = re.compile(r'\b(long|bought|buy|buying|breakout|breaking out|pullback|leader|leading|strong|entry|watch|watching|setup)\b')
SHORT = re.compile(r'\b(short|shorts|shorting|shorted|weak|lagging|fade)\b')


def stream_dates(path):
    v = collections.defaultdict(list)
    for r in csv.DictReader(open(path, encoding='utf-8')):
        for m in re.findall(r'([\w-]{11})@', r['source']):
            if r['entry_date']:
                v[m].append(r['entry_date'])
    return {k: max(x) for k, x in v.items() if (np.datetime64(max(x)) - np.datetime64(min(x))).astype(int) <= 5}


def mentions(A, ledger):
    code = {str(c).replace('US.', ''): j for j, c in enumerate(A['codes'])}
    days = np.array([str(d) for d in A['days']])
    out = []
    for vid, day in stream_dates(ledger).items():
        f = SUBS / f'{vid}.en-orig.txt'
        if not f.exists() or day < '2024-01-02':
            continue
        lines = f.read_text(errors='ignore').splitlines()
        toks = collections.Counter()
        for i, line in enumerate(lines):
            near = ' '.join(lines[max(0, i - 1):i + 2]).lower()
            if LONG.search(near) and not SHORT.search(near):
                toks.update(FIX.get(t, t) for t in re.findall(r'\b[A-Z]{2,5}\b', line))
        d = int(np.searchsorted(days, day))
        if d < len(days):
            out += [(day, d, code[t], t) for t in toks if t in code and t not in DROP]
    return out


def main():
    W, cfg = SY.get('martin_luk').load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    reg, rules, mask, pool = W.build(A, cfg)
    rk = T4.ranks(A, pool)
    M = mentions(A, base.ledger)
    print('mentions', len(M), 'streams', len({m[0] for m in M}), 'names', len({m[3] for m in M}), 'in list', sum(rk[m[1], m[2]] < K for m in M), flush=True)
    print(collections.Counter(m[3] for m in M).most_common(30), flush=True)
    F = {**features(A, rk), **words(A, rk)}
    said = np.zeros(rk.shape)
    for day, d, j, t in M:
        said[d + 1:d + 21, j] = 1
    F['said20'] = said
    F['said20'][:] = said
    keys = NAMES + tuple(WORDS)
    di = {str(d): i for i, d in enumerate(A['days'])}
    his = [(t.entry_date, di[t.entry_date], j) for t, j, a, z in base.located(A, base.trades()) if t.side == 'long' and t.dated and t.entry_date >= '2024-01-02' and t.entry_date in di]
    his = [h for h in his if rk[h[1], h[2]] < K]
    say = [(m[0], m[1], m[2]) for m in M if rk[m[1], m[2]] < K]
    def row(ks, x):
        names = np.flatnonzero(rk[x[1]] < K)
        return x[0], day_matrix(F, ks, names, x[1]), int(np.flatnonzero(names == x[2])[0])
    res = {}
    def cv(k, label, ks):
        L = [row(ks, x) for x in label]
        T = [row(ks, x) for x in his]
        pl = []
        for a, b in FOLDS:
            w = fit([(X, y) for dt, X, y in L if not a <= dt <= b], len(ks), 3.0)
            pl += [(int(((X @ w) > (X @ w)[y]).sum()), dt) for dt, X, y in T if a <= dt <= b]
        p = np.array([x[0] for x in pl])
        res[k] = {n: round(float((p < n).mean()), 2) for n in (4, 10, 20)}
        print(k, res[k], 'train', len(L), 'test', len(T), dict(sorted(zip(ks, w.round(2).tolist()), key=lambda v: -abs(v[1]))[:8]), flush=True)
    cv('trades', his, keys)
    cv('W1A_said', say, keys)
    cv('W1B_both', say + his, keys)
    cv('W1C_both_said20', say + his, keys + ('said20',))
    RV.write('martin_w2.json', res)


if __name__ == '__main__':
    main()
