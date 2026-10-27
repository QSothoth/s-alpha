#!/usr/bin/env python3
"""Intraday tape watcher: VWAP + EMA9/21 + RSI14 bias, SMC structure triggers.

Bias (unchanged from the original): price vs session VWAP, EMA9/21, RSI14.
Triggers:
    BOS    break of structure through a swing confirmed on BOTH sides
    FVG    3-bar fair value gap wider than FVG_ATR x ATR14
    SWEEP  wick takes out a confirmed swing then closes back inside (stop hunt)

Every trigger that passes the bias is marked. Sessions averaging fewer than
GATE_TPB ticks per bar are shown dim and tagged `~`. Each mark also gets a
daily-context tag, D+ or D-, and a strength grade 1-5 on one scale for every
market (W27 parts, W31 cuts), which replaced the old bold emphasis (D2). These
labels came from studies W2/W6; W12 corrects dated tick sizes and the volume
baseline, so earlier performance figures describe the old implementation.
Hong Kong marks also carry one S00-S100 joint stock-and-HSI directional
strength percentile from W19 (pipe output only); it is not a future-return
probability. The board shows the swing reference level, which is not a stop,
and W24's expected rest-of-day range `left` for Hong Kong names.
Volume expansion and the premium/discount half of the day's range only split
`plain` from `vol` marks for de-duplication.

Read-only OpenD quotes, any number of codes. Every poll re-reads the day's
closed 1m bars and derives the whole mark list from them, so nothing accumulates
in memory and a mid-session restart reproduces the same state.

    ./smc_watch.py                      # default code
    ./smc_watch.py HK.02513 HK.09988
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from math import exp, isfinite, log
from zoneinfo import ZoneInfo
import unicodedata
from pathlib import Path

logging.getLogger('futu').setLevel(logging.ERROR)
logging.getLogger().setLevel(logging.ERROR)

from futu import AuType, KLType, OpenQuoteContext, RET_OK, SubType  # noqa: E402
from signal_grade import grade as signal_grade  # noqa: E402
from signal_strength import score as signal_strength_score  # noqa: E402

# futu prints connection notices to stdout through its own logger, which would
# break the one-JSON-object-per-line output that `| jq` relies on.
logging.getLogger('FTConsoleLog').setLevel(logging.ERROR)

DEFAULT_CODES = ['HK.02513']
HOST = '127.0.0.1'
PORT = 11111
POLL_SEC = 30
KLINE_BACK = 400        # > one HK session of 1m bars
TENCENT_M1 = 'https://ifzq.gtimg.cn/appstock/app/kline/mkline?param=%s,m1,,320'
TENCENT_DAY = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=%s,day,,,30,qfq'
DAILY_BACK = 30         # daily bars requested; ATR20 needs 21 closed sessions, D+/D- needs 6
# Market of each code: Hong Kong and US quotes come from OpenD, A shares from
# Tencent. The index is the market leg of the strength grade (W27).
INDEX = {'HK': 'HK.800000', 'US': 'US.SPY', 'A': 'SH.000300'}
LAST_BARS = {'HK': ' 16:00', 'A': ' 16:00', 'US': ' 16:01'}   # exclusive cutoffs
SESSIONS = {'HK': ((570, 720), (780, 960)), 'A': ((570, 690), (780, 900)), 'US': ((570, 960),)}
SWING_LEFT = 3          # bars confirmed on BOTH sides of a swing
VOL_MULT = 1.5          # trigger bar volume vs the trailing 20-bar mean
VOL_LOOKBACK = 20
FVG_ATR = 0.25          # gap must be this fraction of ATR14 to count
ATR_LEN = 14
PREMIUM = 0.5           # longs below this much of the day's range, shorts above
WARMUP_BARS = 25
DEDUP_BARS = 15         # per direction
GATE_TPB = 2.0          # below this many ticks per bar a "break" is a bid/ask flip
FINE_TPB = 5.0          # `fine` flag in the log; no longer decides emphasis (W9)
HK_TICK_BANDS = ((0.25, 0.001), (0.5, 0.005), (10, 0.01), (20, 0.02), (100, 0.05),
                 (200, 0.1), (500, 0.2), (1000, 0.5), (2000, 1.0), (5000, 2.0))
STALE_POLLS = 4
# W24 rest-of-day range (studies/watch_signal/reports/W24_RESULTS_CN.md): per
# checkpoint, log(range to close) = a + b*log(realized 1m vol so far / minutes)
# + c*log(yesterday's range), fitted on 2025-12..2026-08, validated once on
# 2024-12..2025-05 (out-of-sample R2 0.55, 80% band covered 77.5%). Minutes are
# the study's fixed 30-minute steps; lo/hi are the 10%/90% residual quantiles.
RANGE_MODEL = (
    ('10:00', 30, 1.0265, 0.6363, 0.2306, -0.4816, 0.4990),
    ('10:30', 60, 1.5006, 0.7525, 0.1455, -0.4669, 0.4913),
    ('11:00', 90, 1.6593, 0.7946, 0.1106, -0.4664, 0.4851),
    ('11:30', 120, 1.6151, 0.7943, 0.1029, -0.4639, 0.4859),
    ('13:30', 150, 1.4673, 0.8298, 0.0737, -0.4609, 0.4995),
    ('14:00', 180, 1.2360, 0.8087, 0.0821, -0.4592, 0.4910),
    ('14:30', 210, 0.9164, 0.7855, 0.0712, -0.4636, 0.4755),
    ('15:00', 240, 0.3957, 0.7525, 0.0384, -0.4683, 0.4787),
)
UNTIL = '16:10'         # board header; main() sets it from the markets watched
HKT = timezone(timedelta(hours=8))
ET = ZoneInfo('America/New_York')
LOG_DIR = Path(__file__).resolve().parent / 'logs'

DIM, BOLD, OFF = '\033[2m', '\033[1m', '\033[0m'
GREEN, YELLOW, RED = '\033[32m', '\033[33m', '\033[31m'


def now_hkt():
    return datetime.now(HKT)


def close_hkt():
    return now_hkt().replace(hour=16, minute=10, second=0, microsecond=0)


def market(code):
    """'A' for Tencent A-share codes, 'US' for US.*, else 'HK'."""
    if tencent_symbol(code):
        return 'A'
    return 'US' if code.upper().startswith('US.') else 'HK'


def now_in(mkt):
    """Wall clock in the market's own time zone (bars are labelled in it)."""
    now = now_hkt()
    return now.astimezone(ET) if mkt == 'US' else now


