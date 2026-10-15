"""One-off US 1m regular-session history for W26 (quota approved by the user).

usage: fetch_us.py OUT.csv.gz START END CODE,CODE,...
Refuses any code outside the W26 list so quota cannot leak to other names.
"""
import csv
import gzip
import logging
import sys
import time

logging.disable(logging.CRITICAL)
import futu as ft  # noqa: E402

W26 = set('US.' + c for c in (
    'SPY AAPL AMD AMZN AVGO GOOGL INTC META MSFT MU NVDA TSLA SNDK '
    'NFLX ORCL PLTR COIN MSTR SMCI CRM ADBE QCOM UBER SHOP JPM BAC XOM UNH LLY '
    'COST WMT BA DIS HOOD SOFI BABA PDD ARM CRWD PANW GS').split())


def main():
    out, start, end = sys.argv[1], sys.argv[2], sys.argv[3]
    codes = sys.argv[4].split(',')
    stray = [c for c in codes if c not in W26]
    if stray:
        raise SystemExit('refuse, not in W26: %s' % stray)
    ctx = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
    try:
        print('quota before', ctx.get_history_kl_quota(get_detail=False)[1][:2], flush=True)
        n = calls = 0
        t0 = time.time()
        with gzip.open(out, 'wt', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(('code', 'time_key', 'open', 'high', 'low', 'close', 'volume', 'turnover', 'last_close'))
            for i, code in enumerate(codes):
                key = None
                while True:
                    calls += 1
                    if calls % 50 == 0:
                        wait = 30 - (time.time() - t0)
                        if wait > 0:
                            time.sleep(wait)
                        t0 = time.time()
                    ret, fr, key = ctx.request_history_kline(
                        code, start=start, end=end, ktype=ft.KLType.K_1M, autype=ft.AuType.QFQ,
                        max_count=1000, page_req_key=key, extended_time=False)
                    if ret != ft.RET_OK:
                        print('ERR', code, str(fr)[:120], flush=True)
                        break
                    for r in fr.itertuples(index=False):
                        w.writerow([code, str(r.time_key), r.open, r.high, r.low, r.close,
                                    r.volume, r.turnover, r.last_close])
                        n += 1
                    if key is None:
                        break
                print(i, code, n, flush=True)
        print('rows', n, 'quota after', ctx.get_history_kl_quota(get_detail=False)[1][:2], flush=True)
    finally:
        ctx.close()


if __name__ == '__main__':
    main()
