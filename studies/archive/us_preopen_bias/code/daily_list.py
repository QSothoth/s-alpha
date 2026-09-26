"""Daily in-play list (S22, validated): the small / mid caps most likely to make a big move today, with the gap side.

Direction is NOT validated (S21: 46%-53% on every rule); the list says which names should move, the gap side is context.
Run after 09:30 ET for the backtested definition (official open, full pre-market); before the open it uses the latest
pre-market price and the pre-market turnover so far, which is an estimate.  Read-only; no new history-kline quota.

    /opt/futu-opend/venv/bin/python studies/us_preopen_bias/code/daily_list.py
"""
import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preopen  # noqa: E402

HERE = Path(__file__).resolve().parents[1]
EXCLUDE = ('US.KOD', 'US.AVTX')
MIN_OPTION_VOLUME = 5000


def features_at(daily, ext, T, open_T):
    """Same formulas as preopen.build for day T: ATR20, gap and gap_z at the open, pre-market turnover ratio.
    ``daily``: {date: {high, low, close}} (dates >= T are ignored); ``ext``: preopen._ext30-style aggregate."""
    days = sorted(d for d in daily if d < T)
    if len(days) < 22:
        return None
    h = {d: preopen._f(daily[d]['high']) for d in days}
    lo = {d: preopen._f(daily[d]['low']) for d in days}
    c = {d: preopen._f(daily[d]['close']) for d in days}
    i, P = len(days), days[-1]
    atr = preopen.atr20(days, h, lo, c, i)
    gap = open_T / c[P] - 1 if open_T else None
    pm = ext.get(T)
    pm_turn = pm['pm_turn'] if pm else None
    hist = [ext[d]['pm_turn'] for d in days[i - 20:i] if d in ext and ext[d]['pm_turn'] > 0]
    ratio = pm_turn / mean(hist) if pm_turn and pm_turn > 0 and len(hist) >= 15 else None
    return {'atr20': atr, 'gap': gap, 'gap_z': gap / atr if gap is not None and atr else None, 'pm_ratio': ratio, 'prev_close': c[P]}


def gate_before(nominal, T):
    """Eligibility from actual prices before T: close >= 5, ATR14 >= 0.50, 20-day mean turnover >= 10M."""
    days = sorted(d for d in nominal if d < T)
    if len(days) < 21:
        return False
    n = nominal
    trs = [max(n[days[j]][1], n[days[j - 1]][0]) - min(n[days[j]][2], n[days[j - 1]][0]) for j in range(len(days) - 14, len(days))]
    return n[days[-1]][0] >= 5 and mean(trs) >= 0.5 and mean(n[d][3] for d in days[-20:]) >= 1e7


def lists(rows, n=3):
    """rows: [{'symbol', ...features}] of eligible names -> (M1 gap list, M2 pre-market list), each (ups, downs)."""
    def top(xs, key, reverse=True):
        return sorted(xs, key=lambda r: (r[key], r['symbol']), reverse=reverse)[:n]
    g = [r for r in rows if r['gap_z'] is not None]
    m1 = (top([r for r in g if r['gap_z'] >= 0.5], 'gap_z'), top([r for r in g if r['gap_z'] <= -0.5], 'gap_z', False))
    p = [r for r in rows if r['pm_ratio'] is not None and r['pm_ratio'] >= 2 and r['gap'] is not None]
    m2 = (top([r for r in p if r['gap'] > 0], 'pm_ratio'), top([r for r in p if r['gap'] < 0], 'pm_ratio'))
    return m1, m2


