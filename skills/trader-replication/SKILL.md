---
name: trader-replication
description: 按公开交易员自己的流程复刻。先核对一手规则与带日期台账，再依次通过 G0–G6：资料、工程、行情 Switch、S 信号覆盖、交易行为、账户、冻结。用于复刻某个交易员、继续研究或从注册表选人。冻结后的日常筛选见 trader-screens。不产生交易许可，不下单，不接 custody。
---

# 逼近一个交易员（trader-replication）

工程为 `/opt/opend-us-options`。沿用根及 `studies/AGENTS.md`：先预登记，每轮最多 5 个候选，选择段与验证段分开，失败照记，不为单笔加例外。只否定当前版本，先查数据、翻译与执行差距。公开成绩先当作能做到。

方法与接口详见 [METHOD_CN](references/METHOD_CN.md)，数据与工程检查见 [TRADER_PROTOCOL_CN](../../docs/TRADER_PROTOCOL_CN.md)。主尺子只有三把：S 信号覆盖、交易行为、账户。随机基线、10 天超额、资金纯度、毛利纯度及段吃到比例只作诊断，不能否决。

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

信号期只回答池里有哪些票、当晚按什么顺序点名。交易期决定触发、分配、入场、止损、仓位与离场。regime可以读交易员自己池子里的市场数据及本系统已知的点名，不读他的台账、段表或账户结果。行情状态可决定做不做、做多大、是否做空，以及名额分到哪些票档或形态家族；不决定同一档内先买哪只，不改变止损宽度。档内沿用各固定家族的排序。

P3的名单宽度及已成熟点名反馈在 `studies/martin_luk/p3_signal.py` 按日推进；它是独立研究入口，没有替换通用三种producer、登记版或看板。信号层和仓位层可paired成对改，主尺仍是S覆盖，账户结果另报。

配置分为 `universe / signal / allocate / trade / switch` 五节。`Config` 提供旧扁平键的只读别名。旧的 `build()` 覆盖实现标为 `legacy`，继续原样运行；没有统一点名接口的旧版本不能冒充 S 覆盖通过。

Switch 每人最多两个开关，每个开关逐字引用本人 `notes/RULES_CN.md` 的一句原话。定义、常见参数与 SHA 先冻结。没观察到本人交易的状态按原话设规则，标“未观测”，冻结后由前向记录检验；不能把推测写成已复刻。

## 按顺序过 G0–G6

检查函数在 `studies/trader_replication/pipeline.py`，返回 `pass / fail / unobserved`、原因和数字。`allowed_actions` 给出最早未通过卡子的允许动作。G2 中有出处的未观测状态可保留规则，其余缺证据不能算通过。

| 卡子 | 查什么、通过线 | 不过时允许做什么 |
|---|---|---|
| G0 资料与台账 | 本人一手原话带来源；至少 30 笔带日期交易，exact 单报；公开数字有出处或明确缺失；台账、段表、选择与验证切分冻结并记 SHA | 补资料。台账不足只能称“按原话的规则评测”，不进入 G4 之后 |
| G1 数据与引擎 | `gate.check_data / check_fills / check_lookahead / check_win` 全过；已平仓不少于 30 笔、胜率 ≤35%；DATA_PIN 和代码指纹齐；先让参照系统同口径过关 | 修数据或实现，不研究策略 |
| G2 行情 Switch | 有样本的每状态至少 3 个有交易 episode、15 笔本人交易；预登记行为指标的整段置换 p<0.1，至少两段同向；无未来函数；定义扰动日重合率 ≥90%。无样本状态按原话冻结并标未观测 | 只改 switch；不因未观测就取消整个 Switch |
| G3 S 信号覆盖 | S0 的早期合格夜、10 日冷却、K=3；主留出覆盖 ≥80%，同冷却不限 K 的平均新点名 ≤5。按年留一三折全报，先报池与窗口的可达上限 | 主改 universe 或 signal；可paired改allocate/trade，但选择只看覆盖，上限不足照写 |
| G4 交易行为 | 已平仓胜率 ≤35%，至少 30 笔；每年 ≥52 笔。有出处的盈亏比、持有天数、每年笔数差在 ±20% 内；实际买到与三层对照齐；按 episode 留一 | 用逐笔漏斗定位，只改 allocate 或 trade 的一层 |
| G5 账户 | 每年不亏；本人在数据期内有出处的每一年，`abs(log((1+我们)/(1+他))) ≤0.3`。按 episode 留一；三市场分报 | 先诊断，定位后回 G3 或 G4，不改尺子或段表 |
| G6 冻结 | 指纹、三市场报告、robust 报告齐；冻结日为数据末日，登记与 forward 起点一致；用户同意 | 报告缺口，保留原登记系统，不自动冻结 |

G4 与 G5 合起来就是复刻成功标准。没有出处的行为数字不代填、不强行匹配；缺少我们自己的必要事实判不过。资金纯度、毛利纯度、段吃到、回撤、利润集中度、等权持有、随机对照和去掉两笔的结果都只报告。

新 round JSON 必填 `layer`、`sections_changed`、`upper_bound`，候选只改该层。成对改写 `paired: true` 和 `mechanism`；G3未过时，还须声明 `selection_layer` 为上游signal/universe及 `selection_metric` 为该层主尺，才可配对allocate/trade。资料、工程卡仍不可越过。校验器检查声明；实际选择器是否只用覆盖须另核实，P3先写chosen再运行账户。`Study.round` 对新文件先校验层，再读取已有卡子结果；旧轮次按冻结指纹兼容，不回改判定。格式见 METHOD 第 13 节。

S 检验按年份留一，Switch 与交易检验按 episode 留一。三折、逐段结果全部报，不能挑最好的一折。2026 已被反复查看，历史留出记“留出*”；没有冻结的留一模型就报未观测，本轮不补拟合。只有 G6 后逐日保留的 forward 记录是独立样本外，不能改冻结日来抹掉坏表现。

## 建目录与交接

从 [35 人档案与注册表](../../studies/trader_registry/README.md) 选人，先核对一手规则、带日期台账以及市场与周期的数据可得性。暂缓理由只能是资料或数据缺口，不用相似交易员代填。资料收集与台账精度按 METHOD 第 2、3 节。

新建 `studies/<名字>/notes/RULES_CN.md`、`trades.csv`、冻结段表与切分文件、预登记和 `rounds/`，再实现上表。评测用台账和未来行情段标签，信号、分配、交易及 `regime` 都不能读这些标签。先跑 dummy 一致性测试与执行时点测试，再接真实行情。例子见 [Martin Luk](references/MARTIN_LUK_CN.md)、[Sean Ryan](references/SEAN_RYAN_CN.md)。

完成后写中文结论与运行入口，更新个人参考和注册表的实际状态。未经用户同意不改登记配置、冻结日或看板。三个市场只在本人市场调规则，其余市场只报结果。

使用项目 `.venv/bin/python`。4GB VPS 上先看内存；重计算用 `systemd-run --scope -p CPUQuota=60% -p MemoryMax=900M -q`，同时只跑一个重计算进程，设置 `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1`。不构造全市场 N×N 矩阵，不无界加载数据。
