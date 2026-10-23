"""The traders' board (skills/trader-screens): every registered trader system (studies/trader_replication/systems.py)
run on one market up to the newest finished session, what each bought and sold that day, what it holds with its
exit levels, and where the traders overlap.

Each trader is exactly the system the research compares (same configuration, engine and account rules, replayed from
2024-01-02 with studies/trader_replication/runner.py), on the live data (studies/trader_data, filled first) or, with
--mode frozen, on the frozen release.  The replay up to the freeze day is checked against the comparison report.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.trader_screens.scan list
    $PY -m studies.trader_screens.scan refresh us                  # fill the live data to the newest session
    $PY -m studies.trader_screens.scan run us                      # today's board (live; fills first)
    $PY -m studies.trader_screens.scan run us --days 5             # the week's trades
    $PY -m studies.trader_screens.scan run us --mode frozen        # on the frozen release (to 2026-10-16)
    $PY -m studies.trader_screens.scan industry us                 # fill missing OpenD industry names
    $PY -m studies.trader_screens.scan board                       # newest run of every market -> board.md
    $PY -m studies.trader_screens.scan run us --provisional        # during the session, ~10 min before the close
    $PY -m studies.trader_screens.scan diff us 2026-10-21          # after the close: provisional vs official

``run`` writes data/trader-screens/out/<market>_<day>_<n>d.json and board_<market>_<day>_<n>d.md.  Output is the
rule state, not orders.  ``run --provisional`` (intraday.py) adds today's bar from one snapshot taken during the
session, stores no data, and writes <market>_<day>_provisional_<HHMM>.json / board_<market>_<day>_provisional_<HHMM>.md;
``diff`` compares it with the official run of that day.
"""
from __future__ import annotations

import argparse
import json
import time
import warnings
from collections import Counter, defaultdict
from contextlib import nullcontext

import numpy as np

from . import board, data, screens as S

WANTED_N = 8


def pool_index(F):
    """The existing pool equal-weight index, computed one row at a time."""
    def f():
        pool = F.rank_pool
        returns = np.zeros(len(F.c))
        with np.errstate(invalid='ignore', divide='ignore'):
            for t in range(1, len(F.c)):
                prev = F.c[t - 1]
                row = np.where(pool[t] & np.isfinite(prev), F.c[t] / prev - 1, np.nan)
                if np.any(~np.isnan(row)):
                    returns[t] = np.nanmean(row)
        return np.cumprod(1 + np.nan_to_num(returns))
    return F.get('pool_index', f)


def index_above(F, n):
    """Pool equal-weight index closing above its EMA(n), as of each day's close."""
    def f():
        idx = pool_index(F)[:, None]
        return (idx > S.ema(idx, n))[:, 0]
    return F.get(('index_above', n), f)


def overlaps(traders, inds):
    """Names several traders bought (held) the same day, longs and shorts apart."""
    def multi(key, side=1):
        who = defaultdict(list)
        for t in traders:
            for x in t[key]:
                if (x.get('side', 1) > 0) != (side > 0):
                    continue
                if t['name'] not in who[x['code']]:
                    who[x['code']].append(t['name'])
        rows = [dict(code=c, traders=v, industry=inds.get(c, '')) for c, v in who.items() if len(v) >= 2]
        return sorted(rows, key=lambda x: (-len(x['traders']), x['code']))
    held = Counter(inds.get(h['code'], '') or '未知' for t in traders for h in t['holdings'])
    return dict(bought=multi('buys'), held=multi('holdings'), shorted=multi('buys', -1),
                held_short=multi('holdings', -1), industries_held=held.most_common(10),
                in_cash=[t['name'] for t in traders if not t['holdings']])


