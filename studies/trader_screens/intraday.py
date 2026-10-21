"""The board during the session (scan run <market> --provisional): every registered system run on the stored
finished sessions plus today's bar taken from one quote snapshot shortly before the close, so the orders the
systems confirm at today's close (fill at the close, stop at today's low) can be placed in the closing minutes.

Nothing is stored in the data: the stored sessions must already end on the session before today (refresh first),
the snapshot is taken once and shared by every system, and today's provisional bar is appended to the cached panel
in memory (a corporate action shows as the exchange's previous close differing from our last close, exactly as in
the live update).  The run is refused outside the regular session (before the open, at or after the close, on a
non-trading day, on a half day after its early close), when the stored data does not end on the previous session,
when the snapshot is not of today (OpenD update time; Sina tick time), and when the previous closes in the snapshot
do not match ours (studies.trader_data.live.SNAP_MATCH).  A-shares: a buy whose provisional close is at the daily
limit cannot be bought at the close and is marked skipped (limit_up).  The result is written only to
data/trader-screens/out/<market>_<day>_provisional_<HHMM>.json (and its Markdown board) by scan.py.

`diff` compares that result with the official run of the same day after the close: entries and exits in both
(same), only provisional (gone at the close) and only official (missed in the closing minutes), with the price
and stop differences.
"""
from __future__ import annotations

import hashlib
import time
from contextlib import contextmanager
from datetime import datetime, time as clock, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np

ZONE = {'us': 'America/New_York', 'hk': 'Asia/Hong_Kong', 'cn': 'Asia/Shanghai'}
OPEN_AT = {'us': clock(9, 30), 'hk': clock(9, 30), 'cn': clock(9, 30)}       # continuous trading starts
CLOSE_AT = {'us': clock(16, 0), 'hk': clock(16, 0), 'cn': clock(15, 0)}      # regular close (auctions start before)
HALF_CLOSE = {'us': clock(13, 0), 'hk': clock(12, 0), 'cn': clock(11, 30)}   # trade_date_type MORNING
QUOTE_AGE = timedelta(minutes=15)    # Sina gives no date: the newest tick must be this recent (lunch break excepted)


class Refused(RuntimeError):
    """The provisional run cannot be made now (the message says why)."""


def market_now(market, now=None):
    return (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(ZONE[market]))


def opend_calendar(market, start, end):
    """{day: trade_date_type} ('WHOLE' | 'MORNING' | 'AFTERNOON') from OpenD."""
    import futu as ft
    q = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
    try:
        ret, data = q.request_trading_days(market=getattr(ft.TradeDateMarket, market.upper()), start=start, end=end)
        if ret != ft.RET_OK:
            raise RuntimeError(f'request_trading_days: {data}')
        return {d['time'][:10]: d.get('trade_date_type', 'WHOLE') for d in data}
    finally:
        q.close()


def session(market, last, now=None, calendar=opend_calendar):
    """Today's session if a provisional run is allowed now: dict(day, prev, close_at, hhmm); else Refused."""
    mnow = market_now(market, now)
    today = mnow.date().isoformat()
    if last >= today:
        raise Refused(f'{market}: stored data already ends {last} (today {today}): nothing provisional to add')
    cal = calendar((mnow.date() - timedelta(days=20)).isoformat(), today)
    if today not in cal:
        raise Refused(f'{market}: {today} is not a trading day')
    prev = max((d for d in cal if d < today), default=None)
    if prev != last:
        raise Refused(f'{market}: stored data ends {last}, the previous session is {prev}: '
                      f'run `scan refresh {market}` first (before the open, one snapshot)')
    close_at = HALF_CLOSE[market] if cal[today] == 'MORNING' else CLOSE_AT[market]
    if mnow.time() < OPEN_AT[market]:
        raise Refused(f'{market}: the session has not opened ({mnow:%H:%M} < {OPEN_AT[market]:%H:%M})')
    if mnow.time() >= close_at:
        raise Refused(f'{market}: the session has closed ({mnow:%H:%M} >= {close_at:%H:%M}); run the board normally')
    return dict(day=today, prev=prev, close_at=close_at.strftime('%H:%M'), hhmm=mnow.strftime('%H%M'),
                now=mnow.isoformat(timespec='seconds'), half=cal[today] == 'MORNING')


def check_time(market, snap, day, now=None):
    """The snapshot shows today: OpenD update times on `day` for >= SNAP_MATCH of the trading names; Sina (time only)
    the newest tick within QUOTE_AGE of now, or the lunch break."""
    from studies.trader_data.live import SNAP_MATCH
    times = [s.get('time') or '' for s in snap.values() if s['trading']]
    if not times:
        raise Refused(f'{market}: the snapshot has no trading names')
    dated = [t for t in times if len(t) >= 10 and t[4] == '-']
    if dated:
        on_day = sum(t[:10] == day for t in dated)
        if on_day / len(dated) < SNAP_MATCH:
            raise Refused(f'{market}: snapshot is not of {day}: {on_day}/{len(dated)} quotes dated that day')
        return dict(quotes_on_day=[on_day, len(dated)], newest=max(dated))
    mnow = market_now(market, now)
    newest = max(times)
    tick = datetime.combine(mnow.date(), clock.fromisoformat(newest), mnow.tzinfo)
    lunch = market in ('hk', 'cn') and HALF_CLOSE[market] <= mnow.time() < clock(13, 0)
    if not lunch and mnow - tick > QUOTE_AGE:
        raise Refused(f'{market}: newest quote {newest} is older than {QUOTE_AGE} at {mnow:%H:%M:%S}')
    return dict(newest=newest)


