"""Render the version ledger and append a system after merge acceptance."""
from __future__ import annotations

import argparse
from datetime import date
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile

from studies.trader_replication import funnel
from . import adapter as D, capital, version_profile

LEDGER = D.FLOW/'versions.json'
TABLE = D.FLOW/'VERSIONS_CN.md'
DETAIL = D.OUT/'version_state_profile.json'
DRAFT = D.OUT/'profile_draft.json'
YEARS = ('2024', '2025', '2026')
PROFILES = ('L1', 'L2', 'L2.8')
FIELDS = ('peak_held', 'early_buy', 'segments', 'return', 'win', 'payoff',
          'trades', 'closed', 'days', 'max_gross', 'behaviour_within', 'behaviour_sourced')


def initial_entries():
    cfg = D.read(D.FLOW/'config.json')
    replay = D.OUT/'work/leverage_profiles'
    rows = []
    for version, name, role, system_name, components in (
        ('v0', 'master', '底线', cfg['bar'], dict(regime='B4_PCT2', selection='master', trading='master', conversion='master')),
        ('v1', cfg['base']['name'], '底座', cfg['base']['trading'], dict(regime='B4_PCT2',
            selection=cfg['base']['selection'], trading=cfg['base']['trading'], conversion=cfg['base']['conversion']))):
        runs = {profile: D.read(replay/f'{system_name}_{profile}_weakest_first.json') for profile in PROFILES}
        comparison = D.read(replay/f'{system_name}_L2.8_pro_rata.json')
        for profile, run in runs.items():
            if run['system'] != system_name or run['profile'] != profile:
                raise ValueError('replay identity mismatch')
            capital.check_rules(D.load_rules(run['rules']), cfg['capital'], profile)
        capital.check_rules(D.load_rules(comparison['rules']), cfg['capital'], 'L2.8')
        rows.append(dict(version=version, name=name, role=role, components=components,
            capital_profile=cfg['capital']['acceptance_profile'], date=cfg['base']['date'],
            source_account=cfg['systems'][system_name]['account'],
            scorecard={profile: run['annual'] for profile, run in runs.items()},
            deleverage_comparison={'L2.8': {'pro_rata': comparison['annual']}},
            replay_source=str(replay.relative_to(D.ROOT))))
    missing = {key: None for key in FIELDS}
    his = {y: dict(missing) for y in YEARS}
    his['2024'].update({'return': 2.83, 'win': 104/423, 'payoff': 15/3, 'trades': 423})
    his['2025'].update({'return': 9.698, 'win': 209/940, 'payoff': 14.12/2.08, 'trades': 940})
    his['2026'].update({'return': 8.686})
    rows.append(dict(version='本人', name='他本人', role='公开资料', components=None,
        capital_profile=None, source_account=None, date='2026-10-16', scorecard={'public': his},
        source='studies/martin_luk/notes/SOURCES.md',
        note='2026 收益截至 7 月；2024、2025 收益与笔数以出处所记原文为准。'))
    return rows


def write_initial(entries, path=LEDGER):
    path = Path(path)
    with path.open('x') as out:
        out.write('[\n'+',\n'.join(json.dumps(r, ensure_ascii=False, separators=(',', ':')) for r in entries)+'\n]\n')


def _display(value, fmt):
    return '—' if value is None else format(value, fmt)


def score_cell(row):
    segments = row['segments']
    def ratio(value):
        return '—' if value is None or segments is None else f'{value}/{segments}'
    pct_return = '—' if row['return'] is None else f"{row['return']:+.1%}"
    win = '—' if row['win'] is None else f"{row['win']:.1%}"
    payoff = _display(row['payoff'], '.2f')
    trades = '—' if row['trades'] is None else str(row['trades'])
    days = _display(row['days'], '.1f')
    gross = '—' if row['max_gross'] is None else f"{row['max_gross']:.2f}倍"
    within = ('—' if row['behaviour_within'] is None else
              f"{row['behaviour_within']}/{row['behaviour_sourced']}")
    return (f"峰前持有 {ratio(row['peak_held'])}；早买 {ratio(row['early_buy'])}<br>"
            f"收益 {pct_return}；胜率 {win}；盈亏比 {payoff}<br>"
            f"笔数 {trades}；平均持有 {days} 天<br>最高总敞口 {gross}；行为达标 {within}")


