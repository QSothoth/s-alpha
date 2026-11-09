"""Validate and render a trader profile without changing its configuration.

Metadata can live beside a value (source/date), in the parent's sources/dates
maps, or in config.profile_meta keyed by dotted path. An unavailable item must
be an object with status, reason, source and date. State cards are keyed by
behaviour_card.by_state[year][state]; state names can be declared in
regime.states or inferred from those cards.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path

# These are workflow columns, not trader-specific targets.
MEASURES = {
    'goal': ('目标逐条对照', '每轮对照用户目标'),
    'hard_lines': ('底线判定', '必须满足'),
    'accept': ('各线接受判定', '按该线条件判定'),
    'checkpoint': ('检查点判定', '触发即停止'),
    'datasets': ('数据集核对', '只读登记数据'),
    'bar': ('版本总表 v0', '底线参照'),
    'base': ('版本总表 v1', '底座'),
    'capital': ('档位与杠杆对照', '硬上限及可优化范围'),
    'regime': ('开关与分状态表', '原话、上限和日历'),
    'selection_years': ('选择年判定', '只用于选择'),
    'holdout': ('留出年结果', '不用于选择'),
    'legs': ('峰前持有/段数', '冻结评测口径'),
    'win': ('胜率', '按有出处的行为容差对照'),
    'payoff': ('盈亏比', '按有出处的行为容差对照'),
    'n': ('笔数', '按有出处的行为容差对照'),
    'days': ('持有天数', '按有出处的行为容差对照'),
    'return': ('收益', '按有出处的账户目标对照'),
    'side': ('多空比例', '按有出处的行为容差对照'),
    'setup': ('买点形态构成', '按有出处的行为容差对照'),
    'turnover_percentile': ('成交额分位', '按有出处的行为容差对照'),
    'adr_percentile': ('ADR 分位', '按有出处的行为容差对照'),
}

SECTIONS = ('goal', 'hard_lines', 'accept', 'checkpoint', 'datasets', 'bar', 'base',
            'capital', 'regime', 'selection_years', 'holdout', 'legs')
BEHAVIOUR = ('win', 'payoff', 'n', 'days', 'return', 'side', 'setup',
             'turnover_percentile', 'adr_percentile')
REGIME_FIELDS = ('enabled', 'words', 'max_states', 'max_switches',
                 'max_overrides_per_line_state', 'calendar')
UNAVAILABLE = ('不适用', '证据弱，按原话')


def _present(value):
    if isinstance(value, dict):
        metadata = {'source', 'date', 'status', 'reason', 'set_by', 'draft', 'sources', 'dates'}
        return any(_present(v) for k, v in value.items() if k not in metadata)
    if isinstance(value, (list, tuple)):
        return any(_present(v) for v in value)
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def _date(value):
    try:
        date.fromisoformat(str(value))
        return True
    except (TypeError, ValueError):
        return False


def _metadata(config, path, item, parent=None):
    all_meta = config.get('profile_meta') if isinstance(config.get('profile_meta'), dict) else {}
    found = all_meta.get(path, {})
    meta = dict(found) if isinstance(found, dict) else {}
    if isinstance(parent, dict):
        key = path.rsplit('.', 1)[-1]
        sources = parent.get('sources') if isinstance(parent.get('sources'), dict) else {}
        dates = parent.get('dates') if isinstance(parent.get('dates'), dict) else {}
        if sources.get(key):
            meta.setdefault('source', sources[key])
        if dates.get(key):
            meta.setdefault('date', dates[key])
        for field in ('source', 'date'):
            if parent.get(field):
                meta.setdefault(field, parent[field])
        if parent.get('set_by'):
            meta.setdefault('source', parent['set_by'])
        if path.startswith('datasets.') and _date(parent.get('approved_by_user')):
            meta.setdefault('source', '用户确认数据集')
            meta.setdefault('date', parent['approved_by_user'])
    if isinstance(item, dict):
        for field in ('source', 'date', 'status', 'reason'):
            if item.get(field):
                meta[field] = item[field]
        if item.get('set_by'):
            meta.setdefault('source', item['set_by'])
        if path == 'datasets' and _date(item.get('approved_by_user')):
            meta.setdefault('source', '用户确认数据集')
            meta.setdefault('date', item['approved_by_user'])
    return meta


def inspect(config):
    """Return rows and precise missing requirements; never read external drafts."""
    rows, errors = [], []

    def add(path, value, category, parent=None):
        meta = _metadata(config, path, value, parent)
        display = value.get('value') if isinstance(value, dict) and 'value' in value else value
        status = meta.get('status') or (display if isinstance(display, str) and display in UNAVAILABLE else None)
        if status in UNAVAILABLE:
            if not meta.get('reason'):
                errors.append(f'{path}: {status} 缺理由')
        elif not _present(display):
            errors.append(f'{path}: 缺值')
        if status == '草稿' or (isinstance(value, dict) and value.get('draft') is True):
            errors.append(f'{path}: 草稿未确认')
        if not _present(meta.get('source')):
            errors.append(f'{path}: 缺来源')
        if not _date(meta.get('date')):
            errors.append(f'{path}: 缺有效来源日期（YYYY-MM-DD）')
        measure, constraint = MEASURES.get(category, ('', ''))
        if not measure:
            errors.append(f'{path}: 缺衡量列')
        rows.append(dict(path=path, value=display, source=meta.get('source'), date=meta.get('date'),
                         status=status, draft=isinstance(value, dict) and value.get('draft') is True,
                         reason=meta.get('reason'), measure=measure, constraint=constraint))

    for key in SECTIONS:
        value = config.get(key)
        if key == 'goal' and isinstance(value, list) and value:
            for i, item in enumerate(value):
                add(f'goal.{i}', item.get('quote') if isinstance(item, dict) else item, key, item)
        else:
            add(key, value, key)
    datasets = config.get('datasets')
    if isinstance(datasets, dict) and datasets.get('status') not in UNAVAILABLE:
        items = datasets.get('items')
        if not isinstance(items, list) or not items:
            errors.append('datasets.items: 缺数据集清单')
        else:
            for i, item in enumerate(items):
                add(f'datasets.items.{i}', item, 'datasets', datasets)
                for field in ('name', 'path', 'schema'):
                    if not isinstance(item, dict) or not _present(item.get(field)):
                        errors.append(f'datasets.items.{i}.{field}: 缺值')
    capital = config.get('capital')
    if isinstance(capital, dict) and capital.get('status') not in UNAVAILABLE:
        for field in ('profiles', 'acceptance_profile', 'definition', 'optimizable'):
            add(f'capital.{field}', capital.get(field), 'capital', capital)
    regime = config.get('regime') if isinstance(config.get('regime'), dict) else {}
    if regime and regime.get('status') not in UNAVAILABLE:
        for key in REGIME_FIELDS:
            if regime.get('enabled') is False and key != 'enabled':
                continue
            add(f'regime.{key}', regime.get(key), 'regime', regime)
        for i, word in enumerate(regime.get('words', []) if isinstance(regime.get('words'), list) else []):
            add(f'regime.words.{i}', word.get('text') if isinstance(word, dict) else word, 'regime', word)
        calendar = regime.get('calendar')
        if isinstance(calendar, dict) and calendar.get('status') in ('待重判', 'candidate', 'draft', '草稿'):
            errors.append('regime.calendar: 日历待重判或未冻结')

    card = config.get('behaviour_card')
    if not isinstance(card, dict) or not card:
        add('behaviour_card', None, 'win')
        return rows, errors
    selection = config.get('selection_years')
    if isinstance(selection, dict):
        selection = selection.get('value')
    years = list(selection) if isinstance(selection, list) else ([selection] if isinstance(selection, (str, int)) else [])
    holdout = config.get('holdout')
    if isinstance(holdout, list):
        years.extend(holdout)
    elif isinstance(holdout, (str, int)):
        years.append(holdout)
    elif isinstance(holdout, dict):
        years.extend(holdout.get('years', []))
        if holdout.get('year') is not None:
            years.append(holdout['year'])
        elif isinstance(holdout.get('value'), list):
            years.extend(holdout['value'])
        elif isinstance(holdout.get('value'), (str, int)) and holdout['value'] not in UNAVAILABLE:
            years.append(holdout['value'])
    years = list(dict.fromkeys(map(str, years)))
    if not years:
        errors.append('behaviour_card: 缺可核对的年份')
    for year in years:
        annual = card.get(year) if isinstance(card.get(year), dict) else {}
        for field in BEHAVIOUR:
            add(f'behaviour_card.{year}.{field}', annual.get(field), field, annual)
    if regime.get('enabled') is not False:
        by_state = card.get('by_state')
        if not isinstance(by_state, dict) or not by_state:
            add('behaviour_card.by_state', None, 'side')
        else:
            calendar = regime.get('calendar') if isinstance(regime.get('calendar'), dict) else {}
            declared = regime.get('states') or calendar.get('states') or []
            if isinstance(declared, dict):
                declared = list(declared)
            states = set(map(str, declared))
            for groups in by_state.values():
                if isinstance(groups, dict):
                    states.update(groups)
            if not states:
                add('behaviour_card.by_state.states', None, 'side')
            for year in years:
                groups = by_state.get(year, {})
                for state in sorted(states):
                    group = groups.get(state, {}) if isinstance(groups, dict) else {}
                    group = group if isinstance(group, dict) else {}
                    for field in BEHAVIOUR:
                        add(f'behaviour_card.by_state.{year}.{state}.{field}', group.get(field), field, group)
    return rows, errors


def _text(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    return str(value if value is not None else '缺失').replace('|', '\\|').replace('\n', '<br>')


def _summary(path, value):
    if path == 'datasets' and isinstance(value, dict):
        items = value.get('items') if isinstance(value.get('items'), list) else []
        names = [str(x.get('name', '未命名')) for x in items if isinstance(x, dict)]
        return f"{len(names)} 个数据集：{'、'.join(names)}；具体 schema、路径及校验值见配置"
    if path.startswith('datasets.items.') and isinstance(value, dict):
        schema = value.get('schema') if isinstance(value.get('schema'), dict) else {}
        files = schema.get('files') if isinstance(schema.get('files'), dict) else {}
        return (f"{value.get('name', '缺名称')}；路径 {value.get('path', '缺失')}；"
                f"{len(files)} 个登记文件，完整 schema 和校验值见配置")
    if path == 'capital' and isinstance(value, dict):
        profiles = value.get('profiles') if isinstance(value.get('profiles'), dict) else {}
        def percentage(item):
            return f'{item:.0%}' if isinstance(item, (int, float)) else '无' if item is None else str(item)
        parts = [f"{name}：开仓上限 {item.get('initial')} 倍，维持线 {percentage(item.get('maintenance'))}，"
                 f"融资利率 {percentage(item.get('margin_rate'))}"
                 for name, item in profiles.items() if isinstance(item, dict)]
        return '；'.join(parts + [f"验收档 {value.get('acceptance_profile', '缺失')}",
                                  value.get('definition', ''), value.get('optimizable', '')])
    if path == 'regime' and isinstance(value, dict):
        cal = value.get('calendar') or {}
        name = cal.get('version', '缺失') if isinstance(cal, dict) else cal
        return f"{'启用' if value.get('enabled') else '不启用'}；{value.get('why', '')}；日历 {name}；原话及上限见下列各项"
    if path == 'regime.words' and isinstance(value, list):
        return '；'.join(str(x.get('text', x)) if isinstance(x, dict) else str(x) for x in value)
    names = {'annual_return_min': '每年最低收益', 'max_win': '胜率上限', 'min_closed': '最少平仓笔数',
             'min_entries_per_year': '每年最少开仓笔数', 'behaviour_tolerance': '行为容差',
             'max_log_return_gap': '收益对数差上限', 'min_agreement': '最小重合率',
             'min_extra_legs': '多覆盖段数', 'max_unlimited_mean_new_names': '每晚新名单上限',
             'max_unique_growth': '不同股票数增长上限', 'default_rounds': '默认轮数',
             'no_progress_rounds': '连续无进步轮数', 'review_failures': '审查失败次数',
             'selection': '选股', 'trading': '交易', 'conversion': '衔接', 'merge': '合并',
             'regime': '行情', 'version': '版本', 'name': '名称', 'note': '说明',
             'year': '年份', 'label': '标记', 'independent': '独立样本外', 'path': '路径',
             'sha256': 'SHA256', 'initial': '开仓上限', 'maintenance': '维持线',
             'margin_rate': '融资利率', 'date': '日期', 'status': '状态'}

    def plain(item):
        if isinstance(item, dict):
            return '；'.join(f'{names.get(k, k)}：{plain(v)}' for k, v in item.items())
        if isinstance(item, list):
            return '、'.join(plain(v) for v in item)
        if isinstance(item, bool):
            return '是' if item else '否'
        return '未提供' if item is None else str(item)

    return plain(value)


def _label(path):
    names = {'goal': '目标', 'hard_lines': '硬底线', 'accept': '接受条件', 'checkpoint': '检查点',
             'datasets': '数据白名单', 'items': '数据集', 'bar': '底线', 'base': '底座',
             'capital': '资金', 'profiles': '资金档位', 'acceptance_profile': '验收档',
             'definition': '杠杆及追保时点', 'optimizable': '可优化范围', 'regime': '行情',
             'enabled': '是否随行情调整', 'words': '原话', 'max_states': '状态数上限',
             'max_switches': '开关数上限', 'max_overrides_per_line_state': '每线每状态修正上限',
             'calendar': '行情日历', 'selection_years': '选择年', 'holdout': '留出年', 'legs': '段表',
             'behaviour_card': '行为画像', 'by_state': '分状态', 'win': '胜率', 'payoff': '盈亏比',
             'n': '笔数', 'days': '持有天数', 'return': '收益', 'side': '多空比例',
             'setup': '买点形态', 'turnover_percentile': '成交额分位', 'adr_percentile': 'ADR分位'}
    return ' / '.join(names.get(part, part) for part in path.split('.')) + f'（{path}）'


def render(config, path):
    rows, errors = inspect(config)
    lines = ['# 交易员档案', '', '由配置生成；草稿未确认或缺项时不能作为完整档案。', '',
             '| 档案项 | 内容 | 来源和日期 | 怎么约束 | 怎么衡量 |', '|---|---|---|---|---|']
    for row in rows:
        value = _summary(row['path'], row['value'])
        if row['status'] in UNAVAILABLE:
            value = f"{row['status']}：{row['reason'] or '缺理由'}"
        if row['status'] == '草稿' or row['draft']:
            value = f'草稿：{_text(value)}'
        source = f"{_text(row['source'])}；{_text(row['date'])}"
        lines.append('| ' + ' | '.join(map(_text, (_label(row['path']), value, source, row['constraint'], row['measure']))) + ' |')
    lines += ['', f'核对：{len(errors)} 处缺项。', '']
    if errors:
        lines.extend(f'- {_text(error)}' for error in errors)
        lines.append('')
    Path(path).write_text('\n'.join(lines), encoding='utf-8')
    return errors


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('command', choices=('check', 'render'))
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    if args.command == 'check':
        _, errors = inspect(config)
        print('\n'.join(errors) if errors else '档案完整')
        return 1 if errors else 0
    output = args.config.resolve().parent / 'PROFILE_CN.md'
    errors = render(config, output)
    print(f'{output}（{len(errors)} 处缺项）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