def with_today(p, day, rows, acts):
    """The panel p with day's bar of each row appended (raw (code, day, o, h, l, c, v, t)); an action (code, day,
    a, b) rescales that code's earlier prices as panel.assemble does, so the result equals a full rebuild."""
    codes = [str(c) for c in p['codes']]
    col = {c: j for j, c in enumerate(codes)}
    fields = ('open', 'high', 'low', 'close', 'volume', 'turnover', 'raw_close')
    row = {k: np.full(len(codes), np.nan, np.float32) for k in fields}
    out = {k: v for k, v in p.items()}
    for k in ('open', 'high', 'low', 'close', 'volume'):
        out[k] = p[k].copy()
    have = set()
    for c, d, o, h, l, cl, v, t in rows:
        if d != day or c not in col:
            continue
        j = col[c]
        have.add(c)
        for k, x in zip(fields, (o, h, l, cl, v, t, cl)):
            row[k][j] = x
    for c, d, a, b in acts:
        if d != day or c not in have:
            continue
        j = col[c]
        ok = np.flatnonzero(np.isfinite(p['raw_close'][:, j]))
        if not len(ok):
            continue
        prev = float(p['raw_close'][ok[-1], j])
        step = (a * prev + b) / prev
        for k in ('open', 'high', 'low', 'close'):
            out[k][:, j] = (out[k][:, j].astype(float) * step).astype(np.float32)
        out['volume'][:, j] = (out['volume'][:, j].astype(float) / step).astype(np.float32)
    row['high'] = np.fmax(row['high'], np.fmax(row['open'], row['close']))
    row['low'] = np.fmin(row['low'], np.fmin(row['open'], row['close']))
    for k in fields:
        out[k] = np.concatenate([out[k], row[k][None, :]])
    out['days'] = np.append(p['days'], day)
    h = hashlib.sha256((str(p.get('digest')) + repr(sorted(rows)) + repr(sorted(acts))).encode())
    out['digest'], out['dataset'] = h.hexdigest(), f"provisional:{p.get('dataset')}"
    return out


@contextmanager
def shared(p, market):
    """Every study's panels.load(market, ...) returns a copy of p (cut at upto) while inside: one snapshot, every
    system."""
    from studies.trader_replication import panels
    orig = panels.load

    def load(m, upto=None, mode=None):
        if m != market:
            return orig(m, upto, mode)
        q = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in p.items()}
        if upto is not None:
            k = int(np.searchsorted(q['days'], upto, side='right'))
            q = {key: (v[:k] if isinstance(v, np.ndarray) and v.ndim and key != 'codes' else v)
                 for key, v in q.items()}
        return q
    panels.load = load
    try:
        yield
    finally:
        panels.load = orig


LIMIT_WIDE = ('300', '301', '688', '689')          # ChiNext / STAR: 20%


def limit_pct(code, name=''):
    """The A-share daily limit (the rule of trader_replication common.limit_pct; ST names 5% by their name)."""
    num = str(code).split('.')[-1]
    if 'ST' in (name or '').upper():
        return .05
    return .3 if num[:1] in ('8', '4') or num.startswith('920') else .2 if num[:3] in LIMIT_WIDE else .1


def at_limit_up(code, name, price, prev_close):
    """price at or above the A-share limit-up price (prev_close x (1 + limit), rounded to the cent)."""
    lim = np.floor(prev_close * (1 + limit_pct(code, name)) * 100 + .5) / 100
    return bool(price >= lim - 1e-6)


