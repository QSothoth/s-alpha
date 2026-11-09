---
name: trader-replication
description: 按公开交易员自己的流程复刻：固定卡、行情层、选股/交易/衔接三条线、合并验收。用于复刻某个交易员、继续研究或从注册表选人。冻结后的日常筛选见 trader-screens。不产生交易许可，不下单，不接 custody。
---

# 逼近一个交易员（trader-replication）

工程为 `/opt/opend-us-options`。沿用根及 `studies/AGENTS.md`：先预登记，每轮最多 5 个候选，选择段与验证段分开，失败照记，不为单笔加例外。只否定当前版本，先查数据、翻译与执行差距。公开成绩先当作能做到。

动态流程以 [WORKFLOW_CN](references/WORKFLOW_CN.md) 为准，入口为 [trader-replication-loop.js](../../.claude/workflows/trader-replication-loop.js)。方法与接口见 [METHOD_CN](references/METHOD_CN.md)，工程检查见 [TRADER_PROTOCOL_CN](../../docs/TRADER_PROTOCOL_CN.md)。资金纯度、毛利纯度、随机及段吃到只报告。

继续既有研究前读 [R75–R108 复盘](../../studies/martin_luk/reports/POSTMORTEM_R75_R108_CN.md)及 METHOD 第 9 节。保留用户原始基线，对照本人目标。先算上游可达上限；信号和仓位可声明 paired 成对研究，选择仍只看上游覆盖主尺，不能用下游收益补覆盖。收益与行为的权衡须有用户授权。

本 skill 管研究。登记系统、看板与前向记录由 [trader-screens](../trader-screens/SKILL.md) 运行。旧报告保留原数字和原判定，新标准不回改历史。

## 先划清信号期、交易期与行情 Switch

新交易员继承 `studies.trader_replication.study.Study`，提供以下几块。共享 `build()` 把它们组合起来。

| 接口 | 新交易员填什么 | 共享层负责什么 |
|---|---|---|
| `arrays(market, upto, mode)` | 适配统一行情面板 | frozen 数据、截断检查与指纹 |
| `universe(A, cfg)` | 用 t−1 及以前条件得到天×股布尔池 | 检查形状 |
| `signal(A, pool, cfg)` | 每晚有序点名，含空夜，键为日历下标 | S 与 allocate 共读这一份点名 |
| `entries(A, picks, cfg)` | 原话有特殊入场时覆盖 | 默认次日开盘、前夜低点止损；也支持当晚收盘 |
| `trade(cfg)` | 返回 `system.Rules`，写本人风险、止损与离场 | 共享账户引擎 |
| `allocate(...)` | 通常不覆盖；只填配置 | 10 日冷却、候选名额或成功开仓名额、同时持仓上限、换仓 |
| `regime(A, cfg)` | 可选，配置状态到本人行为的映射 | 三种行情定义选一种、状态数组与 episode |

信号期回答池与有序点名；交易期决定买点、止损与离场；衔接决定名额和资金分配。行情只读市场与自身点名，不读他的台账、段表和账户结果。每次只改一条线的一格；行情冻结前只用 common，冻结后每线每状态最多两项修正，档内沿用固定家族排序。

P3的名单宽度及已成熟点名反馈在 `studies/martin_luk/p3_signal.py` 按日推进；它是独立研究入口，没有替换通用三种producer、登记版或看板。信号层和仓位层可paired成对改，主尺仍是S覆盖，账户结果另报。

配置分为 `universe / signal / allocate / trade / switch` 五节。`Config` 提供旧扁平键的只读别名。旧的 `build()` 覆盖实现标为 `legacy`，继续原样运行；没有统一点名接口的旧版本不能冒充 S 覆盖通过。

Switch 每人最多两个开关，每个开关逐字引用本人 `notes/RULES_CN.md` 的一句原话。定义、常见参数与 SHA 先冻结。没观察到本人交易的状态按原话设规则，标“未观测”，冻结后由前向记录检验；不能把推测写成已复刻。

## 固定卡、行情层、三条线与合并验收

`pipeline.accept` 按 config 判 accepted/branch，`checkpoint` 判停点，`freeze_switch` 判行情；`funnel` 报逐段漏斗与测试台。`datasets check/scan` 核对输入。G0–G6 历史函数保留，旧轮次兼容；新流程 G2/G3 不再阻断其他线。

