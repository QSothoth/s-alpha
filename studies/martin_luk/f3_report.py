"""Read persisted F3 accounts, audit them and render the requested Chinese report."""
from __future__ import annotations

from collections import Counter
import csv
import difflib
from pathlib import Path
import re

import numpy as np

from . import f3_research as R
from .m1_report import COLUMNS, annual_cells, amount, pct, table, leg_cell

OUT, HOME = R.OUT, R.HOME


def baselines():
    return {n: R.read(HOME/'reports'/p/'metrics.json') for n, p in (
        ('M2A', 'm2_work/candidates/M2A'), ('M3B', 'm3_work/candidates/M3B'),
        ('M1B', 'm1_work/candidates/M1B'), ('登记master', 'm1_work/baseline/native_master'))}


def leg_accounts(refs, choice):
    result = {}
    for name, record in refs.items():
        result[name] = {g['key']: dict(g, early=g['covered'], profitable=g['pnl'] > 0)
                        for g in record['legs']}
    for name, folder in (('M2A', 'm2_work'), ('M3B', 'm3_work'), ('M1B', 'm1_work')):
        for g in R.read(HOME/'reports'/folder/'validation/continuous/metrics.json')['legs']:
            if g['year'] == '2026':
                result[name][g['key']] = dict(g, early=g['covered'], profitable=g['pnl'] > 0)
    patterns = R.read(HOME/'reports/u1_work/patterns_48.json')['legs']
    result['登记master'] = {g['key']: g['capture']['master'] for g in patterns}
    result['IE47'] = {g['key']: g['capture']['IE47_C062'] for g in patterns}
    for name in R.CANDIDATES:
        rows = R.read(OUT/'candidates'/name/'metrics.json')['legs']
        result[name] = {g['key']: dict(g, early=g['covered'], profitable=g['pnl'] > 0) for g in rows}
    if choice:
        for g in R.read(OUT/'validation/continuous/metrics.json')['legs']:
            if g['year'] == '2026':
                result[choice][g['key']] = dict(g, early=g['covered'], profitable=g['pnl'] > 0)
    return result, patterns


def diagnostics(accounts, patterns):
    folder = OUT/'features/validation'
    meta = R.read(folder/'meta.json')
    f = {n: np.load(folder/(n+'.npy'), mmap_mode='r') for n in R.FEATURES}
    A = R.M3.arrays(HOME/'reports/m1_work/validation_prepared')
    ci, di = ({str(v): i for i, v in enumerate(meta[k])} for k in ('codes', 'days'))
    nightly = []
    with (folder/'nightly.jsonl').open() as stream:
        import json
        for line in stream:
            nightly.append(json.loads(line))
    widths = {}
    for year in ('2024', '2025', '2026'):
        rows = [r for r in nightly if r['day'].startswith(year)]
        values = np.array([r['count'] for r in rows])
        widths[year] = dict(nights=len(rows), mean=float(values.mean()), median=float(np.median(values)),
            p90=float(np.quantile(values, .9)), min=int(values.min()), max=int(values.max()),
            distinct=len(set(c for r in rows for c in r['codes'])),
            fire=sum(r['fire'] for r in rows), armed_mean=float(np.mean([r['armed'] for r in rows])))
    evidence = []
    frozen = R.read(HOME/'notes/legs_frozen.json')['legs']
    for g in frozen:
        j = ci[g['code']]
        start, peak = g['first'], g['peak']
        window = slice(max(0, start-3), peak)
        active = np.flatnonzero(f['active'][window, j])+max(0, start-3)
        fires = np.flatnonzero(f['fire'][window, j])+max(0, start-3)
        early = [int(d) for d in fires if np.isfinite(f['width'][d, j])
                 and g['top']/float(A['close'][d, j])-1 >= .5*g['gain']]
        evidence.append(dict(key=g['key'], code=g['code'], year=g['first_date'][:4],
            anchor_in_list=bool(f['active'][start, j]), window_ever_in_list=bool(len(active)),
            list_nights=int(len(active)), window_nights=peak-max(0, start-3),
            first_list=meta['days'][active[0]] if len(active) else None,
            source_actions=int(len(fires)), early_source_offers=len(early),
            first_early_source=meta['days'][early[0]] if early else None,
            peers_at_anchor=float(f['peers'][start, j]),
            group_rank_at_anchor=float(f['peer_rank'][start, j]),
            accounts={n: rows.get(g['key']) for n, rows in accounts.items()}))
    categories = ['EP跳空形态', '长期强势回调再起', '新共振近似', '突破整理', '其他']
    groups = []
    for year in ('all', '2024', '2025', '2026'):
        for category in categories:
            keys = [g['key'] for g in patterns if g['pattern'] == category and (year == 'all' or g['year'] == year)]
            row = dict(year=year, pattern=category, n=len(keys), systems={})
            for name, lookup in accounts.items():
                valid = [lookup[k] for k in keys if k in lookup]
                row['systems'][name] = dict(evaluated=len(valid), n=len(keys), early=sum(g['early'] for g in valid),
                    any=sum(g['any'] for g in valid), profitable=sum(g['profitable'] for g in valid))
                if keys and not valid:
                    row['systems'][name].update(early=None, any=None, profitable=None)
            groups.append(row)
    membership = {year: dict(n=sum(g['year'] == year for g in evidence),
        anchor=sum(g['anchor_in_list'] for g in evidence if g['year'] == year),
        window=sum(g['window_ever_in_list'] for g in evidence if g['year'] == year),
        early_source=sum(g['early_source_offers'] > 0 for g in evidence if g['year'] == year))
        for year in ('2024', '2025', '2026')}
    R.write('source_diagnostics.json', dict(widths=widths, membership=membership, legs=evidence,
        scope='market features for all dates; labels only in this post-account evaluation'))
    R.write('patterns_48.json', dict(groups=groups, legs=evidence, categories=categories))
    with (OUT/'legs_48.csv').open('w', newline='') as stream:
        rows = [dict(key=g['key'], year=g['year'], anchor_in_list=g['anchor_in_list'],
            window_ever_in_list=g['window_ever_in_list'], early_source_offers=g['early_source_offers'],
            **{n: '未评' if g['accounts'][n] is None else '/'.join(str(int(g['accounts'][n][k]))
                 for k in ('early', 'any', 'profitable')) for n in accounts}) for g in evidence]
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return dict(widths=widths, membership=membership, groups=groups, evidence=evidence)


