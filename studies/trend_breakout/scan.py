"""Whole-market weekly scan with each market's final scheme (final.py). Run after the week's last close.

    PY="env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/opend-us-options/.venv/bin/python"
    $PY -m studies.trend_breakout.scan refresh hk           # fetch ~3 years of daily bars for today's stock list
    $PY -m studies.trend_breakout.scan run hk --capital 100000 --holding HK.00700:2026-09-01
    $PY -m studies.trend_breakout.scan run all --folder data/trend-breakout-v1   # replay on any dataset

``refresh`` is a foreground, on-demand fetch into data/trend-scan/<date>/<market> (resumable): US/HK through
OpenD get_cur_kline (no history-kline quota), A-shares through Sina (>= 10bn cap list, about 70 minutes for ~1700 stocks).
``run`` takes each market's newest refresh (or --folder), uses only completed weeks, replays the scheme's rule book over the data, and writes <folder>/<market>_scan.json.
Output is the rule state, not orders.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date, datetime, time, timedelta, timezone
import gzip
import json
from pathlib import Path
import shutil
from zoneinfo import ZoneInfo

import numpy as np

from . import chan, fetch, pit
from .final import SCHEMES, Book

ROOT = Path(__file__).resolve().parents[2]
SCANS = ROOT / 'data' / 'trend-scan'
LOT = {'cn': 100, 'us': 1, 'hk': 1}  # HK board lots differ by stock; shares are not rounded to them
NAMES = {'cn': 'A 股', 'hk': '港股', 'us': '美股'}
# local close plus a margin for the sources to publish the day's final bar
CLOSE = {'cn': ('Asia/Shanghai', time(15, 30)), 'hk': ('Asia/Hong_Kong', time(16, 30)),
         'us': ('America/New_York', time(16, 30))}


def market_now(market, now=None):
    return (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(CLOSE[market][0]))


def closed_at(market, day):
    zone, at = CLOSE[market]
    return datetime.combine(day, at, ZoneInfo(zone))


def latest_folder(market):
    """Newest data/trend-scan/<date> folder holding this market, or None."""
    done = sorted(p for p in SCANS.glob('*') if (p / market / 'universe.json').exists())
    return done[-1] if done else None


def stale(folder, market, now=None):
    """A finished fetch taken before the market's close of its own date, while that close has now passed."""
    path = folder / market / 'progress.json'
    if not path.exists():
        return False
    finished = json.loads(path.read_text(encoding='utf-8')).get('finished_utc')
    if not finished:
        return False  # interrupted: resume it
    close = closed_at(market, date.fromisoformat(folder.name))
    return datetime.fromisoformat(finished) < close <= (now or datetime.now(timezone.utc))


def refresh(market, now=None):
    """Fetch ~3 years of daily bars into data/trend-scan/<market-local date>/<market>; an unfinished fetch resumes,
    a fetch taken before today's close is redone after it."""
    today = market_now(market, now).date()
    out = SCANS / today.isoformat()
    if stale(out, market, now):
        shutil.rmtree(out / market)
    start = (today - timedelta(days=3 * 366)).isoformat()
    progress = fetch.fetch(out, market, start, today.isoformat())
    return out, progress