def close_us():
    return now_in('US').replace(hour=16, minute=10, second=0, microsecond=0)


def log_path():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / ('%s.log' % now_hkt().strftime('%Y-%m-%d'))


def emit(kind, payload):
    line = json.dumps({'kind': kind, 'payload': payload}, ensure_ascii=True, default=str)
    with open(log_path(), 'a', encoding='utf-8') as fh:
        fh.write(line + '\n')
    if not sys.stdout.isatty():
        print(line, flush=True)
    elif kind == 'FAILED':  # the board never shows it, so say why we exit
        print('FAILED: %s' % payload.get('error'), file=sys.stderr, flush=True)


def frame_name(frame):
    """OpenD ships the display name on every kline row; use it, do not re-query."""
    if frame is None or len(frame) == 0 or 'name' not in frame.columns:
        return ''
    return str(frame['name'][0])


def frame_bars(frame):
    if frame is None or len(frame) == 0:
        return []
    times = frame['time_key'] if 'time_key' in frame.columns else frame['time']
    out = []
    for t, o, h, l, c, v in zip(
        times, frame['open'], frame['high'], frame['low'], frame['close'], frame['volume'],
    ):
        row = (str(t), float(o), float(h), float(l), float(c), float(v or 0))
        if all(x == x for x in row[1:]):  # NaN poisons VWAP into silence
            out.append(row)
    return out


def closed_session(bars, mkt='HK'):
    """Today's finished 1-minute bars. The bar still forming is dropped."""
    now = now_in(mkt)
    day = now.strftime('%Y-%m-%d')
    # End-labelled live bars can be ahead of the wall-clock minute. Exclude
    # both those and the current minute until it has fully settled.
    cutoff = min(now.strftime('%Y-%m-%d %H:%M'), day + LAST_BARS[mkt])
    return [b for b in bars if day <= b[0] < cutoff]


