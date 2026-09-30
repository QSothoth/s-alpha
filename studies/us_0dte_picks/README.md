# 美股末日期权选标的

每天从周一、周三、周五有当日到期期权（0DTE）的个股中，选出最多 5 只、带做多或做空方向的名单，可以为空；不含指数和 ETF。先用日线形态筛候选，再在 10:00 确认方向，关注相对隐含剩余波动足够大的行情。买卖时机交给用户的日内执行，本目录不下单。

**接手请先读 [notes/HANDOFF.md](notes/HANDOFF.md)**：用户要求、目前结论、没做完的事与环境要点。

## 人工候选的盘中监测

**2026-09-29 更新：用户允许最近到期，不再只限 0DTE。** 今日运行与统一入口见 [操作流程](notes/WORKFLOW_CN.md) 和 [今日会话](notes/SESSION_20260929.md)。`prepare_watch --launch` 生成当天排名、15／30 分钟基准并启动观察；`session status` 汇总；`session accept` 按当前卡先 dryrun、再人工明确选择执行模式。旧研究工具 `daily_list` 的 0DTE 口径不变。

用户于 2026-09-28 确认先从当日候选里选相对最好的 1–2 个机会，盘中观察后交给既有执行策略。[live_watch.py](live_watch.py) 接收当日盘前排名和已冻结的 15／30 分钟量基准，在每个整分钟结束后约 3 秒更新候选、真实合约报价、预算检查与原版 `open_hold_v3` 的状态。只输出供人工审视的草稿，不发送订单，也不调用历史 K 线接口。

正式试运行优先用受 systemd 托管的启动器。它限制内存和最长运行时间，并等到所有候选指定最近到期日的标准 Call／Put 链核验完成后才报告成功：

```bash
PYTHONUTF8=1 python3 -m studies.us_0dte_picks.launch_watch \
  --candidates data/当天目录/ranking.json \
  --baselines data/当天目录/baselines.json \
  --out data/当天目录/monitor \
  --until 10:45 --budget-usd 300 --fee-reserve-usd 20
```

启动成功以 `ready.json` 为准；`latest.json` 保存完整观察，`review_card.json` 是给人工环节的短卡。短卡只有在原版 v3 **本分钟首次**产生入场意图且当前合约仍通过到期日、报价、流动性和预算检查时才显示 `ENTER_REVIEW`，并给出可原样传入 custody 的 `custody_request`。卡片的 `valid_until` 到下一分钟，过期必须等新卡；旧的 `EARLIER_ENTRY_UNFILLED` 只留在审计记录，不能追单。人工确认后先用 `python3 -m custody dryrun` 核对参数和实时状态；真实委托仍只能由明确启动的 `python3 -m custody run --mode live ...` 执行。

```bash
PYTHONUTF8=1 /opt/futu-opend/venv/bin/python -m studies.us_0dte_picks.live_watch \
  --candidates data/human-top10-2026-09-28-090327/ranking.json \
  --baselines data/human-trial-2026-09-28/baselines.json \
  --out data/human-trial-2026-09-28/new-monitor \
  --until 10:05 --budget-usd 300 --fee-reserve-usd 20
```

盘前排名与分母必须提前准备且日期有效，输出目录必须不存在。`latest.json` 是最新状态，每分钟另留一份快照。按开盘至当前的绝对变动除以前日 IV 对应的剩余时段尺度排序，再比较同段量比；这只是人工候选排序，未经独立验证。开盘 15–29 分钟时量比固定比较首 15 分钟，30 分钟后比较首 30 分钟，均除以此前 14 个完整日同段均量；不足 15 分钟只观察正股。量比 1.5 不作本模式的一票否决，A4 研究规则不变。

