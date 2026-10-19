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
       '到期分批': '到期分批', '信号分批': '分批', '当天止损': '当天止损'}


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


def exit_text(h):
    """Next session's exit plan, short: stop · trail · next partial · day partial · add."""
    parts = [f"止损 {px(h['stop'])}"]
    if h.get('trail_name') and h.get('trail') is not None:
        parts.append(f"破 {line_name(h['trail_name'])} {px(h['trail'])}")
    if h.get('next_trim') is not None:
        parts.append(f"{px(h['next_trim'])} 卖{h['trim_frac']:.0%}")
    if h.get('day_trim_pending'):
        left = h['trim_day'] - h['days']
        parts.append(f"第{h['trim_day']}天{'盈利' if h.get('trim_day_profit') else ''}卖{h['trim_day_frac']:.0%}"
                     f"（{'明天' if left == 1 else f'{left}天后' if left > 1 else '已到'}）")
    if h.get('next_add') is not None:
        parts.append(f"{px(h['next_add'])} 加码")
    return ' · '.join(parts)


def gate_text(t):
    return '无过滤' if t['gate_today'] is None else ('可开新仓' if t['gate_today'] else '不开新仓')


def today_text(t):
    out = [f"买 {'、'.join(ticker(b['code']) for b in t['buys'])}"] if t['buys'] else []
    if t['sells']:
        out.append(f"卖 {'、'.join(ticker(s['code']) for s in t['sells'])}")
    return '；'.join(out) or '—'


def table(head, rows, right=()):
    if not rows:
        return []
    out = ['| ' + ' | '.join(head) + ' |', '|' + '|'.join('---:' if h in right else '---' for h in head) + '|']
    return out + ['| ' + ' | '.join(str(v).replace('|', '/') for v in r) + ' |' for r in rows]


def trader(t, days):
    lines = [f"**{t['name']}**" + ('' if days == 1 else f'（近 {days} 个交易日）')]
    for b in t['buys']:
        stop = f"，止损 {px(b['stop'])}" if b['stop'] else ''
        lines.append(f"- 买 {stock(b)}：{KIND.get(b['setup'], b['setup'])}，{px(b['price'])}{stop}，仓位 {pct(b['weight'], False)}"
                     + (f"（{b['day']}）" if days > 1 else ''))
    for s in t['sells']:
        lines.append(f"- 卖 {stock(s)}：{WHY.get(s['why'], s['why'])}{'' if s['full'] else '一部分'}，{px(s['price'])}，"
                     f"{pct(s['ret'])}" + (f"（{s['day']}）" if days > 1 else ''))
    if t['wanted_n']:
        lines.append(f"- 另有 {t['wanted_n']} 个买点没做：" + '、'.join(ticker(x['code']) for x in t['wanted'][:5])
                     + ('等' if t['wanted_n'] > 5 else ''))
    if t['holdings']:
        lines += [''] + table(['持仓', '买入日', '盈亏', '仓位', '明天的离场线'], [
            [stock(h), h['entry_day'][5:], pct(h['ret']), pct(h['weight'], False), exit_text(h)]
            for h in sorted(t['holdings'], key=lambda h: -h['weight'])], right=('盈亏', '仓位'))
    return lines + ['']


def market(r):
    days = r['days']
    st = r['state']
    state = '、'.join(f"{'站上' if st[f'above_ema{n}'] else '跌破'} {n} EMA" for n in (20, 50))
    lines = [f"## {NAMES[r['market']]} · {r['last_day']}", '', f'股票池等权指数{state}。', '']
    lines += table(['交易员', '版本', '仓位', '市况', '账户', '冻结后', '今天' if days == 1 else f'近 {days} 天'], [
        [t['name'], f"{t['version']}（{STATUS[t['status']]}）", pct(t['account']['exposure'], False), gate_text(t),
         f"{pct(t['account']['ret'])} / 回撤 {pct(t['account']['maxdd'], False)}",
         pct(t['forward']['ret']) if t['forward']['days'] else '—', today_text(t)] for t in r['traders']],
        right=('仓位',))
    c = r['common']
    both = [(title, c[key]) for key, title in (('bought', '多人买入'), ('held', '多人持有')) if c[key]]
    if both:
        lines.append('')
        lines += [f"{title}：" + '；'.join(f"{ticker(x['code'])}（{'、'.join(x['traders'])}）" for x in rows[:8])
                  for title, rows in both]
    active = [t for t in r['traders'] if t['buys'] or t['sells'] or t['holdings']]
    if active:
        lines.append('')
        for t in active:
            lines += trader(t, days)
    bad = [t['name'] for t in r['traders'] if 'check' in t and not t['check']['ok']]
    if bad:
        lines.append(f"**回放到冻结日与比对表不一致：{'、'.join(bad)}**")
        lines.append('')
    return lines


def render(results):
    results = results if isinstance(results, list) else [results]
    lines = ['# 交易员看板', '',
             '> 各交易员按研究里登记的系统（与横向比对表同一版本）从 2024-01-02 回放到最新收盘。买卖按收盘价，'
             '“今天”的买卖是收盘那一刻的操作；离场线是下一交易日的计划：盘中破止损即卖，收盘破跟踪线即卖。'
             '冻结日 2026-10-16 之前全是样本内。不是投资建议或订单。', '']
    for r in results:
        lines += market(r)
    checked = [t for r in results for t in r['traders'] if 'check' in t]
    if checked and all(t['check']['ok'] for t in checked):
        lines += ['回放核对：到冻结日的分年收益与比对表全部一致。', '']
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