def audit():
    A = R.M3.arrays(HOME/'reports/m1_work/validation_prepared')
    di, ci = ({str(v): i for i, v in enumerate(A[n])} for n in ('days', 'codes'))
    errors, accounts, executions = [], 0, 0
    for path in sorted(OUT.rglob('trades.json')):
        accounts += 1
        for trade in R.read(path):
            for event in trade['executions']:
                d, j = di[event['time']], ci[trade['code']]
                lo, hi = float(A['low'][d, j]), float(A['high'][d, j])
                tolerance = 2*max(abs(float(np.spacing(np.float32(lo)))), abs(float(np.spacing(np.float32(hi)))))
                executions += 1
                if not lo-tolerance <= event['price'] <= hi+tolerance:
                    errors.append(dict(file=str(path), code=trade['code'], event=event, range=[lo, hi]))
        rec = R.read(path.parent/'reconciliation.json')
        assert abs(rec['error']) < 1e-9, rec
        management = R.read(path.parent/'management.json')
        assert all(r['used'] <= r['budget']+1e-12 for r in management.get('new_risk', ()))
    train = OUT/'features/train'
    full = OUT/'features/validation'
    agreement = {n: np.array_equal(np.load(train/(n+'.npy'), mmap_mode='r'),
        np.load(full/(n+'.npy'), mmap_mode='r')[:len(R.read(train/'meta.json')['days'])], equal_nan=True)
        for n in R.FEATURES}
    assert not errors and all(agreement.values()), (errors, agreement)
    caches = {folder.name: {n: R.sha(folder/(n+'.npy')) == h for n, h in R.read(folder/'meta.json')['sha256'].items()}
              for folder in (OUT/'features').iterdir() if (folder/'meta.json').exists()}
    assert all(all(row.values()) for row in caches.values()), caches
    result = dict(ok=True, accounts=accounts, executions=executions, violations=errors,
        training_features_equal_full_prefix=agreement, fifo_financing_terminal_reconciled=True,
        daily_initial_stop_budget_checked=True, feature_cache_hashes=caches)
    R.write('artifact_audit.json', result)
    return result


