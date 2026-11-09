"""IE6 offline, whole-calendar gate search, backward ablation and fixed-selection execution."""
from collections import Counter, defaultdict
from contextlib import nullcontext
from dataclasses import asdict, replace
from datetime import datetime, timezone
import argparse
import ast
import gc
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
from unittest.mock import patch

import numpy as np

from studies.trader_replication import martin_continue_ie5 as old
from studies.trader_replication import ie_factor_models as models
from studies.trader_replication import preopen, system
from studies.trader_replication.martin_continue_ie_periods import distribution, file_sha

ROOT, REPORTS = old.ROOT, old.REPORTS
WORK = REPORTS / 'ie6_work'
PREFIX = 'strong_continue_ie6_'
PLAN = ROOT / 'studies/martin_luk/notes/PLAN_IE6_CN.md'
PREREG = ROOT / 'studies/martin_luk/notes/PREREG_IE6_CN.md'
TRAIN_END = old.prior.CUTOFF
YEARS = ('2024', '2025')
ABSOLUTE = ('money20', 'iv', 'hv', 'option_volume', 'call_volume', 'put_volume', 'option_open_interest')
EPS = 1e-9


def read(path):
    return old.read_json(path)


def write(name, value):
    old.prior.write_json(REPORTS / (PREFIX + name + '.json'), value)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def catalogue():
    """Readable hypotheses, fixed without inspecting new account results."""
    specs = {}
    def add(name, bounds, meaning, reason, unit):
        specs[name] = dict(bounds=bounds, meaning=meaning, reason=reason, unit=unit)
    for n in (1, 3, 5, 10, 21, 63, 126):
        add(f'g{n}', [(0., None), (.05 if n <= 10 else .20, None),
                       (-.05, .05) if n <= 5 else (-.20, .50)],
            f'{n}日价格涨幅', '正收益表示已有动量；短期双边区间表示涨后整理，长期区间避免弱势或过度伸展。', .01)
        add(f'rs{n}', [(0., None), (-.10 if n <= 21 else -.25, None),
                        (-.05, .05) if n <= 5 else (-.25, .50)],
            f'{n}日涨幅减去基准涨幅', '比较相对市场的强弱；短期接近市场可解释为强股暂停，中期底线排除落后太多的票。', .01)
    for n, floor in ((20, .05), (60, .10), (120, .20)):
        add(f'low{n}', [(floor, None), (2 * floor, None), (floor, 1.)],
            f'比{n}日最低收盘高多少', '先确认脱离低位，再等回调；一倍涨幅的上界是避免过度伸展的备选解释。', .01)
    for n in (20, 60, 252):
        add(f'high{n}', [(-.20, -.03), (-.20, None), (None, -.03)],
            f'收盘相对{n}日最高价的折价', '接近高位但已有回调；单边下界限制破坏深度，单边上界要求确实退离高点。', .01)
    for n in (20, 60):
        add(f'fresh_high{n}', [(-20., -1.), (-20., None), (None, -1.)],
            f'最近一次创{n}日新高距今天数的负值', '既可检查近期领涨身份，也可等创新高后至少一天再观察回调。', 1.)
    add('money20', [(1e7, None), (3e7, None), (1e8, None)], '20日平均股票成交额',
        '优先成交活跃、容量足够的票；一亿美元对应本人 premier 名单的量级。', 1e7)
    for name in ('rvol1', 'rvol3', 'rvol5'):
        add(name, [(.4, None), (1., None), (.4, 1.5)], '近期成交量相对20日均量的倍数',
            '量下限排除冷清；适度缩量区间观察涨后整理，放量下限观察资金重新进入。', .1)
    add('adr20', [(.03, None), (.05, None), (.08, None)], '20日平均日内振幅',
        '走得快才有足够的获利空间；5%有本人方向依据。', .01)
    add('contract5', [(-1., None), (None, -.5), (-1.5, -.5)], '负的5日振幅除以20日ADR',
        '下界选择振幅收窄；上界排除几乎不动的整理；中间带寻找仍有交易空间的整理。', .1)
    add('range10', [(-6., None), (None, -2.), (-8., -2.)], '负的10日全区间除以ADR',
        '区间不能宽到破坏整理，也可要求至少有两倍ADR的可交易结构；效果由消融判断。', .5)
    add('close_position', [(.1, None), (.5, None), (.75, None)], '收盘在当日高低范围的位置',
        '避开弱收盘，或要求买方在收盘前收回大部分振幅。', .05)
    for n in (9, 21, 50):
        add(f'ema{n}', [(0., None), (-.05, .10), (-.03, .05)], f'价格相对EMA{n}的位置',
            '站上均线或回到均线附近，避免远离支撑追价。', .01)
        add(f'near_ema{n}', [(-1., None), (-1.5, None), (-2., None)], f'负的距EMA{n}绝对距离除以ADR',
            '用股票自身波动衡量是否靠近均线支撑。', .1)
        add(f'cross{n}', [(-20., None), (-40., None), (None, -2.)], f'最近上穿EMA{n}距今天数的负值',
            '近期上穿表示趋势启动；等两天避免把刚穿越和回调混在一起，但不保证当前仍在均线上方。', 1.)
    add('ema_stack', [(1., None), (2., None)], 'EMA9>EMA21与EMA21>EMA50的成立项数',
        '均线多头排列对应领涨股名单。', 1.)
    add('gap20', [(1., None), (None, 3.), (.15, 2.5)], '20日最大正跳空除以前日ADR',
        '跳空提供催化；设上限或中间带观察消化事件后的回调，避免追极端缺口。', .05)
    add('fresh_gap', [(-60., -8.), (-20., None), (None, -5.)], '最近一次至少两倍ADR跳空距今天数的负值',
        '8至60天可以解释为跳空后等回调；另测新近事件与等数日消化两种形态。', 1.)
    add('pot_count20', [(1., None), (2., None), (3., None)], '20日内进入强势涨幅扫描的次数',
        '反复出现在扫描里表示持续关注与资金活跃。', 1.)
    add('fresh_pot', [(-20., None), (-40., None), (-60., None)], '最近强势扫描距今天数的负值',
        '保留刚变强且仍在观察期内的票。', 1.)
    add('earn_age', [(-30., None), (-60., None), (-100., None)], '最近已发生且已知财报距今自然日的负值',
        '财报后的信息消化与事件动量，绝不使用尚未发生的报告。', 5.)
    add('peer_g5', [(-.10, None), (0., None), (.05, None)], '相关同伙5日平均收益',
        '同伙一起强或至少没有大跌，代理题材资金环境；相关同伙不等于真实行业。', .01)
    add('peer_rank', [(.5, None), (.75, None), (.9, None)], '股票21日收益在相关同伙中的位置',
        '同一群体里优先领涨者。', .05)
    h4 = dict(activity='成交活跃', momentum='价格动量', history='历史强势', stack='均线结构', peers='同伙', coil='振幅收窄')
    for name, meaning in h4.items():
        add('h4_' + name, [(.5, None), (.75, None), (.25, .95)], f'H4{meaning}组百分位',
            '优先该组偏强者；中间带解释为已有趋势但避开极端状态，是否有用交给删除实验。', .05)
    add('offlow252', [(.25, None), (.50, None), (1., None)], '比252日最低价高多少',
        '选择脱离长期低位、已经被市场确认的强势股。', .05)
    for name, levels in (('iv', (50., 75., 100.)), ('hv', (30., 50., 75.))):
        add(name, [(x, None) for x in levels], '隐含波动率' if name == 'iv' else '历史波动率',
            '偏向波动较大的动量股；绝对量级同时配当晚百分位以检查市场波动漂移。', 5.)
    for name, levels in (('option_volume', (1000., 10000., 50000.)),
                         ('call_volume', (1000., 10000., 50000.)),
                         ('put_volume', (500., 5000., 25000.)),
                         ('option_open_interest', (10000., 80000., 250000.))):
        add(name, [(x, None) for x in levels], '期权市场关注度：' + name,
            '总量、Call量、Put量或未平仓量衡量参与活跃度；Put量只作关注代理，不能解释成看涨方向。',
            500. if name == 'put_volume' else 1000.)
    add('iv_hv', [(.5, 2.), (1., None), (None, 2.)], '隐含波动率除以历史波动率',
        '预期波动相对已实现波动的溢价；中间带避开波动预期异常，不将其冒称本人规则。', .1)
    add('pcr', [(.25, .9), (None, 1.), (.25, None)], 'Put成交量除以Call成交量',
        '偏Call活跃但保留双边参与的市场；极低值可能是单边追涨，这是待验证的交易解释。', .05)
    expected = set(old.ie4.raw_names()) - {'raw_price', 'observed_sessions'}
    if set(specs) != expected:
        raise AssertionError(('raw catalogue differs', expected ^ set(specs)))
    return specs


