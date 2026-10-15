# 日 K 技术面参考

用于机会研究之后，或直接给定股票代码时，提供可复算的行情背景。三个市场共用同一套计算，只需要日 K 的开、高、低、收和成交量。输出供模型解释、由人决定，不做策略收益认证、组合管理或下单。

独立入口：[daily-technical-review 技能](../SKILL.md)。脚本为 [assess.py](../../../studies/daily_technical/assess.py)，无需 numpy/pandas；仅 OpenD 入口使用已安装的 `futu-api`。

## 运行

从仓库根目录运行：

```bash
/opt/futu-opend/venv/bin/python -m studies.daily_technical.assess US.AAPL HK.00700 SH.600519 SZ.000001
python3 -m studies.daily_technical.assess SH.600519 --source tencent
python3 -m studies.daily_technical.assess HK.00700 --source tencent
python3 -m studies.daily_technical.assess US.AAPL --csv /tmp/aapl.csv --csv-adjustment qfq
```

默认最多五只标的、每只最近 300 根，`--bars` 可设 60–1000。输出为 stdout JSON，SDK 日志写 stderr；某只失败仍输出其他标的，存在错误时退出码为 1。正常退出只代表完成计算，不代表适合买入。

CSV 必须单标的、不超过 1000 行或 2 MB，列为 `date,open,high,low,close,volume`；也接受 OpenD 的 `time_key` 日期列。可选 `code` / `symbol` 列必须匹配参数。日期冲突、非有限值、价格关系错误直接拒绝；零成交量行剔除并提示。默认 CSV 复权口径未知，不生成可直接采用的介入判断；`--csv-adjustment qfq` 是调用者声明，程序不能证明输入已经正确复权。

`--as-of YYYY-MM-DD` 只截断当前获得的有限序列，不补取更早历史；当前前复权数据可能包含截止日之后的公司行动信息，不能当成点时回测输入。

## 数据口径与费用

| 市场 | `auto` 取数顺序 | 边界 |
|---|---|---|
| 美股 `US.AAPL` | OpenD | 需要该账户已有行情权限；失败就报告缺口，无额外付费或历史接口兜底 |
| 港股 `HK.00700` | OpenD，接口失败后腾讯 | 港股代码五位；腾讯必须明确返回 `qfqday` |
| 沪深 A 股 `SH.600519` / `SZ.000001` | 腾讯，接口失败后 OpenD | 不含北交所；本机 OpenD 可能没有 A 股权限 |