def audit(folder, market):
    """What a refresh produced: coverage, the latest bar date, stocks behind it, histories shorter than a year."""
    sub = Path(folder) / market
    stocks = json.loads((sub / 'universe.json').read_text(encoding='utf-8'))['stocks']
    progress = json.loads((sub / 'progress.json').read_text(encoding='utf-8'))
    count, last = Counter(), {}
    with gzip.open(sub / 'bars_raw.csv.gz', 'rt', encoding='utf-8', newline='') as f:
        for row in csv.reader(f):
            if row and row[0] != 'code':
                count[row[0]] += 1
                last[row[0]] = row[1]
    latest = max(last.values()) if last else None
    bars = sorted(count.values())
    return {'stocks': len(stocks), 'fetched': len(count), 'failed': progress.get('failed', {}),
            'finished': bool(progress.get('finished_utc')), 'latest_bar': latest,
            'behind_latest': sorted(c for c, d in last.items() if d < latest),
            'median_bars': bars[len(bars) // 2] if bars else 0,
            'under_250_bars': sum(n < 250 for n in bars)}


def week_complete(last_bar, now_local, close_time):
    """The last weekly bar counts only once its last day has closed and that day is a Friday or the week is over."""
    today = now_local.date()
    if last_bar > today or (last_bar == today and now_local.time() < close_time):
        return False  # the day (and so its week) is still trading
    if last_bar.weekday() >= 4:
        return True
    return today.isocalendar()[:2] > last_bar.isocalendar()[:2]


def load_panel(folder, market):
    sub = Path(folder) / market
    window = json.loads((sub / 'universe.json').read_text(encoding='utf-8')).get('window', ['2000-01-01', '2100-01-01'])
    return pit.load([(sub, window[0], window[1], None)], [sub])


def shares_for(market, scheme, capital, price, stop):
    if not capital or not np.isfinite(price) or price <= 0:
        return None
    slots = scheme['slots']
    value = capital / slots
    if scheme['sizing'] == 'RISK':
        risk = price - stop if np.isfinite(stop) and stop < price else price
        value = min(capital * .10 / slots / risk * price, capital * 2 / slots)
    lot = LOT[market]
    return int(value / price // lot * lot)


def check_holding(book, scheme, code, bought, scan_week):
    """Stop and exit state of a held stock under the scheme's exit rules, as of the scan week's close."""
    codes = [str(c) for c in book.p['codes']]
    if code not in codes:
        return {'code': code, 'error': '不在本市场股票名单里'}
    j = codes.index(code)
    dates = np.array(book.pw['dates'])
    entry = int(np.searchsorted(dates, bought))
    if entry > scan_week:
        return {'code': code, 'error': '买入日期晚于扫描周'}
    w = book.w
    stop = book.initial[entry - 1, j] if entry and np.isfinite(book.initial[entry - 1, j]) else book.support[entry - 1, j]
    trail = book.support if scheme['trail'] == 'STRUCT' else w['low']
    for t in range(entry, scan_week):
        if np.isfinite(w['close'][t, j]) and np.isfinite(trail[t, j]):
            stop = np.nanmax([stop, trail[t, j]])
    close = w['close'][scan_week, j]
    up, _ = book.line(scheme['line'])
    held = scan_week - entry + 1
    reasons = []
    if np.isfinite(stop) and close < stop:
        reasons.append('周收盘跌破止损')
    if scheme['exit_on_line'] and not up[scan_week]:
        reasons.append('大盘跌破均线')
    if scheme['max_hold'] and held >= scheme['max_hold']:
        reasons.append(f'已持 {held} 周，达到 {scheme["max_hold"]} 周上限')
    next_stop = np.nanmax([stop, trail[scan_week, j]]) if np.isfinite(trail[scan_week, j]) else stop
    to_raw = w['raw_close'][scan_week, j] / close
    return {'code': code, 'name': book.p.get('names', {}).get(code, ''), 'weeks_held': held,
            'close_raw': float(w['raw_close'][scan_week, j]),
            'stop_raw': float(stop * to_raw) if np.isfinite(stop) else None,
            'next_week_stop_raw': float(next_stop * to_raw) if np.isfinite(next_stop) else None,
            'sell_next_open': bool(reasons), 'reasons': reasons}


def run(market, folder, capital=None, holdings=(), now=None):
    p = load_panel(folder, market)
    dates = [str(d) for d in p['dates']]
    last_bar = date.fromisoformat(dates[-1])
    weeks = chan.week_rows(p['dates'])[1]
    end_row = int(weeks[-1]) if week_complete(last_bar, market_now(market, now), CLOSE[market][1]) else int(weeks[-2])
    replay_start = dates[min(len(dates) - 1, 250)]
    book = Book(market, p=p, span=(replay_start, dates[end_row]), cap=False)
    scheme = SCHEMES[market]
    metrics, account = book.run(scheme)
    state = book.holdings(scheme, account)
    hi = book.hi
    up, streak = book.line(scheme['line'])
    for c in state['next_week_candidates']:
        c['shares'] = shares_for(market, scheme, capital, c['close_raw'], c['stop_raw'])
    result = {'market': market, 'folder': str(folder), 'scan_week_end': dates[end_row],
              'last_bar': dates[-1], 'last_week_dropped_as_incomplete': end_row != len(dates) - 1,
              'scheme': scheme, 'market_line_ok': bool(up[hi]),
              'weeks_above_line': int(streak[hi]) if streak is not None else None,
              'buying_open': bool(up[hi]) and (scheme['early'] is None or (streak is not None and streak[hi] <= scheme['early'])),
              'candidates': state['next_week_candidates'], 'rule_book_positions': state['positions'],
              'rule_book_replay': {k: metrics[k] for k in ('total_return', 'max_drawdown', 'trades')},
              'replay_from': replay_start, 'capital': capital,
              'holdings': [check_holding(book, scheme, code, day, hi) for code, day in holdings]}
    out = Path(folder) / f'{market}_scan.json'
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1, default=float) + '\n')
    return result


