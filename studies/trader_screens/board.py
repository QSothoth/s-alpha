"""Markdown board of one or more markets' runs (scan.run results), kept short: per market one overview row per
trader (today's trades inline), the overlaps that exist, and holdings with their exit levels only for traders that
hold or traded; each system's rules once at the end."""
from __future__ import annotations

NAMES = {'us': '美股', 'hk': '港股', 'cn': 'A 股'}
STATUS = {'frozen': '已冻结', 'research': '研究中', 'baseline': 'B 级基线'}
KIND = {'n1': '收盘买入', 'hi52': '52 周新高', 'brk52': '52 周突破', 'ep': 'EP', 'fine': '精选突破', 'pb': '均线回踩',
        'pop': 'Wedge Pop', 'cross': 'EMA Crossback', 'vcp': 'VCP', 'vcp_mm': 'VCP', 'ib2': '内包突破',
        'ur': '收回 20 EMA', 'brk': '收紧突破', 'pp': 'Power Play', '加码': '加码'}
LINE = {'e9': 'EMA9', 'e21': 'EMA21', 'e50': 'EMA50', 'w9': '周 EMA9'}
WHY = {'跌破止损': '止损', '跳空跌破止损': '跳空止损', '收盘跌破跟踪线': '破跟踪线', '按 R 分批': '分批',
       '到期分批': '到期分批', '信号分批': '分批', '当天止损': '当天止损', '涨破止损回补': '止损',
       '跳空涨破止损回补': '跳空止损', '收盘站上跟踪线回补': '站上跟踪线', '按 R 回补一部分': '分批',
       '当天止损回补': '当天止损', '持有到期回补': '到期', '到达目标线回补': '到目标线',
       'day_trim': '第 N 天盈利回补'}           # a short's day partial (the runner passes the engine's name through)
STAGE = {'open': '开盘', 'intraday': '盘中', 'close': '收盘'}
SIGNAL = {'atr50x8': '高出 50 日线 8 ATR', 'ext10_30': '高出 10 日线 30%'}
SHORT_KIND = {'Z1': '首次反抽 50 EMA', 'Z2': '反抽下行均线', 'Z5': '收紧后跌破前低', 'Z6': '前领涨股反抽 9 EMA',
              'Z8': '高开到 21 EMA 被拒'}


def kind(setup):
    """Setup label; a short setup 's_<name>' reads 空·<label>."""
    if setup.startswith('s_'):
        return '空·' + SHORT_KIND.get(setup[2:], setup[2:])
    return KIND.get(setup, setup)


def pct(x, sign=True):
    if x is None:
        return '—'
    out = f'{x:+.0%}' if sign else f'{x:.0%}'
    return '0%' if out in ('+0%', '-0%') else out


def px(x):
    if x is None:
        return '—'
    return f'{x:.2f}' if abs(x) < 1000 else f'{x:,.0f}'


def ticker(code):
    return code.split('.', 1)[1] if '.' in code else code


def stock(x):
    name = (x.get('name') or '').strip()[:10]
    return f"{ticker(x['code'])} {name}".strip()


def line_name(key):
    if key in LINE:
        return LINE[key]
    return f"{key[3:]} 日线" if key.startswith('sma') else f"{key[3:]} EMA" if key.startswith('ema') else key


def when(n, days):
    left = n - days
    return '明天' if left == 1 else f'{left}天后' if left > 1 else '已到'


