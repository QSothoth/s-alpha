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

``run`` writes data/trader-screens/out/<market>_<day>_<n>d.json and board_<market>_<day>_<n>d.md.  Output is the
rule state, not orders.
"""
from __future__ import annotations

import argparse
import json
import warnings
from collections import Counter, defaultdict

import numpy as np

from . import board, data, screens as S

WANTED_N = 8


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
    return dict(bought=multi('buys'), held=multi('holdings'), industries_held=held.most_common(10),
                in_cash=[t['name'] for t in traders if not t['holdings']])


def run(market, mode='live', days=1, only=None):
    """The board of one market: every registered system through the runner on the given data mode."""
    from studies import trader_data as TD
    from studies.trader_replication import runner, systems as SY
    warnings.simplefilter('ignore', RuntimeWarning)
    np.seterr(invalid='ignore', divide='ignore')
    ds = TD.dataset(market, mode)
    p = ds.panel()
    F = S.Feat(p, market)
    state = {f'above_ema{n}': bool(index_above(F, n)[-1]) for n in (20, 50)}
    last, digest, codes = str(p['days'][-1]), p['digest'], [str(c) for c in p['codes']]
    del p, F
    traders = []
    for x in SY.all_():
        if only and x.id not in only:
            continue
        t = runner.run(x, market, mode, days)
        if t['last_day'] != last:
            raise RuntimeError(f"{x.id}: replay ends {t['last_day']}, data {last}")
        t['wanted_n'] = len(t['wanted'])
        t['wanted'] = t['wanted'][:WANTED_N]
        traders.append(t)
    nm = ds.names()
    inds = data.industries(codes, market)
    for t in traders:
        for key in ('buys', 'sells', 'holdings', 'wanted'):
            for y in t[key]:
                y['name'], y['industry'] = nm.get(y['code'], ''), inds.get(y['code'], '')
    return dict(market=market, mode=mode, data=ds.id, digest=digest, last_day=last, days=days, names=len(codes),
                state=state, traders=traders, common=overlaps(traders, inds))


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
            stop = f" 止损 {px(b['stop'])}（{(b['price'] - b['stop']) / b['price']:.1%}）" if b['stop'] else ''
            print(f"    {b['code']} {b['name'][:10]} {b['setup']} 买 {px(b['price'])}{stop} 仓位 {b['weight']:.0%} "
                  f"{b['industry']}")
        if t['wanted_n']:
            print(f"  另有 {t['wanted_n']} 个买点没做：" + '、'.join(x['code'] for x in t['wanted']))
        print(f"  {span}卖出：" + ('无' if not t['sells'] else ''))
        for x in t['sells']:
            print(f"    {x['code']} {x['name'][:10]} {x['why']}{'' if x['full'] else '（部分）'} {px(x['price'])}，"
                  f"相对买价 {pct(x['ret'])}")
        print(f"  持仓 {len(t['holdings'])} 只：" + ('空仓' if not t['holdings'] else ''))
        for h in t['holdings']:
            print(f"    {h['code']} {h['name'][:10]} {h['entry_day']} 买 {px(h['fill'])} → {px(h['close'])}"
                  f"（{pct(h['ret'])}）仓位 {h['weight']:.0%}，" + board.exit_text(h) + f" {h['industry']}")
    c = r['common']
    print('\n== 交集')
    for key, title in (('bought', f'{span}被多人买入'), ('held', '被多人同时持有')):
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
    parser.add_argument('--mode', choices=('live', 'frozen'), default='live',
                        help='live (default): the release continued to the newest finished session; frozen: the '
                             'release only')
    parser.add_argument('--days', type=int, default=1, help='trades of the last N sessions (5 = the week)')
    parser.add_argument('--traders', help='comma-separated ids (default: every registered trader)')
    args = parser.parse_args(argv)
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
    if args.action == 'refresh' or (args.action == 'run' and args.mode == 'live'):
        r = TD.dataset(args.market, 'live').update()
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