def bar_stale(code, stamp, at):
    """None outside continuous trading or its opening grace, else freshness."""
    mkt = market(code)
    tz = ET if mkt == 'US' else HKT
    at = at.astimezone(tz)
    if at.weekday() >= 5:
        return None
    minute = at.hour * 60 + at.minute
    open_ = next((lo for lo, hi in SESSIONS[mkt] if lo <= minute < hi), None)
    if open_ is None:
        return None
    start = at.replace(hour=open_ // 60, minute=open_ % 60, second=0, microsecond=0)
    grace = POLL_SEC * STALE_POLLS
    if (at - start).total_seconds() <= grace:
        return None
    if not stamp:
        return True
    try:
        last = datetime.fromisoformat(stamp).replace(tzinfo=tz)
    except ValueError:
        return True
    return (at - last).total_seconds() > grace


def session_bars(ctx, code):
    """(today's closed 1m bars, display name, previous close), or empty values.

    The minute still being traded is dropped: OpenD returns it half-built, and a
    mark fired on it would be emitted and then quietly stop being true once the
    bar completes.
    """
    try:
        ret, frame = ctx.get_cur_kline(code, KLINE_BACK, KLType.K_1M, AuType.NONE)
    except Exception:
        return None, '', None
    if ret != RET_OK:
        return None, '', None
    bars = closed_session(frame_bars(frame), market(code))
    previous = None
    if bars and 'last_close' in frame.columns:
        # The day's first row (HK 09:30 auction, US 09:31) carries yesterday's
        # close; later rows carry the previous minute's.
        times = frame['time_key'] if 'time_key' in frame.columns else frame['time']
        for stamp, value in zip(times, frame['last_close']):
            if str(stamp) == bars[0][0]:
                value = float(value)
                previous = value if isfinite(value) and value > 0 else None
                break
    return bars, frame_name(frame), previous


def index_session(ctx, mkt):
    """Closed index minute closes plus yesterday's close, or None.

    Yesterday's close is the `last_close` of today's first bar; the window
    also holds yesterday's minutes, whose `last_close` is only the minute before.
    """
    if mkt == 'A':
        bars, _name, previous = tencent_session(INDEX['A'])
        if not bars or not previous:
            return None
        return {bar[0][11:16]: bar[4] for bar in bars}, previous
    if ctx is None:
        return None
    bars, _name, previous = session_bars(ctx, INDEX[mkt])
    if not bars or not previous:
        return None
    return {bar[0][11:16]: bar[4] for bar in bars}, previous


def hsi_session(ctx):
    return index_session(ctx, 'HK')


def daily_context(rows, day):
    """Pre-open daily context from sessions strictly before `day`.

    rows: [(YYYY-MM-DD, open, high, low, close, volume)], any order. Returns
    None when fewer than six closed sessions are available or prices are invalid.
    """
    rows = sorted(r for r in rows if r[0] < day)
    prev = rows[-6:]
    if len(prev) < 6 or any(not isfinite(x) or x <= 0 for r in prev for x in r[1:5]):
        return None
    return {'ret5d': prev[-1][4] / prev[-6][4] - 1.0, 'pdh': prev[-1][2],
            'pdl': prev[-1][3], 'pdo': prev[-1][1], 'day': prev[-1][0],
            'atr20': atr20(rows)}


def atr20(rows):
    """Mean true range / previous close over the last 20 sessions, or None."""
    rows = rows[-21:]
    if len(rows) < 21 or any(not isfinite(x) or x <= 0 for r in rows for x in r[2:5]):
        return None
    return sum((max(h, c0) - min(lo, c0)) / c0
               for (_, _, _, _, c0, _), (_, _, h, lo, _, _) in zip(rows, rows[1:])) / 20


def range_left(bars, dctx, tick=None):
    """W24 expected high-low range from the latest checkpoint to the close.

    Half of it, in percent, with the ~80% band: {'cp', 'half', 'lo', 'hi'}.
    Validated for Hong Kong names with >= 2 ticks per bar only; None before
    10:00, without yesterday's range, or on tick-bound tape.
    """
    if not bars or not dctx or not dctx.get('pdo'):
        return None
    prev_range = (dctx['pdh'] - dctx['pdl']) / dctx['pdo']
    index = {b[0][11:16]: i for i, b in enumerate(bars)}
    done = [m for m in RANGE_MODEL if m[0] in index]
    if not done or prev_range <= 0:
        return None
    cp, minutes, a, b, c, lo, hi = done[-1]
    i = index[cp]
    if ticks_per_bar(bars[:i + 1], tick or hk_tick)[-1] < GATE_TPB:
        return None
    rv = sum(abs(log(bars[k][4] / bars[k - 1][4])) for k in range(1, i + 1))
    if rv <= 0:
        return None
    mid = a + b * log(rv / minutes) + c * log(prev_range)
    return {'cp': cp, 'half': exp(mid) * 50.0, 'lo': exp(mid + lo) * 50.0, 'hi': exp(mid + hi) * 50.0}


def daily_support(m, dctx):
    """Study W6 (K5): the mark goes against the last five sessions AND has not
    broken the previous session's high (BUY) / low (SELL). None without data.

    Granular marks held to the close, D+ minus D-: +11.5bp (t=2.0) over the
    two segments not used for selection (2025-06..11 and 2026-08-17..09-23),
    with BUY and SELL agreeing in every segment. Below round-trip cost.
    """
    if not dctx:
        return None
    if m['side'] == 'BUY':
        return dctx['ret5d'] <= 0 and m['close'] <= dctx['pdh']
    return dctx['ret5d'] >= 0 and m['close'] >= dctx['pdl']


def with_daily(ms, dctx):
    return [dict(m, daily=daily_support(m, dctx)) for m in ms]


def with_grade(ms, dctx, index_atr):
    """W27 strength grade 1-5 on one scale for every market (not a win rate).

    Needs the volume ratio, the stock/index moves from with_strength, and the
    stock's and index's ATR20 from daily bars; any gap leaves `grade` None.
    """
    stock_atr = dctx.get('atr20') if dctx else None
    return [dict(m, grade=signal_grade(
        m['side'], m.get('vol_ratio'),
        None if m.get('hsi_pct') is None else m['hsi_pct'] / 100.0, index_atr,
        None if m.get('stock_pct') is None else m['stock_pct'] / 100.0, stock_atr))
            for m in ms]


def with_strength(ms, hsi, stock_previous, score=True):
    """Raw stock and index moves vs yesterday's close (percent; `hsi_pct` is
    the market's index: HSI, CSI 300 or SPY) plus the W19 score, which is
    calibrated for Hong Kong only (`score=False` elsewhere)."""
    closes, previous = hsi if hsi else ({}, None)
    out = []
    for m in ms:
        hsi_close = closes.get(m['t']) if previous is not None else None
        out.append(dict(
            m,
            strength=(signal_strength_score(m['side'], m['t'], m['close'], stock_previous,
                                            hsi_close, previous)
                      if score and stock_previous is not None and hsi_close is not None else None),
            stock_pct=(round((m['close'] / stock_previous - 1.0) * 100.0, 4)
                       if stock_previous else None),
            hsi_pct=round((hsi_close / previous - 1.0) * 100.0, 4) if hsi_close else None))
    return out


def hk_daily(ctx, code):
    """Daily bars from OpenD (subscription quota only, never history quota)."""
    try:
        ret, frame = ctx.get_cur_kline(code, DAILY_BACK, KLType.K_DAY, AuType.QFQ)
    except Exception:
        return None
    if ret != RET_OK:
        return None
    return [(b[0][:10],) + b[1:] for b in frame_bars(frame)]


def parse_tencent_day(payload, symbol):
    """Tencent daily row is date, open, close, high, low, volume."""
    node = (payload.get('data') or {}).get(symbol) or {}
    out = []
    for row in node.get('qfqday') or node.get('day') or []:
        try:
            out.append((str(row[0]), float(row[1]), float(row[3]), float(row[4]), float(row[2]), float(row[5] or 0)))
        except (TypeError, ValueError, IndexError):
            continue
    return out


def index_daily(ctx, mkt):
    """Daily bars of the market's index (for its ATR20), or None."""
    if mkt == 'A':
        return tencent_daily(INDEX['A'])
    return hk_daily(ctx, INDEX[mkt]) if ctx is not None else None


def tencent_daily(code):
    symbol = tencent_symbol(code)
    if not symbol:
        return None
    try:
        req = urllib.request.Request(TENCENT_DAY % symbol, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=12) as resp:
            return parse_tencent_day(json.loads(resp.read().decode('utf-8')), symbol) or None
    except Exception:
        return None


def tencent_symbol(code):
    """Futu-style or bare A-share code -> sz300795. HK codes return None."""
    raw = code.strip().upper().replace(' ', '')
    if raw.startswith('HK.') or not raw:
        return None
    prefix = {'SH': 'sh', 'SZ': 'sz', 'BJ': 'bj'}
    if '.' in raw:
        left, right = raw.split('.', 1)
        if left in prefix and right.isdigit() and len(right) == 6:
            return prefix[left] + right
        if right in prefix and left.isdigit() and len(left) == 6:
            return prefix[right] + left
        return None
    low = code.strip().lower()
    if len(low) == 8 and low[:2] in ('sh', 'sz', 'bj') and low[2:].isdigit():
        return low
    if len(raw) == 6 and raw.isdigit():
        head = {'6': 'sh', '0': 'sz', '3': 'sz', '4': 'bj', '8': 'bj'}.get(raw[0])
        return head + raw if head else None
    return None


def canonical_code(code):
    code = code.encode('ascii', 'ignore').decode()  # pasted args can carry stray bytes
    symbol = tencent_symbol(code)
    if not symbol:
        return code.strip()
    return '%s.%s' % (symbol[:2].upper(), symbol[2:])


def parse_tencent_m1(payload, symbol):
    """Tencent m1 row is time, open, close, high, low, volume."""
    node = (payload.get('data') or {}).get(symbol) or {}
    qt = (node.get('qt') or {}).get(symbol) or []
    name = str(qt[1]) if len(qt) > 1 else ''
    bars = []
    for row in node.get('m1') or []:
        if not row or len(row) < 6:
            continue
        stamp = str(row[0])
        if len(stamp) != 12 or not stamp.isdigit():
            continue
        try:
            o, c, h, l, v = (float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5] or 0))
        except (TypeError, ValueError):
            continue
        if not all(x == x for x in (o, h, l, c, v)):
            continue
        bars.append(('%s-%s-%s %s:%s:00' % (stamp[0:4], stamp[4:6], stamp[6:8], stamp[8:10], stamp[10:12]),
                     o, h, l, c, v))
    return bars, name


