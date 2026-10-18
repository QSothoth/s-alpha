"""The traders' board (skills/trader-screens): if these traders were trading this market now, what would each of
them buy today, sell today and be holding, and where do they overlap.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.trader_screens.scan list
    $PY -m studies.trader_screens.scan refresh us                  # on-demand daily bars (OpenD, no history quota)
    $PY -m studies.trader_screens.scan run us                      # today's board
    $PY -m studies.trader_screens.scan run us --days 5             # the week's trades
    $PY -m studies.trader_screens.scan run us --folder data/martin-luk-universe-us   # research data
    $PY -m studies.trader_screens.scan industry us                 # fill missing OpenD industry names

Each draft trader trades an account replayed over the last REPLAY sessions with his own rules (book.py): from
all of the day's setups he buys only the few his limits allow.  The replicated system (frozen.py) replays its
research configuration from 2024-01-02.  ``run`` writes data/trader-screens/out/<market>_<day>_<n>d.json and
board_<market>_<day>_<n>d.md; ``board`` joins the newest daily run of each market into board.md (and a dated
copy).  Output is the rule state, not orders.
"""
from __future__ import annotations

import argparse
import json
import warnings
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from . import board, book as B, data, frozen, screens as S

TAIL = 420            # rows: 252-day windows, a 200-day average 21 days back, and the replay below
REPLAY = 126          # sessions each draft account is replayed over (about six months)
WATCH_N = 5
LEVEL_TEXT = {'replicated': '已复刻冻结', 'draft': '按原话初版'}
STEP_TEXT = {'no_signal': '没有信号', 'no_entry': '止损规则挡掉', 'market_filter': '市况不许开仓',
             'daily_cap': '被每天笔数上限挤掉', 'no_room': '没有仓位空间', 'traded': '规则账户买到'}


def all_screens():
    return list(frozen.REPLICATED) + list(S.DRAFTS)


def tail(p, n):
    k = max(len(p['days']) - n, 0)
    return {key: (v[k:] if isinstance(v, np.ndarray) and len(v) == len(p['days']) else v) for key, v in p.items()}


def index_above(F, n):
    """Pool equal-weight index closing above its EMA(n), as of each day's close."""
    def f():
        pool = F.rank_pool
        prev = S.lag(F.c)
        with np.errstate(invalid='ignore', divide='ignore'):
            r = np.where(pool & np.isfinite(prev), F.c / prev - 1, np.nan)
            idx = np.cumprod(1 + np.nan_to_num(np.nanmean(r, axis=1)))[:, None]
        return (idx > S.ema(idx, n))[:, 0]
    return F.get(('index_above', n), f)


def line(F, key):
    return None if not key else (F.sma if key.startswith('sma') else F.ema)(int(key[3:]))


def drawdown(curve):
    v = curve[np.isfinite(curve)]
    return float(np.max(1 - v / np.maximum.accumulate(v))) if len(v) else 0.0


