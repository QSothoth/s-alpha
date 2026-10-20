"""Side-by-side comparison of every replicated trader's carried configuration on the common data layer (panels):
the same panels, window, costs, engine, placebo and benchmark for everybody, each run through the engineering gate.
Writes studies/trader_replication/reports/compare.json and COMPARISON_CN.md; the numbers are for a person to judge.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.trader_replication.compare run [us,hk,cn] [trader ...]   # one process, one run at a time
    $PY -m studies.trader_replication.compare render
"""
from __future__ import annotations

import gc
import json
import sys
import time
from pathlib import Path

import numpy as np

from . import gate as G, panels, study, system as Y

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / 'reports'
MARKETS = ('us', 'hk', 'cn')
DRAWS = 100
SUFFIX = '' if panels.TAG == panels.DEFAULT else '_' + panels.TAG.replace('trader-data-', '')   # e.g. _v2
FLOORS = {'us': (5.0, 20e6), 'hk': (1.0, 50e6), 'cn': (3.0, 200e6)}   # common benchmark pool: price, 20-day turnover


def traders():
    """name -> (study, configuration, version label): the registered systems (systems.py)."""
    from . import systems
    return {x.id: (x.study, x.config, x.label) for x in systems.all_()}


def ew_bench(A, seg):
    """Equal-weight daily-rebalanced holding of the market's common liquid pool, pool as of the day before."""
    price, turnover = FLOORS[A['market']]
    with np.errstate(invalid='ignore'):
        pool = (A['raw'] >= price) & (A['to20'] >= turnover)
    return study.ew_hold(A, pool, seg, lagged=True)


SOURCES = ('studies/trader_replication/*.py', 'studies/trader_data/*.py', 'studies/christian_flanders/replicate.py',
           'studies/clement_ang/replicate.py', 'studies/qullamaggie/replicate.py', 'studies/oliver_kell/replicate.py',
           'studies/mark_minervini/replicate.py', 'studies/martin_luk/replicate.py', 'studies/martin_luk/luk.py',
           'studies/martin_luk/selection.py', 'studies/trader_screens/screens.py', 'studies/trader_screens/data.py',
           'studies/trend_breakout/panel.py')


def code_digest():
    """SHA-256 over the source files a comparison run executes (works on uncommitted code too)."""
    import hashlib
    h = hashlib.sha256()
    for pat in SOURCES:
        for f in sorted(ROOT.glob(pat)):
            h.update(f.relative_to(ROOT).as_posix().encode())
            h.update(f.read_bytes())
    return h.hexdigest()


def config_digest(cfg):
    import hashlib
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()


def exact_ledger(st, A, tr):
    """His exact-dated longs inside the window: all of them, those on our panel (ticker and day found), and those
    the system actually bought; the rest are listed with the reason."""
    from . import fidelity as F
    inside = [t for t in st.trades() if t.side == 'long' and t.precision == 'exact'
              and panels.WINDOW[0] <= t.entry_date <= panels.WINDOW[1]]
    loc = F.locate(inside, A['days'], A['codes'], prefix=study.PREFIX.get(A['market'], ''), has=A['has'])[0]
    found = {x[0].id for x in loc}
    return dict(all=len(inside), on_panel=len(loc), bought=study.bought(A, tr, loc),
                missing=sorted({t.ticker for t in inside if t.id not in found}))


