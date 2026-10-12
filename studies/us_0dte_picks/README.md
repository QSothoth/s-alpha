# 美股末日期权选标的

上游研究：从当天有近到期期权的个股里挑标的和方向，再交给 custody 择时执行。本目录只观察、出草稿，不下单。

**现状（2026-10-12）**：方向规则一条都没成立（A4 在 P5 新截面失败，TS1–TS67 全部未过）；只有「大波动名单」（财报日、放量宽幅次日）成立，不带方向。实际在用的是下面的**盘中人工会话流程**，择时用 custody 的 `zero_dte_timing_v6.6`，目前只做 mock。会话改动是否有效由 **SV1** 回答（10-12 数据齐，评测一次）。

先读 [notes/FAILED_TRIALS.md](notes/FAILED_TRIALS.md) 开头的「总教训」。2026-10-12 清理时，TS / FD 系列的代码、预登记和报告都移出了仓库，只在失败记录里留了结论。

## 人工候选的盘中监测

**2026-09-29 更新：用户允许最近到期，不再只限 0DTE。** 运行入口见 [操作流程](notes/WORKFLOW_CN.md)。`prepare_watch --launch` 生成当天排名、15／30 分钟基准并启动观察；`session status` 汇总；`session accept` 按当前卡先 dryrun、再人工明确选择执行模式。旧研究工具 `daily_list` 的 0DTE 口径不变。

用户于 2026-09-28 确认先从当日候选里选相对最好的 1–2 个机会，盘中观察后交给既有执行策略。[live_watch.py](live_watch.py) 接收当日盘前排名和已冻结的 15／30 分钟量基准，在每个整分钟结束后约 3 秒更新候选、真实合约报价、预算检查与择时策略的状态（2026-10-02 起为 `zero_dte_timing_v6.6`，CALL、PUT 两边独立判断；此前为 `open_hold_v3`）。只输出供人工审视的草稿，不发送订单，也不调用历史 K 线接口。

正式试运行优先用受 systemd 托管的启动器。它限制内存和最长运行时间，并等到所有候选指定最近到期日的标准 Call／Put 链核验完成后才报告成功：

```bash
PYTHONUTF8=1 python3 -m studies.us_0dte_picks.launch_watch \
  --candidates data/当天目录/ranking.json \
  --baselines data/当天目录/baselines.json \
  --out data/当天目录/monitor \
  --until 15:45 --budget-usd 300 --fee-reserve-usd 20
```

启动成功以 `ready.json` 为准；`latest.json` 保存完整观察，`review_card.json` 是给人工环节的短卡。短卡只有在当前 v6.6 **本分钟首次**产生入场意图且当前合约仍通过到期日、报价、流动性和预算检查时才显示 `ENTER_REVIEW`，并给出可原样传入 custody 的 `custody_request`。卡片的 `valid_until` 到下一分钟，过期必须等新卡；旧的 `EARLIER_ENTRY_UNFILLED` 只留在审计记录，不能追单。取得当日适用授权后统一用 `session accept` 预览、dryrun复核与显式模式交接；当前 v6.6 为 candidate，live 会被 custody 拒绝，不因人工选择卡片获得实盘资格。

```bash
PYTHONUTF8=1 /opt/futu-opend/venv/bin/python -m studies.us_0dte_picks.live_watch \
  --candidates data/human-top10-2026-09-28-090327/ranking.json \
  --baselines data/human-trial-2026-09-28/baselines.json \
  --out data/human-trial-2026-09-28/new-monitor \
  --until 10:05 --budget-usd 300 --fee-reserve-usd 20
```

盘前排名与分母必须提前准备且日期有效，输出目录必须不存在。`latest.json` 是最新状态，每分钟另留一份快照。按开盘至当前的绝对变动除以前日 IV 对应的剩余时段尺度排序，再比较同段量比；这只是人工候选排序，未经独立验证。开盘 15–29 分钟时量比固定比较首 15 分钟，30 分钟后比较首 30 分钟，均除以此前 14 个完整日同段均量；不足 15 分钟只观察正股。量比 1.5 不作本模式的一票否决，A4 研究规则不变。

