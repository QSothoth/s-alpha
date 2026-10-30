"""Auditable cross-stock comparisons of existing rule accounts, not trading signals."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

from . import focus

ROOT = Path(__file__).resolve().parents[2]
PHASES = ('hold', 'open', 'add', 'reduce', 'exit')
PHASE_LABELS = {
    'hold': {1: '持多', -1: '持空'}, 'open': {1: '开多', -1: '开空'},
    'add': {1: '加多', -1: '加空'}, 'reduce': {1: '减多', -1: '减空'},
    'exit': {1: '平多', -1: '平空'},
}
RULES = (
    '每组至少两位不同交易员、两只不同股票；同一交易员重复出现只计一人。期权、未执行和涨停跳过不参与。',
    '持仓、新开、加仓、减仓、平仓及多空分别统计。动作共性要求同一交易日；平空属于退出空头。',
    '行业与概念沿用本地已有 OpenD 标签；缺失不猜测，缓存未记录标签生效日，不代表历史时点分类。',
    '量能用前20个完整交易日均量作分母；盘中只读原始累计量，不使用情形推演量，不判定缩量。',
    '价格接近高点指达到前252日最高价的95%；20日强弱、流动性按同市场有效池分位计算。',
    '高波动指前20日日均振幅≥4%；集中仓位指单只占其所属账户≥20%；窄止损为距离≤3%。',
    '形态是账本记录的入场形态；仓位不跨账户相加，止损距离只读既有止损，不改变离场规则。',
    '分歧优先、当日动作优先，再按不同交易员数与股票数排序；完全相同的参与明细合并标签。'
    '首页按行业、概念、交易状态、风险特征依次各选一组，缺项由其余组补足，最多四组。',
)


def records(run):
    for trader in run['traders']:
        weights = defaultdict(float)
        for row in trader.get('holdings', []):
            if not row.get('option') and _number(row.get('weight')):
                weights[(row['code'], focus.side(row))] += row['weight']
        for key in ('holdings', 'buys', 'sells'):
            for row in trader.get(key, []):
                if row.get('option') or row.get('limit_up'):
                    continue
                phase = ('hold' if key == 'holdings' else
                         ('add' if row.get('setup') == '加码' else 'open') if key == 'buys' else
                         'exit' if row.get('full', True) else 'reduce')
                if phase == 'hold':
                    row = dict(row, weight=weights[(row['code'], focus.side(row))])
                yield dict(trader_id=trader['id'], trader_name=trader['name'], code=row['code'],
                           name=row.get('name', ''), side=focus.side(row), phase=phase,
                           day=run['last_day'] if phase == 'hold' else row.get('day', run['last_day']), row=row)


def attach(run, features=None):
    """Persist only scalar metrics for displayed stocks plus existing label provenance."""
    rows = list(records(run))
    codes = sorted({r['code'] for r in rows})
    sources = []

    def cached(relative):
        path = ROOT / relative
        if not path.exists():
            return {}
        content = path.read_bytes()
        sources.append(dict(path=relative, sha256=hashlib.sha256(content).hexdigest()))
        return json.loads(content)

    market = run['market']
    industries = cached('data/martin-luk-cache/industry.json') if market == 'us' else {}
    industries.update(cached(f'data/trader-screens/cache/industry_{market}.json'))
    concepts = cached('data/martin-luk-cache/concepts.json') if market == 'us' else {}
    for r in rows:
        if r['row'].get('industry'):
            industries[r['code']] = r['row']['industry']
    if features is not None and features['asof'] != run['last_day']:
        raise ValueError('aggregation metrics must match the report date')
    features = features or dict(asof=run['last_day'], basis='unavailable', stocks={}, background={})
    metadata = {code: dict(industry=industries.get(code) or '', concepts=concepts.get(code, []),
                           concepts_known=code in concepts) for code in codes}
    context = dict(features, version=1, stocks={c: features['stocks'][c] for c in codes if c in features['stocks']},
                   metadata=metadata, taxonomy_sources=sources,
                   coverage=dict(total=len(codes), industry=sum(bool(v['industry']) for v in metadata.values()),
                                 concepts=sum(bool(v['concepts']) for v in metadata.values()),
                                 concepts_known=sum(v['concepts_known'] for v in metadata.values())))
    run.setdefault('presentation', {})['aggregation'] = context
    return context


def _number(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def _facts(member, context):
    row, code, phase = member['row'], member['code'], member['phase']
    meta = context['metadata'].get(code, {})
    if meta.get('industry'):
        yield ('行业', meta['industry'], '本地已有 OpenD 行业标签', '')
    for name in sorted(set(meta.get('concepts', []))):
        yield ('概念', name, '本地已有 OpenD 概念标签', '')
    setup = row.get('setup')
    if setup and phase in ('hold', 'open'):
        from .board import kind
        yield ('入场形态', kind(setup), '账本记录的入场形态，持仓不代表今天再次触发', '')
    if member['day'] == context['asof']:
        stock = context['stocks'].get(code, {})
        values = stock.get('metrics', {})
        for key in stock.get('tags', []):
            rule = context['background'][key]
            metric = ('rvol20' if key.startswith('volume_') else 'return20' if key in ('strong', 'weak') else
                      'high_ratio' if key == 'near_high' else 'adr20' if key == 'volatile' else 'turnover20')
            value = values[metric]
            fact = (f'{value:.2f}倍' if metric == 'rvol20' else f'{value / 1e6:.1f}百万本币/日'
                    if metric == 'turnover20' else f'{value:.1%}')
            yield (rule['dimension'], rule['label'], rule['definition'], fact)
    if phase in ('hold', 'open', 'add'):
        weight = row.get('weight')
        if _number(weight) and weight >= .2:
            yield ('仓位', '单股仓位 ≥20%', '该笔股票占所属模拟账户的仓位；不跨账户相加', f'{weight:.1%}')
        price = row.get('close') if phase == 'hold' else row.get('snapshot_price') or row.get('price')
        stop = row.get('stop')
        fresh = phase != 'hold' or row.get('close_day', context['asof']) == context['asof']
        if fresh and _number(price) and price > 0 and _number(stop) and stop > 0:
            distance = member['side'] * (price - stop) / price
            if 0 <= distance <= .03:
                yield ('止损距离', '离止损 ≤3%', '当前估值/入场价到既有止损的方向距离；不含移动跟踪线', f'{distance:.1%}')


def _identity(member):
    return tuple(member[k] for k in ('trader_id', 'code', 'phase', 'side', 'day'))


def _multiple(members):
    return len({m['trader_id'] for m in members}) >= 2 and len({m['code'] for m in members}) >= 2


def _cross(left, right):
    return any(a['trader_id'] != b['trader_id'] and a['code'] != b['code'] for a in left for b in right)


def _relations(members):
    labels, conflict = [], False
    held = {s: [m for m in members if m['phase'] == 'hold' and m['side'] == s] for s in (1, -1)}
    if _cross(held[1], held[-1]):
        labels.append('组内多空并存')
        conflict = True
    for s, word in ((1, '多'), (-1, '空')):
        if _multiple(held[s]):
            labels.append('共同持' + word)
    days = sorted({m['day'] for m in members if m['phase'] != 'hold'})
    for day in days:
        for s, word in ((1, '多'), (-1, '空')):
            opens = [m for m in members if m['phase'] == 'open' and m['side'] == s and m['day'] == day]
            adds = [m for m in members if m['phase'] == 'add' and m['side'] == s and m['day'] == day]
            exits = [m for m in members if m['phase'] in ('reduce', 'exit') and m['side'] == s and m['day'] == day]
            opposite = [m for m in members if m['phase'] == 'open' and m['side'] == -s and m['day'] == day]
            for selected, label in ((opens, '共同开' + word), (adds, '共同加' + word),
                                    (exits, '共同退出' + word + '头')):
                if _multiple(selected):
                    labels.append(f'{day[5:]} {label}' if len(days) > 1 else label)
            if _cross(opens, opposite) or _cross(opens, held[-s]):
                labels.append('开仓方向不一')
                conflict = True
            if _cross(exits, held[s]):
                labels.append('退出与持有并存')
                conflict = True
            old = [m for m in held[s] if (m.get('entry_day') or day) < day]
            if _cross(opens, old):
                labels.append('新开加入老持仓')
    return list(dict.fromkeys(labels)), conflict


def groups(run):
    context = run.get('presentation', {}).get('aggregation') or attach(run)
    candidates = {}
    for member in records(run):
        for dimension, label, definition, fact in _facts(member, context):
            group = candidates.setdefault((dimension, label), dict(dimension=dimension, label=label,
                                           definition=definition, members={}))
            identity = _identity(member)
            if identity not in group['members']:
                group['members'][identity] = {k: v for k, v in member.items() if k != 'row'}
                group['members'][identity].update(entry_day=member['row'].get('entry_day'), facts=[])
            elif member['phase'] == 'hold' and member['row'].get('entry_day'):
                existing = group['members'][identity]
                existing['entry_day'] = min(existing.get('entry_day') or member['row']['entry_day'],
                                            member['row']['entry_day'])
            facts = group['members'][identity]['facts']
            if fact and fact not in facts:
                facts.append(fact)
    merged = {}
    for group in candidates.values():
        members = sorted(group['members'].values(), key=_identity)
        if not _multiple(members):
            continue
        labels, conflict = _relations(members)
        if not labels:
            continue
        key = tuple(_identity(m) for m in members)
        background = next((v for v in context['background'].values()
                           if (v['dimension'], v['label']) == (group['dimension'], group['label'])), None)
        tag = dict(dimension=group['dimension'], label=group['label'], definition=group['definition'],
                   background=background)
        if key in merged:
            merged[key]['tags'].append(tag)
            for existing, extra in zip(merged[key]['members'], members):
                existing['evidence'].append(dict(label=group['label'], values=extra['facts']))
            continue
        for m in members:
            m['evidence'] = [dict(label=group['label'], values=m.pop('facts'))]
        merged[key] = dict(market=run['market'], asof=run['last_day'], tags=[tag], labels=labels,
                           conflict=conflict, members=members,
                           trader_count=len({m['trader_id'] for m in members}),
                           stock_count=len({m['code'] for m in members}),
                           changed=any(m['phase'] != 'hold' and m['day'] == run['last_day'] for m in members))
    return sorted(merged.values(), key=lambda g: (not g['conflict'], not g['changed'], -g['trader_count'],
                  -g['stock_count'], title(g)))


def title(group):
    return ' / '.join(f"{t['dimension']}·{t['label']}" for t in group['tags'])


def highlights(groups, limit=4):
    """Keep distinct questions visible; rank within each category by the shared order."""
    chosen = []
    for dimensions in ({'行业'}, {'概念'}, {'入场形态', '量能', '价格位置', '相对强弱'},
                       {'仓位', '止损距离', '波动', '流动性'}):
        if any(any(t['dimension'] in dimensions for t in g['tags']) for g in chosen):
            continue
        first = next((g for g in groups if any(t['dimension'] in dimensions for t in g['tags'])), None)
        if first is not None:
            chosen.append(first)
    chosen.extend(g for g in groups if g not in chosen)
    return chosen[:limit]


def _sample(members, limit):
    if limit is None:
        return members
    chosen, traders, codes = [], set(), set()
    for m in members:
        if m['trader_id'] not in traders and m['code'] not in codes:
            chosen.append(m)
            traders.add(m['trader_id'])
            codes.add(m['code'])
    chosen.extend(m for m in members if m not in chosen)
    return chosen[:limit]


def lines(group, *, evidence=False, limit=None, counts=False):
    result = []
    for phase in PHASES:
        for s in (1, -1):
            selected = [m for m in group['members'] if m['phase'] == phase and m['side'] == s]
            if not selected:
                continue
            parts = []
            for m in _sample(selected, limit):
                item = f"{focus.trader_name(m['trader_name'])} {m['code'].split('.')[-1]}"
                if phase != 'hold' and m['day'] != group['asof']:
                    item = m['day'][5:] + ' ' + item
                if evidence:
                    facts = [e['label'] + ' ' + ' / '.join(e['values']) for e in m['evidence'] if e['values']]
                    if facts:
                        item += '（' + '；'.join(facts) + '）'
                parts.append(item)
            if limit and len(selected) > limit:
                parts.append(f'另{len(selected) - limit}条')
            label = PHASE_LABELS[phase][s]
            if counts:
                label += f"（{len({m['trader_id'] for m in selected})}位/{len({m['code'] for m in selected})}只）"
            result.append(label + '：' + '、'.join(parts))
    return result


def coverage_text(run):
    c = run['presentation']['aggregation']
    coverage, total = c['coverage'], c['coverage']['total']
    volume = sum('rvol20' in s.get('metrics', {}) for s in c['stocks'].values())
    text = (f'涉及 {total} 只股票；行业标签 {coverage["industry"]}/{total}，'
            f'概念标签 {coverage["concepts"]}/{total}，量能 {volume}/{total}。缺失不归类；标签沿用存量缓存。')
    if c['basis'] == 'unavailable':
        text += '原始量价特征未留存或数据摘要不一致，未补猜。'
    elif c['basis'] == 'snapshot':
        text += '量能为盘中累计量 / 前20日整日均量。'
    if run.get('early'):
        text += '持仓为中位量情形的模拟结果；新动作仅取5情形均成立的信号。'
    return text
