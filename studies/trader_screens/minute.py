"""Five-minute bars of a whole stock list, for the provisional-bar study (notes/INTRADAY_PREREG_CN.md): one
foreground fetch per market, never scheduled, no historical K-line quota.

    US / HK   OpenD get_cur_kline(K_5M, 1000, unadjusted) after subscribing (batches of 200, held >= 1 minute):
              about 12 US / 15 HK sessions, regular hours only, time_key = the bar's end (US 09:35 .. 16:00, HK
              09:35 .. 16:00 without the lunch break; the 16:00 bar holds the closing auction)
    A-shares  Sina CN_MarketData.getKLineData scale=5 datalen=1023 (unadjusted): about 21 sessions, 09:35 .. 15:00,
              volume in shares, no turnover (estimated as volume x the bar's typical price)

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.trader_screens.minute fetch hk          # data/trader-screens/k5/hk_<day>.csv.gz

aggregate(stream(path), cuts) turns every (code, session) into the daily bar known at each cut (HH:MM, bars ending
at or before it), one row at a time: the US file holds ~3.4M bars, and reading it whole once took the 4GB machine
out of memory.
"""
from __future__ import annotations

import csv
import gzip
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
K5 = ROOT / 'data' / 'trader-screens' / 'k5'
HEADER = ('code', 'time_key', 'open', 'high', 'low', 'close', 'volume', 'turnover')
LAST_BAR = {'us': '16:00', 'hk': '16:00', 'cn': '15:00'}


def opend_k5(codes, log=print):
    import futu as ft
    q = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
    batch_n, hold = 200, 61.0
    try:
        for b in range(0, len(codes), batch_n):
            batch = list(codes[b:b + batch_n])
            ret, err = q.subscribe(batch, [ft.SubType.K_5M], subscribe_push=False)
            if ret != ft.RET_OK:
                raise RuntimeError(f'subscribe: {err}')
            t0 = time.time()
            time.sleep(5)
            try:
                for code in batch:
                    ret, df = q.get_cur_kline(code, 1000, ft.SubType.K_5M, ft.AuType.NONE)
                    if ret != ft.RET_OK:
                        log(f'  {code}: {df}')
                        continue
                    for r in df.itertuples():
                        yield (code, r.time_key, float(r.open), float(r.high), float(r.low), float(r.close),
                               float(r.volume), float(r.turnover))
            finally:
                time.sleep(max(0.0, hold - (time.time() - t0)))
                q.unsubscribe(batch, [ft.SubType.K_5M])
            log(f'  {min(b + batch_n, len(codes))}/{len(codes)}')
    finally:
        q.close()


def sina_k5(codes, log=print):
    from studies.trend_breakout.sources import CnHttpSource
    for k, code in enumerate(codes):
        symbol = code[:2].lower() + code[3:]
        url = ('https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData'
               f'?symbol={symbol}&scale=5&ma=no&datalen=1023')
        time.sleep(.5)
        try:
            rows = json.loads(CnHttpSource.get(url, CnHttpSource.REFERER) or b'null') or []
        except Exception as e:                                      # one failed name does not stop the list
            log(f'  {code}: {e}')
            continue
        for r in rows:
            o, h, l, c, v = (float(r[x]) for x in ('open', 'high', 'low', 'close', 'volume'))
            yield code, r['day'], o, h, l, c, v, v * (h + l + c) / 3
        if (k + 1) % 200 == 0:
            log(f'  {k + 1}/{len(codes)}')


def fetch(market, log=print):
    from studies import trader_data as TD
    from studies.trader_data.live import market_now
    codes = sorted(s['code'] for s in TD.dataset(market, 'live').stocks())
    K5.mkdir(parents=True, exist_ok=True)
    path = K5 / f"{market}_{market_now(market).date().isoformat()}.csv.gz"
    tmp = path.with_suffix('.part')
    n = 0
    with gzip.open(tmp, 'wt', encoding='utf-8', newline='') as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(HEADER)
        for row in (sina_k5 if market == 'cn' else opend_k5)(codes, log):
            w.writerow(row)
            n += 1
    tmp.rename(path)
    log(f'{market}: {n} bars of {len(codes)} names -> {path}')
    return path


def latest(market):
    """The newest fetch of the market."""
    got = sorted(K5.glob(f'{market}_????-??-??.csv.gz'))
    if not got:
        raise SystemExit(f'no five-minute bars of {market}: run `minute fetch {market}` first')
    return got[-1]


def stream(path, days=None, codes=None):
    """(code, day, hhmm, o, h, l, c, v, t) of a fetch file, one row at a time (only `days` / `codes` when given)."""
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as f:
        rows = csv.reader(f)
        if tuple(next(rows)) != HEADER:
            raise ValueError(f'unexpected header in {path}')
        for code, tk, *v in rows:
            day = tk[:10]
            if (days is None or day in days) and (codes is None or code in codes):
                yield (code, day, tk[11:16], *map(float, v))


def aggregate(rows, cuts):
    """{(code, day): dict(first, last, last_v, parts={cut | 'full': (o, h, l, c, v, t)})} from rows in time order
    within each (code, day): the bar known at every cut (bars ending at or before it), without keeping the bars."""
    out = {}
    for code, day, hh, o, h, l, c, v, t in rows:
        s = out.get((code, day))
        if s is None:
            s = out[(code, day)] = dict(first=hh, last=hh, last_v=v, cur=[o, h, l, c, v, t], parts={})
        else:
            cur = s['cur']
            cur[1], cur[2], cur[3] = max(cur[1], h), min(cur[2], l), c
            cur[4] += v
            cur[5] += t
            s['last'], s['last_v'] = hh, v
        for cut in cuts:
            if hh <= cut:
                s['parts'][cut] = tuple(s['cur'])
    for s in out.values():
        s['parts']['full'] = tuple(s.pop('cur'))
    return out


def complete(s, market):
    """A whole session: first bar by 10:00 (the first day of a 1000-bar window starts mid-session), last at the
    close."""
    return s['first'] <= '10:00' and s['last'] == LAST_BAR[market]


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'fetch':
        fetch(sys.argv[2])
    else:
        raise SystemExit(__doc__)