def tencent_previous(payload, symbol):
    """Yesterday's close from the quote array (field 4), or None."""
    qt = (((payload.get('data') or {}).get(symbol) or {}).get('qt') or {}).get(symbol) or []
    try:
        value = float(qt[4])
    except (TypeError, ValueError, IndexError):
        return None
    return value if isfinite(value) and value > 0 else None


def fetch_tencent_m1(symbol):
    req = urllib.request.Request(TENCENT_M1 % symbol, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=12) as resp:
        payload = json.loads(resp.read().decode('utf-8'))
    if payload.get('code') not in (0, None):
        return [], '', None
    return parse_tencent_m1(payload, symbol) + (tencent_previous(payload, symbol),)


def tencent_session(code):
    """(today's closed 1m bars, name, yesterday's close) from Tencent."""
    symbol = tencent_symbol(code)
    if not symbol:
        return None, '', None
    try:
        bars, name, previous = fetch_tencent_m1(symbol)
    except Exception:
        return None, '', None
    bars = closed_session(bars, 'A')
    return (bars, name, previous) if bars else (None, name, previous)


def ema_last(closes, period):
    if len(closes) < period:
        return None
    k = 2.0 / (period + 1)
    prev = sum(closes[:period]) / period
    for v in closes[period:]:
        prev = v * k + prev * (1.0 - k)
    return prev


def rsi_last(closes, period=14):
    if len(closes) <= period:
        return None
    avg_g = avg_l = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        avg_g += max(d, 0.0)
        avg_l += max(-d, 0.0)
    avg_g /= period
    avg_l /= period
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_g = (avg_g * (period - 1) + max(d, 0.0)) / period
        avg_l = (avg_l * (period - 1) + max(-d, 0.0)) / period
    if avg_l == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_g / avg_l)


def vwap_last(bars):
    pv = vol = 0.0
    for _t, _o, h, l, c, v in bars:
        pv += ((h + l + c) / 3.0) * v
        vol += v
    return pv / vol if vol > 0 else None


def last_swing(highs, lows, left=SWING_LEFT):
    """Last swing with `left` bars confirmed on BOTH sides.

    An unconfirmed swing sits at or above the latest high, which makes
    `close > swing_high` unreachable -- that bug kept BOS silent all day.
    """
    sh = sl = None
    for j in range(left, len(highs) - left):
        if highs[j] == max(highs[j - left:j + left + 1]):
            sh = highs[j]
        if lows[j] == min(lows[j - left:j + left + 1]):
            sl = lows[j]
    return sh, sl


def read(bars):
    """Indicators plus the volume / structure context for the latest bar."""
    closes = [b[4] for b in bars]
    highs = [b[2] for b in bars]
    lows = [b[3] for b in bars]
    d = {'t': bars[-1][0], 'close': closes[-1], 'n': len(bars),
         'vwap': vwap_last(bars), 'ema9': ema_last(closes, 9),
         'ema21': ema_last(closes, 21), 'rsi': rsi_last(closes)}
    win = bars[-VOL_LOOKBACK - 1:-1]
    avg_v = sum(b[5] for b in win) / len(win) if win else 0.0
    d['vol_ratio'] = bars[-1][5] / avg_v if avg_v > 0 else None
    atr_win = bars[-ATR_LEN:]
    d['atr'] = sum(b[2] - b[3] for b in atr_win) / len(atr_win)
    hi, lo = max(highs), min(lows)
    d['day_hi'], d['day_lo'] = hi, lo
    d['pos'] = (closes[-1] - lo) / (hi - lo) if hi > lo else 0.5
    d['swing_high'], d['swing_low'] = last_swing(highs[-24:], lows[-24:])
    return d


def structure(bars, d):
    """(bull triggers, bear triggers) on the latest bar. Volume is NOT judged
    here; `marks` uses it only to split `plain` marks from `vol` ones."""
    if d['atr'] <= 0:
        return [], []
    highs = [b[2] for b in bars]
    lows = [b[3] for b in bars]
    close = d['close']
    bull, bear = [], []
    sh, sl = d['swing_high'], d['swing_low']
    if sh is not None and close > sh:
        bull.append('BOS')
    if sl is not None and close < sl:
        bear.append('BOS')
    if len(bars) >= 3:
        gap_up = lows[-1] - highs[-3]
        gap_dn = lows[-3] - highs[-1]
        if gap_up > FVG_ATR * d['atr']:
            bull.append('FVG')
        elif gap_dn > FVG_ATR * d['atr']:
            bear.append('FVG')
    # liquidity sweep: wick through a confirmed swing, close back inside
    if sl is not None and lows[-1] < sl <= close:
        bull.append('SWEEP')
    if sh is not None and highs[-1] > sh >= close:
        bear.append('SWEEP')
    return bull, bear


