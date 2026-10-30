"""Stock-level comparisons of recorded trades and current simulated positions."""
from __future__ import annotations

from collections import defaultdict


def side(row):
    return -1 if row.get('side', 1) < 0 else 1


def action(row, opening):
    if row.get('option'):
        return '卖 Put（偏多期权）' if opening else row.get('why', '期权到期')
    if opening:
        verb = ('加空' if side(row) < 0 else '加多') if row.get('setup') == '加码' else (
            '开空' if side(row) < 0 else '开多')
        return verb + ('（涨停跳过）' if row.get('limit_up') else '')
    return ('平空' if side(row) < 0 else '平多') + ('' if row.get('full', True) else '（部分）')


def trader_name(name):
    return {'Martin Luk': 'Martin', 'Christian Flanders': 'Flanders', 'Clement Ang': 'Clement',
            'Oliver Kell': 'Kell', 'Mark Minervini': 'Minervini', 'Marios Stamatoudis': 'Marios',
            'Evan Medeiros': 'Evan', 'Alfredo Holguin': 'Holguin'}.get(name, name)


def _different(left, right):
    return bool(left and right and len(left | right) > 1)


def stock_groups(run):
    """Group by instrument and symbol, never infer holdings from trade events.

    A new-entry consensus requires different traders on the same day. Adds, skipped
    entries and short-put contracts cannot contribute to stock-entry consensus.
    """
    groups = {}
    for trader in run['traders']:
        for key in ('holdings', 'buys', 'sells'):
            for row in trader.get(key, []):
                instrument = 'put' if row.get('option') else 'stock'
                group = groups.setdefault((instrument, row['code']), dict(
                    market=run['market'], asof=run['last_day'], days=run.get('days', 1),
                    code=row['code'], instrument=instrument, name=row.get('name', ''),
                    industry=row.get('industry', ''), holdings=[], events=[]))
                group['name'] = group['name'] or row.get('name', '')
                group['industry'] = group['industry'] or row.get('industry', '')
                entry = dict(trader_id=trader['id'], trader_name=trader['name'], row=row)
                if key == 'holdings':
                    group['holdings'].append(entry)
                else:
                    group['events'].append(dict(entry, opening=key == 'buys',
                                                day=row.get('day', run['last_day'])))

    for group in groups.values():
        held = {s: {h['trader_id'] for h in group['holdings'] if side(h['row']) == s} for s in (1, -1)}
        opened = defaultdict(set)
        closed = defaultdict(set)
        exits = {s: set() for s in (1, -1)}
        for event in group['events']:
            row = event['row']
            if event['opening']:
                if row.get('setup') != '加码' and not row.get('limit_up'):
                    opened[(event['day'], side(row))].add(event['trader_id'])
            else:
                exits[side(row)].add(event['trader_id'])
                closed[(event['day'], side(row))].add(event['trader_id'])
        labels = []
        if group['instrument'] == 'stock':
            if _different(held[1], held[-1]):
                labels.append('当前多空分歧')
            if any(_different(ids, opened.get((day, -s), set())) for (day, s), ids in opened.items()):
                labels.append('同日多空新开')
            if any(_different(ids, held[-s]) for (_, s), ids in opened.items()) and '当前多空分歧' not in labels:
                labels.append('新开与反向持仓')
            if any(_different(exits[s], held[s]) for s in (1, -1)):
                labels.append('退出与持有并存')
            if any(_different(ids, {h['trader_id'] for h in group['holdings']
                                    if side(h['row']) == s and h['row'].get('entry_day', day) < day})
                   for (day, s), ids in opened.items()):
                labels.append('新开加入老持仓')
            for s, word in ((1, '多'), (-1, '空')):
                if any(len(ids) > 1 for (_, direction), ids in opened.items() if direction == s):
                    labels.append(f'同日多人开{word}')
                if len(held[s]) > 1:
                    labels.append(f'共同持{word}')
                if any(len(ids) > 1 for (_, direction), ids in closed.items() if direction == s):
                    labels.append(f'共同退出{word}头')
        group['labels'] = labels or (['期权单列'] if group['instrument'] == 'put' else ['其他信号 / 持仓'])
        group['focus'] = bool(labels)
        group['conflict'] = any(word in labels for word in ('当前多空分歧', '同日多空新开', '新开与反向持仓', '退出与持有并存'))
        group['trader_count'] = len({x['trader_id'] for x in group['holdings'] + group['events']})
        group['events'].sort(key=lambda x: (x['day'], {'open': 0, 'intraday': 1, 'close': 2}.get(
            x['row'].get('stage', 'close'), 2), not x['opening'], x['trader_id']))
    return sorted(groups.values(), key=lambda g: (g['instrument'] == 'put', not g['focus'],
                  not g['conflict'], not bool(g['events']), -g['trader_count'], g['code']))


def holding_text(group):
    parts = []
    for s, word in ((1, '持多'), (-1, '持空')):
        holders = [h for h in group['holdings'] if side(h['row']) == s]
        if not holders:
            continue
        word = '卖 Put' if group['instrument'] == 'put' else word
        parts.append(word + '：' + '、'.join(dict.fromkeys(trader_name(h['trader_name']) for h in holders)))
    return '；'.join(parts) or '当前无持仓'


def event_text(group, opening):
    parts = []
    for event in group['events']:
        if event['opening'] != opening:
            continue
        row = event['row']
        verb = action(row, opening)
        suffix = ''
        if opening and not row.get('limit_up') and group['instrument'] == 'stock' and not any(
                h['trader_id'] == event['trader_id'] and side(h['row']) == side(row) for h in group['holdings']):
            suffix = '，现已不持有'
        date = event['day'][5:] + ' ' if group['days'] > 1 else ''
        parts.append(f"{date}{trader_name(event['trader_name'])} {verb}{suffix}")
    return '；'.join(parts) or '—'


LEGEND = '开多＝买入股票；平多＝卖出多仓；开空＝卖空股票；平空＝买回股票，结束或减少空头仓位（回补）。'
READING = '当前持仓为本次模拟结束后的状态，已包含仍在持有的新开仓；新开后又退出会单独注明。多人重合仅描述规则行为。'
RULES = {
    '共同持多 / 持空': '当前至少两位不同交易员持有同一股票、同方向仓位。',
    '同日多人开多 / 开空': '至少两位交易员在同一天同方向新开仓；加仓和涨停跳过不计入。',
    '共同退出（平多 / 平空）': '至少两位不同交易员在同一天平掉或减少同方向仓位。平多、平空分开统计，多次分批只计一人。',
    '新开加入老持仓': '一位交易员新开，另一位当前仍持有，且其开仓日早于这笔新开。',
    '退出与持有并存': '一位交易员平仓或减仓，另一位当前仍持有同方向仓位。',
    '当前多空分歧': '不同交易员当前分别持多和持空。',
    '同日多空新开': '不同交易员在同一天分别新开多仓和空仓。',
    '新开与反向持仓': '一位交易员的新开方向与另一位当前持仓相反；与当前多空分歧分开标注。',
}
ORDERING = '满足任一条件进入共识与分歧。每个市场内：分歧优先、有本期动作优先、涉及的不同交易员人数由多到少，最后按股票代码排序。收益率不参与排序。'