def metrics(curve, days, tr, entries, d0, d1):
    """The comparison's own definitions (one place, the same for everybody):
    total / by_year   equity at the last close (open positions valued there, not liquidated) over 1
    cagr              (1 + total) ** (365.25 / calendar days from the first to the last trading day) - 1
    maxdd             largest fall from the running peak, the starting equity 1 included
    trade statistics  closed trades only ('end' rows are positions still open at the last close: open_at_end)
    win / avg         ret = trade cash result / initial position value; win is ret > 0
    payoff            avg win / -avg loss of closed trades
    hold days         sessions from the entry close to the exit (entry day 0)
    pnl_top10         share of the gross profit (positive pnl, open positions valued) made by the top tenth of all
                      trades by pnl: the account's concentration
    stop_width        median initial stop distance of all trades
    entry_weight      first fill value / equity at the previous close (adds not included)
    open_mean         positions held at each close, averaged over the window's sessions
    candidates_day    median entries offered to the engine per window session (before the engine's daily cap)"""
    from datetime import date
    n = len(curve)
    cl = [t for t in tr if t['why'] != 'end']
    ret = np.array([t['ret'] for t in cl]) if cl else np.zeros(0)
    win = ret > 0
    span = (date.fromisoformat(str(days[-1])) - date.fromisoformat(str(days[0]))).days or 1
    years = span / 365.25
    peak = np.maximum.accumulate(np.concatenate([[1.0], curve]))[1:]
    by_year = {}
    for y in sorted({str(d)[:4] for d in days}):
        idx = [i for i, d in enumerate(days) if str(d)[:4] == y]
        base = curve[idx[0] - 1] if idx[0] > 0 else 1.0
        by_year[y] = float(curve[idx[-1]] / base - 1)
    di = {str(d): i for i, d in enumerate(days)}
    open_ = np.zeros(n)
    weights = []
    for t in tr:
        i0 = di[t['entry']]
        i1 = n if t['why'] == 'end' else di[t['exit']]
        open_[i0:i1] += 1
        ex = t.get('executions') or []
        if ex:
            weights.append(ex[0]['shares'] * ex[0]['price'] / (curve[i0 - 1] if i0 > 0 else 1.0))
    pnl = np.sort([t['pnl'] for t in tr])[::-1]
    gross = pnl[pnl > 0].sum()
    k = max(1, len(pnl) // 10)
    hold = lambda sel: [t['days'] for t, w in zip(cl, win) if w == sel]
    return dict(total=float(curve[-1] - 1), cagr=float(curve[-1] ** (1 / years) - 1),
                maxdd=float(np.max(1 - curve / peak)), by_year=by_year,
                trades=len(cl), open_at_end=len(tr) - len(cl), per_year=len(cl) / years,
                win=float(win.mean()) if len(ret) else None,
                avg_win=float(ret[win].mean()) if win.any() else None,
                avg_loss=float(ret[~win].mean()) if (~win).any() else None,
                payoff=float(ret[win].mean() / -ret[~win].mean()) if win.any() and (~win).any()
                and ret[~win].mean() < 0 else None,
                days_win=float(np.mean(hold(True))) if win.any() else None,
                days_loss=float(np.mean(hold(False))) if (~win).any() else None,
                median_days_win=float(np.median(hold(True))) if win.any() else None,
                pnl_top10=float(pnl[:k][pnl[:k] > 0].sum() / gross) if gross > 0 else None,
                stop_width=float(np.median([t['risk_pct'] for t in tr])) if tr else None,
                entry_weight=float(np.mean(weights)) if weights else None, open_mean=float(open_.mean()),
                candidates_day=float(np.median([len(entries[d]) for d in range(d0, d1)])))


def short_columns(st, A, cfg, tr, days, d0, d1, draws, seed):
    """Long-short columns: the run's long and short sides, and (with a short side, US only) the short-only account
    of the same system with its same-pool random-short placebo.  Without a short side: no_short; outside the US:
    not_applicable (docs/TRADER_PROTOCOL_CN.md section 5)."""
    from . import shorts as SH
    out = dict(long=SH.side_stats(tr, 1), short=SH.side_stats(tr, -1))
    if not cfg.get('short'):
        out['status'] = 'no_short'
        return out
    if A['market'] != 'us':
        out['status'] = 'not_applicable'
        return out
    out['status'] = 'long_short'
    se, rules, spool = SH.wrap(st).short_only(A, cfg)
    curve, _, trs = SH.run(SH.wrap(st), A, se, rules, spool)
    m = metrics(curve, days, trs, se, d0, d1)
    px, ema = st.px(A), st.ema_inputs(A, spool, rules)
    m['placebo'] = Y.placebo_rank(px, ema, rules, se, *panels.WINDOW, spool, draws=draws, seed=seed)
    out['short_only'] = m
    return out


def one(name, st, cfg, market, src, draws=DRAWS, seed=1):
    from studies import trader_data as TD
    if TD.resolve_mode() != 'frozen':
        raise SystemExit('comparisons run on the frozen release: unset TRADER_DATA_MODE')
    t0 = time.time()
    A = st.arrays(market)
    entries, rules, mask, pool = st.build(A, cfg)
    res, tr = st.run(A, entries, panels.WINDOW, pool, rules, placebo=0, audit=True)
    curve = res['_curve']
    px, ema = st.px(A), st.ema_inputs(A, pool, rules)
    placebo = Y.placebo_rank(px, ema, rules, entries, *panels.WINDOW, pool, draws=draws, seed=seed)
    d0 = int(np.searchsorted(A['days'], panels.WINDOW[0]))
    d1 = int(np.searchsorted(A['days'], panels.WINDOW[1], side='right'))
    days = A['days'][d0:d1]
    out = metrics(curve, days, tr, entries, d0, d1)
    years = sorted(out['by_year'])
    out.update(placebo=placebo, ew=ew_bench(A, panels.WINDOW),
               ew_by_year={y: ew_bench(A, (f'{y}-01-01', f'{y}-12-31')) for y in years})
    if market == st.home[0] and st.ledger is not None and st.ledger.exists():
        out['exact'] = exact_ledger(st, A, tr)
    out['sides'] = short_columns(st, A, cfg, tr, days, d0, d1, draws, seed)
    by_code = {}
    for t in tr:
        n, p = by_code.get(t['code'], (0, 0.0))
        by_code[t['code']] = (n + 1, p + t['pnl'])
    out['by_code'] = {c: [n, round(p, 9)] for c, (n, p) in sorted(by_code.items())}   # trades, pnl (equity units)
    pin = panels.pinned()
    span = [str(days[0]), str(days[-1])] if len(curve) == len(days) else ['?', '?']
    checks = dict(data=G.check_data(panels.TAG, A.get('digest'), span, pin['tag'], pin['markets'].get(market),
                                    panels.WINDOW, A['days']),
                  win_rate=G.check_win(tr), fills=G.check_fills(A, tr),
                  lookahead=G.check_lookahead(st, cfg, market, full=A))
    out['gate'] = G.verdict(checks)
    out['run'] = dict(source=src, config=cfg, config_digest=config_digest(cfg), data=panels.TAG,
                      data_digest=A.get('digest'), window=list(panels.WINDOW), span=span, placebo_seed=seed,
                      draws=draws, code_digest=code_digest(), numpy=np.__version__, seconds=round(time.time() - t0))
    print(name, market, f"total {out['total']:+.3f} dd {out['maxdd']:.2f} win {out['win']} rank "
          f"{out['placebo']['rank']:.2f} ew {out['ew']:+.3f} gate {out['gate']['ok']}",
          {k: v['ok'] for k, v in checks.items()}, f"{out['run']['seconds']}s", flush=True)
    del A, entries, mask, pool, tr
    gc.collect()
    return out


def run(names=None, markets=MARKETS):
    """Markets outer, traders inner.  Each trader x market record carries its own configuration, data digest, code
    digest and seed; a partial rerun merges only into records of the same configuration and code, otherwise the
    trader's other markets are dropped (rerun them) so one table never mixes versions."""
    path = OUT / f'compare{SUFFIX}.json'
    res = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    res['_meta'] = dict(data=panels.TAG, window=list(panels.WINDOW), draws=DRAWS, gate=dict(
        max_win=G.MAX_WIN, min_trades=G.MIN_TRADES, cuts=G.CUTS))
    all_ = traders()
    code = code_digest()
    for m in markets:
        for name, (st, cfg, src) in all_.items():
            if names and name not in names:
                continue
            row = res.setdefault(name, {})
            row.update(name=st.name, his=st.his, his_behaviour=st.his_behaviour)
            kept = {k: v for k, v in row.get('markets', {}).items()
                    if v.get('run', {}).get('config_digest') == config_digest(cfg)
                    and v['run'].get('code_digest') == code}
            row['markets'] = {**kept, m: one(name, st, cfg, m, src)}
            OUT.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(res, indent=1, default=float, ensure_ascii=False), encoding='utf-8')
    render(res)
    return res