def entry_fingerprint(entry):
    data = json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(data).hexdigest()


def add_version_evidence(entries, evidence):
    """Load each version's own evidence, retaining the WF00 legacy evidence."""
    for entry in entries:
        version = entry['version']
        if not (version.startswith('v') and version[1:].isdigit()):
            continue
        paths = sorted((D.FLOW/'rounds').glob(f'*/version_profile_{version}.json'))
        if len(paths) > 1:
            raise ValueError('multiple profile evidence files for '+version)
        if not paths:
            continue
        item = D.read(paths[0])
        if (item['version'] != version or item.get('entry_sha256') != entry_fingerprint(entry)
                or not item.get('sources')):
            raise ValueError('invalid profile evidence for '+version)
        if any(D.sha(D.ROOT/name) != digest for name, digest in item['sources'].items()):
            raise ValueError('stale profile evidence for '+version)
        evidence['by_state'][version] = item['by_state']
        evidence['switches'][version] = item['switch']
        evidence.setdefault('alignment_by_version', {})[version] = item['alignment']
        evidence.setdefault('version_notes', {})[version] = item['note']
    return evidence


def render(entries, path=TABLE):
    acceptance = D.read(D.FLOW/'config.json')['capital']['acceptance_profile']
    versions = [r for r in entries if r['version'].startswith('v') and r['version'][1:].isdigit()]
    person = next(r for r in entries if r['version'] == '本人')
    lines = ['# 版本总表', '',
        f'验收统一采用 {acceptance}。2024、2025 为选择年；2026 标为留出*，但已多次查看，不是独立样本外检验。', '',
        '| 年份 | 他本人（公开资料） | ' + ' | '.join(r['version'] for r in versions) + ' |',
        '|---|---|' + '---|' * len(versions)]
    for year in YEARS:
        cells = [year + (' 留出*' if year == '2026' else ''), score_cell(person['scorecard']['public'][year])]
        cells.extend(score_cell(r['scorecard'][acceptance][year]) for r in versions)
        lines.append('| '+' | '.join(cells)+' |')
    lines += ['', '## 杠杆对照', '',
        '每格依次为年收益、收盘最高杠杆、峰前持有段数；默认先减最弱持仓。', '',
        '| 版本 | 年份 | L1 | L2 | L2.8 | L2.8 按比例减仓相对先减最弱 |',
        '|---|---|---|---|---|---|']
    def compact(row):
        return f"{row['return']:+.1%}；{row['max_gross']:.2f}倍；{row['peak_held']}/{row['segments']}"
    for entry in versions:
        for year in YEARS:
            base = entry['scorecard'][acceptance][year]
            other = entry.get('deleverage_comparison', {}).get(acceptance, {}).get('pro_rata', {}).get(year)
            difference = ('—' if other is None else
                f"收益 {(other['return']-base['return'])*100:+.2f} 个百分点；"
                f"最高杠杆 {other['max_gross']-base['max_gross']:+.2f} 倍；"
                f"峰前持有 {other['peak_held']-base['peak_held']:+d} 段；"
                f"追保 {other['margin_calls']-base['margin_calls']:+d} 次")
            cells = [entry['version'], year + (' 留出*' if year == '2026' else '')]
            cells.extend(compact(entry['scorecard'][profile][year]) for profile in PROFILES)
            lines.append('| '+' | '.join(cells+[difference])+' |')
    lines.extend(['',
        'L1 为现金档，L2 的维持线为 25%，L2.8 的维持线为 30%；杠杆为多空持仓总市值除以权益。开仓线与维持线之间不强制卖。',
        '峰前持有包括晚买；早买和峰前持有可以重叠。段按首锚点所属年份统计，含回看的跨年段；定格时排除选择年末未完成的段。',
        '收益按日历年权益计算。2026 系统账户截至 10 月 16 日，本人收益截至 7 月。胜率、盈亏比和平均持有天数只算已平仓；2024、2025 的平仓截止日为 2025 年末。系统笔数按入场年统计。',
        '最高杠杆为日终多空持仓市值合计除以权益。本人数字来自 [资料出处](../notes/SOURCES.md)，其使用档位并非从系统回放推断。缺资料时写“—”。',
        '主表行为达标项数沿用原有可量化项目；新增的证据弱画像及持有说明没有改变该项数。2025 盈亏比：config 按 14.1%/2.1% 记为 6.71，本人来源较精确的 14.12%/2.08% 为 6.79；主表本人数字与下方配置对齐判定因此不同，未改 config。',
        '', '组件：' + '；'.join(f"{r['version']}：拆账日历 {r['components']['regime']}、选股 {r['components']['selection']}、交易 {r['components']['trading']}、衔接 {r['components']['conversion']}" for r in versions) + '。',
        '', '生成：`/opt/opend-us-options/.venv/bin/python -m studies.martin_luk.workflow.versions render`。', ''])
    if Path(path) == TABLE and DETAIL.exists() and DRAFT.exists():
        evidence = add_version_evidence(entries, D.read(DETAIL))
        lines.extend(version_profile.details(entries, evidence, D.read(D.FLOW/'config.json'), D.read(DRAFT)))
    Path(path).write_text('\n'.join(lines))