def swing_points(highs, lows, left=SWING_LEFT):
    """last_swing() over the last 24 bars, with each swing's absolute position."""
    s = max(0, len(highs) - 24)
    sh = sl = jh = jl = None
    for j in range(s + left, len(highs) - left):
        if highs[j] == max(highs[j - left:j + left + 1]):
            sh, jh = highs[j], j
        if lows[j] == min(lows[j - left:j + left + 1]):
            sl, jl = lows[j], j
    return sh, jh, sl, jl


def turn(bars, arm, prev):
    """W34/W35 first turn on the latest bar: (side, stop) or None; updates `arm`.

    Arm a SELL when a bar wicks above the last confirmed swing high and closes
    back at or below it, that swing being the highest high since the last BUY
    mark (or the open). It fires once a later close falls below the lowest low
    between the swing and the arming bar, and is cancelled by any high above
    the sweep. BUY mirrors it. No VWAP / EMA / RSI here: the turn comes
    first, before the bias has flipped. `prev` maps side -> last mark index.
    """
    i = len(bars) - 1
    highs = [b[2] for b in bars]
    lows = [b[3] for b in bars]
    close = bars[i][4]
    fired = {}
    for side, a in list(arm.items()):
        if a is None:
            continue
        if (highs[i] > a[0]) if side == 'SELL' else (lows[i] < a[0]):
            arm[side] = None
        elif (close < a[1]) if side == 'SELL' else (close > a[1]):
            fired[side] = a[0]
            arm[side] = None
    sh, jh, sl, jl = swing_points(highs, lows)
    if sh is not None and highs[i] > sh >= close and jh + 1 <= i - 1:
        if max(highs[prev.get('BUY') or 0:i]) == sh:
            arm['SELL'] = (highs[i], min(lows[jh + 1:i]))
    if sl is not None and lows[i] < sl <= close and jl + 1 <= i - 1:
        if min(lows[prev.get('SELL') or 0:i]) == sl:
            arm['BUY'] = (lows[i], max(highs[jl + 1:i]))
    return next(iter(fired.items())) if len(fired) == 1 else None


def hk_tick(price, day=None):
    """HKEX equity spreads, with inclusive upper bounds and dated reductions."""
    day = day or now_hkt().strftime('%Y-%m-%d')
    if day >= '2026-08-03' and 0.5 < price <= 10:
        return 0.005
    if day >= '2025-08-04':
        if 10 < price <= 20:
            return 0.01
        if 20 < price <= 50:
            return 0.02
    for upper, tick in HK_TICK_BANDS:
        if price <= upper:
            return tick
    return 5.0


def us_tick(price, _day=None):
    return 0.01 if price >= 1 else 0.0001


def a_tick(_price):
    return 0.01


def ticks_per_bar(bars, tick=hk_tick):
    """Session-to-date mean bar range (high - low) in ticks, one value per bar.

    Bar 0 is the opening auction print (O=H=L=C), so it is left out. Causal:
    entry i only uses bars 0..i, which keeps a restart reproducible.
    """
    out, total = [], 0.0
    for i, b in enumerate(bars):
        if i:
            step = hk_tick(b[4], b[0][:10]) if tick is hk_tick else tick(b[4])
            total += (b[2] - b[3]) / step if step > 0 else 0.0
        out.append(total / max(i, 1))
    return out


def _emit_ok(rule, i, side, tier, d, last, anchor):
    """Whether this bar may become a mark. Indicators are already computed.

    repeat15  current rule: same side and tier, quiet for 15 bars.
    repeat30  the same quiet stretch, 30 bars.
    episode   one mark per side until the opposite side prints.
    extend2   repeat15, and drop a same-side mark once price has run more
              than 2x ATR past the close of the last emitted mark of that side.
    """
    if rule == 'episode':
        return not (anchor and anchor[0] == side)
    if rule == 'extend2' and anchor and anchor[0] == side:
        moved = (d['close'] - anchor[1]) if side == 'BUY' else (anchor[1] - d['close'])
        if d['atr'] > 0 and moved > 2.0 * d['atr']:
            return False
    gap = 30 if rule == 'repeat30' else DEDUP_BARS
    return i - last.get((side, tier), -10 ** 9) >= gap