def run(market, mode='live', days=1, only=None, panel=None, seconds=None):
    """The board of one market: every registered system through the runner on the given data mode; `panel` (the
    provisional panel of intraday.py) is used instead of the dataset's and shared by every system; `seconds`
    (a dict) receives each system's run time."""
    from studies import trader_data as TD
    from studies.trader_replication import runner, systems as SY
    warnings.simplefilter('ignore', RuntimeWarning)
    np.seterr(invalid='ignore', divide='ignore')
    from . import intraday
    ds = TD.dataset(market, mode)
    p = ds.panel() if panel is None else panel
    F = S.Feat(p, market)
    state = {f'above_ema{n}': bool(index_above(F, n)[-1]) for n in (20, 50)}
    last, digest, codes = str(p['days'][-1]), p['digest'], [str(c) for c in p['codes']]
    nm = ds.names()
    capped = set()
    if market == 'cn':
        with np.errstate(invalid='ignore', divide='ignore'):
            prev = p['close'][-2] * p['raw_close'][-1] / p['close'][-1]
        capped = {code for j, code in enumerate(codes)
                  if intraday.at_limit_up(code, nm.get(code, ''), p['raw_close'][-1, j], prev[j], last)}
    tail_days, tail_close = p['days'][-61:].copy(), p['close'][-61:].copy()
    market_curve = runner.bounded_history(p['days'], pool_index(F), last)
    del p, F
    traders = []
    with intraday.shared(panel, market) if panel is not None else nullcontext():
        for x in SY.all_():
            if only and x.id not in only:
                continue
            t0 = time.perf_counter()
            t = runner.run(x, market, mode, days)
            if seconds is not None:
                seconds[x.id] = round(time.perf_counter() - t0, 2)
            if t['last_day'] != last:
                raise RuntimeError(f"{x.id}: replay ends {t['last_day']}, data {last}")
            t['wanted_n'] = len(t['wanted'])
            t['wanted'] = t['wanted'][:WANTED_N]
            traders.append(t)
    inds = data.industries(codes, market)
    signal_codes = set()
    for t in traders:
        for key in ('buys', 'sells', 'holdings', 'wanted'):
            for y in t[key]:
                y['name'], y['industry'] = nm.get(y['code'], ''), inds.get(y['code'], '')
                if key == 'buys' and y.get('day') == last and y.get('side', 1) > 0 and y['code'] in capped:
                    y['limit_up'] = True
                signal_codes.add(y['code'])
    columns = {code: j for j, code in enumerate(codes)}
    stocks = {}
    for code in sorted(signal_codes):
        history = (runner.bounded_history(tail_days, tail_close[:, columns[code]], last)
                   if code in columns else dict(days=[], values=[]))
        name, industry = nm.get(code, ''), inds.get(code, '')
        description = f'{name}，所属行业为{industry}。' if name and industry else ''
        stocks[code] = dict(history, description=description)
    return dict(market=market, mode=mode, data=ds.id, digest=digest, last_day=last, days=days, names=len(codes),
                state=state, traders=traders, common=overlaps(traders, inds),
                presentation=dict(window=60, market_curve=market_curve, stocks=stocks))


def pct(x):
    return '—' if x is None else f'{x:+.1%}'


def px(x):
    return '—' if x is None else (f'{x:.2f}' if abs(x) < 1000 else f'{x:.0f}')


