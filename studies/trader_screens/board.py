"""Markdown board of one or more markets' runs (scan.run results): per trader today's buys, sells, holdings and
tomorrow's watch, plus where the traders overlap."""
from __future__ import annotations

NAMES = {'us': '美股', 'hk': '港股', 'cn': 'A 股'}
LEVEL = {'replicated': '已复刻冻结', 'draft': '按原话初版'}


def pct(x, sign=True):
    if x is None:
        return '—'
    return f'{x:+.1%}' if sign else f'{x:.0%}'


def px(x):
    if x is None:
        return '—'
    return f'{x:.2f}' if abs(x) < 1000 else f'{x:,.0f}'


def cell(x):
    return str(x).replace('|', '/').replace('\n', ' ')


def ticker(code):
    return code.split('.', 1)[1] if '.' in code else code


def stock(x):
    name = (x.get('name') or '').strip()[:14]
    return f"{ticker(x['code'])} {name}".strip()


def table(head, rows):
    if not rows:
        return []
    out = ['| ' + ' | '.join(head) + ' |', '|' + '|'.join('---:' if h in NUM else '---' for h in head) + '|']
    return out + ['| ' + ' | '.join(cell(v) for v in r) + ' |' for r in rows]


NUM = {'买价', '止损', '仓位', '价格', '相对买价', '成本 → 现价', '盈亏'}


def trader(t, days):
    span = '今天' if days == 1 else f'近 {days} 个交易日'
    a, s = t['account'], t['stance']
    acct = f"账户自 {a['since']} 起 {pct(a['ret'])}"
    if a.get('trades'):
        acct += f"，回撤 {a['maxdd']:.0%}，{a['trades']} 笔平仓，胜率 {a['win']:.0%}"
    lines = [f"#### {t['name']}（{LEVEL[t['level']]}）", '',
             f"{t['summary']}。仓位 {s['exposure']:.0%}" + (f"；{s['gate']}" if s.get('gate') else '') + f"；{acct}。", '']
    lines.append(f'**{span}买入**' + ('：无' if not t['buys'] else ''))
    if t['buys']:
        lines += [''] + table(['股票', '买点', '买价', '止损', '仓位', '行业'] + (['日期'] if days > 1 else []), [
            [stock(b), b['setup'], px(b['price']), f"{px(b['stop'])}（{(b['price'] - b['stop']) / b['price']:.1%}）",
             pct(b.get('weight'), False), b.get('industry') or ''] + ([b['day']] if days > 1 else []) for b in t['buys']])
    if t['wanted_n']:
        more = '、'.join(ticker(x['code']) for x in t['wanted']) + ('等' if t['wanted_n'] > len(t['wanted']) else '')
        lines += ['', f"另有 {t['wanted_n']} 个买点没做（每天笔数、持仓数或仓位已满）：{more}"]
    lines += ['', f'**{span}卖出**' + ('：无' if not t['sells'] else '')]
    if t['sells']:
        lines += [''] + table(['股票', '原因', '价格', '相对买价'] + (['日期'] if days > 1 else []), [
            [stock(x), x['why'] + ('' if x['full'] else '（部分）'), px(x['price']), pct(x['ret'])]
            + ([x['day']] if days > 1 else []) for x in t['sells']])
    lines += ['', f"**持仓 {len(t['holdings'])} 只**" + ('：空仓' if not t['holdings'] else '')]
    if t['holdings']:
        rows = []
        for h in t['holdings']:
            exit_ = f"止损 {px(h['stop'])}"
            if h.get('trail'):
                exit_ += f"，跟踪线 {px(h['trail'])}"
            if h.get('next_trim'):
                exit_ += f"，到 {px(h['next_trim'])} 卖 30%"
            rows.append([stock(h), h['entry_day'], f"{px(h['fill'])} → {px(h['close'])}", pct(h['ret']),
                         pct(h['weight'], False), exit_, h.get('industry') or ''])
        lines += [''] + table(['股票', '买入日', '成本 → 现价', '盈亏', '仓位', '离场线', '行业'], rows)
    if t['watch']:
        lines += ['', f"**明天关注**（{t['watch_n']} 个待触发，按强度前 {len(t['watch'])}）：" + '；'.join(
            f"{ticker(x['code'])} {x['setup']} 越过 {px(x['price'])}" for x in t['watch'])]
    if t.get('book'):
        b = t['book']
        chk = '；'.join(f"{y} 回放 {v['replay']:+.1%}（研究 {v['research']:+.1%}）" for y, v in b['check'].items())
        f = b['forward']
        fwd = (f"冻结日 {b['freeze']} 之后 {f['days']} 个交易日 {pct(f['ret'])}，回撤 {f['maxdd']:.0%}"
               if f['days'] else f"冻结日 {b['freeze']} 之后还没有数据")
        lines += ['', f'回放核对：{chk}。{fwd}。']
    lines += ['', f"<sub>账户规则：{t.get('rules', '')}</sub>", '']
    return lines


def market(r):
    days = r['days']
    span = '今天' if days == 1 else f'近 {days} 个交易日'
    st = r['state']
    state = '、'.join(f"{'站上' if st[f'above_ema{n}'] else '跌破'} {n} EMA" for n in (20, 50))
    lines = [f"## {NAMES[r['market']]} · {r['last_day']}" + (f'（近 {days} 个交易日）' if days > 1 else ''), '',
             f'股票池等权指数{state}。', '']
    lines += table(['交易员', '等级', '仓位', f'{span}买', f'{span}卖', '持仓', '市况'], [
        [t['name'], LEVEL[t['level']], pct(t['stance']['exposure'], False), len(t['buys']), len(t['sells']),
         len(t['holdings']), t['stance'].get('gate') or ''] for t in r['traders']])
    c = r['common']
    lines += ['', '### 交集', '']
    for key, title in (('bought', f'{span}被多人买入'), ('held', '被多人同时持有'), ('watch', '多人明天都在关注')):
        rows = c[key]
        if not rows:
            lines.append(f'- {title}：无')
            continue
        lines.append(f'- {title}：')
        lines += [f"  - {ticker(x['code'])}{('（' + x['industry'] + '）') if x.get('industry') else ''}："
                  f"{'、'.join(x['traders'])}" for x in rows[:12]]
    lines.append('- 持仓行业：' + ('、'.join(f'{k} {v}' for k, v in c['industries_held'][:8]) or '无持仓'))
    if c['in_cash']:
        lines.append('- 空仓：' + '、'.join(c['in_cash']))
    lines += ['', '### 各交易员', '']
    for t in r['traders']:
        lines += trader(t, days)
    return lines


def render(results):
    results = results if isinstance(results, list) else [results]
    dates = '、'.join(f"{NAMES[r['market']]} {r['last_day']}" for r in results)
    lines = ['# 交易员看板', '',
             f'数据：{dates}。假设这几位交易员此刻在这个市场里交易：每人按自己的规则和仓位限制，今天买了什么、卖了什么、'
             '手里拿着什么。', '',
             '> 这是规则此刻会怎么做，不是投资建议或订单。Martin Luk 是按他真实交易逼近、冻结的系统，研究数字全是样本内；'
             '其余几位是按档案里本人公开的规则写的初版，账户规则里有研究者取值，没有对照过他们的真实交易，也没有检验过收益。'
             '按日 K 近似：他们多在盘中按开盘区间入场，这里用越过触发价或收盘代替。', '']
    for r in results:
        lines += market(r)
    return '\n'.join(lines).rstrip() + '\n'