def marks(bars, rule='repeat15', tick=hk_tick):
    """Two tiers of marks, derived purely from `bars`.

    plain  bias + structure trigger.
    vol    the same trigger with volume expansion AND in the right half of the
           day's range.

    `rule` only changes emission. Bias stays VWAP / EMA9 / EMA21 / RSI14, and
    triggers stay BOS / FVG / SWEEP. The live default retains `repeat15`: on
    HK.02513 / HK.09988 / HK.01810 / HK.00100 from 2026-07-28 through
    2026-09-22 it had the best second-half 30-bar mean among repeat15,
    repeat30, episode, and extend2, and none of the others raised that
    half without giving up the pooled mean. That comparison predates W12's
    corrected volume baseline and dated spreads. `vol` marks are NOT more
    accurate than `plain` ones on the older 40-day cut -- only rarer.

    Tick density (historical study W2, studies/watch_signal/): a mark whose bar sits in
    a session averaging fewer than GATE_TPB ticks per bar is `coarse`. There
    a break is often the close flipping from bid to ask; those marks averaged
    -1.88bp out of sample (t = -6.6), about 0.2 tick -- real but small, so
    they are downgraded on the board, not dropped. `fine` (>= FINE_TPB ticks
    per bar) is logged only: on its own it was never significant (W9).
    W2/W9 figures used the old spread table, not the corrected W12 groups.

    TURN (W34/W35, studies/watch_signal/): the first mark of a turn may come
    from `turn()` without the bias; it is tagged `TURN` in `trigger` and its
    stop is the sweep extreme. Repeats still need bias + structure, and TURN
    marks go through the same de-duplication. On 32 unused HK days it came
    a median 3 (SELL) / 2 (BUY) bars after the leg's extreme vs 11 / 9 for the
    current first mark, with direction right +3.7 / +3.6 points more often.
    Both are negative after the 10bp round trip.
    """
    if rule not in ('repeat15', 'repeat30', 'episode', 'extend2'):
        raise ValueError('unknown mark rule %r' % rule)
    out, last, anchor, d = [], {}, None, None
    arm, prev = {'SELL': None, 'BUY': None}, {}
    tpb = ticks_per_bar(bars, tick)
    for end in range(1, len(bars) + 1):
        i = end - 1
        d = read(bars[:end])
        if i < WARMUP_BARS:
            continue
        fired = turn(bars[:end], arm, prev)
        side = trig = stop = None
        if None not in (d['vwap'], d['ema9'], d['ema21'], d['rsi']):
            bull, bear = structure(bars[:end], d)
            long_bias = d['close'] > d['vwap'] and d['ema9'] > d['ema21'] and d['rsi'] >= 50
            short_bias = d['close'] < d['vwap'] and d['ema9'] < d['ema21'] and d['rsi'] <= 50
            if long_bias and bull:
                side, trig = 'BUY', '+'.join(bull)
            elif short_bias and bear:
                side, trig = 'SELL', '+'.join(bear)
        if fired and side in (None, fired[0]):  # an opposite bias mark wins
            trig = 'TURN+' + trig if side else 'TURN'
            side, stop = fired
        if side is None:
            continue
        ok_zone = d['pos'] <= PREMIUM if side == 'BUY' else d['pos'] >= 1 - PREMIUM
        vr = d['vol_ratio']
        tier = 'vol' if (vr is not None and vr >= VOL_MULT and ok_zone) else 'plain'
        if not _emit_ok(rule, i, side, tier, d, last, anchor):
            continue
        last[(side, tier)] = i
        prev[side] = i
        anchor = (side, d['close'])
        if stop is None:
            stop = d['swing_low'] if side == 'BUY' else d['swing_high']
        out.append({'i': i, 't': bars[i][0][11:16], 'side': side, 'tier': tier,
                    'tpb': round(tpb[i], 2), 'fine': tpb[i] >= FINE_TPB,
                    'coarse': tpb[i] < GATE_TPB,
                    'trigger': trig, 'close': d['close'],
                    'rsi': round(d['rsi'], 1) if d['rsi'] is not None else None,
                    'vwap': round(d['vwap'], 3) if d['vwap'] is not None else None,
                    'vol_ratio': round(vr, 2) if vr is not None else None,
                    'pos': round(d['pos'], 2), 'stop': stop})
    if d is not None and tpb:
        d['tpb'] = tpb[-1]
    return out, d


def volume_text(ratio):
    return '-' if ratio is None else '%.1fx' % ratio


def paint_side(side):
    return (GREEN + 'B' if side == 'BUY' else RED + 'S') + OFF


def stop_crossed(m):
    """The swing reference already sits on the wrong side of the signal close."""
    stop = m.get('stop')
    if stop is None:
        return False
    return stop >= m['close'] if m['side'] == 'BUY' else stop <= m['close']


def ref_text(m):
    """Swing reference, not a stop: exiting there averaged -1.15bp (W2)."""
    stop = m.get('stop')
    if stop is None:
        return 'ref -'
    if stop_crossed(m):
        return 'ref crossed'
    return 'ref %.2f %+.1f%%' % (stop, (stop / m['close'] - 1.0) * 100.0)


def disp_width(text):
    """Terminal columns a string occupies; CJK glyphs take two."""
    return sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text)


def clip(text, width):
    """Truncate to `width` terminal columns, never splitting a wide glyph."""
    out, used = [], 0
    for c in text:
        step = 2 if unicodedata.east_asian_width(c) in 'WF' else 1
        if used + step > width:
            break
        out.append(c)
        used += step
    return ''.join(out)


def cell(text, width, color=''):
    """Pad to `width` terminal columns; ANSI codes must not count toward it."""
    text = clip(text, width)
    pad = ' ' * max(0, width - disp_width(text))
    return (color + text + OFF if color else text) + pad


def mark_text(m, width, run=1):
    """One signal: side, strength grade 1-5 (W27/W31), `~` and dim = tick-bound.

    `#n` = the n-th mark in a row on this side (display only). The grade
    replaced bold emphasis (D2); neither is a profitability claim. The stock
    and index moves the grade uses stay in the pipe JSON, not on the board.
    `ref` is the swing level, not a stop.
    """
    rest = clip(('~' if m.get('coarse') else ' ') + cell('#%d' % run if run > 1 else '', 3)
                + cell(m['trigger'], 13) + cell('%.2f' % m['close'], 9)
                + cell(volume_text(m['vol_ratio']), 6)
                + cell({True: 'D+', False: 'D-'}.get(m.get('daily'), ''), 3)
                + ref_text(m), width - 10)
    base = DIM if m.get('coarse') else ''
    grade = '?' if m.get('grade') is None else str(m['grade'])   # '-' read as negative
    return base + '  ' + cell(m['t'], 6) + paint_side(m['side']) + base + grade + rest + OFF


def caption(width):
    """Column names over the signal rows, aligned with mark_text."""
    return DIM + clip('  ' + cell('time', 6) + cell('', 3) + cell('#', 3) + cell('trigger', 13)
                      + cell('close', 9) + cell('vol', 6) + cell('D', 3) + 'ref', width) + OFF


def range_text(r):
    """W24: how far the rest of the day is expected to travel, not which way."""
    if not r:
        return DIM + '  left -' + OFF
    return ('  ' + BOLD + 'left \u00b1%.2f%%' % r['half'] + OFF
            + DIM + ' (%.2f-%.2f) @%s' % (r['lo'], r['hi'], r['cp']) + OFF)