def show(r):
    st = r['state']
    span = '今天' if r['days'] == 1 else f"近 {r['days']} 个交易日"
    print(f"\n== {data.NAMES[r['market']]} {r['last_day']} 交易员看板（{r['mode']}）；股票池等权指数"
          f"{'站上' if st['above_ema20'] else '跌破'} 20 EMA、{'站上' if st['above_ema50'] else '跌破'} 50 EMA")
    for t in r['traders']:
        a = t['account']
        gate = '' if t['gate_today'] is None else ('；今天市况允许开新仓' if t['gate_today'] else '；今天市况不许开新仓')
        print(f"\n[{t['name']}｜{t['label']}] 仓位 {a['exposure']:.0%}{gate}；账户自 {a['since']} 起 {pct(a['ret'])}，"
              f"回撤 {a['maxdd']:.0%}，{a['trades']} 笔平仓" + (f"、胜率 {a['win']:.0%}" if a['win'] is not None else ''))
        if 'check' in t:
            print(f"  回放核对（到冻结日 {t['freeze']}）：{'一致' if t['check']['ok'] else '不一致'}")
        f = t['forward']
        if f['days']:
            print(f"  冻结日之后 {f['days']} 个交易日：{pct(f['ret'])}，回撤 {f['maxdd']:.0%}，新开 {f['trades']} 笔")
        print(f"  {span}买入：" + ('无' if not t['buys'] else ''))
        for b in t['buys']:
            short = b.get('side', 1) < 0
            stop = (f" 涨破 {px(b['stop'])} 回补（{(b['stop'] - b['price']) / b['price']:.1%}）" if short else
                    f" 止损 {px(b['stop'])}（{(b['price'] - b['stop']) / b['price']:.1%}）") if b['stop'] else ''
            print(f"    {b['code']} {b['name'][:10]} {b['setup']} {'卖空' if short else '买'} {px(b['price'])}{stop} "
                  f"仓位 {b['weight']:.0%} {b['industry']}" + ('｜涨停，收盘买不到，跳过' if b.get('limit_up') else ''))
        if t['wanted_n']:
            print(f"  另有 {t['wanted_n']} 个买点没做：" + '、'.join(x['code'] for x in t['wanted']))
        print(f"  {span}卖出：" + ('无' if not t['sells'] else ''))
        for x in t['sells']:
            print(f"    {x['code']} {x['name'][:10]} {board.WHY.get(x['why'], x['why'])}{'' if x['full'] else '（部分）'} {px(x['price'])}，"
                  f"{'空单盈亏' if x.get('side', 1) < 0 else '相对买价'} {pct(x['ret'])}")
        print(f"  持仓 {len(t['holdings'])} 只：" + ('空仓' if not t['holdings'] else ''))
        for h in t['holdings']:
            print(f"    {h['code']} {h['name'][:10]} {h['entry_day']} {'卖空' if h.get('side', 1) < 0 else '买'} "
                  f"{px(h['fill'])} → {px(h['close'])}"
                  f"（{pct(h['ret'])}）仓位 {h['weight']:.0%}，" + board.exit_text(h) + f" {h['industry']}")
    c = r['common']
    print('\n== 交集')
    for key, title in (('bought', f'{span}被多人买入'), ('held', '被多人同时持有'), ('shorted', f'{span}被多人卖空'),
                       ('held_short', '被多人同时做空')):
        rows = c.get(key, [])
        print(f"{title}：" + ('无' if not rows else ''))
        for x in rows[:15]:
            print(f"  {x['code']} {x['industry']}：{'、'.join(x['traders'])}")
    print('持仓行业：' + '、'.join(f'{k}({v})' for k, v in c['industries_held']))
    if c['in_cash']:
        print('空仓的：' + '、'.join(c['in_cash']))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=('list', 'refresh', 'run', 'industry', 'board', 'diff'))
    parser.add_argument('market', nargs='?', default='us', choices=('us', 'hk', 'cn'))
    parser.add_argument('day', nargs='?', help='diff: the session (ISO date)')
    parser.add_argument('--provisional', action='store_true',
                        help='run: during the session, today from one snapshot (stores no data; intraday.py)')
    parser.add_argument('--at', help='diff: the provisional run HHMM (default: the latest of the day)')
    parser.add_argument('--mode', choices=('live', 'frozen'), default='live',
                        help='live (default): the release continued to the newest finished session; frozen: the '
                             'release only')
    parser.add_argument('--days', type=int, default=1, help='trades of the last N sessions (5 = the week)')
    parser.add_argument('--traders', help='comma-separated ids (default: every registered trader)')
    args = parser.parse_args(argv)
    if args.provisional and (args.action != 'run' or args.mode != 'live' or args.days != 1):
        parser.error('--provisional requires run, --mode live and --days 1')
    from studies import trader_data as TD
    if args.action == 'list':
        from studies.trader_replication import systems as SY
        for x in SY.all_():
            print(f"{x.id}: {x.name}｜{x.label}｜冻结日 {x.freeze}")
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
    if args.action == 'diff':
        diff_cli(args.market, args.day, args.at)
        return
    if args.action == 'run' and args.provisional:
        provisional_cli(args.market, set(args.traders.split(',')) if args.traders else None)
        return
    freshness = None
    if args.action == 'refresh' or (args.action == 'run' and args.mode == 'live'):
        r = freshness = TD.dataset(args.market, 'live').update()
        print(f"== {data.NAMES[args.market]} 数据：原有最后一天 {r['last_before']}，补 {len(r['missing'])} 个交易日"
              f"{'（' + r['method'] + '）' if r['method'] else '（已是最新）'}，{r['rows']} 根日 K，{r['actions']} 个复权")
        if args.action == 'refresh':
            return
    if args.action == 'industry':
        p = TD.dataset(args.market, args.mode).panel()
        got = data.industries([str(c) for c in p['codes']], args.market, fetch=True)
        print(f"{data.NAMES[args.market]}：{sum(bool(v) for v in got.values())}/{len(got)} 只有行业")
        return
    only = set(args.traders.split(',')) if args.traders else None
    r = run(args.market, args.mode, args.days, only)
    if freshness is not None:
        if r['last_day'] != freshness['expected_last_day']:
            raise RuntimeError(f"{args.market}: replay ends {r['last_day']}, expected {freshness['expected_last_day']}")
        r['freshness'] = freshness
        rejected = {x['code'] for x in freshness.get('rejected_bars', [])}
        affected = sorted({x['code'] for t in r.get('traders', [])
                           for key in ('buys', 'sells', 'holdings') for x in t[key]} & rejected)
        if affected:
            raise RuntimeError(f'{args.market}: invalid prices affect positions or trades: {affected}')
    out = data.SCANS / 'out'
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{args.market}_{r['last_day']}_{args.days}d.json"
    path.write_text(json.dumps(r, indent=1, ensure_ascii=False, default=float), encoding='utf-8')
    md = out / f"board_{args.market}_{r['last_day']}_{args.days}d.md"
    md.write_text(board.render(r), encoding='utf-8')
    show(r)
    print(f'\n结果：{path}\n看板：{md}')


