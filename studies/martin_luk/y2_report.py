"""Render Y2 from sealed attribution artifacts; no account or label evaluation."""
import argparse
from collections import defaultdict
import csv
import re

from . import y2_research as Y

LABELS = dict(IE47_C062='IE47+C062', master_C062='master+C062', registered_master='登记 master',
              M1B='M1B', M2A='M2A', M3B='M3B')
TARGETS = ('capital', 'gross', 'early', 'capture', 'top10')


def pct(x):
    return '—' if x is None else f'{100*x:.1f}%'


def amount(x):
    return f'{x:+.3f}'


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |', '| '+' | '.join('---' for _ in headers)+' |',
                      *['| '+' | '.join(map(str, row))+' |' for row in rows]])


def tests():
    out = {}
    for name in ('martin_luk', 'trader_replication', 'custody'):
        path = Y.WORK/f'test_{name}.log'
        if not path.exists():
            out[name] = dict(ok=False, reason='not run')
            continue
        text = path.read_text()
        count = re.findall(r'Ran (\d+) tests? in ([0-9.]+)s', text)
        end = text.strip().splitlines()[-1]
        out[name] = dict(ok=bool(count) and bool(re.fullmatch(r'OK(?: \([^\n]*\))?', end)),
            n=int(count[-1][0]) if count else None, seconds=float(count[-1][1]) if count else None,
            ending=end, sha256=Y.sha(path), log=path.name)
    return out


def pairs(accounts, vintage):
    for name in Y.NAMES:
        account = accounts.get(name+'__'+vintage)
        if account:
            for year, old in account['years']['Y1'].items():
                yield name, year, old, account['years']['lifecycle'][year]


def annual_table(accounts, vintage):
    rows = []
    for name, year, a, b in pairs(accounts, vintage):
        ca, cb = a['coverage']['including_censored'], b['coverage']['including_censored']
        rows.append([LABELS[name], year, pct(b['account_return']),
            f"{pct(a['cap_equity'])} → {pct(b['cap_equity'])}",
            f"{pct(a['purity_gross'])} → {pct(b['purity_gross'])}",
            f"{ca['covered']}/{ca['n']} → {cb['covered']}/{cb['n']}",
            f"{pct(a['capture_total'])} → {pct(b['capture_total'])}",
            f"{a['top10_his_leg']} → {b['top10_his_leg']}",
            f"{sum(a['targets']['checks'][k] for k in TARGETS)}/5 → {sum(b['targets']['checks'][k] for k in TARGETS)}/5"])
    return table(['账户','年','原账户收益','资金纯度','毛利纯度','早买段','段吃到','前10赢单H笔数','五线通过数'], rows)


