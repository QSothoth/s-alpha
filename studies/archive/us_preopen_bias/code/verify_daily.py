"""Cross-check OpenD daily closes against Yahoo (adjclose) and Tencent (qfq), consensus rule.

On tradable day pairs (nominal close >= 5 on both days) a pair is OpenD-suspect when OpenD's close-to-close return
disagrees (> 0.2% + cent rounding) with every source that has it.  A symbol passes with <= 1% suspect pairs.
Both sources round prices to the cent, and Tencent's dividend adjustment differs, hence the consensus rule.

    python3 studies/us_preopen_bias/code/verify_daily.py --data data/preopen-s23-raw > reports/s23_verify_raw.txt
"""
import argparse
import csv
import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

UA = {'User-Agent': 'Mozilla/5.0'}


def _get(url):
    err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as e:   # retry transient network errors
            err = e
            time.sleep(2 * (attempt + 1))
    raise err


def yahoo(tick):
    d = _get('https://query1.finance.yahoo.com/v8/finance/chart/%s?period1=1577836800&period2=%d&interval=1d&events=div,split'
             % (tick, int(time.time())))['chart']['result'][0]
    tz = timezone(timedelta(hours=-5))
    return {datetime.fromtimestamp(t, timezone.utc).astimezone(tz).date().isoformat(): a
            for t, a in zip(d['timestamp'], d['indicators']['adjclose'][0]['adjclose']) if a}


def tencent(tick):
    """A wrong exchange suffix still answers with today's quote only: keep the longest series."""
    best = {}
    for suffix in ('.OQ', '.N', '.AM', ''):
        key = 'us%s%s' % (tick, suffix)
        try:
            d = _get('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=%s,day,,,800,qfq' % key)
        except Exception:
            continue
        data = d.get('data')
        rows = data.get(key) if isinstance(data, dict) else None
        k = (rows or {}).get('qfqday') or (rows or {}).get('day') or []
        if len(k) > len(best):
            best = {r[0]: float(r[2]) for r in k}
    return best


def read(path, col='close'):
    with open(path, encoding='utf-8') as fh:
        return {r['date']: float(r[col]) for r in csv.DictReader(fh)}


def consensus(od, sources, nominal, min_price=5.0):
    days = sorted(d for d in od if nominal.get(d, 0) >= min_price)
    n = bad = 0
    per = {k: [0, 0] for k in sources}
    for p, d in zip(days, days[1:]):
        votes = []
        for k, b in sources.items():
            if p in b and d in b:
                ok = abs((od[d] / od[p] - 1) - (b[d] / b[p] - 1)) < 0.002 + 0.01 / min(b[p], b[d])
                votes.append(ok)
                per[k][0] += 1
                per[k][1] += ok
        if votes:
            n += 1
            bad += not any(votes)
    return n, (bad / n if n else None), {k: (c, g / c if c else None) for k, (c, g) in per.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True, help='dir with daily/ (adjusted) and daily_none/')
    ap.add_argument('--sources', default='yahoo,tencent', help='comma list; Tencent throttles long runs')
    ap.add_argument('--min-price', type=float, default=5.0, help='tradable-day price floor (the study gate)')
    ap.add_argument('--only', default=None, help='comma list of tickers')
    a = ap.parse_args()
    use = set(a.sources.split(','))
    for p in sorted(Path(a.data, 'daily').glob('*.csv')):
        tick = p.stem
        if a.only and tick not in a.only.split(','):
            continue
        od, nominal = read(p), read(Path(a.data, 'daily_none', p.name))
        srcs, errs = {}, {}
        for name, fn in (('yahoo', yahoo), ('tencent', tencent)):
            if name not in use:
                continue
            try:
                srcs[name] = fn(tick)
            except Exception as e:
                errs[name] = str(e)[:60]
        n, bad, per = consensus(od, srcs, nominal, a.min_price)
        print(json.dumps({'symbol': 'US.' + tick, 'tradable_pairs': n, 'suspect': bad, 'per_source': per, 'errors': errs,
                          'pass': n >= 20 and bad is not None and bad <= 0.01}), flush=True)
        time.sleep(0.5)


if __name__ == '__main__':
    main()