def draft_board(s, F, days, T, d0):
    out = s.run(F)
    prio = -S.lag(S.strength(F))
    entries = [[] for _ in range(T + 1)]
    for st in out['setups']:
        if st.kind != 'triggered':
            continue
        m = st.mask & ~st.skip if st.skip is not None else st.mask
        for d, j in zip(*np.nonzero(m)):
            pr = prio[d, j]
            entries[d].append((pr if np.isfinite(pr) else 0.0, int(j), st.price[d, j], st.stop[d, j], st.name))
    trail = line(F, s.book.trail)
    gate = None
    if s.book.gate:
        gate = S.lag(index_above(F, int(s.book.gate[3:])))          # known before the day's trades
    r = B.replay(F.o, F.h, F.l, F.c, trail, entries, s.book, d0, B.COSTS[F.market], gate)
    codes = [str(c) for c in F.codes]
    eq = r['curve']
    span = range(max(T - days + 1, d0), T + 1)
    buys = [dict(code=codes[b['j']], day=str(F.days[d]), setup=b['setup'], price=b['fill'], stop=b['stop'],
                 weight=b['weight']) for d in span for b in r['buys'][d]]
    sells = [dict(code=codes[x['j']], day=str(F.days[d]), why=x['why'], price=x['price'], ret=x['ret'],
                  full=x['full']) for d in span for x in r['sells'][d]]
    holdings = []
    for p in r['open']:
        j = p['j']
        close = float(F.c[T, j])
        holdings.append(dict(code=codes[j], entry_day=str(F.days[p['d']]), setup=p['setup'], fill=p['fill'],
                             close=close, ret=close / p['fill'] - 1, stop=p['stop'],
                             trail=float(trail[T, j]) if trail is not None else None,
                             weight=p['size'] * close / r['equity'], days=T - p['d']))
    taken = {(b['code'], b['day']) for b in buys}
    wanted = sorted(({'code': codes[e[1]], 'day': str(F.days[d]), 'setup': e[4], 'price': float(e[2]), 'prio': e[0]}
                     for d in span for e in entries[d] if (codes[e[1]], str(F.days[d])) not in taken),
                    key=lambda x: x['prio'])
    ready = []
    for st in out['setups']:
        if st.kind == 'ready':
            for j in np.flatnonzero(st.mask[T]):
                stop = st.stop[T, j]
                pr = -S.strength(F)[T, j]
                ready.append(dict(code=codes[j], setup=st.name, price=float(st.price[T, j]),
                                  stop=float(stop) if np.isfinite(stop) else None,
                                  prio=float(pr) if np.isfinite(pr) else 0.0))
    ready.sort(key=lambda x: x['prio'])
    closed = r['trades']
    wins = [x for x in closed if x['ret'] > 0]
    gate_text = ''
    if s.book.gate:
        up = bool(index_above(F, int(s.book.gate[3:]))[T])
        then = '明天不开新仓' if s.book.gate_mode == 'block' else '明天风险减半'
        gate_text = f"指数{'在' if up else '跌破'} {s.book.gate[3:]} EMA{'' if up else '，' + then}"
    return dict(id=s.id, name=s.name, level=s.level, summary=s.summary, rules=s.book_note, dossier=s.dossier,
                buys=buys, sells=sells, holdings=sorted(holdings, key=lambda x: -x['weight']),
                wanted=wanted[:WATCH_N], wanted_n=len(wanted), watch=ready[:WATCH_N], watch_n=len(ready),
                watchlist=sorted(codes[j] for j in np.flatnonzero(out['watch'][T])),
                stance=dict(exposure=float(sum(h['weight'] for h in holdings)), gate=gate_text),
                account=dict(since=str(F.days[d0]), ret=float(eq[T] - 1), maxdd=drawdown(eq[d0:T + 1]),
                             trades=len(closed), win=len(wins) / len(closed) if closed else None))


def replicated_board(s, folder, days, capital):
    r = s.today(folder, days, capital)
    b = r['book']
    holdings = [dict(code=p['code'], entry_day=p['entry'], setup='收盘买入', fill=p['fill'], close=p['close'],
                     ret=p['close'] / p['fill'] - 1, stop=p['stop'], trail=p['trail'], weight=p['weight'],
                     r_now=p['r_now'], next_trim=p['next_trim'], next_add=p['next_add'], armed=p['armed'])
                for p in b['positions']]
    gate = f"{'允许开新多' if b['buying_open'] else '指数跌破 50 EMA，不开新多'}；下一笔风险 {b['risk_next']:.2%}"
    return dict(id=s.id, name=s.name, level=s.level, summary=s.summary,
                rules='每笔 0.5%（顺风 0.8%，指数回调 × 1.6）、每天最多 4 笔按成交额、单只 ≤ 50%、总 ≤ 280%；'
                      '+10R 卖 30%，收盘跌破 EMA21 清仓；+10R、+20R 加码',
                buys=r['buys'], sells=r['sells'], holdings=sorted(holdings, key=lambda x: -x['weight']),
                wanted=r['wanted'][:WATCH_N], wanted_n=len(r['wanted']), watch=[], watch_n=0, watchlist=r['watch'],
                stance=dict(exposure=float(b['gross']), gate=gate),
                account=dict(since=b['start'], ret=b['equity'] - 1, maxdd=None, trades=None, win=None),
                book=b)


def overlaps(traders, inds):
    def multi(key):
        who = defaultdict(list)
        for t in traders:
            for x in t[key]:
                if t['name'] not in who[x['code']]:
                    who[x['code']].append(t['name'])
        rows = [dict(code=c, traders=v, industry=inds.get(c, '')) for c, v in who.items() if len(v) >= 2]
        return sorted(rows, key=lambda x: (-len(x['traders']), x['code']))
    held = Counter(inds.get(h['code'], '') or '未知' for t in traders for h in t['holdings'])
    bought = Counter(inds.get(b['code'], '') or '未知' for t in traders for b in t['buys'])
    return dict(bought=multi('buys'), held=multi('holdings'), watch=multi('watch'),
                industries_held=held.most_common(10), industries_bought=bought.most_common(10),
                in_cash=[t['name'] for t in traders if not t['holdings']],
                exposure={t['name']: t['stance']['exposure'] for t in traders})