def exit_text(h):
    """Next session's exit plan, short: stop · trail · next partial · breakeven · day partial · signal partial ·
    holding limit · add, every rule the engine manages the position with.  A short covers above its stop ("涨破 X
    回补") and on a close above its trail line.  Line values are today's: tomorrow's close line moves with tomorrow."""
    if h.get('side', 1) < 0:
        parts = [f"涨破 {px(h['stop'])} 回补"]
        if h.get('trail_name') and h.get('trail') is not None:
            parts.append(f"收盘站上 {line_name(h['trail_name'])} {px(h['trail'])} 回补")
        if h.get('next_trim') is not None:
            parts.append(f"{px(h['next_trim'])} 回补{h['trim_frac']:.0%}")
        if h.get('breakeven') is not None:
            parts.append(f"跌到 {px(h['breakeven'])} 止损移到成本")
        if h.get('next_target') is not None:
            parts.append(f"跌到 {line_name(h['target_name'])} {px(h['next_target'])} 回补")
        if h.get('short_trim_day_pending'):
            parts.append(f"第{h['short_trim_day']}天收盘盈利回补{h['short_trim_day_frac']:.0%}"
                         f"（{when(h['short_trim_day'], h['days'])}）")
        if h.get('max_days'):
            parts.append(f"第{h['max_days']}天收盘回补（{when(h['max_days'], h['days'])}）")
        return ' · '.join(parts)
    parts = [f"止损 {px(h['stop'])}"]
    if h.get('trail_name') and h.get('trail') is not None:
        parts.append(f"破 {line_name(h['trail_name'])} {px(h['trail'])}")
    if h.get('next_trim') is not None:
        parts.append(f"{px(h['next_trim'])} 卖{h['trim_frac']:.0%}")
    if h.get('breakeven') is not None:
        parts.append(f"到 {px(h['breakeven'])} 止损移到成本")
    if h.get('trim_signal'):
        parts.append(f"收盘{SIGNAL.get(h['trim_signal'], h['trim_signal'])}卖{h['trim_signal_frac']:.0%}")
    if h.get('day_trim_pending'):
        left = h['trim_day'] - h['days']
        parts.append(f"第{h['trim_day']}天{'盈利' if h.get('trim_day_profit') else ''}卖{h['trim_day_frac']:.0%}"
                     f"（{'明天' if left == 1 else f'{left}天后' if left > 1 else '已到'}）")
    if h.get('max_days'):
        parts.append(f"第{h['max_days']}天收盘卖（{when(h['max_days'], h['days'])}）")
    if h.get('next_add') is not None:
        parts.append(f"{px(h['next_add'])} 加码")
    if h.get('tradable') is False:
        parts.append(f"今天无报价，按 {h.get('close_day', '')} 收盘估值")
    return ' · '.join(parts)


def gate_text(t):
    return '无过滤' if t['gate_today'] is None else ('可开新仓' if t['gate_today'] else '不开新仓')


def today_text(t):
    out = []
    for word, key, side in (('买', 'buys', 1), ('卖', 'sells', 1), ('卖空', 'buys', -1), ('回补', 'sells', -1)):
        names = [ticker(x['code']) for x in t[key] if (x.get('side', 1) > 0) == (side > 0)]
        if names:
            out.append(f"{word} {'、'.join(names)}")
    return '；'.join(out) or '—'


def stage(x):
    """'（盘中）' for an execution that happened before the close (the board's default is the close)."""
    s = x.get('stage', 'close')
    return '' if s == 'close' else f"（{STAGE.get(s, s)}）"


def table(head, rows, right=()):
    if not rows:
        return []
    out = ['| ' + ' | '.join(head) + ' |', '|' + '|'.join('---:' if h in right else '---' for h in head) + '|']
    return out + ['| ' + ' | '.join(str(v).replace('|', '/') for v in r) + ' |' for r in rows]


def trader(t, days):
    lines = [f"**{t['name']}**" + ('' if days == 1 else f'（近 {days} 个交易日）')]
    for b in t['buys']:
        short = b.get('side', 1) < 0
        stop = (f"，涨破 {px(b['stop'])} 回补" if short else f"，止损 {px(b['stop'])}") if b['stop'] else ''
        lines.append(f"- {'卖空' if short else '买'}{stage(b)} {stock(b)}：{kind(b['setup'])}，{px(b['price'])}{stop}，"
                     f"仓位 {pct(b['weight'], False)}" + (f"（{b['day']}）" if days > 1 else ''))
    for s in t['sells']:
        short = s.get('side', 1) < 0
        lines.append(f"- {'回补' if short else '卖'}{stage(s)} {stock(s)}：{WHY.get(s['why'], s['why'])}"
                     f"{'' if s['full'] else '一部分'}，{px(s['price'])}，{pct(s['ret'])}"
                     + (f"（{s['day']}）" if days > 1 else ''))
    if t['wanted_n']:
        lines.append(f"- 另有 {t['wanted_n']} 个买点没做：" + '、'.join(
            ticker(x['code']) + ('（涨停买不到）' if x.get('limit_up') else '') for x in t['wanted'][:5])
                     + ('等' if t['wanted_n'] > 5 else ''))
    if t['holdings']:
        lines += [''] + table(['持仓', '方向', '开仓日', '盈亏', '仓位', '明天的离场线'], [
            [stock(h), '空' if h.get('side', 1) < 0 else '多', h['entry_day'][5:], pct(h['ret']),
             pct(h['weight'], False), exit_text(h)]
            for h in sorted(t['holdings'], key=lambda h: -h['weight'])], right=('盈亏', '仓位'))
    return lines + ['']