def pct(x, f='{:+.0%}'):
    return '—' if x is None else f.format(x)


def num(x, f='{:.1f}'):
    return '—' if x is None else f.format(x)


def his_rows(his, hb):
    """His published numbers per year (win rate derived from wins / losses when that is what he gave)."""
    rows = []
    for y, v in (his or {}).items():
        w = v.get('win')
        if w is None and v.get('wins') is not None and v.get('losses') is not None:
            w = v['wins'] / (v['wins'] + v['losses'])
        rows.append((y, v.get('ret'), w, v.get('avg_win'), v.get('avg_loss'), v.get('days_win'), v.get('days_loss')))
    if not rows and hb:
        rows.append(('—', None, hb.get('win'), hb.get('avg_win'), hb.get('avg_loss'), hb.get('days_win'),
                     hb.get('days_loss')))
    return rows


def render(res=None):
    res = res or json.loads((OUT / f'compare{SUFFIX}.json').read_text(encoding='utf-8'))
    meta = res['_meta']
    names = [k for k in res if not k.startswith('_')]
    years = sorted({y for k in names for m in res[k]['markets'].values() for y in m['by_year']})
    L = ['# 交易员横向比对（统一数据层）', '',
         f"数据 `{meta['data']}`，评测区间 {meta['window'][0]} → {meta['window'][1]}（各市场相同，2023 年只作指标暖机），"
         f"同一引擎、成本、安慰剂（{meta['draws']} 次，种子固定）与基准。全部是样本内：各人的配置是在研究数据上逐轮选出的。"
         '由 `python -m studies.trader_replication.compare` 生成，不手改；每格结果在 compare.json 里带着自己的配置、'
         '数据摘要和代码指纹。指标定义见 `compare.metrics` 的说明。', '',
         f"门禁（工程检查，与策略无关）：读入的面板就是固定的数据集（摘要）、净值覆盖整个评测区间；截到 "
         f"{' / '.join(meta['gate']['cuts'])} 的面板与全量面板在截止日以前喂给引擎的一切（入场的全部字段与顺序、账户规则、"
         f"规则读取的数组、安慰剂股票池）相同（不看未来）；每笔都有成交记录且成交价在当日最低—最高价之间；已平仓胜率不超过 "
         f"{meta['gate']['max_win']:.0%}（不足 {meta['gate']['min_trades']} 笔记为未检查）。门禁只说明结果可以拿来评价，"
         '好坏由人对照下表和本人公开成绩判断。', '',
         '口径：收益按最后一个收盘估值（未平仓不清算）；交易统计只算已平仓，期末未平的另列；年化按日历天数；最大回撤含起始净值；'
         '“利润集中度”是盈利最多的前 10% 笔占全部盈利（按金额）；“候选 / 天”是评测区间内每天交给引擎的入场数中位（Martin 在'
         '交给引擎前已按每天笔数截断，其余人由引擎按成功开仓数限制）；等权持有不扣成本；安慰剂从各人自己的股票池（前一天收盘确定）'
         '随机换股，同一天、同样止损宽度和账户规则。', '']
    for m in MARKETS:
        if not any(m in res[k]['markets'] for k in names):
            continue
        L += [f'## {dict(us="美股", hk="港股", cn="A 股")[m]}', '']
        head = ['交易员', '配置', '门禁', '全段', '年化', '最大回撤'] + [f'{y}' for y in years] + \
               ['等权持有', '安慰剂中位 / 排位', '已平仓笔数（期末未平）', '笔数 / 年', '胜率', '平均赚 / 亏', '盈亏比',
                '赢家持有（中位天）', '利润集中度', '止损宽度中位', '单笔仓位', '同时持仓', '候选 / 天']
        L += ['| ' + ' | '.join(head) + ' |', '|' + '---|' * len(head)]
        for k in names:
            r = res[k]['markets'].get(m)
            if not r:
                continue
            g = r['gate']
            fails = [lab for c, lab in (('data', '数据'), ('lookahead', '不看未来'), ('fills', '成交价'),
                                        ('win_rate', '胜率')) if not g[c]['ok']]
            gate = ('通过' if g['ok'] else '不过：' + '、'.join(fails)) + \
                   ('（胜率未检查）' if g['win_rate'].get('status') == 'unchecked' else '')
            cells = [res[k]['name'], r['run']['source'], gate,
                     pct(r['total']), pct(r['cagr']), pct(r['maxdd'], '{:.0%}')] + \
                    [pct(r['by_year'].get(y)) for y in years] + \
                    [pct(r['ew']), f"{pct(r['placebo']['median'])} / {r['placebo']['rank']:.2f}",
                     f"{r['trades']}（{r['open_at_end']}）", num(r['per_year'], '{:.0f}'), pct(r['win'], '{:.0%}'),
                     f"{pct(r['avg_win'])} / {pct(r['avg_loss'])}", num(r['payoff']),
                     num(r['median_days_win'], '{:.0f}'), pct(r['pnl_top10'], '{:.0%}'),
                     pct(r['stop_width'], '{:.1%}'), pct(r['entry_weight'], '{:.0%}'), num(r['open_mean']),
                     num(r['candidates_day'], '{:.0f}')]
            L.append('| ' + ' | '.join(cells) + ' |')
        L.append('')
    L += ['## 多空：多空合计与只做空', '',
          '多空合计就是上表的账户（登记版本带空头时）；只做空是同一系统去掉多头、只留空单的账户，安慰剂为同池随机做空（同一天、'
          '同样止损宽度）。空头只在美股研究，港股、A 股“不适用”（港股只有指定证券能沽空、A 股融券受限）；口径见 '
          'docs/TRADER_PROTOCOL_CN.md 第 5 节。', '',
          '| 交易员 | 市场 | 配置 | 多空合计 | 合计回撤 | 多头已平仓 / 胜率 | 空头已平仓 / 胜率 | 空单盈亏 | 只做空 全段 / 回撤 | '
          '只做空 安慰剂中位 / 排位 |', '|---|---|---|---|---|---|---|---|---|---|']
    for m in MARKETS:
        for k in names:
            r = res[k]['markets'].get(m)
            if not r or 'sides' not in r:
                continue
            sd = r['sides']
            lo, sh = sd['long'], sd['short']
            status = sd.get('status')
            if status == 'long_short':
                so = sd['short_only']
                tail = [f"{pct(sh['win'], '{:.0%}')}", f"{sh['pnl']:+.2f}",
                        f"{pct(so['total'])} / {pct(so['maxdd'], '{:.0%}')}",
                        f"{pct(so['placebo']['median'])} / {so['placebo']['rank']:.2f}"]
                both = pct(r['total'])
                shorts = f"{sh['trades']} / {pct(sh['win'], '{:.0%}')}"
            else:
                word = '不做空' if status == 'no_short' else '不适用'
                both, shorts, tail = word, '—', ['—'] * 4
            L.append('| ' + ' | '.join([res[k]['name'], dict(us='美股', hk='港股', cn='A 股')[m], r['run']['source'],
                                         both, pct(r['maxdd'], '{:.0%}'),
                                         f"{lo['trades']} / {pct(lo['win'], '{:.0%}')}", shorts] + tail[1:]) + ' |')
    L += ['', '## 本人公开成绩（供对照，口径与区间可能和上表不同）', '',
          '| 交易员 | 年份 | 收益 | 胜率 | 平均赚 / 亏 | 赢家 / 输家持有天数 |', '|---|---|---|---|---|---|']
    for k in names:
        rows = his_rows(res[k]['his'], res[k]['his_behaviour']) or [('数据期内无',) + (None,) * 6]
        for y, ret, w, aw, al, dw, dl in rows:
            L.append('| ' + ' | '.join([res[k]['name'], y, pct(ret), pct(w, '{:.0%}'), f'{pct(aw)} / {pct(al)}',
                                         f'{num(dw)} / {num(dl)}']) + ' |')
    L += ['', '## 美股：他 exact 日期的交易', '',
          '| 交易员 | 区间内全部 | 数据里能找到 | 系统实际买到 | 找不到的票 |', '|---|---|---|---|---|']
    for k in names:
        e = res[k]['markets'].get('us', {}).get('exact')
        if e:
            L.append(f"| {res[k]['name']} | {e['all']} | {e['on_panel']} | {e['bought']} | "
                     f"{'、'.join(e['missing']) or '—'} |")
    L += ['', '## 策略要点（各人当前带入的配置）', '', '| 交易员 | 配置 | 选股与形态 | 入场与止损 | 离场 | 仓位与市况 |',
          '|---|---|---|---|---|---|']
    for k in names:
        from .systems import STRATEGY
        src, *parts = STRATEGY[k]
        runs = {r['run']['source'] for r in res[k]['markets'].values()}
        if runs != {src}:
            parts = ['（配置已变，要点待更新）'] * 4
        L.append('| ' + ' | '.join([res[k]['name'], '、'.join(sorted(runs))] + parts) + ' |')
    L += ['', '## 门禁明细与版本', '']
    for k in names:
        for m, r in res[k]['markets'].items():
            g = r['gate']
            bad = []
            if not g['data']['ok']:
                bad.append('数据：' + '；'.join(g['data']['why']))
            if not g['lookahead']['ok']:
                bad.append('不看未来：' + '；'.join(f"{c['cut']} {'、'.join(c['diff'])}" for c in g['lookahead']['cuts']
                                               if not c['ok']))
            if not g['fills']['ok']:
                bad.append(f"成交价：{g['fills']['n_bad']} 处问题，例 {g['fills']['bad'][:2]}")
            if not g['win_rate']['ok']:
                w = g['win_rate']
                bad.append(f"胜率 {w['win']:.1%} > {w['max_win']:.0%}（{w['trades']} 笔已平仓）" if w['win'] is not None
                           else f"胜率：{w['note']}")
            run_ = r['run']
            L.append(f"- {res[k]['name']} {m}：" + ('通过' if not bad else '；'.join(bad)) +
                     f"（配置 {run_['config_digest'][:8]}，数据 {str(run_['data_digest'])[:8]}，代码 {run_['code_digest'][:8]}，"
                     f"numpy {run_['numpy']}）")
    (OUT / f'COMPARISON{SUFFIX}_CN.md').write_text('\n'.join(L) + '\n', encoding='utf-8')


