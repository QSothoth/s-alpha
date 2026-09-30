# 最近到期期权：筛选、确认、执行与盯盘

2026-09-29 用户要求今天运行，并允许使用最近到期合约。以下是人工确认后交给 custody 的试运行流程。研究 A4、P5 和原 0DTE 评测不变；盘前组合排序与近到期收益均未经独立验证。

交互入口为 [near-expiry-session skill](../skills/near-expiry-session/SKILL.md)，可用 `$near-expiry-session` 调用。skill 负责授权上下文、候选解释、异常处理与复盘，以下 CLI 负责确定性检查与执行；不会因加载 skill 自动启动交易或采集。

## 1. 盘前一条命令

在美东当天 09:30 前运行，目录必须是新的：

```bash
PYTHONUTF8=1 /opt/futu-opend/venv/bin/python -m studies.us_0dte_picks.prepare_watch \
  --out data/human-nearest-2026-09-29-pre --launch --until 10:45
```

`prepare_watch` 固定观察 AAPL、AMD、AMZN、AVGO、GOOGL、INTC、META、MSFT、MU、NVDA、TSLA；每只实时查询最近未到期日，并核对该日标准 Call／Put 链。不会为更便宜的期权跳到其他到期日。没有合格链的股票记入 `excluded.json`；没有完整量基准则整次准备失败，保留原始资料供检查，不估造分母。

排序沿用 09-28 人工启发式：财报反应日、前日放量宽幅、其他依次分档，同档比较 `绝对盘前跳空 / ATR20百分比 + HV/IV`。全部合格股票进入观察；兼容字段仍叫 `top10`，实际可以有 11 只。它是固定科技股池，不覆盖全市场和创新药个股。

只用订阅 K 线，每股每周期最多 1000 根，依次处理并保存。`ranking.json`、`baselines.json`、原始返回、方法、请求日志及 `CHECKSUMS.sha256` 留作复核。15／30 分钟分母必须使用相同的 14 个完整历史交易日。

`--launch` 先做 `launch_watch --check-only`，再启动受 systemd 管理的只读观察，内存上限 512 MiB，到 10:45 结束。`ready.json` 表明输入与合约链已核验；`service.json` 保存服务名。进程会等开盘，不会在盘前制造信号。`monitor/inputs/` 保存每分钟取到的当日分钟 K、开盘量、参考行情和期权快照，`monitor/sources/` 保存策略相关源码，分钟判断另存独立输出文件。

## 2. 查看一个入口

```bash
PYTHONUTF8=1 python3 -m studies.us_0dte_picks.session status \
  --session data/human-nearest-2026-09-29-pre
```

输出观察服务状态、最新审视卡、盘中排名、行情错误、当天交接记录和 custody 仓位状态。盘前显示 `PREMARKET_WAIT`；旧卡或过时输出不会当成新机会。观察服务结束与 custody 持仓管理互不影响，须分别查看服务和任务状态。

`mock` 字段另外汇总本 session 的模拟观察状态、交接错误、快照年龄与是否结束；超过 120 秒或来自未来的快照标记 `fresh=false`，历史错误仍保留。顶层 `status` 只描述扫描状态；不能据此忽略 `mock.status=HANDOFF_FAILED`。`handoffs/jobs` 是该交易日全部 session 和账户的记录，按执行模式分组，需结合卡片 hash 判断归属。

盘中每个完成整分钟约第 3 秒开始采集。卡片附 SPY、QQQ、SMH、XBI 的开盘至今表现和 VWAP 位置，参考行情不进入可交易池；参考数据缺失明确列出，不自动推断行业方向。09:45 前只观察正股，之后比较真实合约；v3 仍按原参数择时。

`ENTER_REVIEW` 只包含本分钟首次出现的入场意图。人工核对方向、参考环境、到期日、报价和有效期；`WAIT` 不操作。报价要求乘数 100、Delta 绝对值至少 0.30、成交至少 100 张、价差不超过 10%、报价不超过 30 秒。仅检查每只最近五档行权价，不声称穷尽全链。

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
- 单笔权利金上限 280 美元；同卡两笔各 140 美元，每笔最多一张。
- 每日每执行模式共享 `data/near-expiry-runtime/<日期>/<模式>/ledger.json`，用文件锁串行交接；最多两个不同标的，累计预留上限不超过 280 美元。dryrun、paper、live 分开统计，同模式跨观察目录和账户共用限制。
- 预留的是任务上限，不是当前卖一价；确认过的预留不自动回收。启动失败或结果不明也保留记录，防止重复接单。此限制只覆盖该交接入口，不覆盖另行手写的 custody 命令或其他程序。
- 常驻 custody 由 systemd 管理，内存上限 512 MiB，异常退出可重启，使用同一 SQLite 恢复任务。不会因观察在 10:45 结束而停止持仓管理；策略按原规则退出，未收到真实平仓确认就不宣称完成。
- 状态里的 `JOB_CREATED` 只代表任务已经落库，真实持仓看 `position_qty` 与订单日志。查看日志用 `journalctl -u <服务名>`；人工退出用 `python3 -m custody stop --db <状态中的数据库路径> --job <任务ID>`。

`open_hold_v3` 的估算权利金止盈与锁盈仍按当日剩余时间建模，近到期合约实际时间价值不同。这次没有修改策略参数、重新认证收益或承诺风险收益效果。盘后应按实际合约报价和真实成交复盘，不能沿用到期内在价值作为未到期期权的损益。