def orders(r):
    """The orders of a provisional run (scan run --provisional): today's close-time buys and sells are the closing
    orders; what the replay already filled earlier in the day (shorts at the open or a level, stops, R partials) is
    listed apart as done in the simulation, not as an order still to place."""
    p = r['provisional']
    lines = [f"**盘中临时**：{p['now'][11:16]} 的快照当作今天的收盘算出（{p['snapshot_names']} 只有报价），不是收盘后的正式结果；"
             f"信号价沿用登记系统的模拟成交价，快照价是当前报价；收盘后用 `scan diff` 对照。", '']
    rows, done = [], []
    for t in r['traders']:
        for b in t['buys']:
            short = b.get('side', 1) < 0
            act = '卖空' if short else ('加码' if b['setup'] == '加码' else '买')
            note = '涨停，收盘买不到，跳过' if b.get('limit_up') else kind(b['setup'])
            row = [t['name'], act, stock(b), px(b['price']), px(b.get('snapshot_price')),
                   (('涨破 ' if short else '') + px(b['stop'])) if b['stop'] else '—', pct(b['weight'], False), note]
            (rows if b.get('stage', 'close') == 'close' else done).append(row)
        for s in t['sells']:
            short = s.get('side', 1) < 0
            row = [t['name'], '回补' if short else '卖', stock(s), px(s['price']), px(s.get('snapshot_price')), '—',
                   '全部' if s['full'] else '一部分', WHY.get(s['why'], s['why'])]
            (rows if s.get('stage', 'close') == 'close' else done).append(row)
    head = ['交易员', '操作', '股票', '信号价', '快照价', '止损', '仓位', '说明']
    lines += table(head, rows, right=('信号价', '快照价')) or ['尾盘没有单子。']
    if done:
        lines += ['', '今天盘中已在模拟里成交（开盘或盘中价位，不是尾盘要下的单）：', ''] + table(head, done,
                                                                         right=('信号价', '快照价'))
    return lines + ['']


def confidence(r):
    """The I3 columns of a provisional run: every order the scenario reruns found, with its chance to stand at the
    close (p) and how far it is from triggering; p >= p_hi to order, p_lo <= p < p_hi to watch."""
    c = r.get('confidence')
    if not c:
        return []
    if c.get('skipped'):
        return [f"**盘中置信度**：{c['skipped']}。", '']
    th = c['thresholds']
    names = {t['id']: t['name'] for t in r['traders']}
    lines = [f"**盘中置信度**（{c['hhmm']}，已过交易时间 {c['t']:.0%}）：p 是这笔单子到收盘仍成立的估计概率；"
             f"p ≥ {th['p_hi']:.2f} 进“下单”，{th['p_lo']:.2f}–{th['p_hi']:.2f} 进“观察”"
             f"（阈值在训练段按下单栏精确率 ≥ 80% 定，所有时点共用；`notes/INTRADAY_I3_PREREG_CN.md`）。", '']
    for col, title in (('order', '下单'), ('watch', '观察')):
        rows = []
        for x in c['rows']:
            if x['column'] != col:
                continue
            short = x['side'] < 0
            if x['kind'] == 'buy':
                act = '加码' if x['add'] else ('卖空' if short else '买')
                what = '涨停，收盘买不到' if x.get('limit_up') else kind(x['setup'] or '')
            else:
                act = '回补' if short else '卖'
                what = WHY.get(x['setup'], x['setup'])
            rows.append([names.get(x['trader'], x['trader']), act, stock(x), px(x['price']), f"{x['p']:.2f}", what,
                         x['distance'], '有' if x.get('direct') else '—'])
        lines.append(f'{title}（{len(rows)}）：')
        lines += table(['交易员', '操作', '股票', '快照价', 'p', '说明', '离触发 / 失效', '直接跑'], rows,
                       right=('快照价', 'p')) or ['无。']
        lines.append('')
    return lines


