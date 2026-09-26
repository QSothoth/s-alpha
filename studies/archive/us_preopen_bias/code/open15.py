"""S28: daily Top 3 long / Top 3 short decided at 09:45 from the first 15 minutes (notes/S28_PREREG.md).

Inputs: 5-minute regular-session K (time_key = bar close, ET; first bar 09:35).  Per day T and name:
drive = 09:45 close / 09:30 open - 1, gap = 09:30 open / previous close - 1 (both / ATR20), rvol15 = 09:30-09:45 volume /
mean of the same window over the previous 14 sessions.  Label: 09:45 close -> 16:00 close (shorts negated), net of
topn.COST_BP.  Standard library only.

    python3 studies/us_preopen_bias/code/open15.py --k5 data/preopen-us-k5-select-v1 --k5 data/preopen-s20-select-v1 \
        --start 2019-10-01 --end 2024-05-31 --split 2022-06-01
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topn  # noqa: E402

HERE = Path(__file__).resolve().parents[1]
ETFS = {'SPY', 'QQQ', 'IWM'}
LARGE = {'AAPL', 'AMD', 'AMZN', 'AVGO', 'GOOGL', 'INTC', 'META', 'MSFT', 'MU', 'NVDA', 'TSLA'}   # k5 releases minus the ETFs
SMALL_EXCLUDE = {'KOD', 'AVTX'}
TOP_IN_PLAY, MIN_POOL, N = 10, 12, 3
FIRST = ('09:35', '09:40', '09:45')


def universe():
    """The 11 large single stocks of the k5 releases plus the small / mid caps of notes/universe_smallmid.json."""
    d = json.load(open(HERE / 'notes' / 'universe_smallmid.json', encoding='utf-8'))
    small = {x['code'].split('.')[1] for v in d['themes'].values() for x in v} - SMALL_EXCLUDE
    return small


def load_days(dirs, names=None):
    """{sym: {date: {'o', 'p945', 'c', 'h', 'l', 'v15'}}} from k5/<SYM>.csv in every dir (later dirs extend earlier)."""
    out = defaultdict(dict)
    for d in dirs:
        for f in sorted((Path(d) / 'k5').glob('*.csv')):
            sym = f.stem
            if sym in ETFS or (names is not None and sym not in names):
                continue
            bars = defaultdict(list)
            with f.open(encoding='utf-8') as fh:
                for r in csv.DictReader(fh):
                    bars[r['time_key'][:10]].append(r)
            for day, rows in bars.items():
                rows.sort(key=lambda r: r['time_key'])
                first = [r for r in rows if r['time_key'][11:16] in FIRST]
                if len(first) != 3 or rows[0]['time_key'][11:16] != '09:35' or rows[-1]['time_key'][11:16] != '16:00':
                    continue
                out[sym][day] = {'o': float(first[0]['open']), 'p945': float(first[-1]['close']), 'c': float(rows[-1]['close']),
                                 'h': max(float(r['high']) for r in rows), 'l': min(float(r['low']) for r in rows),
                                 'v15': sum(float(r['volume']) for r in first)}
    return out


def rows_for(days_by_sym, start, end):
    """[{'symbol', 'date', 'f': {drive_atr, gap_atr, rvol15}, 'y': {'ret_oc': 09:45 -> close}}], point-in-time."""
    out = []
    for sym, days in days_by_sym.items():
        order = sorted(days)
        for i in range(21, len(order)):
            T = order[i]
            if not (start <= T <= end):
                continue
            x, prev = days[T], days[order[i - 1]]
            tr = []
            for j in range(i - 20, i):
                a, b = days[order[j]], days[order[j - 1]]
                tr.append((max(a['h'], b['c']) - min(a['l'], b['c'])) / b['c'])
            atr = mean(tr)
            v14 = [days[order[j]]['v15'] for j in range(i - 14, i) if days[order[j]]['v15'] > 0]
            if atr <= 0 or len(v14) < 10 or x['o'] <= 0:
                continue
            out.append({'symbol': 'US.' + sym, 'date': T,
                        'f': {'drive_atr': (x['p945'] / x['o'] - 1) / atr, 'gap_atr': (x['o'] / prev['c'] - 1) / atr,
                              'rvol15': x['v15'] / mean(v14), 'atr20': atr},
                        'y': {'ret_oc': x['c'] / x['p945'] - 1}})
    return out


def pools(rows):
    out = defaultdict(list)
    for r in rows:
        out[r['date']].append(r)
    return {d: v for d, v in out.items() if len(v) >= MIN_POOL}


def in_play(pool, top=TOP_IN_PLAY, min_rvol=1.0):
    xs = sorted((r for r in pool if r['f']['rvol15'] >= min_rvol), key=lambda r: (-r['f']['rvol15'], r['symbol']))
    return xs[:top] if top else xs


def signed_picks(pool, score, n=N, flip=False):
    """Top n with score > 0 long and bottom n with score < 0 short (reversed with ``flip``)."""
    xs = sorted(pool, key=lambda r: (score(r['f']), r['symbol']))
    up = [r for r in xs if score(r['f']) > 0][-n:]
    dn = [r for r in xs if score(r['f']) < 0][:n]
    if flip:
        return [(-1, r) for r in up] + [(1, r) for r in dn]
    return [(1, r) for r in up] + [(-1, r) for r in dn]


DRIVE = lambda f: f['drive_atr']  # noqa: E731
GAP_DRIVE = lambda f: f['gap_atr'] + f['drive_atr']  # noqa: E731


def candidates(day_pools):
    rules = {
        'O1_sip_drive': lambda p: signed_picks(in_play(p), DRIVE),
        'O2_drive_all': lambda p: signed_picks(p, DRIVE),
        'O3_sip_gap_drive': lambda p: signed_picks(in_play(p), GAP_DRIVE),
        'O4_sip_fade': lambda p: signed_picks(in_play(p), DRIVE, flip=True),
        'O5_sip_drive_rvol2': lambda p: signed_picks(in_play(p, top=None, min_rvol=2.0), DRIVE),
    }
    return {name: [(d, side, r) for d in sorted(day_pools) for side, r in fn(day_pools[d])] for name, fn in rules.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--k5', action='append', required=True)
    ap.add_argument('--start', required=True)
    ap.add_argument('--end', required=True)
    ap.add_argument('--split', default=None)
    ap.add_argument('--final', action='store_true')
    ap.add_argument('--only', default=None)
    a = ap.parse_args()
    data = load_days(a.k5, LARGE | universe())
    large = sorted(s for s in data if s in LARGE)
    print('names %d (large %d: %s; small/mid %d)' % (len(data), len(large), ' '.join(large), len(data) - len(large)))
    rows = rows_for(data, a.start, a.end)
    dp = pools(rows)
    print('days %d, mean pool %.1f, mean in-play %.1f' % (len(dp), mean(len(v) for v in dp.values()),
                                                          mean(len(in_play(v)) for v in dp.values())))
    for name, items in candidates(dp).items():
        if a.only and name.split('_')[0] not in a.only.split(','):
            continue
        m = topn.evaluate(items, a.split)
        print(topn.fmt(name, m, topn.final_gates(m) if a.final else topn.gates(m)))
        b = topn.basket(items, a.split)
        if b.get('days'):
            print(topn.fmt_basket('', b))
        for label, keep in (('large', lambda r: r['symbol'][3:] in large), ('small/mid', lambda r: r['symbol'][3:] not in large)):
            sub = [x for x in items if keep(x[2])]
            if sub:
                mm = topn.evaluate(sub)
                print('      %-9s n=%5d win %.1f%% payoff %s exp %+6.1fbp [%+6.1f, %+6.1f]' % (
                    label, mm['n'], 100 * mm['win'], '%.2f' % mm['payoff'] if mm['payoff'] else '-', mm['exp'],
                    mm['ci95'][0], mm['ci95'][1]))


if __name__ == '__main__':
    main()
