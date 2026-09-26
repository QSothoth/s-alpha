# RG1：对照的既有G记录重叠审计

2026-09-26，事后描述性审计，不是新候选、第二次验证或门槛修订。只读冻结的118条事件及其80个原peer链接／既有30分钟标签，没有读取任何价格文件、调用行情API、重新生成信号或标签，也没有计算新区间。原[登记](RG1_PREREG.md)、[报告](../reports/rg1_asset_transfer.json)及`ASSET_TRANSFER_NOT_PASSED`判定不变。

## 定义：有先前记录，不等于此刻仍满足结构

对事件E的每个原peer P，仅检查原事件清单是否存在：同日、标的P、`original_direction`与E相同、G记录时刻≤E时刻。满足者记为 **already-recorded same-original-direction G**（此前或同刻已有同原方向G记录）。用的是原G方向，不是翻转后的预测方向；不利用E时刻之后才出现的记录判断是否重叠。

这个定义**不是 exact contemporaneous G／no-G 分类**。较早出现过G，随后可能已触回边界；本审计不读当前价格，不能证明它此刻仍满足G。剩余对照也只能叫“没有上述先触发记录”，不能称从未／以后不会触发，更不能冒充已经重建了当前no-G状态。因此这里只量化原对照共享既有触发记录的程度，不识别边界结构的因果效应。

## 计数与覆盖

| 项目 | 数量 |
|---|---:|
| 原事件／原matched事件／原无peer事件 | 118／64／54 |
| 原peer链接 | 80 |
| 有上述既有G记录的链接 | 41（51.25%） |
| 其中同clock记录／较早clock记录 | 38／3 |
| 至少一个上述链接的matched事件 | 34／64（53.13%） |
| 没有上述链接的matched事件 | 30 |
| 同时含重叠与非重叠peer的事件 | 0 |
| 描述性移除41条重叠控制后，剩余链接／有控制事件 | 39／30 |

34条受影响事件中，27条有一个重叠peer，7条有两个；它们原有peer恰好全部属于该标记，因此这34条在本审计口径下无剩余对照。另30条有21个单peer事件、9个双peer事件，原peer全部保留。不存在按收益优劣在同一事件内挑控制的步骤。

剩余对照覆盖为 **30／118＝25.42%**，或原matched队列内30／64＝46.88%；不能把后者当总体覆盖。无剩余对照为88条，其中原本无peer54条、新增34条；均是“无对照”，不是未来价格标签缺失，不能填零。原118条自身标签一条未删。

三条“较早clock”链接分别为：2021-06-24 XLY 09:50→XLV 09:45；2022-01-24 XLI 09:50→XLV、XLY各09:45。这三条尤其不能依据早先记录断言09:50仍是hold状态。

## 仅复用已有标签的等权会计

每条事件先将其保留peer的原`peer_returns`等权平均，再对事件等权汇总；不是把39或80个链接直接平均。事件收益、peer收益均仍为原事件时刻及原反方向的固定30分钟标签，没有换clock。

| 队列 | 事件数 | 自身均值bp | 每事件控制均值bp | 自身减控制bp |
|---|---:|---:|---:|---:|
| 原matched队列 | 64 | +21.3830 | +17.9477 | +3.4353 |
| 尚有“无先触发记录”控制的描述性队列 | 30 | +2.8252 | −4.5670 | +7.3921 |

第二行不是“改进后RG1”：它对应更小、非随机且在看过结果后定义的队列，自身均值与第一行已经不同。+7.3921bp不能解释成原118条的总体增量，不能与原paired下限拼接，也没有新的显著性或晋级含义。这只是队列均值，不代表删除34条自身事件即可执行的新策略；未另算筛后胜率、PF或任何新的bootstrap区间。

可支持的判断是：原peer确实经常也有同方向G的既有记录，因而不能把原paired直接解释为“有20日结构”相对于“没有20日结构”的干净比较；但按这个有限记录标记移除控制后，可用覆盖只剩四分之一，现有三ETF不足以稳健隔离结构增量。它既不推翻已有raw方向线索，也不证明边界机制成立或无效。不据此开展下一轮近邻阈值搜索。

## 指纹与最小复算

唯一数据输入：`data/rg1-asset-transfer-signals-20260926.jsonl`，118行，SHA256 `8bbb1a564c2b403916b40ed5c6f0b7c4be01e6882a535784ee0b4c6569929be4`。该指纹与原[运行记录](RG1_RUN_RECORD.md)一致。以下标准库片段只汇总这个小型派生文件，不调用引擎、不读K线、不产生文件：

```python
import hashlib, json, math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

p = Path('data/rg1-asset-transfer-signals-20260926.jsonl')
pin = '8bbb1a564c2b403916b40ed5c6f0b7c4be01e6882a535784ee0b4c6569929be4'
assert hashlib.sha256(p.read_bytes()).hexdigest() == pin
with p.open() as handle:
    events = [json.loads(line) for line in handle]
assert len(events) == 118
recorded = defaultdict(list)
for e in events:
    recorded[e['time'][:10], e['symbol']].append(e)

counts, original, remaining = Counter(), [], []
for e in events:
    names, values = e['peers'], e['peer_returns']
    assert len(names) == len(values)
    if e['paired_status'] != 'complete':
        assert not names and e['paired_lift'] is None
        counts['original_no_peers'] += 1
        continue
    counts['original_matched'] += 1
    counts['original_links'] += len(names)
    keep, overlap = [], 0
    for name, value in zip(names, values):
        assert value is not None
        prior = [g for g in recorded[e['time'][:10], 'US.' + name]
                 if g['original_direction'] == e['original_direction']
                 and datetime.fromisoformat(g['time']) <= datetime.fromisoformat(e['time'])]
        if prior:
            overlap += 1
            first = min(prior, key=lambda g: g['time'])
            counts['same_clock' if first['time'] == e['time'] else 'earlier_clock'] += 1
        else:
            keep.append(value)
    counts['overlap_links'] += overlap
    counts['events_with_overlap'] += bool(overlap)
    counts['mixed_events'] += bool(overlap) and bool(keep)
    counts['remaining_links'] += len(keep)
    own, control = e['return_30m'], math.fsum(values) / len(values)
    assert math.isclose(own - control, e['paired_lift'], abs_tol=1e-15)
    original.append((own, control, own - control))
    if keep:
        control = math.fsum(keep) / len(keep)
        remaining.append((own, control, own - control))

assert (len(original), len(remaining), counts['original_links'], counts['overlap_links']) == (64, 30, 80, 41)
assert counts['same_clock'] == 38 and counts['earlier_clock'] == 3 and counts['mixed_events'] == 0
print(dict(counts), 'coverage', len(remaining) / len(events))
for name, rows in [('original', original), ('remaining_controls', remaining)]:
    print(name, len(rows), [10000 * math.fsum(row[i] for row in rows) / len(rows) for i in range(3)])
```

新信息仅为这份描述性分解；原事件、价格、预登记和策略代码均未修改，另外9只ETF及09/25价格未打开。