合约草稿要求所选最近到期日的标准合约（旧输入未提供到期日时仍要求当日到期）、乘数 100、绝对 Delta ≥0.30、当日成交至少 100 张、正且未交叉的买卖价、相对价差 ≤10%、报价时间距读取不超过 30 秒。在每只股票最近五档行权价中取符合预算的最近档，最多两只、每只一张；优先保留排序最高的可负担标的。以上述 300 美元预算为例，一笔权利金上限 280 美元，若前两笔都能各用 140 美元则分配两笔，余 20 美元仅为费用预留，实际费用需核对账户套餐。草稿中的 `max_entry_premium` 可交给 custody 新增的同名执行限制，不能靠张数代替美元上限。

全部检查到的近价合约都会预演注册的 `open_hold_v3`，结果写在 `contracts_checked[].timing`；有首次入场意图的另汇总为 `entry_signals`，不再只计算最终草稿。`engine_action` 来自原策略，`first_enter_at` 标识首次入场意图；`signal_status` 区分尚无信号、本分钟首次入场、以前入场后未报告成交的保持状态。它按当前候选方向重放，未重建历史报价资格；当前合约符合预算，不代表它在旧信号时也符合，不能把旧 ENTER 当作新信号追单。

v3 使用 20 根 1m 收盘的压缩过滤，因此正常信号最早 09:50；09:45 可先准备候选和合约。10:30 的强制入场兜底、估算权利金止盈与锁盈保持原样。若监测在 10:00 后才启动，只要求实际使用的 30 分钟量基准；更早启动必须同时具备 15／30 分钟基准，缺失时不估造。监测截至指定时刻后结束，持仓管理由用户启动的 custody 任务负责。

## 当前结论

- **[P5](reports/P5_RESULTS_CN.md)：A4 新截面再验证失败。** 145 只、53 个细行业，40 次信号仅 7.5% 先到目标、72.5% 先碰止损，平均收益 −0.251 个隐含剩余波动；可交易周五子集 11 次、0 次到目标。**目前没有可视作稳定有效的方向名单规则**；每日工具只保留研究观察。
- **[P2](reports/P2_RESULTS_CN.md)：财报反应日是大概率事件。** 当天开盘后上冲或下探走出 1 个隐含日波动的概率约 78–84%，平日约 35%；四个截面一致，在从未查看的第 601–900 名上验证通过。**放量宽幅日的第二天**也会大动（59.8% 对 36.6%，事后提出，已验证一次）。两者都**不给方向**。
- 日 K 方向形态（52 周新高 / 新低、连跌 + 锤子线、放量宽幅的方向）在「盘中机会」口径下仍没有方向倾斜；NR7 收缩后反而更安静。
- **[P1](reports/P1_RESULTS_CN.md)：开盘后出单越晚越准。** 按「已动幅度 ÷ 期权定价」选，10:30 比同池高约 20%，验证段 1.1998 倍，差 0.0002 未过预登记门槛。
- **期权价格**：普通交易日真实 0DTE 平值跨式约为估算值的 0.68 倍；**财报反应日的真实价格尚未核对**，这是能否转成期权盈利的关键。
- **[P3](reports/P3_RESULTS_CN.md)：没有找到「大概率走出期权翻倍行情」的方向信号。** 10:00 入场先于止损走出 1 个隐含剩余波动的比例最高 26%（门槛 40%）。在场股开盘区间突破有温和的方向优势（+10 个百分点，平均收益为正），形态是低胜率、高盈亏比；OpenD 期权异动数据太稀疏，做不出开盘期权流信号。
- **[P4](reports/P4_RESULTS_CN.md) 的历史结果保留**：A4「放量宽幅次日延续」在 35 只新个股上，44 次信号的目标率 38.6%、止损率 31.8%，当时通过事后门槛；后来 P5 未能推广这一结果。A1 验证失败，给 A1 加过滤提不高胜率。
- 所有失败尝试见 [notes/FAILED_TRIALS.md](notes/FAILED_TRIALS.md)。
- **每日研究工具** [daily_list.py](daily_list.py)：保留固定 A4 规则、每天最多 5 只，可以为空；输出明确标注 `P5_FAILED`，不再标为已验证的方向能力。

## 研究观察用法（周一、周三、周五）