def symbol_lines(code, st, width):
    """One symbol's quote and every signal, oldest first."""
    name = st.get('name', '')
    bars = st.get('bars') or []
    stamp = bars[-1][0] if bars else st.get('last_bar')
    health = DIM + '  data ' + (stamp[11:16] if stamp else '-') + OFF
    if st.get('stale'):
        health += RED + ' STALE' + OFF
    if st.get('error'):
        return [cell(code, 11) + cell(name, 10, DIM) + DIM + st['error'] + OFF, health]
    bars, ms, d = st['bars'], st['marks'], st['read']
    last = bars[-1][4]
    op = bars[0][1] or last
    ret_bp = (last / op - 1.0) * 10000.0
    vwap_bp = (last / d['vwap'] - 1.0) * 10000.0 if d.get('vwap') else 0.0
    rsi = d.get('rsi')
    vr = d.get('vol_ratio')
    tpb = d.get('tpb')
    head = (cell(code, 11) + cell(name, 10, DIM)
            + cell('%.2f' % last, 9)
            + cell('%+dbp' % int(round(ret_bp)), 8)
            + cell('vwap%+d' % int(round(vwap_bp)), 9)
            + cell('rsi%s' % ('-' if rsi is None else '%.1f' % rsi), 8)
            + cell(volume_text(vr), 6,
                   BOLD if vr is not None and vr >= VOL_MULT else DIM))
    tail = DIM + ' tpb%s n%d' % ('-' if tpb is None else '%.1f' % tpb, len(bars)) + OFF
    # A half-width column cannot hold the full quote row; tpb/n then move
    # under it so neighbouring columns stay aligned.
    info = range_text(st.get('range')) + health      # `left` first: it is what guides a trade
    if _plain_width(head + tail) <= width:
        lines = [head + tail, info]
    else:
        lines = [head, info + tail]
    if not ms:
        lines.append(DIM + '  (none)' + OFF)
    run, side = 0, None
    for m in ms:
        run = run + 1 if m['side'] == side else 1
        side = m['side']
        lines.append(mark_text(m, width, run))
    return lines


def _plain_width(text):
    return disp_width(re.sub(r'\x1b\[[0-9;]*m', '', text))


def _pad(text, width):
    gap = width - _plain_width(text)
    return text + (' ' * gap) if gap > 0 else text


def _stack(blocks):
    lines = []
    for i, block in enumerate(blocks):
        if i:
            lines.append('')
        lines.extend(block)
    return lines


def _columns(blocks, width):
    """Two columns of whole symbol blocks. A block is never split."""
    col_w = (width - 1) // 2
    left, right, hl, hr = [], [], 0, 0
    for block in blocks:
        if hl <= hr:
            if left:
                left.append('')
                hl += 1
            left.extend(block)
            hl += len(block)
        else:
            if right:
                right.append('')
                hr += 1
            right.extend(block)
            hr += len(block)
    lines = []
    for i in range(max(len(left), len(right))):
        a = left[i] if i < len(left) else ''
        b = right[i] if i < len(right) else ''
        lines.append(_pad(a, col_w) + ' ' + b)
    return lines


def frame_lines(state, at, width, rows=None):
    """Grouped log. Two columns only when that keeps every signal on screen."""
    head = 'kline.1m %s+08 poll=%ds n=%d until=%s' % (
        at.strftime('%Y-%m-%d %H:%M:%S'), POLL_SEC, len(state), UNTIL)
    if width >= 100:
        head += ' src=%s:%s' % (HOST, PORT)
    legend = (GREEN + 'B' + OFF + '/' + RED + 'S' + OFF
              + DIM + ' 后的1-5=强度档(跨标的,非胜率,?=日线未到)  暗色~ 不到%g跳  D± 日线' % GATE_TPB + OFF)
    legend2 = DIM + clip('left 收盘前还能走±(八成区间)  #n 同方向第n次  ref 结构位,非止损',
                         width) + OFF
    chrome = [BOLD + clip(head, width) + OFF, legend, legend2, '-' * width]
    blocks = [symbol_lines(code, st, width) for code, st in state.items()]
    body = _stack(blocks)
    cap = caption(width)
    room = None if rows is None else rows - 2 - len(chrome)
    if room is not None and len(body) > room and width >= 136:
        col_w = (width - 1) // 2
        narrow = [symbol_lines(code, st, col_w) for code, st in state.items()]
        side = _columns(narrow, width)
        if len(side) <= room:
            body = side
            cap = _pad(caption(col_w), col_w) + ' ' + caption(col_w)
    return chrome[:3] + [cap] + chrome[3:] + body


def board(state, at, width):
    """One log per symbol. No price chart."""
    return '\n'.join(frame_lines(state, at, width))


def paint(lines, prev, rows):
    """Redraw the grouped log. Unchanged lines stay put.

    A new signal changes the length, so the whole frame is rewritten with
    that signal still inside its own symbol block. Absolute row updates are
    only used when the frame fits; a taller frame is written in full so
    nothing is dropped.
    """
    title = '\033]0;kline.1m\007'
    if prev is None or len(lines) != len(prev) or len(lines) > rows - 1:
        sys.stdout.write('\033[H\033[J' + title + '\n'.join(lines) + '\n')
    else:
        parts = [title]
        for i, (old, new) in enumerate(zip(prev, lines)):
            if old != new:
                parts.append('\033[%d;1H\033[2K%s' % (i + 1, new))
        if len(parts) > 1:
            sys.stdout.write(''.join(parts))
    sys.stdout.flush()
    return lines


