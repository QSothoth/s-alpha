"""Pre-open scan for Q2 (PROVISIONAL; see README): single names whose previous session had an after-hours move of at
least 1 ATR, either sign -> SHORT bias for today's open -> close.  Read-only; research output, not an order.

Runs any time after 20:00 ET of the previous session.  Kline requests are refused for symbols not already charged.

    /opt/futu-opend/venv/bin/python studies/us_preopen_bias/code/plan.py            # for today (ET)
    /opt/futu-opend/venv/bin/python studies/us_preopen_bias/code/plan.py --date 2026-09-24
"""
import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preopen  # noqa: E402

SINGLES = ('US.AAPL', 'US.MSFT', 'US.NVDA', 'US.TSLA', 'US.META', 'US.AMZN', 'US.GOOGL', 'US.AMD', 'US.MU', 'US.INTC',
           'US.AVGO', 'US.SNDK', 'US.SKHY')
THRESHOLD = 1.0   # Q2_ah_attention_short_strong


def q2(daily, ext, T):
    """``daily``: {date: {high, low, close}} of completed sessions; ``ext``: preopen._ext30-style aggregate.

    Returns (previous session, ah_z, side) with the same formulas as the backtest (preopen.atr20 / preopen.ah_z)."""
    days = sorted(d for d in daily if d < T)
    if len(days) < 22:
        return None, None, 0
    h = {d: preopen._f(daily[d]['high']) for d in days}
    lo = {d: preopen._f(daily[d]['low']) for d in days}
    c = {d: preopen._f(daily[d]['close']) for d in days}
    i, P = len(days), days[-1]
    z = preopen.ah_z(ext.get(P), c[P], preopen.atr20(days, h, lo, c, i))
    return P, z, (-1 if z is not None and abs(z) >= THRESHOLD else 0)


def main():
    import logging
    logging.disable(logging.CRITICAL)
    import futu as ft
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', default=None, help='trade date T (ET); default today')
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=11111)
    a = ap.parse_args()
    today = datetime.now(timezone(timedelta(hours=-4))).date().isoformat()
    T = a.date or today
    start = (date.fromisoformat(T) - timedelta(days=50)).isoformat()
    ctx = ft.OpenQuoteContext(host=a.host, port=a.port)
    try:
        _, q = ctx.get_history_kl_quota(get_detail=True)
        charged = {x['code'] for x in q[2]}
        out = []
        for s in SINGLES:
            if s not in charged:
                out.append((s, None, None, 0, 'skipped: not charged'))
                continue
            r = ctx.request_history_kline(s, start=start, end=T, ktype=ft.KLType.K_DAY, autype=ft.AuType.QFQ, max_count=100)
            if r[0] != ft.RET_OK:
                out.append((s, None, None, 0, 'kline error'))
                continue
            daily = {str(x.time_key)[:10]: {'high': x.high, 'low': x.low, 'close': x.close} for x in r[1].itertuples()}
            days = sorted(d for d in daily if d < T)
            if not days:
                out.append((s, None, None, 0, 'no history'))
                continue
            r = ctx.request_history_kline(s, start=days[-1], end=days[-1], ktype=ft.KLType.K_30M, autype=ft.AuType.QFQ,
                                          max_count=100, extended_time=True)
            ext = {}
            if r[0] == ft.RET_OK:
                for x in r[1].itertuples():
                    hm = str(x.time_key)[11:16]
                    if hm > '16:00' and hm >= ext.get('hm', ''):
                        ext = {'hm': hm, 'ah_last': x.close}
            P, z, side = q2(daily, {days[-1]: ext} if ext else {}, T)
            if T < today:   # OpenD lists only current and future expiries
                note = '0DTE n/a for a past date'
            else:
                r = ctx.get_option_expiration_date(s)
                zero = r[0] == ft.RET_OK and T in set(r[1]['strike_time'].astype(str).str[:10])
                note = '0DTE today' if zero else 'no 0DTE today'
            out.append((s, P, z, side, note))
        print('Q2 pre-open scan for %s (PROVISIONAL: holdout 60.7%% on 117; 2026 so far 50%% on 30)' % T)
        for s, P, z, side, note in sorted(out, key=lambda t: -abs(t[2] or 0)):
            print('  %-8s prev %s  after-hours %s  %s  %s' % (
                s, P or '-', '   -  ' if z is None else '%+5.2f ATR' % z, 'SHORT' if side else '  -  ', note))
    finally:
        ctx.close()


if __name__ == '__main__':
    main()