def run(market, now=None, provider=None, calendar=None, board=None, only=None, log=print):
    """The provisional board of one market (see the module docstring); returns the scan.run result with
    'provisional' (snapshot, checks, stage seconds)."""
    from studies import trader_data as TD
    from studies.trader_data.live import LiveDataset
    from . import scan
    stages, t0 = {}, time.perf_counter()

    def stage(name):
        nonlocal t0
        t = time.perf_counter()
        stages[name] = round(t - t0, 2)
        log(f'  [{name}] {t - t0:.1f} 秒')
        t0 = t
    ds = TD.dataset(market, 'live')
    base = ds.panel()
    last = str(base['days'][-1])
    stage('stored panel')
    sess = session(market, last, now, calendar or (lambda s, e: opend_calendar(market, s, e)))
    stage('calendar')
    codes = [str(c) for c in base['codes']]
    raw = base['raw_close']
    last_raw = {}
    for j, c in enumerate(codes):
        ok = np.flatnonzero(np.isfinite(raw[:, j]))
        if len(ok):
            last_raw[c] = (str(base['days'][ok[-1]]), float(raw[ok[-1], j]))
    prov = provider or ds.provider()
    try:
        snap = prov.snapshot(codes)
    finally:
        if provider is None:
            prov.close()
    stage('snapshot')
    timing = check_time(market, snap, sess['day'], now)

    class Once:                                     # from_snapshot reads the snapshot already taken
        @staticmethod
        def snapshot(_):
            return snap
    try:
        rows, acts, chk = LiveDataset.from_snapshot(Once, codes, sess['day'], last_raw)
    except RuntimeError as e:
        raise Refused(f'{market}: {e}') from e
    p = with_today(base, sess['day'], rows, acts)
    del base
    stage('provisional panel')
    seconds = {}
    r = (board or scan.run)(market, 'live', 1, only, panel=p, seconds=seconds)
    stage('systems')
    if r['last_day'] != sess['day']:
        raise RuntimeError(f"{market}: board ends {r['last_day']}, expected {sess['day']}")
    names = ds.names()
    if market == 'cn':
        for t in r['traders']:
            for b in t['buys']:
                s = snap.get(b['code'])
                if b.get('side', 1) > 0 and s and at_limit_up(b['code'], names.get(b['code'], ''), s['close'],
                                                                s['prev_close']):
                    b['limit_up'] = True
    r['provisional'] = dict(sess, rows=len(rows), actions=len(acts), stages=stages, system_seconds=seconds,
                            **chk, **timing)
    return r


# ----- after the close: provisional vs official -----
def keyed(r, key):
    out = {}
    for t in r['traders']:
        for x in t[key]:
            out[(t['id'], x['code'], x.get('side', 1), x.get('setup') == '加码')] = dict(x, trader=t['name'])
    return out


def diff(prov, official):
    """{'buys' | 'sells': {'same': [...], 'gone': [...], 'missed': [...]}}: entries / exits of the provisional run
    and the official run of the same day; 'same' rows carry both prices and stops.  Buys skipped at the A-share
    limit count as not bought."""
    if prov['last_day'] != official['last_day'] or prov['market'] != official['market']:
        raise ValueError('different market or day')
    out = {}
    for key in ('buys', 'sells'):
        a, b = keyed(prov, key), keyed(official, key)
        if key == 'buys':
            a = {k: v for k, v in a.items() if not v.get('limit_up')}
            b = {k: v for k, v in b.items() if not v.get('limit_up')}
        same, gone, missed = [], [], []
        for k in sorted(set(a) | set(b)):
            x, y = a.get(k), b.get(k)
            row = dict(trader=(x or y)['trader'], code=k[1], side=k[2], add=k[3])
            if x and y:
                row.update(prov=x['price'], official=y['price'], gap=y['price'] / x['price'] - 1)
                if key == 'buys' and x.get('stop') and y.get('stop'):
                    row.update(prov_stop=x['stop'], official_stop=y['stop'],
                               width_prov=abs(x['price'] - x['stop']) / x['price'],
                               width_official=abs(y['price'] - y['stop']) / y['price'])
                row.update(what=(x.get('setup') or x.get('why'), y.get('setup') or y.get('why')))
                same.append(row)
            elif x:
                gone.append(dict(row, prov=x['price'], what=x.get('setup') or x.get('why')))
            else:
                missed.append(dict(row, official=y['price'], what=y.get('setup') or y.get('why')))
        out[key] = dict(same=same, gone=gone, missed=missed)
    return out


def diff_text(d, prov, official):
    from .board import kind, px
    p = prov['provisional']
    lines = [f"# 盘中临时 vs 收盘正式 · {prov['market']} {prov['last_day']}", '',
             f"临时快照 {p['now'][11:16]}（{p['hhmm']}），正式结果数据 {official.get('digest', '')[:12]}。", '']
    for key, word in (('buys', '买入 / 卖空'), ('sells', '卖出 / 回补')):
        g = d[key]
        lines.append(f"## {word}：一致 {len(g['same'])}，收盘后消失 {len(g['gone'])}，尾盘漏掉 {len(g['missed'])}")
        lines.append('')
        for title, rows in (('一致', g['same']), ('收盘后消失', g['gone']), ('尾盘漏掉', g['missed'])):
            for x in rows:
                what = x['what'] if isinstance(x['what'], str) else x['what'][1]
                what = kind(what) if key == 'buys' and what else what
                side = '空' if x['side'] < 0 else '多'
                price = (f"临时 {px(x.get('prov'))} → 正式 {px(x.get('official'))}（{x['gap']:+.2%}）" if 'gap' in x
                         else f"临时 {px(x['prov'])}" if 'prov' in x else f"正式 {px(x['official'])}")
                stop = (f"，止损宽度 {x['width_prov']:.1%} → {x['width_official']:.1%}" if 'width_prov' in x else '')
                lines.append(f"- {title}｜{x['trader']}｜{x['code']} {side}{'·加码' if x['add'] else ''}｜{what}｜{price}{stop}")
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'