def candidate_pool():
    specs = catalogue()
    gates, bykey = [], {}
    def add(name, form, lower, upper, origin):
        key = name, form, lower, upper
        if key not in bykey:
            s = specs[name]
            info = dict(id=len(gates), name=name, form=form, lower=lower, upper=upper,
                        meaning=s['meaning'] + ('在当晚完整范围内的百分位' if form == 'pct' else ''),
                        reason=s['reason'], origin=origin)
            gates.append(info)
            bykey[key] = info['id']
        return bykey[key]
    for name in old.ie4.raw_names():
        if name not in specs:
            continue
        for lower, upper in specs[name]['bounds']:
            add(name, 'raw', lower, upper, 'readable_inventory')
        if name in ABSOLUTE:
            for lower in (.5, .75, .9):
                add(name, 'pct', lower, None, 'same_night_drift_control')
    frozen = read(old.FROZEN)
    explanations = read(old.EXPLANATIONS)['gates']
    starts = dict(empty=[], class12=[], core5=[])
    for k, (gate, explanation) in enumerate(zip(frozen['gates'], explanations)):
        name = gate['name']
        if name not in specs:
            continue
        unit = specs[name]['unit']
        bounds = [None if gate[b] is None else float(round(gate[b] / unit) * unit) for b in ('lower', 'upper')]
        bounds = [None if v is None else float(f'{v:.10g}') for v in bounds]
        if name.startswith(('cross', 'fresh_')) or name == 'earn_age' or name.startswith('near_ema'):
            if bounds[1] is not None and bounds[1] >= 0:
                bounds[1] = None
        if explanation['category'] in (1, 2):
            starts['class12'].append(add(name, 'raw', *bounds, 'rounded_ie5_class12'))
        if k < 5:
            # The five core conditions have already been stated in readable units.
            readable = dict(iv=(50., None), pcr=(.25, .9), high20=(-.20, -.03),
                            low120=(.20, None), option_open_interest=(80000., None))
            starts['core5'].append(add(name, 'raw', *readable[name], 'rounded_ie5_core5'))
    return gates, starts


def percentile_missing(raw, slices):
    result = np.full(raw.shape, np.nan, np.float32)
    for sl in slices.values():
        values = old.prior.percentile(raw[sl])
        values[~np.isfinite(raw[sl])] = np.nan
        result[sl] = values
    return result


def corrected_delta(raw, meta, slices):
    p = percentile_missing(raw, slices)
    delta = np.full_like(p, np.nan)
    di = {day: i for i, day in enumerate(meta['days'])}
    for day, sl in slices.items():
        t = di[day]
        prev = meta['days'][t - 5] if t >= 5 else None
        if prev not in slices:
            continue
        ps = slices[prev]
        lookup = {code: ps.start + k for k, code in enumerate(meta['scope'][prev])}
        for k, code in enumerate(meta['scope'][day]):
            if code in lookup:
                delta[sl.start + k] = p[sl.start + k] - p[lookup[code]]
    result = percentile_missing(delta, slices)
    return np.where(np.isfinite(result), result, .5).astype(np.float32), ~np.isfinite(result)