def with_confidence(market, mode, days, only, panel=None, seconds=None):
    """run() on the provisional panel, plus the I3 confidence columns (confidence.live) when the validated model
    is present and was judged worth using (reports/confidence_model.json meta.integrate)."""
    from studies import trader_data as TD
    from studies.trader_replication import systems as SY
    from . import confidence as CF, intraday
    r = run(market, mode, days, only, panel=panel, seconds=seconds)
    if not CF.MODEL_PATH.exists():
        return r
    model = CF.load_model()
    if not model[4].get('integrate'):
        return r
    t0 = time.perf_counter()
    hhmm = intraday.market_now(market).strftime('%H:%M')
    systems = [x for x in SY.all_() if not only or x.id in only]
    try:
        c = CF.live(panel, market, hhmm, model, systems=systems)
    except Exception as e:                          # the direct board stands on its own
        c = dict(skipped=f'置信度没有算出（{type(e).__name__}: {e}）', hhmm=hhmm)
    if c.get('rows') is not None:
        direct = {(t['id'], b['code'], b.get('side', 1), b['setup'] == '加码') for t in r['traders'] for b in t['buys']}
        direct |= {(t['id'], s['code'], s.get('side', 1)) for t in r['traders'] for s in t['sells']}
        nm = TD.dataset(market, mode).names()
        d = len(panel['days']) - 1
        col = {str(x): j for j, x in enumerate(panel['codes'])}
        for x in c['rows']:
            key = (x['trader'], x['code'], x['side'], x['add']) if x['kind'] == 'buy' else \
                (x['trader'], x['code'], x['side'])
            x['direct'], x['name'] = key in direct, nm.get(x['code'], '')
            j = col.get(x['code'])
            if market == 'cn' and x['kind'] == 'buy' and x['side'] > 0 and j is not None:
                x['limit_up'] = intraday.at_limit_up(x['code'], x['name'], float(panel['raw_close'][d, j]),
                                                     float(panel['raw_close'][d - 1, j]), r['last_day'])
    c['seconds'] = round(time.perf_counter() - t0, 2)
    r['confidence'] = c
    return r


def provisional_cli(market, only=None):
    from . import intraday
    t0 = time.perf_counter()
    print(f'== {data.NAMES[market]} 盘中临时看板（只取一次快照，不写数据）')
    try:
        r = intraday.run(market, only=only, board=with_confidence)
    except intraday.Refused as e:
        raise SystemExit(f'拒绝运行：{e}')
    p = r['provisional']
    print('  各系统耗时：' + '，'.join(f'{k} {v:.1f}' for k, v in p['system_seconds'].items()) + ' 秒')
    out = data.SCANS / 'out'
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{market}_{r['last_day']}_provisional_{p['hhmm']}"
    path = out / f'{stem}.json'
    md = out / f'board_{stem}.md'
    p['stages']['total'] = round(time.perf_counter() - t0, 2)
    path.write_text(json.dumps(r, indent=1, ensure_ascii=False, default=float), encoding='utf-8')
    md.write_text(board.render(r), encoding='utf-8')
    show(r)
    c = r.get('confidence')
    if c:
        print('\n== 盘中置信度' + (f"：{c['skipped']}" if c.get('skipped') else
                                    f"（{c['hhmm']}，{c['seconds']:.0f} 秒）"))
        for x in (c.get('rows') or []):
            if x['column']:
                print(f"  {'下单' if x['column'] == 'order' else '观察'} p={x['p']:.2f} {x['trader']} {x['kind']} "
                      f"{x['code']} {'空' if x['side'] < 0 else '多'} {x['setup']}｜{x['distance']}"
                      f"{'｜直接跑有' if x.get('direct') else ''}")
    print(f"\n合计 {p['stages']['total']:.0f} 秒；结果：{path}\n看板：{md}")


def diff_cli(market, day, at=None):
    from . import intraday
    if not day:
        raise SystemExit('diff 需要日期：scan diff us 2026-10-21')
    out = data.SCANS / 'out'
    provs = sorted(out.glob(f'{market}_{day}_provisional_{at or "????"}.json'))
    official = out / f'{market}_{day}_1d.json'
    if not provs or not official.exists():
        raise SystemExit(f'缺少 {market} {day} 的盘中临时结果或收盘后的正式结果（先 run --provisional，收盘后 run）')
    prov = json.loads(provs[-1].read_text(encoding='utf-8'))
    off = json.loads(official.read_text(encoding='utf-8'))
    d = intraday.diff(prov, off)
    text = intraday.diff_text(d, prov, off)
    stem = provs[-1].stem.replace('_provisional_', '_diff_')
    (out / f'{stem}.json').write_text(json.dumps(d, indent=1, ensure_ascii=False, default=float), encoding='utf-8')
    (out / f'{stem}.md').write_text(text, encoding='utf-8')
    print(text + f'\n结果：{out / (stem + ".md")}')


if __name__ == '__main__':
    main()
