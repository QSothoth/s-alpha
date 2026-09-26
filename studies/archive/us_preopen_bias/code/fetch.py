"""One-time pull of the pre-open bias dataset from a local OpenD (read-only).

Only symbols already charged in the 30-day history-kline quota are allowed for
``request_history_kline``; the other endpoints do not touch that quota.

    /opt/futu-opend/venv/bin/python studies/us_preopen_bias/code/fetch.py --out data/preopen-us-raw
"""
import argparse
import csv
import json
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path

logging.disable(logging.CRITICAL)
import futu as ft  # noqa: E402

SYMBOLS = ('US.SPY', 'US.QQQ', 'US.IWM', 'US.AAPL', 'US.MSFT', 'US.NVDA', 'US.TSLA', 'US.META', 'US.AMZN',
           'US.GOOGL', 'US.AMD', 'US.MU', 'US.INTC', 'US.AVGO', 'US.SNDK', 'US.SKHY')
KLINE_START = '2022-06-01'
OPTION_START = '2023-01-01'   # OpenD serves option stats / IV from 2023-06 on
SHORT_START = '2022-06-01'


class Client:
    def __init__(self, ctx, pause=0.55):
        self.ctx, self.pause, self.calls = ctx, pause, 0

    def call(self, name, *args, **kw):
        for attempt in range(6):
            time.sleep(self.pause)
            self.calls += 1
            r = getattr(self.ctx, name)(*args, **kw)
            if r[0] == ft.RET_OK:
                return r
            msg = str(r[1])
            if 'freq' in msg.lower() or '频率' in msg or 'too many' in msg.lower():
                time.sleep(10 * (attempt + 1))
                continue
            raise RuntimeError('%s %s: %s' % (name, args[:1], msg))
        raise RuntimeError('%s %s: rate limited' % (name, args[:1]))


def write_csv(path, rows, cols):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c, '') for c in cols])
    return len(rows)


def records(df):
    return [dict(zip(df.columns, row)) for row in df.itertuples(index=False)]


def fetch_kline(c, code, end, start=KLINE_START, autype=None):
    rows, key = [], None
    while True:
        _, df, key = c.call('request_history_kline', code, start=start, end=end, ktype=ft.KLType.K_DAY,
                            autype=autype or ft.AuType.QFQ, max_count=1000, page_req_key=key)
        rows += [{'date': str(r['time_key'])[:10], 'open': r['open'], 'high': r['high'], 'low': r['low'],
                  'close': r['close'], 'volume': r['volume'], 'turnover': r['turnover']} for r in records(df)]
        if key is None:
            return rows


def fetch_extended_30m(c, code, start, end):
    """Pre-market (time_key <= 09:30) and after-hours (> 16:00) 30m bars; time_key is the bar close (ET)."""
    rows, key = [], None
    while True:
        _, df, key = c.call('request_history_kline', code, start=start, end=end, ktype=ft.KLType.K_30M,
                            autype=ft.AuType.QFQ, max_count=1000, page_req_key=key, extended_time=True)
        for r in records(df):
            hm = str(r['time_key'])[11:16]
            if hm <= '09:30' or hm > '16:00':
                rows.append({'time_key': str(r['time_key']), 'open': r['open'], 'high': r['high'], 'low': r['low'],
                             'close': r['close'], 'volume': r['volume'], 'turnover': r['turnover']})
        if key is None:
            return rows


def fetch_paged(c, name, code, end):
    rows, key = [], None
    while True:
        _, df, key = c.call(name, code, begin_time=OPTION_START, end_time=end, page_req_key=key)
        rows += records(df)
        if key is None:
            return rows


def fetch_short_volume(c, code):
    rows, key = [], None
    while True:
        r = c.call('get_daily_short_volume', code, next_key=key, num=50)
        df = r[1]
        if not len(df):
            return rows
        rows += records(df)
        if min(df.timestamp_str) < SHORT_START:
            return rows
        key = str(int(df.timestamp.min()))


def fetch_capital_flow(c, code, end):
    _, df = c.call('get_capital_flow', code, period_type=ft.PeriodType.DAY, start='2020-01-01', end=end)
    return [{'date': str(r['capital_flow_item_time'])[:10], **{k: r[k] for k in
             ('in_flow', 'super_in_flow', 'big_in_flow', 'mid_in_flow', 'sml_in_flow', 'main_in_flow')}}
            for r in records(df)]


