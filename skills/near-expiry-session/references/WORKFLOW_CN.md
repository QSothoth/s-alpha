# 最近到期期权：筛选、确认、执行与盯盘

2026-09-29 用户要求今天运行，并允许使用最近到期合约。以下是人工确认后交给 custody 的试运行流程。研究 A4、P5 和原 0DTE 评测不变；盘前组合排序与近到期收益均未经独立验证。

交互入口为 [near-expiry-session skill](../SKILL.md)，可用 `$near-expiry-session` 调用。skill 负责授权上下文、候选解释、异常处理与复盘，以下 CLI 负责确定性检查与执行；不会因加载 skill 自动启动交易或采集。

## 1. 盘前一条命令

在美东当天 09:30 前运行，目录必须是新的：

```bash
PYTHONUTF8=1 /opt/opend-us-options/.venv/bin/python -m studies.us_0dte_picks.prepare_watch \
  --out data/human-nearest-2026-09-29-pre --launch --until 15:45
```

`prepare_watch` 固定观察 AAPL、AMD、AMZN、AVGO、GOOGL、INTC、META、MSFT、MU、NVDA、TSLA；每只实时查询最近未到期日，并核对该日标准 Call／Put 链。不会为更便宜的期权跳到其他到期日。没有合格链的股票记入 `excluded.json`；没有完整量基准则整次准备失败，保留原始资料供检查，不估造分母。

排序沿用 09-28 人工启发式：财报反应日、前日放量宽幅、其他依次分档，同档比较 `绝对盘前跳空 / ATR20百分比 + HV/IV`。全部合格股票进入观察；兼容字段仍叫 `top10`，实际可以有 11 只。它是固定科技股池，不覆盖全市场和创新药个股。

只用订阅 K 线，每股每周期最多 1000 根，依次处理并保存。`ranking.json`、`baselines.json`、原始返回、方法、请求日志及 `CHECKSUMS.sha256` 留作复核。15／30 分钟分母必须使用相同的 14 个完整历史交易日。

`--launch` 先做 `launch_watch --check-only`，再启动受 systemd 管理的只读观察，内存上限 512 MiB，默认到 15:45 结束（2026-10-02 起；原 10:45 是为保证入场线设计的）。`ready.json` 表明输入与合约链已核验；`service.json` 保存服务名。进程会等开盘，不会在盘前制造信号。`monitor/inputs/` 保存每分钟取到的当日分钟 K、开盘量、参考行情和期权快照，`monitor/sources/` 保存策略相关源码，分钟判断另存独立输出文件。

### 人类先选标的，再启动

需要人类先挑几只时，先运行 `prepare_watch --out PRE`（不加 `--launch`），说明冻结名单和策略状态并取得当日模式、预算及买卖范围许可。选好后运行：

```bash
/opt/opend-us-options/.venv/bin/python -m studies.us_0dte_picks.launch_watch \
  --candidates PRE/ranking.json --baselines PRE/baselines.json --out PRE/monitor \
  --symbols AAPL,NVDA --until 15:45 --check-only
```

核对预览后去掉 `--check-only` 执行。`--symbols` 只允许冻结名单里的标的，支持 `AAPL` 或 `US.AAPL`，拒绝未知、重复和空列表；输入文件保持原样，扫描和卡片只含所选标的。省略时沿用全池观察。参考指数仍只作为背景。需要自动接受所选范围的新鲜信号时，按下一节固定一次授权再启动 `auto_watch`。原 `mock_watch` 仍保留为本地dryrun观察；当前 v6.6 仍按用户决定只做mock，不因新增工具获得paper/live许可或live资格。

### 一次明确许可，自动等待与交接

人类已经明确选定标的并同意当日模式、预算和买卖权限后，先预览：

```bash
python3 -m studies.us_0dte_picks.session authorize --session PRE \
  --symbols AAPL,NVDA --mode dryrun --trade-action round_trip --until 15:45
```