def preregister():
    gates, starts = candidate_pool()
    manifest = dict(plan_sha256=file_sha(PLAN), gates=gates, starts=starts,
                    excluded=dict(observed_sessions='缓存长度不等于上市年龄', raw_price='整项退出，避免未复权拆股价格的上限'),
                    created_utc=datetime.now(timezone.utc).isoformat())
    target = REPORTS / (PREFIX + 'candidate_pool.json')
    if target.exists():
        previous = read(target)
        if previous['gates'] != gates or previous['starts'] != starts or previous['plan_sha256'] != file_sha(PLAN):
            raise ValueError('pre-registered pool changed')
        return
    write('candidate_pool', manifest)
    rows = ['# IE6 计算前登记', '', '唯一任务书为 [PLAN_IE6_CN.md](PLAN_IE6_CN.md)，运行中不改任务书、旧预登记或旧结果。', '',
            '## 范围、时点和固定排序', '',
            '只读 IE5 的冻结行情、股票/期权中间缓存、原64列和前夜H4订单；不取数。全部交易夜晚计算门禁、排序和订单，不只用68个评价夜晚。',
            '主目标仍为2024–25的28笔，四晚取最好名次，同时报1/3/5/10。2026已被看过一次，不是干净的考试；搜索对象和账户均截到2025年末，冻结最终条件与执行选择后才生成2026比较。',
            '排序沿用IE5冻结的100项logit及原权重，不新增排名模型搜索；其复杂度不算在门禁条数内，报告必须披露。唯一公式修正：delta5的本晚或五个交易日前缺范围/缺数据时置缺失，排名中性0.5。其他列逐值复用。',
            '绝对量级的7项同时进入当晚完整leader范围百分位版本；缺数据保留为缺失，不排成正常中位。主流程门禁缺失放行，最终每条路径报告选入票中因缺失放行比例；超过10%就加测缺失不通过，不据此换条件。', '',
            '## 固定评分、前向和消融', '',
            '每个组合均跑现金六仓和杠杆原H4不分批，全部开启preopen_add_stop_gap。选择门槛按两种账户分别要求：2024、2025各≥52笔、已结束交易胜率≤35%、每年收益不低于原H4同执行基线。两账户四个年度都通过才称合格。',
            '合格组合按主目标前5覆盖、条件少、杠杆两年增长倍数几何平均依次选择。各前向步枚举固定池中全部未用条件，三条起点为空、第1+2类25条的可读取整版、前5核心的可读版；始终报告起点改了哪些数字。',
            '尚无合格组合时，路径允许走覆盖提高或四个年度收益均不退且至少一项提高的探索步，依次按合格、覆盖、条件少、杠杆几何平均排序；这些步不能宣称通过门槛。当前已合格则不再走不合格步。无上述改善即停止，不设任意步数或按结果扩池。',
            '可读阈值事先固定，全部不搜索精细小数。旧门槛取整起点不宣称逐值复现旧成绩；新条件不借用2026。逐条删除：覆盖少至多1笔、四个年度收益都不下降（数值容差1e-9），且已合格路径仍合格，就删除；按统一评分选可删项并重复。',
            '最终每条剩余条件给出去掉后的覆盖、两账户年度笔数/收益/回撤/胜率与四个半年的边际变化。很小但超过容差的账户下降也如实标出，不冒称经济上显著。',
            '打乱标签种子20261106：同晚同池置换，重复披露共享映射，保持四晚窗口。冻结100列的正则logit用打乱训练标签重新拟合（penalty=0.1，100步），再用完全相同三起点前向+消融流程；100列的历史筛选已用真标签，不能当严格显著性检验。',
            '每条不重复的最终组合，同池随机30次（种子1–30），每晚均匀无放回选min(5,池宽)，同一次抽样供两账户使用。按年、2024–25和全段报收益排位。', '',
            '## 固定选股后的执行实验', '',
            'K0=IE5杠杆执行。K1初始风险0.25%权益，亏损/盈利反馈档0.125%/0.4%，所有票乘数1；+1R、+2R前收确认后次开各加初始股数一份。K2只改初始风险乘数：前1为1.5、前2–3为1、前4–5为0.5，共3档。',
            'K3=K1，止损宽度=min(信号日ADR20/2,2.5%)，ADR缺失不生成新单；K4=K2+K3。K3/4在次开仍浮亏或持平时取消已预留的加仓，不释放预留给其他新单；前收未达+1R/+2R本来就不确认加仓。',
            '所有K总仓位预留上限280%、单只35%，保留前收+5%开盘限价、费用、融资、EMA21次开离场与新止损越界修正；漂移后的实际敞口另报，不把预留上限说成硬性实时上限。',
            'K的选择仅用2024–25，先要求每年≥52笔且胜率≤35%，再按两年增长倍数几何平均，平手回撤低。收益、笔数、胜率、全投入盈亏比及≥50%标的涨幅赢家的数量、股票数和PnL都报告；加仓放大的本金回报另列，不混作股价涨幅。',
            '若选股门槛无解，仍冻结三路径中描述性评分最高的名单完成K0–K4诊断，明确标记未达选股目标，执行改善不能倒过来影响选股。',
            '另审计登记R74+S7调用路径：若没有preopen开盘加仓分支，该修正不适用，写明机制与证据，不把开启会报错的参数强塞给登记版。ID旧+531%则用同一真实订单修正前后重放。', '',
            '## 固定候选池', '',
            f'共{len(gates)}个条件。以下是全部条件及白话依据；数值按原字段单位（收益/ADR为小数，IV/HV为缓存单位，成交额为美元）。pct是0–1的当晚百分位。', '',
            '| 编号 | 字段/形式 | 下界 | 上界 | 白话含义 | 交易理由 |', '|---|---|---:|---:|---|---|']
    for gate in gates:
        rows.append('| {id} | {name}/{form} | {lo} | {hi} | {meaning} | {reason} |'.format(
            **gate, lo='无' if gate['lower'] is None else f"{gate['lower']:g}",
            hi='无' if gate['upper'] is None else f"{gate['upper']:g}"))
    rows += ['', '三个起点条件编号：`' + json.dumps(starts, ensure_ascii=False) + '`。', '',
             '候选池JSON及任务书SHA256在结果目录固定；每阶段记录源码指纹，结果按组合、阶段、随机种子分块存盘。一时只运行一个低优先级单线程研究进程。',
             '先运行因果性/执行时点/代码无本人证券常量合成测试，最后跑custody、trader_replication、martin_luk全部测试与git diff --check。data/只读，不提交不推送，不改登记版、custody或工作树外文件。', '']
    PREREG.write_text('\n'.join(rows), encoding='utf-8')
    print('pre-registered', len(gates), 'conditions', {k: len(v) for k, v in starts.items()}, flush=True)


def prepare():
    meta = read(old.WORK / 'prepared.json')
    keys, slices, bycode = old.layout(meta)
    frozen = read(old.FROZEN)
    inventory = {old.prior.factor_name(s, t): (s, t) for s, t in old.prior.factor_specs()}
    specs = [inventory[n] for n in frozen['model']['features'] if inventory[n][1] == 'delta5']
    qqq = np.load(old.WORK / 'qqq.npy')
    for family in dict.fromkeys(s.family for s, _ in specs):
        marker = WORK / ('delta_' + family + '.json')
        if marker.exists():
            continue
        subset = list(dict.fromkeys(s for s, _ in specs if s.family == family))
        raw = np.lib.format.open_memmap(WORK / 'scratch.npy', mode='w+', dtype=np.float32,
                                        shape=(len(keys), len(subset)))
        raw[:] = np.nan
        for k, (code, positions) in enumerate(bycode.items()):
            with np.load(old.WORK / 'stocks' / (code + '.npz')) as z:
                arrays = {n: z[n] for n in z.files if not n.startswith('extra_')}
                extras = {n[6:]: z[n] for n in z.files if n.startswith('extra_')}
            if family == 'group':
                for n in {s.parameter for s in subset}:
                    with np.load(old.WORK / 'group' / (code + f'.{n}.npz')) as z:
                        extras.update({f'group.{key}.{n}': z[key] for key in z.files})
            stock = old.lib.Stock(arrays, meta['days'], qqq, extras)
            values = {n: old.indicator_values(stock, family, n, {s.metric for s in subset if s.parameter == n})
                      for n in {s.parameter for s in subset}}
            ts, rows = map(np.asarray, zip(*positions))
            raw[rows] = np.column_stack([values[s.parameter][s.metric][ts] for s in subset])
            stock.ema.cache_clear()
            stock.f_hilbert.cache_clear()
            if k % 500 == 0:
                print('delta raw', family, k, '/', len(bycode), flush=True)
        transformed, missing = corrected_delta(raw, meta, slices)
        records = []
        for j, s in enumerate(subset):
            name = old.prior.factor_name(s, 'delta5')
            np.save(WORK / 'design' / (name + '.npy'), transformed[:, j])
            previous = np.load(old.WORK / 'design' / (name + '.npy'), mmap_mode='r')
            records.append(dict(name=name, missing=int(missing[:, j].sum()),
                                changed=int(np.count_nonzero(previous != transformed[:, j]))))
        old.prior.write_json(marker, dict(columns=records))
        del transformed, missing, raw, stock, arrays, extras, values
        gc.collect()
        (WORK / 'scratch.npy').unlink()
    score = np.zeros(len(keys), float)
    for name, weight in zip(frozen['model']['features'], frozen['model']['weights']):
        path = WORK / 'design' / (name + '.npy')
        column = np.load(path if path.exists() else old.WORK / 'design' / path.name, mmap_mode='r')
        score += (column - np.float32(.5)).astype(float) * weight
    np.save(WORK / 'true_scores.npy', score)
    raw = np.load(old.WORK / 'raw.npy', mmap_mode='r')
    pct = np.lib.format.open_memmap(WORK / 'absolute_pct.npy', mode='w+', dtype=np.float32,
                                    shape=(len(ABSOLUTE), len(raw)))
    for j, name in enumerate(ABSOLUTE):
        col = raw[:, frozen['raw_feature_names'].index(name):frozen['raw_feature_names'].index(name) + 1]
        pct[j] = percentile_missing(col, slices)[:, 0]
    pct.flush()
    changes = [r for p in sorted(WORK.glob('delta_*.json')) for r in read(p)['columns']]
    write('preparation', dict(rows=len(keys), nights=len(slices), cutoff=meta['prepared_last'],
                             corrected_delta=changes, fixed_ranker_features=len(frozen['model']['features']),
                             dataset_digest=meta['dataset_digest']))