def fetch_broad(ctx, c, out, symbols, end, quota_before, batch=100):
    """Daily K (QFQ and unadjusted) via the K_DAY subscription in batches of 100 (released after each batch, no
    history-kline quota), then option stats and IV/HV via the history statistics APIs."""
    log = {'fetched_at': datetime.utcnow().isoformat() + 'Z', 'end': end, 'symbols': symbols, 'rows': {},
           'subscription_before': ctx.query_subscription()[1]}
    cols = ['date', 'open', 'high', 'low', 'close', 'volume', 'turnover']
    for i in range(0, len(symbols), batch):
        part = symbols[i:i + batch]
        ret, msg = ctx.subscribe(part, [ft.SubType.K_DAY], subscribe_push=False)
        if ret != ft.RET_OK:
            raise SystemExit('subscribe failed: %s' % msg)
        t0 = time.time()
        try:
            for s in part:
                tag = s.split('.')[1] + '.csv'
                n = log['rows'].setdefault(s, {})
                for sub, au in (('daily', ft.AuType.QFQ), ('daily_none', ft.AuType.NONE)):
                    _, df = c.call('get_cur_kline', s, 1000, ft.SubType.K_DAY, au)
                    rows = [{'date': str(r['time_key'])[:10], 'open': r['open'], 'high': r['high'], 'low': r['low'],
                             'close': r['close'], 'volume': r['volume'], 'turnover': r['turnover']}
                            for r in records(df) if str(r['time_key'])[:10] <= end]
                    n[sub] = write_csv(out / sub / tag, rows, cols)
        finally:
            time.sleep(max(0, 65 - (time.time() - t0)))   # OpenD refuses to unsubscribe within a minute
            ctx.unsubscribe(part, [ft.SubType.K_DAY])
        print('daily batch', i // batch + 1, 'done', ctx.query_subscription()[1].get('total_used'), flush=True)
    for s in symbols:
        tag = s.split('.')[1] + '.csv'
        n = log['rows'][s]
        st = fetch_paged(c, 'get_option_underlying_his_statistic', s, end)
        n['option_stats'] = write_csv(out / 'option_stats' / tag, sorted(st, key=lambda r: r['time']),
                                      ['time', 'option_volume', 'call_volume', 'put_volume', 'put_call_volume_ratio',
                                       'option_open_interest', 'call_open_interest', 'put_open_interest', 'underlying_price'])
        iv = fetch_paged(c, 'get_option_underlying_his_volatility', s, end)
        n['iv'] = write_csv(out / 'iv' / tag, sorted(iv, key=lambda r: r['time']), ['time', 'iv', 'hv', 'underlying_price'])
        print(s, n, 'calls', c.calls, flush=True)
    log['subscription_after'] = ctx.query_subscription()[1]
    log.update(calls=c.calls, kline_quota_before=list(quota_before), kline_quota_after=list(ctx.get_history_kl_quota()[1][:2]))
    (out / 'fetch_log.json').write_text(json.dumps(log, indent=1, ensure_ascii=False, default=str), encoding='utf-8')
    print(json.dumps({k: log[k] for k in ('calls', 'kline_quota_before', 'kline_quota_after')}))


def fetch_xsec(ctx, c, out, symbols, end, quota_before):
    """S10: names outside the kline quota.  get_cur_kline needs a K_DAY subscription (subscription quota, released
    by unsubscribing after a minute); it returns the latest 1000 daily bars."""
    log = {'fetched_at': datetime.utcnow().isoformat() + 'Z', 'end': end, 'symbols': symbols, 'rows': {},
           'subscription_before': ctx.query_subscription()[1]}
    ret, msg = ctx.subscribe(symbols, [ft.SubType.K_DAY], subscribe_push=False)
    if ret != ft.RET_OK:
        raise SystemExit('subscribe failed: %s' % msg)
    log['subscription_during'] = ctx.query_subscription()[1]
    t0 = time.time()
    try:
        for s in symbols:
            _, df = c.call('get_cur_kline', s, 1000, ft.SubType.K_DAY, ft.AuType.QFQ)
            rows = [{'date': str(r['time_key'])[:10], 'open': r['open'], 'high': r['high'], 'low': r['low'],
                     'close': r['close'], 'volume': r['volume'], 'turnover': r['turnover']}
                    for r in records(df) if str(r['time_key'])[:10] <= end]
            tag = s.split('.')[1] + '.csv'
            n = {'daily': write_csv(out / 'daily' / tag, rows, ['date', 'open', 'high', 'low', 'close', 'volume', 'turnover'])}
            cf = [r for r in fetch_capital_flow(c, s, end) if r['date'] <= end]
            n['capital_flow'] = write_csv(out / 'capital_flow' / tag, cf, ['date', 'in_flow', 'super_in_flow', 'big_in_flow',
                                                                           'mid_in_flow', 'sml_in_flow', 'main_in_flow'])
            log['rows'][s] = n
            print(s, n, flush=True)
    finally:
        time.sleep(max(0, 65 - (time.time() - t0)))   # OpenD refuses to unsubscribe within a minute
        log['unsubscribe'] = ctx.unsubscribe(symbols, [ft.SubType.K_DAY])[0] == ft.RET_OK
        log['subscription_after'] = ctx.query_subscription()[1]
    log.update(calls=c.calls, kline_quota_before=list(quota_before), kline_quota_after=list(ctx.get_history_kl_quota()[1][:2]))
    (out / 'fetch_log.json').write_text(json.dumps(log, indent=1, ensure_ascii=False, default=str), encoding='utf-8')
    print(json.dumps({k: log[k] for k in ('calls', 'kline_quota_before', 'kline_quota_after', 'unsubscribe')}),
          log['subscription_after'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--end', default='2026-09-23')
    ap.add_argument('--symbols', default=','.join(SYMBOLS))
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=11111)
    ap.add_argument('--allow-new', type=int, default=0,
                    help='allow charging up to N symbols not yet in the 30-day history-kline quota (ask the user first)')
    ap.add_argument('--broad', action='store_true', help='S23: daily K via subscription + option stats + IV/HV')
    ap.add_argument('--xsec', action='store_true',
                    help='new names (S10): daily K via subscription get_cur_kline (no history-kline quota) + capital flow')
    ap.add_argument('--ext30-from', default=None, help='only pull extended-hours 30m bars from this date to --end')
    ap.add_argument('--daily-none-from', default=None, help='only pull unadjusted daily K (actual prices) from this date')
    ap.add_argument('--daily-only-from', default=None,
                    help='only pull daily K from this date to --end (the older price-only holdout)')
    a = ap.parse_args()
    out, symbols = Path(a.out), a.symbols.split(',')
    ctx = ft.OpenQuoteContext(host=a.host, port=a.port)
    c = Client(ctx)
    try:
        _, q = ctx.get_history_kl_quota(get_detail=True)
        charged = {x['code'] for x in q[2]}
        missing = [s for s in symbols if s not in charged]
        if missing and a.allow_new >= len(missing):
            print('charging %d new symbols in the history-kline quota: %s' % (len(missing), ','.join(missing)), flush=True)
            missing = []
        if a.broad:
            fetch_broad(ctx, c, out, symbols, a.end, q[:2])
            return
        if a.xsec:
            fetch_xsec(ctx, c, out, symbols, a.end, q[:2])
            return
        if missing:
            raise SystemExit('refuse: not charged in the 30-day kline quota: %s' % missing)
        quota_before = q[:2]
        if a.ext30_from:
            log = {'fetched_at': datetime.utcnow().isoformat() + 'Z', 'end': a.end, 'symbols': symbols, 'rows': {}}
            for s in symbols:
                rows = fetch_extended_30m(c, s, a.ext30_from, a.end)
                log['rows'][s] = write_csv(out / 'ext30' / (s.split('.')[1] + '.csv'), rows,
                                           ['time_key', 'open', 'high', 'low', 'close', 'volume', 'turnover'])
                print(s, log['rows'][s], 'calls', c.calls, flush=True)
            log.update(calls=c.calls, kline_quota_before=list(quota_before),
                       kline_quota_after=list(ctx.get_history_kl_quota()[1][:2]))
            (out / 'fetch_log.json').write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding='utf-8')
            print(json.dumps({k: log[k] for k in ('calls', 'kline_quota_before', 'kline_quota_after')}))
            return
        if a.daily_none_from:
            log = {'fetched_at': datetime.utcnow().isoformat() + 'Z', 'end': a.end, 'symbols': symbols, 'rows': {},
                   'note': 'K_DAY with AuType.NONE: actual traded prices, for price / ATR eligibility'}
            for s in symbols:
                rows = fetch_kline(c, s, a.end, a.daily_none_from, ft.AuType.NONE)
                log['rows'][s] = write_csv(out / 'daily' / (s.split('.')[1] + '.csv'), rows,
                                           ['date', 'open', 'high', 'low', 'close', 'volume', 'turnover'])
                print(s, log['rows'][s], flush=True)
            log.update(calls=c.calls, kline_quota_before=list(quota_before),
                       kline_quota_after=list(ctx.get_history_kl_quota()[1][:2]))
            (out / 'fetch_log.json').write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding='utf-8')
            print(json.dumps({k: log[k] for k in ('calls', 'kline_quota_before', 'kline_quota_after')}))
            return
        if a.daily_only_from:
            log = {'fetched_at': datetime.utcnow().isoformat() + 'Z', 'end': a.end, 'symbols': symbols, 'rows': {}}
            for s in symbols:
                rows = fetch_kline(c, s, a.end, a.daily_only_from)
                log['rows'][s] = write_csv(out / 'daily' / (s.split('.')[1] + '.csv'), rows,
                                           ['date', 'open', 'high', 'low', 'close', 'volume', 'turnover'])
                print(s, log['rows'][s], flush=True)
            log.update(calls=c.calls, kline_quota_before=list(quota_before),
                       kline_quota_after=list(ctx.get_history_kl_quota()[1][:2]))
            (out / 'fetch_log.json').write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding='utf-8')
            print(json.dumps({k: log[k] for k in ('calls', 'kline_quota_before', 'kline_quota_after')}))
            return
        log = {'fetched_at': datetime.utcnow().isoformat() + 'Z', 'end': a.end, 'symbols': symbols, 'rows': {}}
        for s in symbols:
            tag = s.split('.')[1]
            n = {}
            n['daily'] = write_csv(out / 'daily' / (tag + '.csv'), fetch_kline(c, s, a.end),
                                   ['date', 'open', 'high', 'low', 'close', 'volume', 'turnover'])
            st = fetch_paged(c, 'get_option_underlying_his_statistic', s, a.end)
            n['option_stats'] = write_csv(out / 'option_stats' / (tag + '.csv'), sorted(st, key=lambda r: r['time']),
                                          ['time', 'option_volume', 'call_volume', 'put_volume', 'put_call_volume_ratio',
                                           'option_open_interest', 'call_open_interest', 'put_open_interest',
                                           'underlying_price'])
            iv = fetch_paged(c, 'get_option_underlying_his_volatility', s, a.end)
            n['iv'] = write_csv(out / 'iv' / (tag + '.csv'), sorted(iv, key=lambda r: r['time']),
                                ['time', 'iv', 'hv', 'underlying_price'])
            sv = [r for r in fetch_short_volume(c, s) if r['timestamp_str'] <= a.end]
            n['short_volume'] = write_csv(out / 'short_volume' / (tag + '.csv'), sorted(sv, key=lambda r: r['timestamp_str']),
                                          ['timestamp_str', 'total_shares_short', 'nasdaq_shares_short', 'nyse_shares_short',
                                           'short_percent', 'volume', 'close_price', 'last_close_price'])
            cf = [r for r in fetch_capital_flow(c, s, a.end) if r['date'] <= a.end]
            n['capital_flow'] = write_csv(out / 'capital_flow' / (tag + '.csv'), cf,
                                          ['date', 'in_flow', 'super_in_flow', 'big_in_flow', 'mid_in_flow',
                                           'sml_in_flow', 'main_in_flow'])
            log['rows'][s] = n
            print(s, n, 'calls', c.calls, flush=True)
        mk = []
        for kind in ('VOLUME', 'OPEN_INTEREST'):
            key = None
            while True:
                _, df, key = c.call('get_option_market_statistic', ft.OptionMarket.US_SECURITY,
                                    getattr(ft.OptionStatisticDataType, kind), begin_time='2023-01-01',
                                    end_time=a.end, page_req_key=key)
                mk += [{'kind': kind, **r} for r in records(df)]
                if key is None:
                    break
        log['rows']['market_option'] = write_csv(out / 'market_option.csv', sorted(mk, key=lambda r: (r['kind'], r['time'])),
                                                 ['kind', 'time', 'call_value', 'put_value', 'total_value', 'ratio'])
        log['calls'] = c.calls
        log['kline_quota_before'] = list(quota_before)
        log['kline_quota_after'] = list(ctx.get_history_kl_quota()[1][:2])
        (out / 'fetch_log.json').write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding='utf-8')
        print(json.dumps({k: log[k] for k in ('calls', 'kline_quota_before', 'kline_quota_after')}))
    finally:
        ctx.close()


if __name__ == '__main__':
    main()