def export_winners(accounts):
    rows = []
    specs = Y.accounts()
    for key, account in accounts.items():
        raw = Y.read(specs[key]['trades'])
        for year, old in account['years']['Y1'].items():
            current = {r['id']:r for r in account['years']['lifecycle'][year]['top10']}
            for rank, r in enumerate(old['top10'], 1):
                t = raw[r['id']]
                rows.append(dict(account=account['name'], vintage=account['vintage'], year=year, rank=rank,
                    trade=r['id'], code=r['code'], entry=t['entry'], exit=t['exit'], pnl=r['pnl'],
                    Y1_H=r['H'], lifecycle_H=current[r['id']]['H']))
    with (Y.WORK/'top10_winners.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def render():
    accounts = Y.read(Y.WORK/'accounts.json')
    complete = Y.read(Y.WORK/'evaluation_complete.json')
    audit = Y.read(Y.WORK/'artifact_checks.json')
    assert audit['ok']
    windows = Y.read(Y.WORK/'windows.json')
    peaks = {r['key']:r for r in windows}
    top = Y.read(Y.WORK/'top10_leg_differences.json')
    checks = tests()
    continuous = list(pairs(accounts, 'continuous'))
    all_rows = continuous+list(pairs(accounts, 'standalone'))
    old_pass = sum(a['targets']['passed'] for _,_,a,b in continuous)
    new_pass = sum(b['targets']['passed'] for _,_,a,b in continuous)
    most_cap = max(continuous, key=lambda r:r[3]['cap_equity'])
    most_gross = max(continuous, key=lambda r:r[3]['purity_gross'])
    early = sum(g['start_minus_y1'] < 0 for g in windows)
    later = sum(g['start_minus_y1'] > 0 for g in windows)
    lots, predates = [], {}
    for key, account in accounts.items():
        diff = Y.read(Y.WORK/(key+'__differences.json'))
        if account['vintage'] == 'continuous':
            lots.extend(dict(r, account=account['name']) for r in diff['lots'])
        run = Y.read(Y.WORK/(key+'__lifecycle.json'))
        predates[key] = {}
        for year in account['years']['lifecycle']:
            rs = [r for r in run['lots'] if r['year'] == year and r['bucket']=='T1']
            before = [r for r in rs if r['original_exit'] < peaks[r['leg']]['first']]
            predates[key][year] = dict(pnl=sum(r['h_pnl'] for r in before),
                gross=sum(max(r['h_pnl'],0.) for r in before),
                pieces=len({(r['trade'],r['lot_piece']) for r in before}))
    lots.sort(key=lambda r:-abs(r['delta']))
    Y.write('old_positions_and_pre_anchor.json', dict(pre_anchor_exits=predates,
        largest_lot_reclassifications=lots[:50]))
    export_winners(accounts)
    stale_gp = sum(account['old_position_audit'][y]['lot']['gross'] for key,account in accounts.items()
                   if account['vintage']=='continuous' for y in account['old_position_audit'])
    h_gp = sum(account['old_position_audit'][y]['gross_H'] for key,account in accounts.items()
               if account['vintage']=='continuous' for y in account['old_position_audit'])
    stale_trade_gp = sum(account['old_position_audit'][y]['trade']['gross'] for key,account in accounts.items()
                         if account['vintage']=='continuous' for y in account['old_position_audit'])
    ie_old = accounts['IE47_C062__continuous']['years']['Y1']['2025']
    ie_new = accounts['IE47_C062__continuous']['years']['lifecycle']['2025']
    extra = next(r for r in lots if r['y1_H']==0 and r['lifecycle_H']>0)
    extra_leg = peaks[next(s['leg'] for s in extra['lifecycle_slices'] if s['leg'])]
    extra_reason = ('原买入早于Y1资格下限'+extra_leg['y1_start_date'] if extra['entry']<extra_leg['y1_start_date']
                    else '旧按成交日归属没有把它算进该H段')
    lines = ['# Y2：按主升浪生命周期，重看钱和利润花在哪里', '',
        f'**改用生命周期并按持有时间切片后，六个连续账户的18个年度中，五条目标连同行为底线全过为{new_pass}行；Y1口径为{old_pass}行。** '
        f"生命周期资金纯度最高是{LABELS[most_cap[0]]} {most_cap[1]}的{pct(most_cap[3]['cap_equity'])}，目标50%；"
        f"毛利纯度最高是{LABELS[most_gross[0]]} {most_gross[1]}的{pct(most_gross[3]['purity_gross'])}，目标60%。", '',
        '新口径会接回更早买入、后来持有穿过行情的仓位，也会计入在本人锚点之前已结束的交易。'
        f'实际lot在生命周期起点前超过20个交易日就买入的部分，占六个连续账户H毛利合计的{pct(stale_gp/h_gp if h_gp else None)}；'
        f'若按整笔交易的最初开仓日判断则为{pct(stale_trade_gp/h_gp if h_gp else None)}。分账户、分年净pnl和毛利占比见第5节。'
        '这是同一批历史成交的归因变化，没有增加真实账户收益，也没有改选股或执行。', '',
        '表格中的箭头一律为 **Y1现行口径 → 生命周期口径**。金额单位为各账户初始本金1，2026截止2026-10-16。', '',
        '## 1. 六个三年连续账户，两把尺子并列', '',
        '每个账户都从2024-01-02连续持有至2026-10-16，含跨年带入仓。登记master为已存D1的R74+S7原登记多空账户，'
        '空头的净pnl、毛利及资金保留在全账户分母并归O；不拿只含多头的子账冒充登记账户。', '',
        annual_table(accounts, 'continuous'), '',
        table(['目标线','门槛'], [['资金纯度','全年mean(H当日市值/当日权益) ≥50%，含现金日'],
            ['毛利纯度','H正盈亏切片/全账户正盈亏切片 ≥60%'],['早买','至少一半冻结段，向上取整'],
            ['段吃到','H净pnl / Σ(股数×原成本×首锚点涨幅) ≥50%'],['前10赢单','至少5笔整笔已平仓赢家有正的H净贡献'],
            ['行为底线','每年≥52笔、已平仓胜率≤35%']]), '',
        '这些阈值沿用Y1，不按本轮结果改门槛。年度收益来自原权益曲线，整笔pnl仍按首次开仓年，'
        '资金按日历年，早买和吃到按原段锚点年；三种年归属不能互相相减。', '',
        '## 2. H和O分别赚多少', '',
        'H为窗口内净贡献，O=原交易总pnl−H。H升高只是把同一笔收益从O重新划来；O也可能为负。'
        '净纯度在交易总pnl≤0时为“—”。', '',
        table(['账户','年','交易总pnl','H','O','净纯度','H/已用资金','H/确认仓'],
              [[LABELS[name],year,amount(b['total_pnl']),f"{amount(a['H'])} → {amount(b['H'])}",
                f"{amount(a['O'])} → {amount(b['O'])}",f"{pct(a['purity_net'])} → {pct(b['purity_net'])}",
                f"{pct(a['cap_share'])} → {pct(b['cap_share'])}",f"{pct(a['cap_conf'])} → {pct(b['cap_conf'])}"]
               for name,year,a,b in continuous]), '',
        '原账户的融资、期末估值卖费和空头借券费在逐账户reconciliation中保留。登记master的完整三年融资没有独立保存的分项，'
        '只报告由交易pnl、终值和估值卖费反推的融资差额；其余账户可与已存融资逐值核对。'
        '所有成交、FIFO和原账户权益曲线都未重跑。', '',
        '## 3. 已有的2026单开账户', '',
        '以下均是2026-01-02重新以本金1开始的已存账户，与连续账户分开。登记master未找到单开2026的逐笔+曲线组合，'
        '不凭汇总数字反造。', '',annual_table(accounts, 'standalone'), '',
        table(['账户','交易总pnl','H','O','lot起点前>20日净pnl/H','对应毛利/H毛利'],
              [[LABELS[name],amount(b['total_pnl']),f"{amount(a['H'])} → {amount(b['H'])}",
                f"{amount(a['O'])} → {amount(b['O'])}",
                pct(accounts[name+'__standalone']['old_position_audit'][year]['lot']['net_share']),
                pct(accounts[name+'__standalone']['old_position_audit'][year]['lot']['gross_share'])]
               for name,year,a,b in pairs(accounts,'standalone')]), '',
        '## 4. 差额最大的10个段、10份FIFO成交', '',
        '先对六个连续账户中同一冻结段的|生命周期H−Y1 H|求和，再取前10个不同段。'
        '这只是定位归因差额的排序，各账户都以原始本金1计；增长快的账户会自然占更大权重，不能用这个合计给策略排收益名次。', '',
        table(['票/本人锚点','生命周期起点','峰值',*[LABELS[n]+' ΔH' for n in Y.NAMES]],
            [[g['accounts'][0]['code'].removeprefix('US.')+' '+g['accounts'][0]['anchor'],
              g['accounts'][0]['start'],g['accounts'][0]['peak'],
              *[amount(next(r['delta'] for r in g['accounts'] if r['account']==n)) for n in Y.NAMES]] for g in top]), '',
        '下面按单份匹配FIFO lot的|ΔH|列前10。买入价是真实成本；跨窗边界只估值，不虚构成交。'
        '同一来源买入被FIFO分次卖出时，各份股数分开保留。完整段差额与全部lot切片见每组__differences.json和__lifecycle.json。', '',
        table(['账户/票','trade/piece','原买入→卖出','成本/股数','Y1 H','生命周期H','ΔH'],
            [[LABELS[r['account']]+'/'+r['code'].removeprefix('US.'),f"{r['trade']}/{r['piece']}",
              r['entry']+' → '+r['exit'],f"{r['cost']:.2f}/{r['shares']:.6f}",amount(r['y1_H']),
              amount(r['lifecycle_H']),amount(r['delta'])] for r in lots[:10]]), '',
        f"例如{LABELS[extra['account']]}的{extra['code'].removeprefix('US.')} trade {extra['trade']}/piece {extra['piece']}，"
        f"在{extra['entry']}按{extra['cost']:.2f}买入，{extra['exit']}卖出；{extra_reason}。"
        f"新窗口为{extra_leg['start_date']}至{extra_leg['peak_date']}，只把相交部分{amount(extra['lifecycle_H'])}划入H，"
        '窗口外的盈亏仍在O。逐片的起始估值和pnl保存在差额工件中。', '',
        f"早买改善也不等于吃到更多。IE47+C062在2025从{ie_old['coverage']['including_censored']['covered']}/22早买"
        f"变为{ie_new['coverage']['including_censored']['covered']}/22，但H从{amount(ie_old['H'])}变为{amount(ie_new['H'])}，"
        f"按段归组的资金潜力分母从{ie_old['coverage']['including_censored']['potential_total']:.3f}变为"
        f"{ie_new['coverage']['including_censored']['potential_total']:.3f}，吃到由{pct(ie_old['capture_total'])}变为{pct(ie_new['capture_total'])}。"
        '新窗口纳入了更多早期尝试，也会移走最低点之前的贡献，不能用早买段数替代利润成绩。', '',
        f'48个冻结段中，生命周期起点比Y1入场资格下限更早{early}段、更晚{later}段、相同{48-early-later}段。'
        '所以新口径不是把Y1窗口统一向左延长：某些最低点发生在本人锚点之后，会移走旧H的早期盈亏；'
        '同票重叠段也可能把同一份持仓在不同时间分给不同峰。', '',
        '## 5. 会不会把很久以前的仓位也算进来', '',
        '**会，只要真实持仓与生命周期窗口相交，就纳入相交部分；不能据此认定当时买入的动机与他一致。** '
        '下面严格按实际lot首次买入日与段起点相差>20个冻结交易日审计。只计算窗口内pnl，不把起点之前已经赚到的钱搬入H。'
        '净占比=这类切片净pnl/H净pnl，H≤0时不定义；毛利占比=这类正切片/H全部正切片，避免盈亏抵消误读。'
        '“交易初开”还会把早已开仓但后来加买的份额算入，作为更宽的审计列。', '',
        table(['账户','年','旧lot匹配份数','旧lot窗口pnl','净pnl/H','毛利/H毛利','交易初开>20日：净pnl/H','其毛利占比'],
            [[LABELS[name],year,accounts[name+'__continuous']['old_position_audit'][year]['lot']['matched_pieces'],
              amount(accounts[name+'__continuous']['old_position_audit'][year]['lot']['pnl']),
              pct(accounts[name+'__continuous']['old_position_audit'][year]['lot']['net_share']),
              pct(accounts[name+'__continuous']['old_position_audit'][year]['lot']['gross_share']),
              pct(accounts[name+'__continuous']['old_position_audit'][year]['trade']['net_share']),
              pct(accounts[name+'__continuous']['old_position_audit'][year]['trade']['gross_share'])]
             for name,year,a,b in continuous]), '',
        '按窗口对齐能回答“钱有没有处在同一主升浪里”，单靠时间相交不能证明同一选股逻辑。'
        '生命周期起点本身由未来峰值回看得到，只能作评测标签。超过20日列为审计，未据此另删H、调门槛或重算2026。'
        '起点后买入、但在本人锚点前已经全卖出的部分另存old_positions_and_pre_anchor.json。', '',
        '## 6. 前10赢单与五线逐条判断', '',
        '前10按真实已平仓整笔pnl排序，期末end估值不算赢家；两把尺子的十笔名单完全一致，仅H净贡献改变。'
        '表中列有正H净贡献的名字，同票多笔保留重复。完整十笔的开/平日、整笔pnl和两种H金额见'
        '[top10_winners.csv](y2_work/top10_winners.csv)。', '',
        table(['账户','年','Y1有正H的前10名字','生命周期有正H的前10名字','五线：资金/毛利/早买/吃到/前十','笔数/已平仓胜率'],
            [[LABELS[name]+(' 单开' if vintage=='standalone' else ''),year,
              '、'.join(r['code'].removeprefix('US.') for r in a['top10'] if r['H']>0) or '无',
              '、'.join(r['code'].removeprefix('US.') for r in b['top10'] if r['H']>0) or '无',
              ''.join('✓' if a['targets']['checks'][k] else '×' for k in TARGETS)+' → '+
              ''.join('✓' if b['targets']['checks'][k] else '×' for k in TARGETS),
              f"{b['n_trades']}/{pct(b['win'])}"]
             for vintage in ('continuous','standalone') for name,year,a,b in pairs(accounts,vintage)]), '',
        '## 7. 精确定义和保留项', '',
        '唯一段表、48段身份、原锚点、原gain、峰值和9/22/17年度分母全部沿用Y1。'
        '新增参数为mainleg.summary_account(..., lifecycle=True)，默认False。'
        '生命周期起点s取peak前60个交易日到peak当日（含端点，共最多61个观测）的最低low，平低取最早日；终点仍为peak。'
        'T1/H只指这48段，未用其他股票或小段扩充H。', '',
        '持仓在每个窗口起点和峰值后一天切开，同票重叠时逐时间段选择top/原成本−1最大的段，'
        '平手按原锚点、段key；同一股数同一天只归一次。已卖出日收盘无持仓，期末估值仍保留末日敞口。'
        '窗口外统归O，生命周期不另细分T2；旧Y1的T1/T2/T3/other/post_peak仍原样保存。', '',
        '若切片从交易日b开始，且原lot在b之前已持有，起始估值用close[b−1]；'
        '结束在窗口末日e时用close[e]，实际卖出则用真实fill。由此窗口首日的价格变化计入H。'
        '买入费只在真实买入所在首切片，卖出费和公开残差只在最后切片；所有切片pnl之和严格回到原lot和交易。', '',
        '设g的首锚点收盘为C_g、峰值high为T_g、原涨幅γ_g=T_g/C_g−1；'
        'h为该段第一次分配到的窗口内持有日，若同日已持有多份则先取实际买入更早的FIFO成本p。', '',
        '```text\n早买 = [T_g/p − 1 ≥ 0.5 × γ_g]\n'
        'capture_total = ΣH切片净pnl / Σ(匹配FIFO份额 q × 原成本p × γ_g)\n'
        'capture_rem = ΣH切片净pnl / Σ(q × 原成本p × (T_g/p−1))\n'
        '资金纯度 = mean_全年交易日(H收盘持仓市值 / 原账户收盘权益)\n'
        '毛利纯度 = Σmax(H切片pnl,0) / Σmax(所有H/O切片pnl,0)\n```', '',
        '早买用实际成本，不用切点估值重置；capture分母同一匹配FIFO份额在同一段只计一次，'
        '同票不同段的互不重叠持有时间可以各自贡献。毛利分母也随切片改变，不能把比例变化全部当成H净pnl变化。'
        '确认仓从真实确认日开始，未追溯放大此前试仓。', '',
        '2026保留两个截断段，并在每组工件的excluding_censored中另报剔除口径；'
        '剔除不把原归截断段的份额转送其他段。事件段和exact/chart/window分层沿用原锚点年与原时长，均在coverage中保存。', '',
        table(['2026连续账户','口径','早买段','资金纯度','毛利纯度','段吃到','H'],
            [[LABELS[name],label,'{}/{}'.format(row['coverage']['covered'],row['coverage']['n']),
              pct(row['cap_equity']),pct(row['purity_gross']),pct(row['capture_total']),amount(row['H'])]
             for name in Y.NAMES for label in ('Y1','lifecycle')
             for row in [accounts[name+'__continuous']['years'][label]['2026']['excluding_censored']]]), '',
        '上表均为不含截断两段的结果；主表为含截断。未覆盖的截断段仍属未决。'
        '本轮为固定定义的只读对照，不拟合、不选新版本，不把2026称为新独立样本外。', '',
        '## 8. 工件和验收', '',
        f"冻结段表SHA256：`{Y.sha(Y.Y1.FROZEN)}`。"
        'protocol.json在重算前封存公式、11组台账来源和输入指纹；preflight.json记录FIFO、持仓收盘价及账户融资核对。'
        'IPO首日可能没有前收盘，只对真实持仓实际跨越的切点要求前收盘，修订在protocol的preflight_amendment中保留；'
        '修订发生在任何账户指标重算之前。', '',
        'Y1已发布报告和y1_work逐文件核对不变，未改登记、看板、账户决策或F3文件。'
        'default_matches_saved覆盖10组已有完整指标工件的账户；登记master为首次完整同口径归因，没有假称Y1过去已有这组数字。', '',
        '另用未切片FIFO逐日累加真实价格变化和收盘持仓，独立核对11组账户的H净pnl、每日H/总资金、确认仓及费用守恒，'
        '全部通过；没有调用新的区间归属函数。结果与可重跑脚本在artifact_checks.json和verify_artifacts.py。', '',
        table(['测试组','测试数','结果','原始日志'],
              [[k,v.get('n','—'),v.get('ending','未运行'),v.get('log','—')] for k,v in checks.items()]), '',
        '首次trader_replication测试中，10项IE21旧试验报fixed engine lifecycle anchor moved；'
        '共享system.py在该次测试期间被并行修改。新进程使用本轮修改前的mainleg副本独立运行14项IE21测试已全部通过，'
        '随后重跑完整trader_replication组，并在资源日志记录引擎前后指纹。首次失败日志保留为'
        'test_trader_replication_concurrent_engine_change.log，隔离记录为isolated_ie21.json；没有为通过测试改共享引擎或旧试验。', '',
        f"重算峰值RSS {complete['resources']['peak_rss_mib']:.1f} MiB；实读CPUQuota对应cpu.max为"
        f"`{complete['resources']['cpu_max']}`，MemoryMax为`{complete['resources']['memory_max']}`字节，线程数"
        f"{complete['resources']['threads']}。逐账户处理，股票价格缓存最多16项，缺失股票复用U1只读mmap；"
        '没有全市场N×N矩阵或无界加载。三组测试串行运行，每组都放在相同资源scope中。未联网、未拉数据、未提交git。', '',
        '工件在[y2_work](y2_work/)：每组__Y1.json与__lifecycle.json保留全部归属和日资金，'
        '__differences.json保留逐段/逐lot差额及旧仓审计，top10_leg_differences.json与top10_winners.csv可直接复核。'
        'completion.json汇总验收、三组测试、代码和工件指纹。', '',
        '只重新渲染，不重开评测：', '',
        '```bash\nsystemd-run --scope -p CPUQuota=60% -p MemoryMax=900M -q env '
        'OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 '
        'PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m studies.martin_luk.y2_report\n```', '']
    Y.REPORT.write_text('\n'.join(lines), encoding='utf-8')
    print('Rendered Y2_CN.md and complete top10 winner/audit artifacts')


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    Y.offline()
    Y.resources()
    render()