| 卡子 | 查什么、通过线 | 不过时允许做什么 |
|---|---|---|
| G0 资料与台账 | 本人一手原话带来源；至少 30 笔带日期交易，exact 单报；公开数字有出处或明确缺失；台账、段表、选择与验证切分冻结并记 SHA | 补资料。台账不足只能称“按原话的规则评测”，不进入 G4 之后 |
| G1 数据与引擎 | `gate.check_data / check_fills / check_lookahead / check_win` 全过；已平仓不少于 30 笔、胜率 ≤35%；DATA_PIN 和代码指纹齐；先让参照系统同口径过关 | 修数据或实现，不研究策略 |
| 行情层 | 稳定性及固定参照账户逐年进攻/防守收益；台账分状态画像只报告 | 未冻结只改各线 common |
| 选股线 | S0早期覆盖、K和冷却；不限K宽度与每年不同票数护栏 | 不跑账户，只改点名 |
| 交易线 | 直接喂他的段及同晚对照票；峰前持有、平均R、盈亏比、行为 | 执行侧禁止读取段表 |
| 衔接线 | 冻结点名与执行，量点到→早买→峰前持有及阻挡 | 只改分配；上限先算 |
| G4 交易行为 | 已平仓胜率 ≤35%，至少 30 笔；每年 ≥52 笔。有出处的盈亏比、持有天数、每年笔数差在 ±20% 内；实际买到与三层对照齐；按 episode 留一 | 用逐笔漏斗定位，只改 allocate 或 trade 的一层 |
| G5 账户 | 每年不亏；本人在数据期内有出处的每一年，`abs(log((1+我们)/(1+他))) ≤0.3`。按 episode 留一；三市场分报 | 先诊断，定位后回 G3 或 G4，不改尺子或段表 |
| G6 冻结 | 指纹、三市场报告、robust 报告齐；冻结日为数据末日，登记与 forward 起点一致；用户同意 | 报告缺口，保留原登记系统，不自动冻结 |

G4 与 G5 合起来就是复刻成功标准。没有出处的行为数字不代填、不强行匹配；缺少我们自己的必要事实判不过。资金纯度、毛利纯度、段吃到、回撤、利润集中度、等权持有、随机对照和去掉两笔的结果都只报告。

合并须通过 WORKFLOW 第四节与成功标准；接受任一线后下一轮强制合并。先读上一轮 STATUS 和总账，按丢段最多的线及可补上限定格。规则/阈值/数据白名单由用户掌握，草案未获确认不开策略轮。源码与数据指纹、逐条接受原因、流程问题及测试写入 completion；不把约定当作所有旧选择器已有的自动保证。

S 检验按年份留一，Switch 与交易检验按 episode 留一。三折、逐段结果全部报，不能挑最好的一折。2026 已被反复查看，历史留出记“留出*”；没有冻结的留一模型就报未观测，本轮不补拟合。只有 G6 后逐日保留的 forward 记录是独立样本外，不能改冻结日来抹掉坏表现。

## 建目录与交接

从 [35 人档案与注册表](../../studies/trader_registry/README.md) 选人，先核对一手规则、带日期台账以及市场与周期的数据可得性。暂缓理由只能是资料或数据缺口，不用相似交易员代填。资料收集与台账精度按 METHOD 第 2、3 节。

新建 `studies/<名字>/notes/RULES_CN.md`、`trades.csv`、冻结段表与切分文件、预登记和 `rounds/`，再实现上表。评测用台账和未来行情段标签，信号、分配、交易及 `regime` 都不能读这些标签。先跑 dummy 一致性测试与执行时点测试，再接真实行情。例子见 [Martin Luk](references/MARTIN_LUK_CN.md)、[Sean Ryan](references/SEAN_RYAN_CN.md)。

完成后写中文结论与运行入口，更新个人参考和注册表的实际状态。未经用户同意不改登记配置、冻结日或看板。三个市场只在本人市场调规则，其余市场只报结果。

使用项目 `.venv/bin/python`。4GB VPS 上先看内存；重计算用 `systemd-run --scope -p CPUQuota=60% -p MemoryMax=900M -q`，同时只跑一个重计算进程，设置 `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1`。不构造全市场 N×N 矩阵，不无界加载数据。