def run(market, folder, days=1, only=None, capital=None):
    warnings.simplefilter('ignore', RuntimeWarning)
    np.seterr(invalid='ignore', divide='ignore')
    chosen = [s for s in all_screens() if market in s.markets and (not only or s.id in only)]
    traders = [replicated_board(s, folder, days, capital) for s in chosen if s.level == 'replicated']
    p = data.panel(folder, market)
    k = max(len(p['days']) - TAIL, 0)
    before = np.nanmax(p['high'][:k], axis=0) if k else np.full(p['high'].shape[1], np.nan)
    F = S.Feat(tail(p, TAIL), market)
    F.high_before = before
    del p
    T = len(F.days) - 1
    d0 = max(T - REPLAY + 1, 0)
    for s in chosen:
        if s.level == 'draft':
            traders.append(draft_board(s, F, days, T, d0))
    nm = data.names(folder, market)
    inds = data.industries([str(c) for c in F.codes], market)
    for t in traders:
        for key in ('buys', 'sells', 'holdings', 'wanted', 'watch'):
            for x in t[key]:
                x['name'], x['industry'] = nm.get(x['code'], ''), inds.get(x['code'], '')
    state = {f'above_ema{n}': bool(index_above(F, n)[T]) for n in (20, 50)}
    return dict(market=market, folder=str(folder), last_day=str(F.days[T]), days=days, names=len(F.codes),
                state=state, replay=REPLAY, traders=traders, common=overlaps(traders, inds))


def pct(x):
    return '—' if x is None else f'{x:+.1%}'


def px(x):
    return '—' if x is None else (f'{x:.2f}' if abs(x) < 1000 else f'{x:.0f}')