def versions(a='trader-data-v1', b='trader-data-v2'):
    """How a looser list (version b) changes each trader x market against version a: returns, trades, win rate,
    placebo, and the trades and profit on the names only b holds."""
    load = lambda t: json.loads((OUT / f"compare{'' if t == panels.DEFAULT else '_' + t.replace('trader-data-', '')}.json")
                                .read_text(encoding='utf-8'))
    ra, rb = load(a), load(b)
    lists = {t: {m: {s['code'] for s in json.loads((ROOT / 'data' / t / m / 'universe.json').read_text(
        encoding='utf-8'))['stocks']} for m in ('us', 'hk')} for t in (a, b)}
    L = [f'# 名单放宽的影响：{a} → {b}', '',
         f'{a}：美股 {len(lists[a]["us"])} 只、港股 {len(lists[a]["hk"])} 只；{b}：美股 {len(lists[b]["us"])} 只、'
         f'港股 {len(lists[b]["hk"])} 只（名单规则见 docs/DATA.md）。同一配置、区间、引擎；“新增名单上的交易”是 {b} '
         '里只有它才有的股票上的交易，盈亏按起始资金 1 计。由 `python -m studies.trader_replication.compare versions` 生成。', '']
    for m in ('us', 'hk'):
        L += [f'## {dict(us="美股", hk="港股")[m]}', '',
              '| 交易员 | 全段 a → b | 分年 a | 分年 b | 已平仓笔数 a → b | 胜率 a → b | 安慰剂排位 a → b | 门禁 a / b | '
              '新增名单上的交易（笔 / 盈亏） |', '|---|---|---|---|---|---|---|---|---|']
        new = lists[b][m] - lists[a][m]
        for k in [x for x in ra if not x.startswith('_')]:
            x, y = ra[k]['markets'].get(m), rb.get(k, {}).get('markets', {}).get(m)
            if not x or not y:
                continue
            yrs = lambda r: ' '.join(f"{pct(v)}" for _, v in sorted(r['by_year'].items()))
            add = [v for c, v in y.get('by_code', {}).items() if c in new]
            L.append('| ' + ' | '.join([
                ra[k]['name'], f"{pct(x['total'])} → {pct(y['total'])}", yrs(x), yrs(y),
                f"{x['trades']} → {y['trades']}", f"{pct(x['win'], '{:.1%}')} → {pct(y['win'], '{:.1%}')}",
                f"{x['placebo']['rank']:.2f} → {y['placebo']['rank']:.2f}",
                f"{'过' if x['gate']['ok'] else '不过'} / {'过' if y['gate']['ok'] else '不过'}",
                f"{sum(n for n, _ in add)} / {sum(p for _, p in add):+.2f}"]) + ' |')
        L.append('')
    (OUT / 'VERSIONS_CN.md').write_text('\n'.join(L) + '\n', encoding='utf-8')


if __name__ == '__main__':
    if sys.argv[1] == 'run':                     # run [us,hk,cn] [trader ...]
        args = sys.argv[2:]
        ms = tuple(args.pop(0).split(',')) if args and set(args[0].split(',')) <= set(MARKETS) else MARKETS
        run(args or None, ms)
    elif sys.argv[1] == 'render':
        render()
    elif sys.argv[1] == 'versions':                # versions [a b]
        versions(*sys.argv[2:4])
    else:
        raise SystemExit(__doc__)