def condition_mask(values, gate, missing_pass=True):
    finite = np.isfinite(values)
    passed = finite.copy()
    if gate['lower'] is not None:
        passed &= values >= gate['lower']
    if gate['upper'] is not None:
        passed &= values <= gate['upper']
    return passed | (~finite if missing_pass else False)


def half_statistics(curve, dates, trades):
    result = {}
    dates = np.asarray(dates, str)
    for year in YEARS:
        for half in (1, 2):
            mask = np.char.startswith(dates, year) & np.array([(s[5:7] <= '06') == (half == 1) for s in dates])
            rows = np.flatnonzero(mask)
            if not len(rows):
                continue
            base = float(curve[rows[0] - 1]) if rows[0] else 1.
            values = np.r_[base, curve[rows]]
            sample = [t for t in trades if t['entry'].startswith(year) and (t['entry'][5:7] <= '06') == (half == 1)]
            result[f'{year}H{half}'] = dict(return_=float(values[-1] / base - 1), entries=len(sample),
                maxdd=float(np.max(1 - values / np.maximum.accumulate(values))))
            result[f'{year}H{half}']['return'] = result[f'{year}H{half}'].pop('return_')
    return result


def account(d, px, ema, rule, book, meta, end=TRAIN_END, detail=False, stop_map=None,
            correction=True, cancel_loss_add=False, entry_close_add=False):
    track = {} if detail else None
    if cancel_loss_add:
        start = int(np.searchsorted(px['dates'], old.panels.WINDOW[0]))
        planner = preopen.plan
        clock = iter(range(start, int(np.searchsorted(px['dates'], end, side='right'))))
        def opening_cancel(candidates, holdings, *args, **kwargs):
            t = next(clock)
            plan = planner(candidates, holdings, *args, **kwargs)
            for h in holdings:
                if h['j'] in plan['adds']:
                    opening = px['open'][t, h['j']]
                    entry = px['open'][h['entry_index'], h['j']]
                    if np.isfinite(opening) and opening <= entry:
                        del plan['adds'][h['j']]
                        for row in plan['trace']:
                            if row['type'] == 'add' and row['j'] == h['j']:
                                row['cancelled_at_open'] = 'not_above_initial_fill'
            return plan
        context = patch.object(preopen, 'plan', opening_cancel)
    else:
        context = nullcontext()
    with context:
        curve, dates, trades = system.simulate(px, ema, rule, book, old.panels.WINDOW[0], end,
            audit=detail, track=track, preopen=True, preopen_fill_stop_pct_by_kind=stop_map or {'n1': .025, 'list': .025},
            preopen_fill_stop_hit=True, preopen_add_stop_gap=correction, preopen_entry_close_add=entry_close_add)
    values = np.r_[1., curve]
    result = dict(annual=old.annual_statistics(curve, dates, trades),
                  halfyear=half_statistics(curve, dates, trades), total=float(curve[-1] - 1),
                  maxdd=float(np.max(1 - values / np.maximum.accumulate(values))),
                  fidelity=old.fill_fidelity(trades, dict(meta, entries=[r for r in meta['entries']
                                                if r['entry_date'] <= end]))['annual'])
    for year, row in result['annual'].items():
        sample = [t for t in trades if t['entry'].startswith(year) and t['why'] != 'end']
        # Price return and return on initial capital differ after pyramiding.
        winners = [t for t in sample if t['executions'][-1]['price'] / t['fill'] - 1 >= .5] if detail else []
        row['big_winners'] = dict(trades=len(winners), names=len({t['code'] for t in winners}),
                                  pnl=float(sum(t['pnl'] for t in winners)),
                                  initial_capital_return_50=sum(t['ret'] >= .5 for t in sample))
    if detail:
        result.update(curve=curve.tolist(), dates=list(map(str, dates)), trades=trades,
                      max_close_gross=float(max(track['gross'])), max_close_positions=max(track['open']),
                      margin_paid=float(track['margin']), plans=track['preopen_plans'],
                      add_orders=track.get('add_orders', []), trade_digest=old.hb.sha_bytes(trades))
    return result


def feasible(accounts, baseline):
    failures = []
    for label in ('cash6', 'lever'):
        for year in YEARS:
            row = accounts[label]['annual'][year]
            if row['entries'] < 52:
                failures.append(label + ':' + year + ':entries')
            if row['win'] is None or row['win'] > .35 + EPS:
                failures.append(label + ':' + year + ':win')
            if row['return'] + EPS < baseline[label]['annual'][year]['return']:
                failures.append(label + ':' + year + ':return')
    return not failures, failures


def geometric(accounts):
    growth = np.prod([1 + accounts['lever']['annual'][y]['return'] for y in YEARS])
    return float(np.sqrt(max(0., growth)) - 1)


def score_key(value):
    return value['eligible'], value['coverage']['primary']['hits']['5'], -len(value['conditions']), value['lever_geo']


def no_worse(after, before):
    return all(after[label]['annual'][year]['return'] + EPS >= before[label]['annual'][year]['return']
               for label in ('cash6', 'lever') for year in YEARS)


def improving(after, before):
    if before['eligible'] and not after['eligible']:
        return False
    if after['eligible'] and not before['eligible']:
        return True
    delta = after['coverage']['primary']['hits']['5'] - before['coverage']['primary']['hits']['5']
    return delta > 0 or (delta == 0 and no_worse(after['accounts'], before['accounts']) and
        any(after['accounts'][label]['annual'][year]['return'] > before['accounts'][label]['annual'][year]['return'] + EPS
            for label in ('cash6', 'lever') for year in YEARS))


def removable(after, before):
    loss = before['coverage']['primary']['hits']['5'] - after['coverage']['primary']['hits']['5']
    return loss <= 1 and no_worse(after['accounts'], before['accounts']) and (not before['eligible'] or after['eligible'])