def completion(artifact):
    protocol = R.registry_check()
    protected = {p: R.sha(R.ROOT/p) == h for p, h in protocol['protected'].items()}
    tests = {}
    for name in ('custody', 'martin_luk', 'trader_replication'):
        path = OUT/('test_'+name+'.log')
        body = path.read_text()
        ran = re.search(r'Ran (\d+) tests? in', body)
        ok = re.search(r'^OK(?: \([^\n]+\))?$', body, re.MULTILINE)
        tests[name] = dict(ok=bool(ran and ok), count=int(ran[1]) if ran else None,
            result=ok[0] if ok else 'FAILED', log=path.name, sha256=R.sha(path))
    compat, prefix, validation = (R.read(OUT/(n+'.json')) for n in
                                 ('compatibility', 'truncation', 'validation_complete'))
    mechanism = R.read(OUT/'mechanism_audit.json')
    choice = R.read(OUT/'selection.json')['chosen']
    policy = (validation['standalone_evaluations'] == validation['continuous_evaluations'] == 1 if choice else
              validation.get('skipped') and validation['standalone_evaluations'] == validation['continuous_evaluations'] == 0)
    success = False
    if choice:
        rows = list(R.read(OUT/'candidates_train.json')[choice]['years'].values())
        rows += [r['years']['2026'] for r in R.read(OUT/'validation.json').values()]
        success = all(row['targets']['passed'] for row in rows)
    done = dict(ok=all(protected.values()) and all(t['ok'] for t in tests.values()) and compat['ok'] and
        compat['actual_serialized_bytes']['ok'] and mechanism['ok'] and prefix['ok'] and artifact['ok'] and bool(policy),
        research_completed=True, strategy_success=success,
        selected=choice, preregistration_unchanged=True, prereg_sha256=protocol['prereg_sha256'],
        source_sha256=protocol['source_sha256'], protected_unchanged=all(protected.values()), protected_checks=protected,
        endpoint_candidates=3, tests=tests, compatibility=compat, truncation=prefix, validation=validation,
        implementation_revision=R.read(OUT/'implementation_revision.json'),
        delivery_revision=R.read(OUT/'delivery_revision.json'), market_mechanism_checks=mechanism,
        artifacts=artifact, resources=dict(freeze=protocol['resources'],
            features=R.read(OUT/'features/validation/meta.json')['resources']),
        network_disabled=True, new_data=False, git_commit=False, Y2_modified=False,
        registration_changed=False, board_changed=False, independent_out_of_sample=False)
    assert done['ok'], {k: v for k, v in done.items() if v is False}
    return done


def group_cell(row):
    if row['n'] and not row['evaluated']:
        return '未评'
    text = f'{row["early"]}/{row["any"]}/{row["profitable"]}'
    return text if row['evaluated'] == row['n'] else text+f'（已评{row["evaluated"]}/{row["n"]}）'


def reasons_text(counts):
    labels = dict(filled='成交', daily_long='每日名额已用完', same_code='已持同票',
        risk_or_gross='敞口、风险或最小金额不合格', max_open='持仓格子已满',
        no_rebuy_day='当日卖后不能再买', max_open_kind='同类持仓已满', month='月度暂停')
    return '；'.join(f'{labels.get(k, k)} {v}次' for k, v in counts.items()) or '无'