def main():
    global UNTIL
    codes = [canonical_code(c) for c in (sys.argv[1:] or DEFAULT_CODES)]
    mkts = sorted({market(c) for c in codes})
    closes = ([close_hkt()] if set(mkts) & {'HK', 'A'} else []) + ([close_us()] if 'US' in mkts else [])
    deadline = max(closes)
    UNTIL = deadline.astimezone(HKT).strftime('%H:%M')
    opend_codes = [c for c in codes if market(c) != 'A']
    opend_index = [INDEX[m] for m in mkts if m != 'A']
    ctx = None
    try:
        if opend_codes:
            ctx = OpenQuoteContext(host=HOST, port=PORT)
            ret, err = ctx.subscribe(sorted(set(opend_codes + opend_index)), [SubType.K_1M],
                                     subscribe_push=False)
            if ret != RET_OK:
                emit('FAILED', {'error': 'subscribe %s' % err})
                return 1
            # separate call: a failed K_DAY subscription only costs daily context
            try:
                ctx.subscribe(sorted(set(opend_codes + opend_index)), [SubType.K_DAY],
                              subscribe_push=False)
            except Exception:
                pass
        emit('START', {'codes': codes, 'until': deadline.isoformat(),
                       'poll_sec': POLL_SEC, 'log': str(log_path())})
        seen, state, names, prev, dctxs = {}, {}, {}, None, {}
        health, last_times, daily_retry = {}, {}, {}
        index_atr, index_retry, graded = {}, {}, set()

        def regrade(code):
            st = state.get(code) or {}
            if not st.get('bars'):
                return
            mkt = market(code)
            today = st['bars'][-1][0][:10]
            context_day, dc = dctxs.get(code, (None, None))
            dc = dc if context_day == today else None
            st['marks'] = with_grade(with_daily(st['marks'], None if mkt == 'US' else dc), dc,
                                     index_atr.get(mkt, (None, None))[1])
            if mkt == 'HK':
                st['range'] = range_left(st['bars'], dc)

        while True:
            poll_start = time.monotonic()
            indexes = {m: index_session(ctx, m) for m in mkts}
            for code in codes:
                mkt = market(code)
                if mkt == 'A':
                    bars, name, stock_previous = tencent_session(code)
                else:
                    bars, name, stock_previous = session_bars(ctx, code)
                if bars:
                    last_times[code] = bars[-1][0]
                at = now_hkt()
                stale = bar_stale(code, last_times.get(code), at)
                if stale is not None and stale != health.get(code, False):
                    emit('STALE' if stale else 'RECOVERED',
                         {'code': code, 'last_bar': last_times.get(code), 'at': at.isoformat()})
                    health[code] = stale
                if not bars:
                    state[code] = {'error': 'no data', 'name': names.get(code, ''),
                                   'last_bar': last_times.get(code), 'stale': stale is True}
                    continue
                names[code] = name or names.get(code, '')
                ms, d = marks(bars, tick={'A': a_tick, 'US': us_tick}.get(mkt, hk_tick))
                ms = with_strength(ms, indexes.get(mkt), stock_previous, score=mkt == 'HK')
                state[code] = {'bars': bars, 'marks': ms, 'read': d or read(bars),
                               'name': names[code], 'stale': stale is True, 'range': None}
                regrade(code)
                for m in state[code]['marks'][seen.get(code, 0):]:
                    emit('MARK', dict(m, code=code, name=names[code]))
                    if m.get('grade') is not None:
                        graded.add((code, m['t'], m['side']))
                seen[code] = len(state[code]['marks'])
            if sys.stdout.isatty():
                size = shutil.get_terminal_size((100, 40))
                width = min(140, max(80, size.columns))
                prev = paint(frame_lines(state, now_hkt(), width, size.lines), prev, size.lines)
            closing = now_hkt() >= deadline
            # Daily context comes after every quote/mark and the board; failures
            # wait five minutes. The final frame also needs context when started
            # after the close.
            context_changed = False
            for mkt in mkts:
                today = now_in(mkt).strftime('%Y-%m-%d')
                if index_atr.get(mkt, (None,))[0] == today or time.monotonic() < index_retry.get(mkt, 0):
                    continue
                rows = index_daily(ctx, mkt)
                value = atr20(sorted(r for r in rows or [] if r[0] < today))
                index_retry[mkt] = time.monotonic() + 300
                if value:
                    index_atr[mkt] = (today, value)
                    for code in codes:
                        if market(code) == mkt:
                            regrade(code)
                    context_changed = True
                    emit('INDEX_CONTEXT', {'market': mkt, 'index': INDEX[mkt], 'day': today, 'atr20': value})
            for code in sorted(codes, key=lambda c: daily_retry.get(c, 0)):
                bars = state[code].get('bars')
                if not bars:
                    continue
                today = bars[-1][0][:10]
                if (dctxs.get(code, (None,))[0] == today
                        or time.monotonic() < daily_retry.get(code, 0)):
                    continue
                remote = market(code) == 'A'
                rows = tencent_daily(code) if remote else hk_daily(ctx, code)
                dc = daily_context(rows or [], today)
                daily_retry[code] = time.monotonic() + 300
                if dc:
                    dctxs[code] = (today, dc)
                    regrade(code)
                    context_changed = True
                    emit('DAILY_CONTEXT', {'code': code, 'day': today, 'context': dc})
                # Tencent is a remote call that can take seconds, so at most one
                # per live poll; OpenD daily bars are local and fill all at once.
                if remote and not closing:
                    break
            if context_changed:
                # Marks already emitted before their daily context get their grade now.
                for code in codes:
                    for m in (state[code].get('marks') or [])[:seen.get(code, 0)]:
                        if m.get('grade') is not None and (code, m['t'], m['side']) not in graded:
                            graded.add((code, m['t'], m['side']))
                            emit('MARK_GRADE', {'code': code, 't': m['t'], 'side': m['side'],
                                                'grade': m['grade'], 'daily': m.get('daily')})
            if context_changed and sys.stdout.isatty():
                size = shutil.get_terminal_size((100, 40))
                width = min(140, max(80, size.columns))
                prev = paint(frame_lines(state, now_hkt(), width, size.lines), prev, size.lines)
            if closing:
                break
            remaining = POLL_SEC - (time.monotonic() - poll_start)
            if remaining > 0:
                time.sleep(min(remaining, max(0, (deadline - now_hkt()).total_seconds())))
        emit('DONE', {'at': now_hkt().isoformat(),
                      'marks': {c: len(s.get('marks', [])) for c, s in state.items()}})
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        emit('FAILED', {'error': str(exc)})
        return 1
    finally:
        if ctx is not None:
            try:
                ctx.close()
            except Exception:
                pass


if __name__ == '__main__':
    sys.exit(main())