```bash
# 前一交易日收盘后到当天 09:25 之间（约 8 分钟）：扫描期权成交量前 600 的个股，找前一天放量宽幅、今天有当日到期合约的
/opt/futu-opend/venv/bin/python -m studies.us_0dte_picks.daily_list premarket --date 2026-09-28 --out data/list-2026-09-28-pre-rth30
# 当天 10:00–10:25（约 2 分钟）：确认 A4，给方向、目标价、止损价与平值 0DTE 的买卖价和价差
/opt/futu-opend/venv/bin/python -m studies.us_0dte_picks.daily_list confirm --watchlist data/list-2026-09-28-pre-rth30/watchlist.json --out data/list-2026-09-28
# 当天 16:05 之后：复盘，按 5 分钟 K 判定先到目标还是止损，并按收盘内在价值记录所列合约的真实盈亏
/opt/futu-opend/venv/bin/python -m studies.us_0dte_picks.daily_list review --list data/list-2026-09-28/list.json --out data/list-2026-09-28-review
```

只读 OpenD，不下单、不扣历史 K 线额度，订阅用完即释放。开盘前和 10:00 确认统一使用常规时段的 30 分钟 K：13 根齐全才算完整日，开盘量分母固定为之前 14 个完整日（都须在最近 20 个市场交易日内），并随观察名单保存。半日交易日不出单；旧版观察名单没有分母版本，须重跑 `premarket`。

这是用户确认采用的近似口径：已有 10 只、120 个共同完整日的开盘和全天价格一致，量最大相对差分别约 0.000448%、0.000765%，不保证阈值附近名单完全一样。详见[分母说明](notes/DENOMINATORS.md)与[原始比对](reports/P5_PARITY_CN.md)。旧 P4 的 44 个信号在 5 分钟聚合成 30 分钟后，正反向触线分类及收益均不变，见[分辨率检查](reports/P4_RESOLUTION_CN.md)；这不是新的验证。

价差 > 10% 或当日成交 < 100 张的合约标「谨慎」。信号质量按正股判定（先到目标价还是止损价），不依赖历史期权价格；期权价格只影响同样的正股波动能赚多少和成交成本，在 10:00 由工具直接显示合约买卖价与价差。复盘里的期权盈亏只作参考。

**频率也是观察结果**：P5 有合格候选池的 52 天里共 40 次信号；具备资格的 11 个周五里有 11 次信号，仅 6 个周五出单，并未达到“每天约 5 只强信号”的目标。新截面没有周一／三到期股；旧快照有此资格的是 11 只大型科技股。2026-09-28 的旧版开盘前扫描曾输出空名单；它使用 K_DAY，不能直接作为新分母版本的观察名单。

已试方向与排除清单见 [notes/SEARCH_MAP.md](notes/SEARCH_MAP.md)，新一轮登记前先对照。

## 文件

- `notes/`：预登记（P1–P4 与 P2 补充登记）、设计稿、排除清单、失败记录、名单文件
- [timing.py](timing.py)：P1 出单时点回测
- [daily_k.py](daily_k.py)：P2 日 K 形态与财报事件回测
- [p3.py](p3.py)、[p4.py](p4.py)：P3 / P4 回测（10:00 入场，先到 +1 还是 −0.5 个隐含剩余波动）
- [daily_list.py](daily_list.py)：每日名单工具
- [分母说明](notes/DENOMINATORS.md)、[测试集清单](notes/TEST_SETS.md)：接口、时间窗、历史使用与验证资格
- [parity.py](parity.py)、[resolution.py](resolution.py)：原生跨周期数据比对与旧 P4 退出分辨率检查
- [p5.py](p5.py)、[fetch_p5.py](fetch_p5.py)：P5 固定规则的单次评测与已完成的一次性采集；该样本已暴露，不能再作新验证
- [fetch_events.py](fetch_events.py)、[fetch_option_events.py](fetch_option_events.py)、[fetch_k5.py](fetch_k5.py)：一次性取数（只读；`fetch_k5` 扣额度，须用户同意）
- [reports/](reports/)：结果与机器报告
- 测试：`python3 -m unittest discover -s studies/us_0dte_picks/tests`