def append(entry, completion, rules, ledger=LEDGER, table=TABLE):
    ledger = Path(ledger)
    lock = ledger.with_name(ledger.name+'.lock')
    with lock.open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        original = ledger.read_text()
        entries = json.loads(original)
        versions = [int(r['version'][1:]) for r in entries if r['version'].startswith('v') and r['version'][1:].isdigit()]
        if entry.get('version') != f'v{max(versions)+1}' or entry.get('role') != '合并通过':
            raise ValueError('version must be the next numbered merge-accepted system')
        decision = completion.get('decision', {})
        checks = decision.get('checks', [])
        if (decision.get('line') != 'merge' or decision.get('status') != 'accepted' or
                not checks or not all(c.get('ok') is True for c in checks)):
            raise ValueError('completion does not contain a passed merge decision')
        required = {'capital_profile', 'max_gross', 'margin_rate', 'maintenance', 'deleverage'}
        if not required <= rules.keys():
            raise ValueError('candidate rules must declare profile, gross, rate, maintenance and deleverage')
        profile = rules['capital_profile']
        capital_cfg = D.read(D.FLOW/'config.json')['capital']
        if entry.get('capital_profile') != profile or profile != capital_cfg['acceptance_profile']:
            raise ValueError('version and candidate must declare the acceptance profile')
        capital.check_rules(D.load_rules(rules), capital_cfg, profile)
        if not all(entry.get(key) for key in ('name', 'components', 'source_account', 'date', 'scorecard')):
            raise ValueError('version entry is missing required metadata')
        date.fromisoformat(entry['date'])
        if any(profile not in entry['scorecard'] or any(
                y not in entry['scorecard'][profile] or not set(FIELDS) <= entry['scorecard'][profile][y].keys()
                for y in YEARS) for profile in PROFILES):
            raise ValueError('scorecard is missing a profile, year or field')
        if not {'regime', 'selection', 'trading', 'conversion'} <= entry['components'].keys():
            raise ValueError('version entry is missing a component')
        if not original.endswith('\n]\n'):
            raise ValueError('version ledger is not in append-only format')
        updated = original[:-3]+',\n'+json.dumps(entry, ensure_ascii=False, separators=(',', ':'))+'\n]\n'
        with tempfile.NamedTemporaryFile('w', dir=ledger.parent, delete=False) as out:
            out.write(updated)
            temporary = out.name
        os.replace(temporary, ledger)
        entries.append(entry)
        render(entries, table)


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('command', choices=('render', 'append'))
    parser.add_argument('--entry')
    parser.add_argument('--completion')
    parser.add_argument('--rules')
    args = parser.parse_args()
    if args.command == 'render':
        render(D.read(LEDGER))
    else:
        if not args.entry or not args.completion or not args.rules:
            parser.error('append requires --entry, --completion and --rules')
        append(D.read(args.entry), D.read(args.completion), D.read(args.rules))


if __name__ == '__main__':
    main()