OpenD 仅短暂订阅 `K_DAY`，用 `get_cur_kline(..., QFQ)` 读取最近 K 线；美股指定常规交易时段。默认端口 11111，支持 `--host/--port`、`FUTU_HOST/FUTU_PORT` 和 `FUTU_OPEND_HOST/FUTU_OPEND_PORT`。不调用历史 K 线接口，不消耗新的历史标的额度；行情权限和临时订阅额度仍适用。连接用完关闭，OpenD 按至少一分钟订阅期释放本连接的订阅，不取消其他连接的订阅。参考 [OpenD K 线接口](https://openapi.futunn.com/futu-api-doc/quote/get-kl.html) 与 [连接关闭后的订阅释放规则](https://openapi.futunn.com/futu-api-doc/en/qa/quote.html)。

腾讯使用仓库盯盘已有的公开前复权接口，不需要密钥，但没有可用性保证。拒绝把 `day` 静默冒充 `qfqday`。OpenD 成交量单位为股，腾讯保留供应商单位；CMF、MFI、量比均在同一标的、同一源内计算，恒定单位倍数不影响结果。不得混拼不同源的数据或把成交量直接解释为资金金额；拆股前后价格和成交量调整口径仍需在异常时核对。

仅用已完成日 K：按当地时间，美股和港股 16:30、A 股 15:30 后才接纳当天数据。未读取交易所日历，提前收市日也等到正常截止时间；这会延迟接纳，不会为了更及时而采用半根 K。数据截止日、最新交易日、排除数量都会输出；超过七个自然日未更新会要求先查数据，也可能是长假或停牌。最近 20 根出现超过 30% 的单日变化时提示核对事件和复权。

不持久化行情、不建数据库、不启动后台采集，按标的顺序处理，单次网络响应和本地输入有上限。若用户要求保存真实数据，沿用仓库 Release 规则，不能把行情提交到 git。

## 固定计算口径

所有参数是为了给出稳定、可解释的描述，并未优化为买卖策略。缺少完整方法必需的数据时保留未知，不冒充原作者完整体系。

### Cycle of Price Action

参考 [Oliver Kell 本人署名说明](https://traderlion.com/technical-analysis/chart-patterns/cycle-of-price-action-by-oliver-kell/)。日线近似采用 EMA10 / EMA20、此前十日高低点和 ATR14；原方法同时使用周线与盘中信息，本脚本不包含这些。

EMA 从首个收盘价递推；上升背景为收盘 > EMA10 > EMA20 且 EMA20 高于五根前，下降背景反之。ATR14 用首 14 根真实波幅均值起步，再用 Wilder 平滑。按下表顺序匹配当前状态，可跳阶段；不从未来数据回填历史标签。

| 输出状态 | 条件 |
|---|---|
| `wedge_drop_candidate` | 收盘低于两条 EMA 和此前十日最低价，前十根至少出现过收盘 > EMA10 > EMA20 |
| `extended` | 收盘比 EMA10 高至少 2.5 ATR，只表示延伸，不确认见顶 |
| `wedge_pop_candidate` | 上升背景，突破此前十日最高价，前十根至少一根低于其 EMA20 |
| `base_break_candidate` | 上升背景，突破此前十日最高价，此前十日高低宽度 ≤ 4 ATR |
| `ema_crossback_candidate` | 上升背景且前十根出现过上升排列，当日最低价触及昨日 EMA 区域上沿或以下，收盘高于开盘和昨收 |
| `advancing` / `declining` | 上升 / 下降背景，但没有优先匹配上述形态 |
| `reversal_attempt` | 前十根有收盘低于 EMA20，今日收盘高于开盘、昨收及 EMA10 |
| `consolidation_or_unclear` | 以上均未满足 |

这不是六阶段必然循环，也不保证每次反转都能识别。输出 `candidate` 表示形态候选；突破当天的量比和 CMF 单独展示，不揉成综合分或胜率。

### SMC 的可观察部分

- 摆动点：高点严格高于左右各两根最高价，低点严格低于左右各两根最低价；直到右侧两根完成才确认，输出原日期与确认日期。
- 收盘首次穿越未消费的确认摆动点：初次为 `structure_break`，延续既有方向为 `BOS`，反向为 `CHoCH`。同一摆动点只触发一次突破，不预测转向成功。
- `high_sweep` / `low_sweep`：最高/最低价越过未突破的摆动价位，但收盘回到原侧，且昨收也在原侧；只描述影线扫过，不声称发生了机构猎杀止损。
- FVG：三根 K 的外侧高低价没有重叠；后续影线部分覆盖就缩小剩余区域，完全覆盖即删除，最多保留 60 根内距现价最近的三个。日 K 跳空也可能形成 FVG，不证明订单失衡或必然回补。
- 区间位置：最近确认高低点之间的相对位置；下半区为 `discount`、上半区为 `premium`，区间外另标注。这里不是公司估值便宜或昂贵。

不推断真实机构订单、不识别主观订单块，不把所有 SMC 流派合成一套“标准答案”。

### Money Flow 与其他参考

- **CMF21**：`sum(volume × (2×close-high-low)/(high-low)) / sum(volume)`；无日内振幅的行贡献 0；范围为 −1 到 +1，不能和放大 100 倍的平台数值混用。
- **MFI14**：典型价 `(high+low+close)/3` 比昨日日升则典型价×成交量计入正向，日降计入负向，相等不计；`100×正向/(正向+负向)`。两者都为零时未知；常见 20/80 仅标注超卖/超买。
- 量比为当日成交量 / 此前 20 根均量；收益变化为 5/20/60 根收盘变化；提供 SMA50、数据足够时 SMA200，以及最近五根 OHLCV。

定义参考 [Fidelity CMF](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/cmf)、[Fidelity MFI](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/MFI)。CMF 和 MFI 都是量价代理，不是券商主力净流入，也不是彼此独立的信息源。

## 输出怎样用

`review.stance` 是模型的阅读起点：

| 值 | 含义 |
|---|---|
| `check_data_first` | 先核对数据，不直接采用技术判断 |
| `avoid_new_entry_for_now` | 简化结构偏下行，技术面暂不支持新增介入 |
| `avoid_chasing` | 已明显延伸，留意追涨位置 |
| `review_entry_conditions` | 出现形态候选，可结合机会逻辑审视介入条件，并不等于批准买入 |
| `wait_for_pullback_or_base` | 上升趋势中未出现上述入场形态，观察回调或整理 |
| `wait_for_structure` | 反弹或方向不明，等待更多结构证据 |

`conflicts` 单列价格、资金流代理和结构的冲突，不自动否决机会。`reference_levels` 的 EMA 区域、此前二十日高低点，以及 SMC 摆动点/FVG，都是技术参考；不是自动委托区间、内在价值或保证执行的止损线。

`review.direction` 固定为 `long_only`：仅考虑新开多仓或已有多头退出，下行结构仍作为风险信息保留，不产生做空计划。

模型须明确回答现在买不买，并给出条件触发、计划买区和追价上限、初始止损依据与执行方式、最近阻力及收益风险比、取消条件；完整要求和 Kell 原始依据见[技能输出约定](../SKILL.md#给人的结果)。脚本提供指标和模型提醒，交易计划由模型分析生成，并非已实现的自动交易策略。观察价位不等于买点，没有合格买点就明确不买；未来确认 K 的价位未知时给条件公式，不伪造可执行报价。基本面缺失时说明未覆盖，最终由人决定。

## 验证

```bash
python3 -m unittest discover -s studies/daily_technical/tests
python3 -m unittest discover -s custody/tests
```