当前会话的价格背景包含OpenD日历确认的MORNING半日市，7根原生30m必须齐全；量基准仍只用14个WHOLE完整日，因此量参考日可以早于昨日。当前交易日仍要求WHOLE，未知日型或截断行情不推断为半日市。旧研究工具`daily_list`的默认完整日口径不变。

合约草稿要求所选最近到期日的标准合约（旧输入未提供到期日时仍要求当日到期）、乘数 100、绝对 Delta ≥0.30、当日成交至少 100 张、正且未交叉的买卖价、相对价差 ≤10%、报价时间距读取不超过 30 秒。在每只股票最近五档行权价中取符合预算的最近档，最多两只、每只一张；优先保留排序最高的可负担标的。以上述 300 美元预算为例，一笔权利金上限 280 美元，若前两笔都能各用 140 美元则分配两笔，余 20 美元仅为费用预留，实际费用需核对账户套餐。草稿中的 `max_entry_premium` 可交给 custody 新增的同名执行限制，不能靠张数代替美元上限。

全部检查到的近价合约（每只 CALL、PUT 各五档）都会按各自方向预演注册的 `zero_dte_timing_v6.6`，结果写在 `contracts_checked[].timing`；有首次入场意图的另汇总为 `entry_signals`，不再只计算最终草稿。`engine_action` 来自原策略，`first_enter_at` 标识首次入场意图；`signal_status` 区分尚无信号、本分钟首次入场、以前入场后未报告成交的保持状态。它按合约自身方向重放（CALL 做多、PUT 做空），未重建历史报价资格；当前合约符合预算，不代表它在旧信号时也符合，不能把旧 ENTER 当作新信号追单。

当前 v6.6 使用20根1m收盘的压缩过滤，因此正常信号最早09:50；09:45可先准备候选和合约。没有强制入场兜底，模型翻倍止盈和锁盈仍保留；TS1–TS7的更早入场及趋势持有实验均未通过，未替换运行策略。若监测在 10:00 后才启动，只要求实际使用的 30 分钟量基准；更早启动必须同时具备 15／30 分钟基准，缺失时不估造。监测截至指定时刻后结束，持仓管理由用户启动的 custody 任务负责。

交互 skill 已缩为 [两层策略与许可](skills/near-expiry-session/SKILL.md)，细节在 [运行细则](notes/SESSION_OPERATIONS_CN.md)。先准备冻结名单，让人类选好，再用 `launch_watch --symbols AAPL,NVDA` 预览和启动，只扫描所选范围；省略范围仍观察全池。明确当天许可后，用`session authorize`预览/保存，再以`auto_watch`自动接受新鲜信号，沿用原custody预检、预算锁与去重；预检后重查撤销/过期，任务最晚入场取卡片与许可的较早截止。当前仅mock许可，不自动切换paper/live。期权检查起点跟随注册策略的 `opening_minutes`，量比信息仍在15/30分钟完成后补充，不承担额外入场门槛。

## 当前结论