def main():
    R.offline()
    artifact = audit()
    done = completion(artifact)
    selection, runs = R.read(OUT/'selection.json'), R.read(OUT/'candidates_train.json')
    choice = selection['chosen']
    refs = baselines()
    accounts, patterns = leg_accounts(refs, choice)
    diag = diagnostics(accounts, patterns)
    lines = ['# F3：长期领涨股回撤后，账户有没有重新把钱放进去', '']
    if choice:
        r = runs[choice]
        lines += [f'**按预登记选中 {choice}，复刻目标'+('全部通过。**' if done['strategy_success'] else '仍未完成，不能替换登记 master。**'), '',
            f'2024/2025 资金纯度 {pct(r["years"]["2024"]["cap_equity"])}/{pct(r["years"]["2025"]["cap_equity"])}，'
            f'毛利纯度 {pct(r["years"]["2024"]["purity_gross"])}/{pct(r["years"]["2025"]["purity_gross"])}，'
            f'两年 H {amount(r["H"])}。', '']
        validation = R.read(OUT/'validation.json')
        lines += [f'固定 2026 单开/连续当年收益为 '
            f'{pct(validation["standalone"]["years"]["2026"]["account_return"])}/'
            f'{pct(validation["continuous"]["years"]["2026"]["account_return"])}，详细资金与毛利仍按下表分别判断。', '']
    else:
        lines += ['**三个候选均未取得相对 M2A 的研究资格，本轮不选中方案，2026 账户评测为零次。** '
            '失败配置和原始结果完整保留。市场名单仍算到冻结末日，用于完成 48 段的名单诊断；它不是验证账户收益。', '']
    v1, v3 = runs['V1'], runs['V3']
    diagnosis = R.read(OUT/'training_diagnosis.json')
    if not choice:
        lines += [f'保留旧排序的V1在2024/2025的账户收益为{pct(v1["years"]["2024"]["account_return"])}/'
            f'{pct(v1["years"]["2025"]["account_return"])}；'
            '新增通道并没有使H与资金纯度一起提高。全局同伴排序和窄止损优先的V2/V3进一步削弱了原盈利结构。'
            '本结论只约束本轮U4股票池、名单/回撤定义及三套资金配置，不否定长期领涨方法本身。', '']
    lines += [f'新增来源 V1 的两年 H 为 {amount(v1["H"])}，资金纯度 {pct(v1["cap_equity"])}；'
        f'再加资金优先级的 V3 为 {amount(v3["H"])}、{pct(v3["cap_equity"])}。'
        f'M2A 对应 {amount(selection["baseline"]["H"])}、{pct(selection["baseline"]["cap_equity"])}。'
        '这比较的是各自完整账户，资金竞争、退出和权益反馈会一起变化，不能把差额全当单一排序项的独立贡献。', '',
        '## 与原账户同表', '',
        '训练账户从 2024-01-02 连续到 2025-12-31，年末持仓只估值。五线沿 Y1：资金≥50%、段毛利≥60%、'
        '首笔早买至少一半段、段吃到≥50%、前十真实平仓赢单至少五笔有正 H；每年≥52笔且已平仓胜率≤35%。'
        'H/O 按首开仓年、资金按日历年、覆盖和吃到按段年。H/O 单位为初始本金1，不能直接与年度收益相减。', '']
    table(lines, COLUMNS, [annual_cells(n, y, row) for n, r in refs.items() for y, row in r['years'].items()]+
        [annual_cells(n, y, row) for n, r in runs.items() for y, row in r['years'].items()])
    table(lines, ['候选', '两年H', '两年资金', '较差年五线', '较差年资金', '较差年毛利', '较差年早买', '较差年回撤', '资格失败'],
        [[n, amount(r['H']), pct(r['cap_equity']), min(v['target_count'] for v in r['years'].values()),
          pct(min(v['cap_equity'] for v in r['years'].values())), pct(min(v['purity_gross'] or 0. for v in r['years'].values())),
          min(v['coverage']['including_censored']['covered'] for v in r['years'].values()),
          pct(max(v['maxdd'] for v in r['years'].values())), '、'.join(
              {'H': '两年H', 'capital': '两年资金'}.get(k, k) for k in selection['failures'][n]) or '合格'] for n, r in runs.items()])
    lines += ['资格只要求两年 H 与加权资金不低于 M2A，并守住每年底线。排序严格为较差年五线数、资金、毛利、'
        '早买段数、回撤，最后按 ID。账户收益与登记 master 的差始终单列，研究入围不代表全面改善。', '',
        '## 新来源自身与挤占的旧交易', '',
        '以下按实际开仓来源和首次开仓年分组，pnl/H单位均为初始本金1，不等于日历年账户收益。'
        '同夜同票保留master报价的交易归旧通道，因此新来源的H只统计新增通道独占的实际成交，'
        '不能把它当作名单机制对所有旧成交的独立影响。', '']
    table(lines, ['候选', '开仓年', '新源笔数/不同票', '新源总pnl', '新源H', '旧通道笔数', '旧通道总pnl', '旧通道H'],
        [[name, year, f'{r["new_source"]["trades"]}/{r["new_source"]["codes"]}',
          amount(r['new_source']['pnl']), amount(r['new_source']['H']), r['master']['trades'],
          amount(r['master']['pnl']), amount(r['master']['H'])]
         for name, data in diagnosis.items() for year, r in data['sources'].items()])
    table(lines, ['候选', '与M3B同日同票仍开仓', '原M3B笔数', '有早报价却未早买的段', '这些报价的真实处理'],
        [[n, r['same_day_same_code_as_M3B'], r['original_M3B_trades'], r['offered_but_not_early_legs'],
          reasons_text(r['refused_or_consumed_early_reasons'])] for n, r in diagnosis.items()])
    table(lines, ['候选', '段年', '新源可早报价', '全部通道可早报价', '实际早买', '任意成交', '段内赚钱'],
        [[n, year, sum(bool(g['early_source_dates']) for g in r['legs'] if g['year'] == year),
          sum(bool(g['offered']) for g in r['legs'] if g['year'] == year),
          sum(g['early'] for g in r['legs'] if g['year'] == year),
          sum(g['any'] for g in r['legs'] if g['year'] == year),
          sum(g['H'] > 0 for g in r['legs'] if g['year'] == year)]
         for n, r in diagnosis.items() for year in ('2024', '2025')])
    lines += ['新增通道扩大了成交，并未提高整个账户的H和资金纯度。V2/V3改变了绝大多数原交易，'
        '不能将它们描述成只给原系统加一点同伴信息。拒绝中的risk_or_gross合并了敞口、'
        '最小金额及V3日风险预算，不把所有这一标签都说成单纯缺现金。'
        '本轮只有三套完整候选，没有再跑额外拆解账户，故不宣称已分别量出排序、格子上限和预算的独立贡献。'
        '逐段报价及拒绝详情见training_diagnosis.json与early_attempts_V*.json。', '',
        '## 名单有多宽，真正接上了多少段', '',
        '当晚 U4 为价格≥2美元、20日平均成交额≥5000万美元、ADR≥3%。过去120晚曾进入六个月前20%或一/三个月前10%，'
        '且周线9>21、收盘≥50EMA进入长期名单。后续不因跌出涨幅榜而忘记，跌破50EMA或周线转空才清掉状态。'
        '新回撤贴近9/21EMA不超过1ADR后武装，首个收回、收盘过前高或E11握手消费一次机会；必须再有新回撤才重来。', '']
    table(lines, ['年', '每晚平均/中位', '90%分位', '最少/最多', '不同票', '平均待触发', '触发动作'],
        [[y, f'{r["mean"]:.1f}/{r["median"]:.0f}', f'{r["p90"]:.0f}', f'{r["min"]}/{r["max"]}',
          r['distinct'], f'{r["armed_mean"]:.1f}', r['fire']] for y, r in diag['widths'].items()])
    table(lines, ['年', '原锚点在名单', 'H窗口内曾在名单', '新来源可早买报价'],
        [[y, f'{r["anchor"]}/{r["n"]}', f'{r["window"]}/{r["n"]}', f'{r["early_source"]}/{r["n"]}']
         for y, r in diag['membership'].items()])
    lines += ['名单只是资格，不等于买到，更不等于赚钱。新来源独立于 master 扫描和 QQQ 低分许可，'
        'master 原通道仍保留。相同夜同票保留 master 原 fill/stop；有再武装动作时可获该排序类别。'
        '名单每晚代码、只数、武装与动作在 features/validation/nightly.jsonl；本表身份交集只在评测侧计算。', '',
        '名单H窗口诊断沿冻结峰日，可能跨年；本表2025段的报价可出现在2026年初。'
        '上一节训练可早报价表则严格止于2025-12-31，两者不能混作训练账户已获得的供给。', '',
        '## 按 U1 的五类起点看全部 48 段', '',
        '单元格为早买/任意成交/赚钱，分类完全沿 U1，不重新贴标签。未评的2026明确缺失，不能当作零或与全48段直接比较。'
        '登记master、IE47采用U1原三年连续口径；M1B/M2A/M3B的24–25用原训练、26用原连续验证，'
        '因此本表与各年度独立账户资金表的用途不同。', '']
    table(lines, ['起点模式', '段数', *accounts], [[g['pattern'], g['n'], *[group_cell(g['systems'][n]) for n in accounts]]
                                               for g in diag['groups'] if g['year'] == 'all'])
    table(lines, ['年', '起点模式', '段数', *R.CANDIDATES], [[g['year'], g['pattern'], g['n'],
        *[group_cell(g['systems'][n]) for n in R.CANDIDATES]] for g in diag['groups'] if g['year'] != 'all' and g['n']])
    by_key = {g['key']: g for g in patterns}
    table(lines, ['段', '模式', '锚点在名单', '新源早报价', *accounts],
        [[g['key'], by_key[g['key']]['pattern'], '是' if g['anchor_in_list'] else '否', g['early_source_offers'],
          *['未评' if g['accounts'][n] is None else '/'.join('是' if g['accounts'][n][k] else '否'
             for k in ('early', 'any', 'profitable')) for n in accounts]] for g in diag['evidence']])
    lines += ['逐段账户原始 H、吃到、首笔成交和报价漏斗保留在各 metrics.json；48段模式与名单交集在 patterns_48.json，'
        '便于筛选的同表在 legs_48.csv。2026两段截断、短事件、精度分层沿原冻结分母，未删失败项。', '',
        '## 同伴排序与资金怎么分配', '',
        'V1仅加新来源。V2在新机会优先于retry后，按60日收益相关≥0.6的强同伴只数、本票在同伴中的月涨幅名次排序。'
        '同伴是当晚U4里的其他股票，强同伴指当晚月涨幅前20%，没有同伴不会被过滤。'
        'V3先分再武装、名单内有强同伴、其他三类，再按真实止损宽度由小到大，同伴只数和名次打破并列。', '',
        'V3每日最多4个成功新仓，初始止损风险日预算为权益2%，按每笔实际名义×止损宽度/当时权益扣减，'
        '当日卖出不返还，下一交易日重置。它不是存量或加仓的总止损风险上限。新仓先于旧仓加仓，'
        '后者仍受单票50%和总敞口280%限制。最多11仓；格子满或敞口余量不足权益5%时，'
        '只腾前夜已持有、未确认、未成功加仓且亏损或持平的较弱仓，盈利/加仓仓保护。'
        '新单不合法或预算后不足最小金额时不卖旧仓。新字段max_new_risk默认0，旧账户不开启。', '']
    table(lines, ['候选', '报价处理', '腾仓次数', '受日风险预算约束的新仓笔数'],
        [[n, reasons_text(R.read(OUT/'candidates'/n/'attempt_counts.json')),
          len(R.read(OUT/'candidates'/n/'management.json').get('score_rotation', [])),
          len(R.read(OUT/'candidates'/n/'management.json').get('new_risk', []))] for n in R.CANDIDATES])
    lines += ['## 2026 固定验证与工程检查', '']
    if choice:
        rows = R.read(HOME/'reports/m2_work/reference_2026.json')
        for name, folder in (('M2A', 'm2_work'), ('M3B', 'm3_work')):
            for label, record in R.read(HOME/'reports'/folder/'validation.json').items():
                rows[name+('单开' if label == 'standalone' else '连续')] = record['years']['2026']
        table(lines, COLUMNS, [annual_cells(n, '2026', r) for n, r in rows.items()]+
            [annual_cells(choice+('单开' if label == 'standalone' else '连续'), '2026', r['years']['2026'])
             for label, r in R.read(OUT/'validation.json').items()])
    else:
        lines += ['无合格者，因此新候选的2026单开/连续账户均未运行。只生成公共市场特征与名单身份交集，未算候选2026收益或纯度。', '']
        rows = R.read(HOME/'reports/m2_work/reference_2026.json')
        for name, folder in (('M2A', 'm2_work'), ('M3B', 'm3_work')):
            for label, record in R.read(HOME/'reports'/folder/'validation.json').items():
                rows[name+('单开' if label == 'standalone' else '连续')] = record['years']['2026']
        table(lines, COLUMNS, [annual_cells(n, '2026', r) for n, r in rows.items()]+
            [[n, '2026', *(['未评']*(len(COLUMNS)-2))] for n in R.CANDIDATES])
        lines += ['上表2026基准直接读取旧报告工件，没有重新评测。原M2A/M3B的全期重放仅验证台账一致，'
            '不参与候选选择。', '']
    lines += ['选中者或无合格时的V3在真正截断至2025-06-30的输入上重建状态与同伴，'
        '并用只改变未来的OHLC×3、量×2、额×6、raw×3及QQQ扰动重建。逐值核对市场特征、报价、成交事件和权益前缀。'
        '前夜G1许可复用M2独立重建并冻结的截断/扰动推断，相关文件指纹保留；没有只裁剪旧结果。', '',
        'M2A、M3B训练与完整连续台账/权益逐位一致。成交区间、FIFO、融资/期末估值对账、'
        '完整数据与训练特征前缀、V3每日初始风险预算均通过。', '']
    table(lines, ['测试组', '数量', '结果', '日志'], [[n, r['count'], r['result'], '[日志](f3_work/'+r['log']+')']
                                                for n, r in done['tests'].items()])
    lines += [f'审计{artifact["accounts"]}个新账户、{artifact["executions"]}条执行。计算使用.venv、'
        'CPUQuota=60%、MemoryMax=900M、单进程单线程。数组mmap，横截面按日期处理，相关块≤128×128。'
        '实际cgroup、线程数、RSS、源文件和输入指纹在completion.json。'
        '密钥安装器发现已有hooksPath后拒绝覆盖；现有pre-commit/pre-push已调用secret_guard.py，未绕过。', '',
        '首次准备把U1的raw.npy特征表误当价格面板，在形状检查处退出，尚未计算任何候选账户。'
        '随后改用panel/raw_close.npy并加形状断言，原错误、空白中间文件和初始协议保存在corrections。'
        '同时给V3加入默认关闭的rotate_actual_adds，区分实际加仓与预算拒绝后已消费的档位，'
        '防止把从未加成仓的探仓当已证实仓保护。局部测试通过后再次核对M2A/M3B完整台账。'
        '这些修正在任何F3账户结果计算前完成，预登记、三个候选和选择门槛均未改；指纹链见implementation_revision.json。', '',
        '交付后处理把冻结段表年份改为从first_date读取，修复了它没有year字段的假设；'
        '只改变报告模块，账户、市场特征、选择与门槛均未改，亦未重测账户。交付指纹另见delivery_revision.json。', '',
        '未联网、未拉数据、未提交Git，未改Y2、登记版、看板或旧报告。预登记SHA256为 '
        f'`{done["prereg_sha256"]}`。正式阶段用独占开始文件禁止重跑，report只读已保存账户。', '',
        '```bash',
        'RUN=(systemd-run --scope -p CPUQuota=60% -p MemoryMax=900M -q env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python)',
        '"${RUN[@]}" -m studies.martin_luk.f3_research freeze',
        '"${RUN[@]}" -m studies.martin_luk.f3_research compatibility',
        '"${RUN[@]}" -m studies.martin_luk.f3_research prepare',
        '"${RUN[@]}" -m studies.martin_luk.f3_research candidates',
        '"${RUN[@]}" -m studies.martin_luk.f3_research prefix',
        '"${RUN[@]}" -m studies.martin_luk.f3_research validate',
        '"${RUN[@]}" -m studies.martin_luk.f3_report',
        '```', '', '## 下一轮', '',
        '下一轮建议按原话检验首次回撤与9/21 EMA、前高、缺口等支撑重合的资格，'
        '同时保留master原通道固定排队作为控制，不再直接把全局队列交给同伴数或最窄止损。'
        '新来源资格与资金入口仍须一起做端到端账户比较，不能把更宽名单或更多早报价当成功。'
        '先按逐段名单→回撤武装→可早买报价→真实成交→证实加仓→资金/毛利的漏斗找限制层。'
        '名单内却没有早报价的段，继续检查回撤和动作；有早报价却没买到的段，结合逐笔拒绝和当时持仓查资金竞争。'
        '若买到而钱仍花在其他票，单独量新来源在同类普通机会中的区分度，不能再靠扩大名单或提高杠杆代替。'
        '本轮失败只约束这三套明确规则与冻结日K，不否定本人方法，也不据2026结果追加候选或改门槛。']
    report = HOME/'reports/F3_CN.md'
    report.write_text('\n'.join(lines)+'\n')
    before, after = (OUT/'original_engine.py.txt').read_text(), Path(R.Y.__file__).read_text()
    (OUT/'engine_delta.diff').write_text(''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
        fromfile='engine_before_F3', tofile='engine_after_F3')))
    done['report_sha256'] = R.sha(report)
    R.write('completion.json', done)
    summary = [f'F3完成；选中={choice}；复刻目标通过={done["strategy_success"]}',
        '报告：studies/martin_luk/reports/F3_CN.md',
        'M2A/M3B训练及完整台账逐位不变；截断与未来扰动通过。',
        '三组测试通过；2026'+('单开/连续各一次。' if choice else '账户未打开。'),
        '下一轮：沿逐段名单、动作、资金竞争与证实加仓漏斗定位限制层。']
    (OUT/'terminal_summary.txt').write_text('\n'.join(summary)+'\n')
    R.write('artifact_manifest.json', {str(p.relative_to(OUT)): R.sha(p) for p in sorted(OUT.rglob('*'))
        if p.is_file() and p.name not in ('artifact_manifest.json', 'report.log')})
    print('\n'.join(summary))


if __name__ == '__main__':
    main()