def main():
    import logging
    logging.disable(logging.CRITICAL)
    import futu as ft
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=3)
    ap.add_argument('--all', action='store_true', help='also print every eligible name sorted by |gap|')
    a = ap.parse_args()
    now = datetime.now(timezone(timedelta(hours=-4)))
    T = now.date().isoformat()
    uni = json.load(open(HERE / 'notes' / 'universe_smallmid.json', encoding='utf-8'))
    theme = {x['code']: t for t, xs in uni['themes'].items() for x in xs if x['code'] not in EXCLUDE}
    start = (date.fromisoformat(T) - timedelta(days=60)).isoformat()
    ctx = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
    rows, skipped = [], []
    try:
        charged = {x['code'] for x in ctx.get_history_kl_quota(get_detail=True)[1][2]}
        for s in sorted(theme):
            if s not in charged:
                skipped.append((s, 'not charged'))
                continue
            time.sleep(1.6)   # three kline requests per name: stay under OpenD's 60 per 30 s
            r = ctx.request_history_kline(s, start=start, end=T, ktype=ft.KLType.K_DAY, autype=ft.AuType.QFQ, max_count=100)
            q = ctx.request_history_kline(s, start=start, end=T, ktype=ft.KLType.K_DAY, autype=ft.AuType.NONE, max_count=100)
            e, key, frames = None, None, []
            while True:   # ~32 extended-hours bars a day: page, or today's bars fall off the first 1,000
                e = ctx.request_history_kline(s, start=start, end=T, ktype=ft.KLType.K_30M, autype=ft.AuType.QFQ,
                                              max_count=1000, extended_time=True, page_req_key=key)
                if e[0] != ft.RET_OK:
                    break
                frames.append(e[1])
                key = e[2]
                if key is None:
                    break
            o = ctx.get_option_underlying_his_statistic(s, begin_time=(date.fromisoformat(T) - timedelta(days=10)).isoformat(), end_time=T)
            if min(r[0], q[0], e[0], o[0]) != ft.RET_OK:
                skipped.append((s, 'request error'))
                continue
            daily = {str(x.time_key)[:10]: {'high': x.high, 'low': x.low, 'close': x.close, 'open': x.open} for x in r[1].itertuples()}
            nominal = {str(x.time_key)[:10]: (x.close, x.high, x.low, x.turnover) for x in q[1].itertuples()}
            ext, last_pm = {}, None
            for x in (row for fr in frames for row in fr.itertuples()):
                d, hm = str(x.time_key)[:10], str(x.time_key)[11:16]
                agg = ext.setdefault(d, {'pm_turn': 0.0, 'pm_0830': None, 'pm_0930': None, 'ah_last': None, 'ah_hm': ''})
                if hm <= '09:30':
                    agg['pm_turn'] += x.turnover or 0.0
                    if d == T and x.volume:
                        last_pm = x.close
            ovols = [(str(x.time)[:10], x.option_volume) for x in o[1].itertuples() if str(x.time)[:10] < T]
            ovol1 = sorted(ovols)[-1][1] if ovols else None
            opened = T in daily and now.strftime('%H:%M') >= '09:30'
            open_T = daily[T]['open'] if opened else last_pm
            f = features_at(daily, ext, T, open_T)
            if f is None or not gate_before(nominal, T) or not ovol1 or ovol1 < MIN_OPTION_VOLUME:
                skipped.append((s, 'not eligible'))
                continue
            rows.append(dict(f, symbol=s, theme=theme[s], ovol1=ovol1, basis='open' if opened else 'pre-market estimate'))
    finally:
        ctx.close()
    (m1_up, m1_dn), (m2_up, m2_dn) = lists(rows, a.n)
    print('In-play list for %s (%s ET; %d eligible, %d skipped). Validated: these names move 1.25-1.32x the pool; '
          'direction NOT validated.' % (T, now.strftime('%H:%M'), len(rows), len(skipped)))

    def show(title, xs):
        print('  ' + title)
        for r in xs:
            print('    %-8s %-9s gap %+6.2f%% (%+.2f ATR)  pre-mkt turnover %sx  options T-1 %d  [%s]' % (
                r['symbol'], r['theme'], 100 * r['gap'], r['gap_z'], '%.1f' % r['pm_ratio'] if r['pm_ratio'] else ' - ',
                r['ovol1'], r['basis']))
    show('M1 biggest gap up', m1_up)
    show('M1 biggest gap down', m1_dn)
    show('M2 pre-market volume, gapping up', m2_up)
    show('M2 pre-market volume, gapping down', m2_dn)
    if a.all:
        show('all eligible, by |gap|', sorted([r for r in rows if r['gap_z'] is not None], key=lambda r: -abs(r['gap_z'])))
        print('  skipped:', ', '.join('%s (%s)' % x for x in skipped) or '-')


if __name__ == '__main__':
    main()