核对后同命令加 `--execute` 保存 `authorization.json`，不会下单；已有文件拒绝覆盖。许可固定交易日、所选股票、策略SHA、模式、账户、买卖权限和15:45以内的截止时间；工程约束仍为每笔1张、每日每模式最多2个标的、合计权利金预留280美元。当前信号可选择CALL或PUT，合约始终走nearest核验。paper/live额外要求明确正数 `--acc-id` 和券商；live还要求当前策略为accepted。2026-10-02的用户授权仅mock，不能因这个CLI存在自行切换模式。

需要固定人工方向时，加 `--plan-json PLAN.json`，内容必须覆盖全部所选股票，例如：

```json
{
  "US.AAPL": {"directions": ["CALL"], "thesis": "已核实催化，等待顺势信号", "invalidation": "催化被否定时人工撤销"},
  "US.NVDA": {"directions": [], "thesis": "证据不足，今天只观察", "invalidation": "新信息出现后另行决策"}
}
```

`CALL/PUT` 对应 custody 的 `LONG/SHORT`；空列表只观察，两者都填允许双向。程序强制方向、原有截止与预算；理由和失效文字只存档，由人判断，不自动理解新闻或价位。原扫描仍双向生成信号，未许可方向被交接层跳过；不会补造同分钟另一方向或追过期信号。`auto/` 保存 `SKIPPED_TRADE_PLAN`、原卡片和允许方向，便于以后与原流程比较；不构成收益验证。`session status` 保留计划，许可失效后也可查。单卡 `accept` 和 `mock_watch` 同样遵守已有许可。

风险参数均须人明确给金额，省略保持原流程，不据280美元工程预算推断账户本金：

- `--max-loss-usd 金额 --estimated-round-trip-fee-per-contract-usd 金额`：仅 dryrun/paper 的 `round_trip`，将实际成交成本、有效bid及估计双边费用的亏损退出阈值传入 custody；触发不保证成交价，详见 [RUNTIME](../../../docs/RUNTIME.md)。
- `--loss-budget-start-date YYYY-MM-DD --loss-budget-usd 金额 --estimated-round-trip-fee-per-contract-usd 金额`：同模式、账户、券商的共享交接记录，自起始日累计估计净亏损，加未结束任务的完整权利金预留和费用，再加拟入场预留，不得超上限。即使计划止损更小，也按完整权利金占用；换session不清零，旧未平仓仍计入。该检查不覆盖外部手工交易；费用为估计，资料无法核对则阻止新交接。

两项可合用，费用明确填0也有效。累计预算按允许的最高入场权利金预留，不按眼前报价计；预算小于该预留时，即使报价便宜也会被拒，首版不自动缩小单笔上限。它们不替代既有280美元每日权利金上限，不自动改变策略评测状态或允许实盘；计划变化先撤销新增交接，已有持仓沿原权限管理。

前节观察服务ready后，核对它监控的股票与许可完全一致，再在前台运行：

```bash
python3 -m studies.us_0dte_picks.auto_watch --session PRE
```

它只读新鲜卡片，调用同一 `session accept` 进行dryrun预检、实时报价复核、预算锁和去重，所有broker委托仍由custody完成。默认约2秒检查一次，不再等待agent每15分钟人工交接；无信号不买。拿到交接锁后先复核卡片字节、时效和许可，过期或被替换的卡不启动预检；预检与报价复核后再检查。任务最晚入场取卡片与人类许可的较早截止，不因预检耗时越过授权。许可撤销、过期、源输入/策略变化或任何交接结果不明时停止新增交接，保留原ledger/DB，不停止已有custody持仓管理，也不自动重试失败任务。已确认的重复标的或预算已满直接跳过；未确认预留必须先对账。`auto/` 保存ready、过程事件、最后状态与终态；`JOB_CREATED`仍不代表成交，成交/仓位继续看同库订单及 `session status` 的jobs。 协调器终态为`STOPPED_REQUIRES_REVIEW`时命令行退出码为1；许可正常到期退出码为0。进程退出码与`auto/final.json`一起核对，不能把扫描进程仍在运行当作交接成功。