- **[SV1](notes/SV1_PREREG.md)（进行中）：会话新流程是否好过旧流程。** v6.6 两边独立 对 open_hold_v3 按开盘缺口方向，在 8 个没用过的交易日上回放一次，预计 10-12 收盘后评测；取数用 [fetch_sv1.py](fetch_sv1.py)，评分用 [sv1.py](sv1.py)。评分入口先核对实际cases恰为指定8日、验证角色及固定股票池；日期未齐拒绝加载行情和评分。在此之前，2026-10-02 的会话改动没有独立证据。
- **[P5](reports/P5_RESULTS_CN.md)：A4 新截面再验证失败。** 145 只、53 个细行业，40 次信号仅 7.5% 先到目标、72.5% 先碰止损，平均收益 −0.251 个隐含剩余波动；可交易周五子集 11 次、0 次到目标。**目前没有可视作稳定有效的方向名单规则**；每日工具只保留研究观察。
- **[P2](reports/P2_RESULTS_CN.md)：财报反应日是大概率事件。** 当天开盘后上冲或下探走出 1 个隐含日波动的概率约 78–84%，平日约 35%；四个截面一致，在从未查看的第 601–900 名上验证通过。**放量宽幅日的第二天**也会大动（59.8% 对 36.6%，事后提出，已验证一次）。两者都**不给方向**。
- 日 K 方向形态（52 周新高 / 新低、连跌 + 锤子线、放量宽幅的方向）在「盘中机会」口径下仍没有方向倾斜；NR7 收缩后反而更安静。
- **[P1](reports/P1_RESULTS_CN.md)：开盘后出单越晚越准。** 按「已动幅度 ÷ 期权定价」选，10:30 比同池高约 20%，验证段 1.1998 倍，差 0.0002 未过预登记门槛。
- **期权价格**：普通交易日真实 0DTE 平值跨式约为估算值的 0.68 倍；**财报反应日的真实价格尚未核对**，这是能否转成期权盈利的关键。
- **[P3](reports/P3_RESULTS_CN.md)：没有找到「大概率走出期权翻倍行情」的方向信号。** 10:00 入场先于止损走出 1 个隐含剩余波动的比例最高 26%（门槛 40%）。在场股开盘区间突破有温和的方向优势（+10 个百分点，平均收益为正），形态是低胜率、高盈亏比；OpenD 期权异动数据太稀疏，做不出开盘期权流信号。
- **[P4](reports/P4_RESULTS_CN.md) 的历史结果保留**：A4「放量宽幅次日延续」在 35 只新个股上，44 次信号的目标率 38.6%、止损率 31.8%，当时通过事后门槛；后来 P5 未能推广这一结果。A1 验证失败，给 A1 加过滤提不高胜率。
- 所有失败尝试和总教训见 [notes/FAILED_TRIALS.md](notes/FAILED_TRIALS.md)，新一轮登记前先对照。
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

## 文件

- 会话流程：[prepare_watch.py](prepare_watch.py)（盘前名单与量基准）、[launch_watch.py](launch_watch.py) / [live_watch.py](live_watch.py)（受管盘中观察）、[session.py](session.py)（状态、许可、交接）、[auto_watch.py](auto_watch.py)（许可范围内自动接受新鲜卡）、[mock_watch.py](mock_watch.py)；运行见 [WORKFLOW_CN](notes/WORKFLOW_CN.md)、[运行细则](notes/SESSION_OPERATIONS_CN.md)、[skill](skills/near-expiry-session/SKILL.md)
- SV1 / SV2：[fetch_sv1.py](fetch_sv1.py) / [sv1.py](sv1.py)（会话验证取数与评分）、[fetch_sv2.py](fetch_sv2.py) / [sv2.py](sv2.py) / [sv2_calibrate.py](sv2_calibrate.py) / [proxy.py](proxy.py)（正股分钟推算期权代理与校准）
- 名单工具依赖：[daily_k.py](daily_k.py)、[p3.py](p3.py)。P1、P4、P5 与 OH3 审计的代码、一次性取数脚本和原始 JSON 输出已移出仓库（见 [archive](../archive/README.md)），结论保留在 `reports/*_CN.md`
- [daily_list.py](daily_list.py)：每日 A4 名单研究工具（标注 `P5_FAILED`）
- `notes/`：P1–P5、SV1、SV2 预登记（代码按 SHA 校验，不能改）、[分母说明](notes/DENOMINATORS.md)、[测试集清单](notes/TEST_SETS.md)（哪些数据已用过、能否再当验证）、失败记录
- `reports/`：P1–P5 结果（中文）与 SV2 校准
- 测试：`python3 -m unittest discover -s studies/us_0dte_picks/tests`