def show(r):
    m = r['market']
    print(f"\n== {NAMES[m]}（周 K 截至 {r['scan_week_end']}{'，最后一周未收完已忽略' if r['last_week_dropped_as_incomplete'] else ''}）")
    s = r['scheme']
    if s['line']:
        print(f"大盘 {s['line']} 日线：{'线上' if r['market_line_ok'] else '线下'}，已连续 {r['weeks_above_line']} 周；"
              f"本周{'可以' if r['buying_open'] else '不'}开新仓")
    else:
        print('不看大盘，本周可以开新仓')
    if r['last_week_dropped_as_incomplete']:
        print(f"注意：这是 {r['scan_week_end']} 那周收盘后的规则状态，候选对应其后第一个交易日开盘，已经过去；"
              "本周收盘后再 refresh + run 得到下周的候选")
    print('候选（按规则排序，下周一开盘买；开盘不低于"放弃价"就不买）：' if r['candidates'] else '没有候选')
    for c in r['candidates']:
        extra = f"，建议 {c['shares']} 股" if c.get('shares') is not None else ''
        print(f"  {c['code']} {c['name']} 收 {c['close_raw']:.2f} 止损 {c['stop_raw']:.2f} 放弃价 {c['skip_if_open_at_or_above']:.2f}{extra}")
    if r['rule_book_positions']:
        print('规则账户当前持有：' + '、'.join(f"{x['code']} {x['name']}" for x in r['rule_book_positions']))
    for h in r['holdings']:
        if 'error' in h:
            print(f"  持仓 {h['code']}：{h['error']}")
        else:
            act = '下周一开盘卖出（' + '；'.join(h['reasons']) + '）' if h['sell_next_open'] else '继续持有'
            print(f"  持仓 {h['code']} {h['name']} 已持 {h['weeks_held']} 周，收 {h['close_raw']:.2f}，"
                  f"止损 {h['stop_raw'] or float('nan'):.2f}，下周止损 {h['next_week_stop_raw'] or float('nan'):.2f}：{act}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=('refresh', 'run'))
    parser.add_argument('market', choices=('cn', 'hk', 'us', 'all'))
    parser.add_argument('--folder', help='dataset root with <market>/ subfolders (default: newest data/trend-scan/<date> per market)')
    parser.add_argument('--capital', type=float, help='account size for suggested shares (in the market currency)')
    parser.add_argument('--holding', action='append', default=[], help='CODE:YYYY-MM-DD buy date, repeatable')
    args = parser.parse_args(argv)
    np.seterr(invalid='ignore', divide='ignore')
    markets = ('cn', 'hk', 'us') if args.market == 'all' else (args.market,)
    if args.action == 'refresh':
        for m in markets:
            out, _ = refresh(m)
            a = audit(out, m)
            print(f"\n== {NAMES[m]} 取数 -> {out / m}{'' if a['finished'] else '（未完成，重跑会续传）'}\n"
                  f"名单 {a['stocks']} 只，取到 {a['fetched']} 只，失败 {len(a['failed'])} 只；最新日 K {a['latest_bar']}，"
                  f"落后的 {len(a['behind_latest'])} 只（多为停牌）；日 K 中位 {a['median_bars']} 根，"
                  f"不足 250 根（上市不满一年，不会出买点）{a['under_250_bars']} 只")
            for code, why in list(a['failed'].items())[:10]:
                print(f'  失败 {code}: {why}')
        return
    holdings = [tuple(h.split(':', 1)) for h in args.holding]
    for m in markets:
        folder = Path(args.folder) if args.folder else latest_folder(m)
        if folder is None or not (folder / m / 'universe.json').exists():
            print(f'\n== {NAMES[m]}：没有数据，先运行 scan refresh {m}')
            continue
        mine = [h for h in holdings if h[0].startswith({'cn': ('SH.', 'SZ.'), 'hk': ('HK.',), 'us': ('US.',)}[m])]
        show(run(m, folder, args.capital, mine))


if __name__ == '__main__':
    main()