class Experiment:
    def __init__(self, shuffled=False, full=False):
        self.meta = read(old.WORK / 'prepared.json')
        self.keys, self.slices, _ = old.layout(self.meta)
        self.raw = np.load(old.WORK / 'raw.npy', mmap_mode='r')
        self.pct = np.load(WORK / 'absolute_pct.npy', mmap_mode='r')
        self.gates = read(REPORTS / (PREFIX + 'candidate_pool.json'))['gates']
        self.names = read(old.FROZEN)['raw_feature_names']
        self.shuffled, self.full = shuffled, full
        self.label = 'shuffle' if shuffled else 'true'
        self.d, self.px, self.rules, self.ema = old.load_account_inputs()
        self.d.A = {name: np.asarray(value) for name, value in self.d.A.items()}
        self.px = {name: np.asarray(value) for name, value in self.px.items()}
        self.ema = {label: {name: np.asarray(value) for name, value in arrays.items()}
                    for label, arrays in self.ema.items()}
        self.ci = {str(c): j for j, c in enumerate(self.d.A['codes'])}
        self.end = self.meta['prepared_last'] if full else TRAIN_END
        self.slices = {day: sl for day, sl in self.slices.items() if day <= self.end}
        self.n = max(sl.stop for sl in self.slices.values())
        self.entries = [r for r in self.meta['entries'] if r['entry_date'] <= self.end]
        self.query = []
        maps = {}
        rng = np.random.default_rng(20261106)
        for day, sl in self.slices.items():
            if shuffled:
                maps[day] = rng.permutation(sl.stop - sl.start)
        for entry in self.entries:
            row = []
            for event in entry['systems']['h4']:
                day = event['date']
                names = self.meta['scope'][day]
                if entry['code'] in names:
                    k = names.index(entry['code'])
                    k = int(maps[day][k]) if shuffled else k
                    row.append(self.slices[day].start + k)
                elif shuffled and names:
                    row.append(self.slices[day].start + int(rng.integers(len(names))))
                else:
                    row.append(-1)
            self.query.append(row)
        self.score = np.load(WORK / (self.label + '_scores.npy'), mmap_mode='r') if (WORK / (self.label + '_scores.npy')).exists() else None
        self.order = {day: np.arange(sl.start, sl.stop)[np.argsort(-self.score[sl], kind='stable')]
                      for day, sl in self.slices.items()} if self.score is not None else {}
        self.baseline = read(REPORTS / (PREFIX + 'baseline_training.json')) if (REPORTS / (PREFIX + 'baseline_training.json')).exists() else None
        self.masks = np.load(WORK / 'gate_masks.npy', mmap_mode='r') if not full and (WORK / 'gate_masks.npy').exists() else None

    def values(self, gate):
        return self.raw[:self.n, self.names.index(gate['name'])] if gate['form'] == 'raw' else self.pct[ABSOLUTE.index(gate['name']), :self.n]

    def mask(self, ids, missing_pass=True):
        mask = np.ones(self.n, bool)
        for i in ids:
            mask &= (np.unpackbits(self.masks[i], count=self.n).astype(bool) if missing_pass and self.masks is not None
                     else condition_mask(self.values(self.gates[i]), self.gates[i], missing_pass))
        return mask

    def selected(self, mask, random_seed=None):
        selected, widths, top = {}, {}, {}
        rng = np.random.default_rng(random_seed) if random_seed is not None else None
        for day, sl in self.slices.items():
            if day < self.meta['first_signal']:
                continue
            rows = self.order[day]
            kept = rows[mask[rows]]
            widths[day] = len(kept)
            top[day] = kept[:10]
            if rng is not None:
                pool = np.flatnonzero(mask[sl]) + sl.start
                kept = rng.choice(pool, min(5, len(pool)), replace=False)
            selected[day] = kept[:5].tolist()
        return selected, widths, top

    def coverage(self, top):
        ranks = {day: {int(q): k + 1 for k, q in enumerate(rows)} for day, rows in top.items()}
        rows = []
        for entry, queries in zip(self.entries, self.query):
            best = min((ranks.get(e['date'], {}).get(q, old.prior.SENTINEL)
                        for e, q in zip(entry['systems']['h4'], queries)), default=old.prior.SENTINEL)
            rows.append(dict(id=entry['id'], entry_date=entry['entry_date'], code=entry['code'],
                             primary=entry['target']['tier'] == 'primary', best_rank=int(best)))
        def summarize(sample):
            return dict(n=len(sample), hits={str(k): sum(r['best_rank'] <= k for r in sample) for k in old.prior.TOPS})
        return dict(primary=summarize([r for r in rows if r['primary']]), all=summarize(rows),
                    halfyear={f'{y}H{h}': summarize([r for r in rows if r['primary'] and r['entry_date'].startswith(y)
                             and (r['entry_date'][5:7] <= '06') == (h == 1)]) for y in YEARS for h in (1, 2)},
                    annual={y: dict(primary=summarize([r for r in rows if r['primary'] and r['entry_date'].startswith(y)]),
                                     all=summarize([r for r in rows if r['entry_date'].startswith(y)]))
                            for y in (*YEARS, '2026')}, rows=rows)

    def book(self, selected, variant='K0'):
        book = [[] for _ in self.d.days]
        stops = {'n1': .025, 'list': .025}
        for day, rows in selected.items():
            t = self.d.di[day]
            if t + 1 >= len(self.d.days) or self.d.days[t + 1] > self.end:
                continue
            for rank, q in enumerate(rows):
                j = self.ci[self.keys[q][1]]
                pct = .025
                if variant in ('K3', 'K4'):
                    adr = float(self.raw[q, self.names.index('adr20')])
                    if not np.isfinite(adr) or adr <= 0:
                        continue
                    pct = min(.025, adr / 2)
                kind = 'list' if pct == .025 else 'ie6_' + float(pct).hex()
                stops[kind] = pct
                mult = .5 if variant == 'K0' else (1.5 if rank == 0 else 1. if rank <= 2 else .5) if variant in ('K2', 'K4') else 1.
                close = float(self.d.A['close'][t, j])
                opening = float(self.d.A['open'][t + 1, j])
                book[t + 1].append(((2., rank), j, 1, opening, close * (1 - pct), kind,
                                     None, None, None, mult, None, bool(np.isfinite(self.d.A['low'][t + 1, j]))))
        return book, stops

    def evaluate(self, ids):
        ids = sorted(ids)
        path = WORK / 'evaluations' / (self.label + '.' + digest(ids) + '.json')
        if path.exists():
            return read(path)
        mask = self.mask(ids)
        selected, widths, top = self.selected(mask)
        selection_hash = digest(selected)
        cached = WORK / 'accounts' / (selection_hash + '.json')
        if cached.exists():
            accounts = read(cached)
        else:
            book, stops = self.book(selected)
            accounts = {label: account(self.d, self.px, self.ema[label], rule, book, self.meta, end=self.end)
                        for label, rule in self.rules.items()}
            old.prior.write_json(cached, accounts)
        eligible, failures = feasible(accounts, self.baseline)
        result = dict(conditions=ids, coverage=self.coverage(top), accounts=accounts,
                      eligible=eligible, failures=failures, lever_geo=geometric(accounts), selection_hash=selection_hash,
                      widths={year: dict(distribution=distribution([n for day, n in widths.items() if day.startswith(year)]),
                          empty=sum(n == 0 for day, n in widths.items() if day.startswith(year)),
                          empty_fraction=float(np.mean([n == 0 for day, n in widths.items() if day.startswith(year)])))
                          for year in YEARS})
        old.prior.write_json(path, result)
        return result