预检期间卡片过期或被新卡替换，且尚未持久化预留/创建任务时，只放弃该卡，记录`SKIPPED_STALE_REVIEW`，重新核对原人类许可后等待新鲜信号，不重复索要许可或延长旧卡期限。已成功交接的标的不再重接。人类许可到期正常结束；撤销、改许可/输入、畸形卡片或任务结果不明仍停止新增交接，原任务继续管理。最后一次跳过原因可在`auto.last_skipped_review`查看。

实时报价复核中，报价过时、价差过宽、权利金超上限、delta或成交量不足、证券状态不合格，且合约身份/到期日仍一致、没有其他结构性错误时，记录`SKIPPED_ENTRY_QUOTE`及`auto.last_skipped_quote`，放弃当前卡并重新核对原许可，继续等新鲜信号。同一张被拒卡不反复预检，预算不预留、不放宽；合约变更、非标准乘数、无效买卖价或其他异常仍停止。报价复核结束后再次核对卡片原字节，更新过的卡不能启动任务。

取消后续自动入场先预览，再执行 `session revoke --session PRE --execute`；它不会撤单或卖出现有仓位。扫描由原systemd服务受控停止；已有委托/仓位仍按原任务处理。`auto_watch`本身不启动后台服务；如需要后台运行，必须已有当天适用许可，说明unit、用户、工作目录、512MiB内存上限与截止时限、实际agent跟进能力，沿用本项目systemd方式，不创建无限期守护进程。worker不转发WxPusher，不承诺主动推送。

## 2. 查看一个入口

```bash
PYTHONUTF8=1 python3 -m studies.us_0dte_picks.session status \
  --session data/human-nearest-2026-09-29-pre
```

输出观察服务状态、最新审视卡、盘中排名、行情错误、当天交接记录和 custody 仓位状态。盘前显示 `PREMARKET_WAIT`；旧卡或过时输出不会当成新机会。观察服务结束与 custody 持仓管理互不影响，须分别查看服务和任务状态。

`mock` 字段另外汇总本 session 的模拟观察状态、交接错误、快照年龄与是否结束；超过 120 秒或来自未来的快照标记 `fresh=false`，历史错误仍保留。`authorization`给当前许可状态；`auto`优先读取协调器终态，报告失败、快照年龄和是否结束，终态错误不会被旧运行快照盖掉。顶层 `status` 只描述扫描状态；不能据此忽略 `mock.status=HANDOFF_FAILED` 或 `auto.status=STOPPED_REQUIRES_REVIEW`。`handoffs/jobs` 是该交易日全部 session 和账户的记录，按执行模式分组，需结合卡片 hash 判断归属。

盘中每个完成整分钟约第 3 秒开始采集。卡片附 SPY、QQQ、SMH、XBI 的开盘至今表现和 VWAP 位置，参考行情不进入可交易池；参考数据缺失明确列出，不自动推断行业方向。09:45 前只观察正股，之后比较真实合约。

**2026-10-02 起的择时（用户决定）**：策略为 `zero_dte_timing_v6.6`，不再是 `open_hold_v3`。每只候选的 CALL 与 PUT 各取最近五档行权价，分别从开盘起按自己的方向重放 v6.6；哪一边首次出入场信号，卡片就给那一边。不按开盘以来涨跌定方向，也没有开盘一小时兜底入场。v6.6 是 candidate，只用于 dryrun（mock）；`live` 会被 custody 拒绝。