def show(r):
    st = r['state']
    span = '今天' if r['days'] == 1 else f"近 {r['days']} 个交易日"
    print(f"\n== {data.NAMES[r['market']]} {r['last_day']} 交易员看板；股票池等权指数"
          f"{'站上' if st['above_ema20'] else '跌破'} 20 EMA、{'站上' if st['above_ema50'] else '跌破'} 50 EMA")
    for t in r['traders']:
        print(f"\n[{t['name']}｜{LEVEL_TEXT[t['level']]}] {t['summary']}")
        a, s = t['account'], t['stance']
        acct = f"账户自 {a['since']} 起 {pct(a['ret'])}"
        if a['trades']:
            acct += f"，回撤 {a['maxdd']:.0%}，{a['trades']} 笔平仓、胜率 {a['win']:.0%}"
        print(f"  仓位 {s['exposure']:.0%}{('；' + s['gate']) if s['gate'] else ''}；{acct}")
        print(f"  {span}买入：" + ('无' if not t['buys'] else ''))
        for b in t['buys']:
            day = f" {b['day']}" if r['days'] > 1 else ''
            print(f"    {b['code']} {b['name'][:10]} {b['setup']}{day} 买 {px(b['price'])} "
                  f"止损 {px(b['stop'])}（{(b['price'] - b['stop']) / b['price']:.1%}）仓位 {b.get('weight', 0):.0%} "
                  f"{b['industry']}")
        if t['wanted_n']:
            print(f"  另有 {t['wanted_n']} 个买点没做（每天笔数 / 持仓数 / 仓位已满）：" +
                  '、'.join(x['code'] for x in t['wanted']))
        print(f"  {span}卖出：" + ('无' if not t['sells'] else ''))
        for x in t['sells']:
            print(f"    {x['code']} {x['name'][:10]} {x['why']}{'' if x['full'] else '（部分）'} {px(x['price'])}，"
                  f"相对买价 {pct(x['ret'])}")
        print(f"  持仓 {len(t['holdings'])} 只：" + ('空仓' if not t['holdings'] else ''))
        for h in t['holdings']:
            trail = f"，跟踪线 {px(h['trail'])}" if h.get('trail') else ''
            print(f"    {h['code']} {h['name'][:10]} {h['entry_day']} 买 {px(h['fill'])} → {px(h['close'])}"
                  f"（{pct(h['ret'])}）仓位 {h['weight']:.0%}，止损 {px(h['stop'])}{trail} {h['industry']}")
        if t['watch']:
            print(f"  明天关注（{t['watch_n']} 个待触发，按强度前 {len(t['watch'])}）：" + '、'.join(
                f"{x['code']} {x['setup']} 越过 {px(x['price'])}" for x in t['watch']))
        if t.get('book'):
            b = t['book']
            for y, v in b['check'].items():
                print(f"  回放核对 {y}：{v['replay']:+.1%}（研究报告 {v['research']:+.1%}）")
            f = b['forward']
            if f['days']:
                print(f"  冻结日 {b['freeze']} 之后：{pct(f['ret'])}，回撤 {f['maxdd']:.0%}，新开 {len(f['trades'])} 笔")
            for h in b['ledger_after_freeze']:
                print(f"    他本人的新交易 {h['ticker']} {h['window'][0]}：{STEP_TEXT[h['step']]}")
    c = r['common']
    print('\n== 交集')
    for key, title in (('bought', f'{span}被多人买入'), ('held', '被多人同时持有'), ('watch', '多人明天都在关注')):
        rows = c[key]
        print(f"{title}：" + ('无' if not rows else ''))
        for x in rows[:15]:
            print(f"  {x['code']} {x['industry']}：{'、'.join(x['traders'])}")
    print('持仓行业：' + '、'.join(f'{k}({v})' for k, v in c['industries_held']))
    if c['in_cash']:
        print('空仓的：' + '、'.join(c['in_cash']))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=('list', 'refresh', 'run', 'industry', 'board'))
    parser.add_argument('market', nargs='?', default='us', choices=('us', 'hk', 'cn'))
    parser.add_argument('--folder', help='dataset root holding <market>/ (default: newest refresh)')
    parser.add_argument('--days', type=int, default=1, help='trades of the last N sessions (5 = the week)')
    parser.add_argument('--traders', help='comma-separated ids (default: every trader for the market)')
    parser.add_argument('--capital', type=float, help='account size for the replicated rule book share counts')
    args = parser.parse_args(argv)
    if args.action == 'list':
        for s in all_screens():
            print(f"{s.id}: {s.name}｜{LEVEL_TEXT[s.level]}｜{'/'.join(s.markets)}｜{s.summary}")
        return
    if args.action == 'board':                      # one page with the newest daily run of every market
        out = data.SCANS / 'out'
        runs = []
        for m in ('us', 'hk', 'cn'):
            got = sorted(out.glob(f'{m}_*_{args.days}d.json'))
            if got:
                runs.append(json.loads(got[-1].read_text(encoding='utf-8')))
        md = board.render(runs)
        latest = out / 'board.md'
        dated = out / f"board_{max(r['last_day'] for r in runs)}.md"
        for path in (latest, dated):
            path.write_text(md, encoding='utf-8')
        print('看板：' + str(latest) + '（另存 ' + dated.name + '；' +
              '、'.join(f"{data.NAMES[r['market']]} {r['last_day']}" for r in runs) + '）')
        return
    if args.action == 'refresh':
        out, a = data.refresh(args.market)
        print(f"\n== {data.NAMES[args.market]} 取数 -> {out / args.market}{'' if a['finished'] else '（未完成，重跑会续传）'}\n"
              f"名单 {a['stocks']} 只，取到 {a['fetched']} 只，失败 {len(a['failed'])} 只；最新日 K {a['latest_bar']}，"
              f"落后的 {len(a['behind_latest'])} 只；日 K 中位 {a['median_bars']} 根")
        return
    folder = Path(args.folder) if args.folder else data.latest_folder(args.market)
    if folder is None or not (folder / args.market / 'universe.json').exists():
        print(f'{data.NAMES[args.market]}：没有数据，先运行 scan refresh {args.market}')
        return
    if args.action == 'industry':
        p = data.panel(folder, args.market)
        got = data.industries([str(c) for c in p['codes']], args.market, fetch=True)
        print(f"{data.NAMES[args.market]}：{sum(bool(v) for v in got.values())}/{len(got)} 只有行业")
        return
    only = set(args.traders.split(',')) if args.traders else None
    r = run(args.market, folder, args.days, only, args.capital)
    out = data.SCANS / 'out'
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{args.market}_{r['last_day']}_{args.days}d.json"
    path.write_text(json.dumps(r, indent=1, ensure_ascii=False, default=float), encoding='utf-8')
    md = out / f"board_{args.market}_{r['last_day']}_{args.days}d.md"
    md.write_text(board.render(r), encoding='utf-8')
    show(r)
    print(f'\n结果：{path}\n看板：{md}')


if __name__ == '__main__':
    main()
