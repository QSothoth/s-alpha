"""QQQ 1-minute bars (regular + extended hours) as the Nasdaq-100 futures proxy for the David Trullas study.

OpenD has no US-futures quote permission here, so NQ/MNQ cannot be fetched. QQQ is already charged in the
history quota within 30 days (custody freeze), so re-fetching it costs no new quota: `fetch` refuses to run
otherwise. Output: data/trullas-qqq-k1/QQQ_k1_raw.csv.gz (time ET, open, high, low, close, volume), unadjusted.

    /opt/opend-us-options/.venv/bin/python -m studies.david_trullas.fetch 2024-01-02 2026-10-27
"""
import csv
import gzip
import os
import sys
import time

OUT = os.environ.get('TRULLAS_DATA', '/opt/opend-us-options/data/trullas-qqq-k1')
CODE = 'US.QQQ'


def fetch(start, end):
    import futu as ft
    q = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
    try:
        used, left, detail = q.get_history_kl_quota(get_detail=True)[1]
        if not any(d['code'] == CODE and '[opt' not in d['name'] for d in detail):
            raise SystemExit(f'{CODE} not charged in the last 30 days: fetching would spend new quota, ask first')
        rows, key = [], None
        while True:
            time.sleep(.55)
            ret, df, key = q.request_history_kline(CODE, start=start, end=end, ktype=ft.KLType.K_1M,
                                                   autype=ft.AuType.NONE, max_count=1000, page_req_key=key,
                                                   extended_time=True)
            if ret != ft.RET_OK:
                raise RuntimeError(f'request_history_kline: {df}')
            rows += [(r.time_key, r.open, r.high, r.low, r.close, int(r.volume)) for r in df.itertuples()]
            if key is None:
                break
        after = q.get_history_kl_quota()[1]
        print(f'quota before {used}/{left} after {after[0]}/{after[1]}; rows {len(rows)}')
    finally:
        q.close()
    os.makedirs(OUT, exist_ok=True)
    with gzip.open(os.path.join(OUT, 'QQQ_k1_raw.csv.gz'), 'wt', newline='') as f:
        w = csv.writer(f)
        w.writerow(['time', 'open', 'high', 'low', 'close', 'volume'])
        w.writerows(rows)


if __name__ == '__main__':
    fetch(sys.argv[1], sys.argv[2])