`ENTER_REVIEW` 只包含本分钟首次出现的入场意图。核对方向、到期日、报价和有效期；`WAIT` 不操作。不凭图形否决信号（见 [agent 审卡评测](../../../studies/archive/README.md)）。报价要求乘数 100、Delta 绝对值至少 0.30、成交至少 100 张、价差不超过 10%、报价不超过 30 秒。仅检查每只 CALL、PUT 各最近五档行权价，不声称穷尽全链。

## 3. 按唯一合约确认

把当前卡的真实合约代码传入，先预览：

```bash
PYTHONUTF8=1 python3 -m studies.us_0dte_picks.session accept \
  --session data/human-nearest-2026-09-29-pre --contract '<当前卡的合约代码>'
```

加 `--execute` 表示接受这张仍有效的卡，默认运行只读 `dryrun`，不发券商订单。程序先做一次真实行情的单次 dryrun，必须产生本地模拟买入；随后再核对卡未更换、未过期、最近到期日与实时合约资格，才启动常驻 custody 任务。

交接还可选 `--trade-action buy_only`，默认是 `round_trip`。只买任务成交后保留 `HELD` 仓位，不因尾盘或 stop 卖出；预算预留仍不释放。只卖已有仓位不需要入场卡，直接使用 custody 的 `--trade-action sell_only`，并沿用原 ledger 所指数据库，详见 [运行时三种模式](../../../docs/RUNTIME.md)。mock_watch 自动交接目前仍固定默认 round_trip；需要只买观察时用上述显式 accept。

要明确执行实盘，使用同一入口的 `--mode live --acc-id <当日确认的账户> --security-firm <券商主体> --execute`；模拟账户订单用 `--mode paper`。不能省略账户，默认券商主体为 `FUTUSECURITIES`。实盘密码只能在环境变量中，按变量名传递给 systemd，不在命令行放密码。人工确认后这条命令会真实委托，不是查看状态。

交接卡一分钟失效；截止时间进入 custody 持久任务，重启后仍有效。过期不再发出新买单，未成交挂单请求撤销，已成交部分继续由原策略管理。卡片任务使用一分钟内已完成的策略帧，并保持 10% 入场价差限制。全部交接任务使用 `--stream-only`，缺分钟数据就等待，不自动消耗历史 K 线额度。

## 4. 总预算与持续管理

- 总预算 300 美元，20 美元仅作费用预留，实际手续费按账户计。
- 明确选择1只时单笔权利金上限280美元；明确选择至少2只时各140美元，信号分开出现也保持这个分配，每笔最多一张。一次授权交接按许可标的数再次收紧旧卡；报价筛选、预检、worker请求与ledger均用同一实际上限。未限定标的的全池观察仍按同卡单笔280/两笔各140分配。
- 每日每执行模式共享 `data/near-expiry-runtime/<日期>/<模式>/ledger.json`，用文件锁串行交接；最多两个不同标的，累计预留上限不超过 280 美元。dryrun、paper、live 分开统计，同模式跨观察目录和账户共用限制。
- 预留的是任务上限，不是当前卖一价；确认过的预留不自动回收。启动失败或结果不明也保留记录，防止重复接单。此限制只覆盖该交接入口，不覆盖另行手写的 custody 命令或其他程序。
- 常驻 custody 由 systemd 管理，内存上限 512 MiB，异常退出可重启，使用同一 SQLite 恢复任务。不会因观察扫描结束而停止持仓管理；策略按原规则退出，未收到真实平仓确认就不宣称完成。
- 状态里的 `JOB_CREATED` 只代表任务已经落库，真实持仓看 `position_qty` 与订单日志。查看日志用 `journalctl -u <服务名>`；人工退出用 `python3 -m custody stop --db <状态中的数据库路径> --job <任务ID>`。

v6.6 的估算权利金止盈与锁盈仍按当日剩余时间建模（与 `open_hold_v3` 同一模型），近到期合约实际时间价值不同。这次没有修改策略参数、重新认证收益或承诺风险收益效果。盘后应按实际合约报价和真实成交复盘，不能沿用到期内在价值作为未到期期权的损益。