def market(r):
    days = r['days']
    st = r['state']
    state = '、'.join(f"{'站上' if st[f'above_ema{n}'] else '跌破'} {n} EMA" for n in (20, 50))
    lines = [f"## {NAMES[r['market']]} · {r['last_day']}", '', f'股票池等权指数{state}。', '']
    if r['market'] == 'cn':
        lines += ['> A 股仅供观察：收盘涨停买不到之后，七个系统在 A 股都不成立（研究区间全段为负或低于同池随机入场，'
                  '`studies/trader_screens/reports/STRATEGY_REVIEW_20261025_FIXES_CN.md`），不作下单依据。', '']
    if r.get('provisional'):
        lines = lines[:1] + [''] + orders(r) + confidence(r) + lines[1:]
    lines += table(['交易员', '版本', '仓位', '市况', '账户', '冻结后', '今天' if days == 1 else f'近 {days} 天'], [
        [t['name'], f"{t['version']}（{STATUS[t['status']]}）", pct(t['account']['exposure'], False), gate_text(t),
         f"{pct(t['account']['ret'])} / 回撤 {pct(t['account']['maxdd'], False)}",
         pct(t['forward']['ret']) if t['forward']['days'] else '—', today_text(t)] for t in r['traders']],
        right=('仓位',))
    c = r['common']
    window = '' if days == 1 else f'近 {days} 天内'
    both = [(key, title, c[key]) for key, title in (('bought', f'{window}多人买入'), ('held', '多人持有'),
                                                     ('shorted', f'{window}多人卖空'), ('held_short', '多人做空'))
            if c.get(key)]

    def who(key, x):
        if days == 1 or key.startswith('held'):
            return '、'.join(x['traders'])
        return '；'.join(f"{n} {'、'.join(d[5:] for d in ds)}" for n, ds in x.get('days', {}).items()) + \
            (f"；同日：{'、'.join(x['same_day'])}" if x.get('same_day') else '；不是同一天')
    if both:
        lines.append('')
        lines += [f"{title}：" + '；'.join(f"{ticker(x['code'])}（{who(key, x)}）" for x in rows[:8])
                  for key, title, rows in both]
    active = [t for t in r['traders'] if t['buys'] or t['sells'] or t['holdings']]
    if active:
        lines.append('')
        for t in active:
            lines += trader(t, days)
    bad = [t['name'] for t in r['traders'] if (t.get('check') or {}).get('status') == 'failed']
    if bad:
        lines.append(f"**回放到冻结日与比对表不一致：{'、'.join(bad)}**")
        lines.append('')
    return lines


def render(results):
    results = results if isinstance(results, list) else [results]
    lines = ['# 交易员看板' + ('（盘中临时）' if any(r.get('provisional') for r in results) else ''), '',
             '> 各交易员按研究里登记的系统（与横向比对表同一版本）从 2024-01-02 回放到最新收盘。多头买入和跟踪线离场按收盘价；'
             '卖空（开盘或反抽到价位）、跳空止损、盘中止损和按 R 分批发生在盘中，表里标了（开盘）（盘中）。'
             '离场线是下一交易日的计划：盘中破止损即卖，收盘破跟踪线即卖；均线值是今天的，明天收盘时的线会变。'
             '冻结日 2026-10-16 之前全是样本内。不是投资建议或订单。', '']
    for r in results:
        lines += market(r)
    status = [((t.get('check') or {}).get('status') or 'missing', t['name'], r['market']) for r in results
              for t in r['traders']]
    missing = [f"{NAMES[m]} {n}" for s, n, m in status if s == 'missing']
    if status and all(s == 'passed' for s, _, _ in status):
        lines += ['回放核对：到冻结日的分年收益与比对表（同配置、同代码）全部一致。', '']
    elif missing:
        lines += [f"回放核对：{'、'.join(missing)} 没有同配置、同代码的比对表参考，未核对。", '']
    seen, rules = set(), []
    for r in results:
        for t in r['traders']:
            if t['id'] in seen:
                continue
            seen.add(t['id'])
            s = t['strategy']
            rules.append(f"- **{t['name']} {t['version']}**：{s['选股与形态']}｜{s['入场与止损']}｜{s['离场']}｜{s['仓位与市况']}")
    lines += ['---', '', '<details><summary>各系统规则</summary>', ''] + rules + ['', '</details>']
    return '\n'.join(lines).rstrip() + '\n'