def setup_search():
    experiment = Experiment()
    path = WORK / 'gate_masks.npy'
    if not path.exists():
        masks = np.lib.format.open_memmap(path, mode='w+', dtype=np.uint8,
                                          shape=(len(experiment.gates), (experiment.n + 7) // 8))
        for gate in experiment.gates:
            masks[gate['id']] = np.packbits(condition_mask(experiment.values(gate), gate))
        masks.flush()
    if experiment.baseline is None:
        orders = read(old.WORK / 'baseline_orders.json')
        book = old.hc.make_books(experiment.d, orders, old.hh.observations(experiment.d, orders), True)[0]
        result = {label: account(experiment.d, experiment.px, experiment.ema[label], rule, book, experiment.meta)
                  for label, rule in experiment.rules.items()}
        write('baseline_training', result)
    if not (WORK / 'shuffle_scores.npy').exists():
        shuffled = Experiment(shuffled=True)
        days = {e['date'] for r in shuffled.entries if r['target']['tier'] == 'primary' for e in r['systems']['h4']}
        rows = np.concatenate([np.arange(sl.start, sl.stop) for day, sl in shuffled.slices.items() if day in days])
        reverse = {int(q): k for k, q in enumerate(rows)}
        positives = defaultdict(Counter)
        for entry, query in zip(shuffled.entries, shuffled.query):
            if entry['target']['tier'] == 'primary':
                for event, q in zip(entry['systems']['h4'], query):
                    if q >= 0:
                        positives[event['date']][reverse[q]] += 1
        groups, offset = [], 0
        for day, sl in shuffled.slices.items():
            if day in days:
                width = sl.stop - sl.start
                groups.append((slice(offset, offset + width), dict(positives[day])))
                offset += width
        frozen = read(old.FROZEN)['model']
        x = np.empty((len(rows), len(frozen['features'])), np.float32)
        for j, name in enumerate(frozen['features']):
            path = WORK / 'design' / (name + '.npy')
            column = np.load(path if path.exists() else old.WORK / 'design' / path.name, mmap_mode='r')
            x[:, j] = column[rows] - .5
        w = np.zeros(x.shape[1])
        for step in range(100):
            gradient = models.gradient(x @ w, groups)[0]
            w -= (x.T @ gradient + .1 * w) / (.1 + x.shape[1] / 4)
        score = np.zeros(len(experiment.raw))
        for name, weight in zip(frozen['features'], w):
            path = WORK / 'design' / (name + '.npy')
            col = np.load(path if path.exists() else old.WORK / 'design' / path.name, mmap_mode='r')
            # No exam prediction is needed or stored for the shuffled training fit.
            score[:experiment.n] += (col[:experiment.n] - .5).astype(float) * weight
        np.save(WORK / 'shuffle_scores.npy', score)
        write('shuffle_model', dict(seed=20261106, features=frozen['features'], weights=w.tolist(),
                                    queries=shuffled.query, training_rows=len(rows), penalty=.1, steps=100,
                                    prediction_last=TRAIN_END))


def delta_report(after, before):
    return dict(top5=after['coverage']['primary']['hits']['5'] - before['coverage']['primary']['hits']['5'],
                annual={label: {year: dict(entries=after['accounts'][label]['annual'][year]['entries'] -
                    before['accounts'][label]['annual'][year]['entries'],
                    return_=after['accounts'][label]['annual'][year]['return'] - before['accounts'][label]['annual'][year]['return'])
                    for year in YEARS} for label in ('cash6', 'lever')},
                halfyear={period: dict(top5=after['coverage']['halfyear'][period]['hits']['5'] -
                    before['coverage']['halfyear'][period]['hits']['5'],
                    accounts={label: {key: after['accounts'][label]['halfyear'][period][key] -
                        before['accounts'][label]['halfyear'][period][key] for key in ('return', 'entries')}
                        for label in ('cash6', 'lever')}) for period in before['coverage']['halfyear']})


def search(shuffled=False):
    experiment = Experiment(shuffled)
    starts = read(REPORTS / (PREFIX + 'candidate_pool.json'))['starts']
    for label, initial in starts.items():
        target = REPORTS / (PREFIX + experiment.label + '_' + label + '.json')
        if target.exists():
            continue
        current = experiment.evaluate(initial)
        start_value = current
        forward_choice = current
        forward, reverse = [], []
        while True:
            best, changed, evaluated = None, None, 0
            for gate in experiment.gates:
                if gate['id'] in current['conditions']:
                    continue
                candidate = experiment.evaluate(current['conditions'] + [gate['id']])
                evaluated += 1
                if improving(candidate, current) and (best is None or score_key(candidate) > score_key(best)):
                    best, changed = candidate, gate['id']
                if evaluated % 40 == 0:
                    print(experiment.label, label, 'forward', len(forward), 'tried', evaluated,
                          'best', None if best is None else (best['coverage']['primary']['hits']['5'], best['eligible']), flush=True)
            if best is None:
                break
            forward.append(dict(added=changed, evaluated=evaluated, before=current['conditions'],
                                after=best['conditions'], delta=delta_report(best, current), eligible=best['eligible']))
            current = best
            if score_key(current) > score_key(forward_choice):
                forward_choice = current
            old.prior.write_json(WORK / (experiment.label + '_' + label + '_forward_checkpoint.json'),
                                  dict(start=start_value, steps=forward, current=current))
        forward_final = current
        current = forward_choice
        while current['conditions']:
            table, options = [], []
            for i in current['conditions']:
                candidate = experiment.evaluate([j for j in current['conditions'] if i != j])
                allowed = removable(candidate, current)
                table.append(dict(removed=i, after=candidate, delta=delta_report(candidate, current), removable=allowed))
                if allowed:
                    options.append((candidate, i))
            if not options:
                break
            best, removed = max(options, key=lambda pair: score_key(pair[0]))
            reverse.append(dict(removed=removed, before=current['conditions'], after=best['conditions'], table=table))
            current = best
        final_table = []
        for i in current['conditions']:
            candidate = experiment.evaluate([j for j in current['conditions'] if i != j])
            delta = delta_report(candidate, current)
            useful = [p for p, row in delta['halfyear'].items() if row['top5'] < 0 or
                      any(a['return'] < -EPS for a in row['accounts'].values())]
            final_table.append(dict(removed=i, after=candidate, delta=delta, useful_halfyears=useful,
                                    useful_only_one_halfyear=len(useful) == 1,
                                    removable=removable(candidate, current)))
        result = dict(start=start_value, forward=forward, forward_final=forward_final, forward_choice=forward_choice, reverse=reverse,
                      final=current, final_leave_one_out=final_table, shuffled=shuffled,
                      evaluation_last=TRAIN_END)
        old.prior.write_json(target, result)
        print('PATH FINAL', experiment.label, label, len(current['conditions']),
              current['coverage']['primary'], current['eligible'], flush=True)


def freeze_selection():
    paths = {name: read(REPORTS / (PREFIX + 'true_' + name + '.json')) for name in ('empty', 'class12', 'core5')}
    winner = max(paths, key=lambda name: score_key(paths[name]['final']))
    true = paths[winner]['final']
    nulls = {name: read(REPORTS / (PREFIX + 'shuffle_' + name + '.json')) for name in paths}
    null = max(nulls, key=lambda name: score_key(nulls[name]['final']))
    result = dict(winner_path=winner, final=true, passed=bool(true['eligible']),
                  status='合格' if true['eligible'] else '没有路径通过门槛；以下仅为描述性最佳覆盖组合',
                  shuffled_path=null, shuffled_final=nulls[null]['final'], selection_years=list(YEARS),
                  freeze_utc=datetime.now(timezone.utc).isoformat(), exam_used_for_selection=False,
                  plan_sha256=file_sha(PLAN), prereg_sha256=file_sha(PREREG),
                  candidate_sha256=file_sha(REPORTS / (PREFIX + 'candidate_pool.json')))
    write('frozen_selection', result)


def full_results():
    frozen = read(REPORTS / (PREFIX + 'frozen_selection.json'))
    experiment = Experiment(full=True)
    paths = {name: read(REPORTS / (PREFIX + 'true_' + name + '.json')) for name in ('empty', 'class12', 'core5')}
    for label, path in paths.items():
        target = REPORTS / (PREFIX + 'final_' + label + '.json')
        if target.exists():
            continue
        ids = path['final']['conditions']
        mask = experiment.mask(ids)
        selected, widths, top = experiment.selected(mask)
        book, stops = experiment.book(selected)
        accounts = {name: account(experiment.d, experiment.px, experiment.ema[name], rule, book, experiment.meta,
                                  end=experiment.end, detail=True) for name, rule in experiment.rules.items()}
        missing = {}
        flat = [q for rows in selected.values() for q in rows]
        for year in (*YEARS, '2026'):
            sample = [q for q in flat if experiment.keys[q][0].startswith(year)]
            counts = {str(i): sum(not np.isfinite(experiment.values(experiment.gates[i])[q]) for q in sample) for i in ids}
            passed = sum(any(not np.isfinite(experiment.values(experiment.gates[i])[q]) for i in ids) for q in sample)
            missing[year] = dict(selected=len(sample), passed_due_to_missing=passed,
                                  fraction=passed / len(sample) if sample else 0., by_condition=counts)
        missing_fail = None
        if any(v['fraction'] > .10 for v in missing.values()):
            strict, strict_width, strict_top = experiment.selected(experiment.mask(ids, missing_pass=False))
            strict_book, _ = experiment.book(strict)
            missing_fail = dict(coverage=experiment.coverage(strict_top),
                accounts={name: account(experiment.d, experiment.px, experiment.ema[name], rule, strict_book,
                            experiment.meta, end=experiment.end) for name, rule in experiment.rules.items()},
                widths=strict_width, note='预登记缺失压力测试，不参与条件选择')
        result = dict(conditions=ids, coverage=experiment.coverage(top), accounts=accounts, nightly_widths=widths,
                      widths={y: dict(distribution=distribution([n for d, n in widths.items() if d.startswith(y)]),
                          empty=sum(n == 0 for d, n in widths.items() if d.startswith(y))) for y in (*YEARS, '2026')},
                      missing=missing, missing_fail=missing_fail,
                      selected={day: [experiment.keys[q][1] for q in rows] for day, rows in selected.items()},
                      note='2026已被看过一次，不是干净的考试；未参与选择')
        old.prior.write_json(target, result)
        print('FULL FINAL', label, result['coverage']['annual']['2026']['primary'], flush=True)
    write('frozen_selection_check', dict(before=file_sha(REPORTS / (PREFIX + 'frozen_selection.json')),
                                         winner=frozen['winner_path']))


def random_controls():
    experiment = Experiment(full=True)
    seen = {}
    rankings = {}
    for label in ('empty', 'class12', 'core5'):
        final = read(REPORTS / (PREFIX + 'final_' + label + '.json'))
        ids = final['conditions']
        key = digest(ids)
        if key in seen:
            rankings[label] = dict(same_as=seen[key])
            continue
        seen[key] = label
        mask = experiment.mask(ids)
        draws = []
        for seed in range(1, 31):
            path = WORK / 'random' / (key + f'.{seed}.json')
            if path.exists():
                draws.append(read(path))
                continue
            selected, _, _ = experiment.selected(mask, seed)
            book, _ = experiment.book(selected)
            result = dict(seed=seed, selection_hash=digest(selected),
                accounts={name: account(experiment.d, experiment.px, experiment.ema[name], rule, book, experiment.meta,
                          end=experiment.end) for name, rule in experiment.rules.items()})
            old.prior.write_json(path, result)
            draws.append(result)
            print('random', label, seed, flush=True)
        table = {}
        for name in experiment.rules:
            table[name] = {}
            for period in (*YEARS, '2026', '2024_2025', 'all'):
                def value(account):
                    if period == 'all':
                        return account['total']
                    if period == '2024_2025':
                        return float(np.prod([1 + account['annual'][y]['return'] for y in YEARS]) - 1)
                    return account['annual'][period]['return']
                real = value(final['accounts'][name])
                values = [value(r['accounts'][name]) for r in draws]
                table[name][period] = dict(real=real, random_distribution=distribution(values),
                    rank_of_31=1 + sum(v > real for v in values), strictly_beats=sum(real > v for v in values),
                    percentile=(sum(real > v for v in values) + .5 * sum(real == v for v in values)) / 30)
        rankings[label] = dict(ranking=table, draws=draws)
        write('random', rankings)


def execution_rule(base, variant, stops):
    if variant == 'K0':
        return base
    return replace(base, risk=.0025, risk_low=.00125, risk_high=.004, add_r=0., add_levels=(1., 2.),
                   management_by_kind={}, intraday_kinds=tuple(stops), max_new_by_kind={}, max_new_long=5,
                   max_position=.35, max_gross=2.8, add_next_open=True)


def execution_experiments():
    frozen = read(REPORTS / (PREFIX + 'frozen_selection.json'))
    for full in (False, True):
        label = 'all' if full else 'training'
        experiment = Experiment(full=full)
        selected, _, _ = experiment.selected(experiment.mask(frozen['final']['conditions']))
        results = {}
        for variant in ('K0', 'K1', 'K2', 'K3', 'K4'):
            target = REPORTS / (PREFIX + 'execution_' + label + '_' + variant + '.json')
            if target.exists():
                results[variant] = read(target)
                continue
            book, stops = experiment.book(selected, variant)
            rule = execution_rule(experiment.rules['lever'], variant, stops)
            value = account(experiment.d, experiment.px, experiment.ema['lever'], rule, book, experiment.meta,
                            end=experiment.end, detail=True, stop_map=stops, cancel_loss_add=variant in ('K3', 'K4'),
                            entry_close_add=variant != 'K0')
            value.update(variant=variant, rules=asdict(rule), selection_hash=digest(selected),
                         stop_policy='min(signal_ADR20/2,.025)' if variant in ('K3', 'K4') else '.025')
            old.prior.write_json(target, value)
            results[variant] = value
            print('execution', label, variant, {y: round(r['return'], 4) for y, r in value['annual'].items()}, flush=True)
        if not full:
            allowed = [k for k, v in results.items() if all(v['annual'][y]['entries'] >= 52 and
                       v['annual'][y]['win'] is not None and v['annual'][y]['win'] <= .35 for y in YEARS)]
            best = max(allowed or list(results), key=lambda k: (
                np.prod([1 + results[k]['annual'][y]['return'] for y in YEARS]), -results[k]['maxdd']))
            write('frozen_execution', dict(winner=best, eligible=best in allowed, selection_years=list(YEARS),
                  training_geometric={k: geometric({'lever': v}) for k, v in results.items()},
                  frozen_before_2026_execution=True, selected_utc=datetime.now(timezone.utc).isoformat()))


def audit_prices(accounts, d):
    errors, checked = [], 0
    ci = {str(c): j for j, c in enumerate(d.A['codes'])}
    for label, account_value in accounts.items():
        for trade in account_value['trades']:
            j = ci[trade['code']]
            for e in trade['executions']:
                if e['action'] == 'end':
                    continue
                t = d.di[e['time']]
                checked += 1
                lo, hi = float(d.A['low'][t, j]), float(d.A['high'][t, j])
                tolerance = max(abs(lo), abs(hi), 1.) * 2e-6
                if not np.isfinite(lo + hi) or e['price'] < lo - tolerance or e['price'] > hi + tolerance:
                    errors.append(dict(account=label, code=trade['code'], execution=e, low=lo, high=hi))
    return dict(checked=checked, errors=errors)


def correction_comparison():
    experiment = Experiment(full=True)
    orders = read(old.WORK / 'baseline_orders.json')
    book = old.hc.make_books(experiment.d, orders, old.hh.observations(experiment.d, orders), True)[0]
    accounts = {}
    for correction in (False, True):
        for label, rule in experiment.rules.items():
            key = label + ('_corrected' if correction else '_original')
            accounts[key] = account(experiment.d, experiment.px, experiment.ema[label], rule, book,
                                     experiment.meta, end=experiment.end, detail=True, correction=correction)
    reference = read(REPORTS / 'strong_continue_ie5_account_baseline_lever.json')
    if accounts['lever_original']['trade_digest'] != reference['trades_digest']:
        raise AssertionError('ID original trades differ before correction')
    # The new engine differs from its IE5 source pin only in the opt-in branch.
    pinned = read_source_tree(old.WORK / 'source_pins/system_before_ie5_add_gap.py.txt')
    current = read_source_tree(Path(system.__file__))
    matching = ast.dump(pinned, include_attributes=False) == ast.dump(current, include_attributes=False)
    if not matching:
        raise AssertionError('engine change extends beyond optional correction')
    calls = []
    for name in ('common.py', 'shorts.py', 'study.py'):
        source = Path(__file__).parent / name
        tree = ast.parse(source.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'simulate':
                calls.append(dict(file=name, line=node.lineno,
                                  preopen=next((ast.unparse(k.value) for k in node.keywords if k.arg == 'preopen'), 'False(default)')))
    registered = read(ROOT / 'studies/martin_luk/reports/final_system_r74.json')
    result = dict(accounts=accounts, engine_change_only_opt_in_branch=matching,
                  registered=dict(calls=calls, source='studies/martin_luk/reports/final_system_r74.json',
                                  source_sha256=file_sha(ROOT / 'studies/martin_luk/reports/final_system_r74.json'),
                                  keys=list(registered), correction_applicable=False,
                                  return_change=0., reason='登记调用不启用preopen；该新分支不可达，强行开启会报配置错误；不改登记版'),
                  corrected_audit=audit_prices({k: v for k, v in accounts.items() if k.endswith('_corrected')}, experiment.d))
    write('correction_comparison', result)


def read_source_tree(path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'simulate':
            args = node.args.args
            while args[-1].arg in ('preopen_add_stop_gap', 'preopen_entry_close_add'):
                args.pop()
                node.args.defaults.pop()
            # Docstring is descriptive; only executable statements matter here.
            node.body = [n for n in node.body if not isinstance(n, ast.Expr) or not isinstance(n.value, ast.Constant)]
    class RemoveCorrection(ast.NodeTransformer):
        def visit_If(self, node):
            if any(name in ast.unparse(node.test) for name in ('preopen_add_stop_gap', 'preopen_entry_close_add')):
                return None
            return self.generic_visit(node)
    return RemoveCorrection().visit(tree)


def boundary_guard():
    def allowed(path):
        p = Path(os.fsdecode(path)).resolve()
        return p.is_relative_to(WORK.resolve()) or (p.parent == REPORTS.resolve() and p.name.startswith(PREFIX))
    def audit(event, args):
        if event == 'open':
            path, _, flags = args
            if not isinstance(path, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND) and not allowed(path):
                raise PermissionError('IE6 output boundary: ' + os.fsdecode(path))
        if event in ('socket.connect', 'socket.bind', 'os.system', 'subprocess.Popen'):
            raise PermissionError('IE6 offline single process')
        if event in ('os.remove', 'os.rename', 'os.rmdir', 'os.mkdir'):
            paths = args[:2] if event == 'os.rename' else args[:1]
            if any(not allowed(p) for p in paths):
                raise PermissionError('IE6 output boundary')
    sys.addaudithook(audit)


def main(stage):
    WORK.mkdir(exist_ok=True)
    for name in ('design', 'evaluations', 'accounts', 'random'):
        (WORK / name).mkdir(exist_ok=True)
    if stage == 'preregister':
        preregister()
        return
    if read(REPORTS / (PREFIX + 'candidate_pool.json'))['plan_sha256'] != file_sha(PLAN):
        raise ValueError('task changed')
    boundary_guard()
    pins = {str(p.relative_to(ROOT)): file_sha(p) for p in (Path(__file__), PLAN, PREREG,
        Path(system.__file__), Path(preopen.__file__), old.FROZEN, old.WORK / 'prepared.json',
        old.WORK / 'raw.npy', old.WORK / 'account_rules.json', REPORTS / (PREFIX + 'candidate_pool.json'))}
    actions = dict(prepare=prepare, setup=setup_search, search=lambda: search(False),
                   shuffle=lambda: search(True), freeze=freeze_selection, finals=full_results,
                   random=random_controls, execution=execution_experiments, correction=correction_comparison)
    actions[stage]()
    if any(file_sha(ROOT / name) != sha for name, sha in pins.items()):
        raise ValueError('pinned input changed during stage')
    write('runtime_' + stage, dict(stage=stage, source_sha256=pins,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        completed_utc=datetime.now(timezone.utc).isoformat()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('preregister', 'prepare', 'setup', 'search', 'shuffle', 'freeze',
                                         'finals', 'random', 'execution', 'correction'))
    main(parser.parse_args().stage)
