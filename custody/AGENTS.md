# custody：美股期权日内单笔交易

> 全仓库规则见 [../AGENTS.md](../AGENTS.md)。

## 边界

上游选好标的、方向和合约；本项目为这张期权做日内择时。2026-09-29 用户允许使用最近到期合约：运行时默认保留原 0–1 DTE 兼容范围，显式 `--expiry-policy nearest` 时向 OpenD 核验最近未到期日，不任意放宽到远月。原研究数据与评测仍限真实 0DTE，近到期执行不代表策略效果已获验证。

- 一个 case = `symbol + contract + trade_date`，最多一笔。默认 `round_trip` 有信号才买、收盘前卖；无信号可以不交易，不为完成率兜底。部分成交也算这一笔。
- 2026-09-30 用户要求灵活的单边执行：显式 `--trade-action buy_only` 只买不卖（包括策略退出、尾盘与 stop 都不卖），确认买单终态后保留仓位为 `HELD`；`sell_only` 接管核实过的多头仓位，按独立的持仓毛收益规则自动退出，兼容人工／尾盘退出，不发新买单；首版 position_pnl_v1 仅支持 dryrun/paper，未获 live 资格。它们是运行时执行权限，不修改历史日内策略和评测；详情见 [RUNTIME](../docs/RUNTIME.md)。
- 永远是买方：LONG 买 CALL，SHORT 买 PUT；不选标的 / 方向 / 合约，不卖出开仓；同一标的不同合约互相独立。
- 2026-10-25 用户要求把 custody 当期权程序化执行工具；2026-10-26 重新定义为两种原子单：`--manual` 智能买（`buy_only`）/ 智能卖（`sell_only`，只卖持仓），在用户给定时间段内一次成交、到点必成交，同一合约一天可挂多张（`jobs.slot`），卖单建票时预留持有数量；默认时间段一开始动手，可选场景剧本二版（`playbook.py`，EXEC8 未通过）决定时机；挂价从中间价追向对手价。可在 live 使用（不受 accepted 限制），但智能买必须设单票与账户每日权利金上限。智能单不是策略，不进评测、不改变任何策略资格；参数与边界见 [RUNTIME](../docs/RUNTIME.md) 1b。
- 策略输入只有：当天已完成的正股 1m K 线、方向、行权价、开收盘时间。禁止期权价格、前日及更早数据、日线、场景标签、未完成或未来的 bar、随机数、跨实例状态。此契约约束原日内正股择时引擎；2026-09-30 用户要求的独立 sell_only 持仓退出使用经核实成本及真实报价，不复用原引擎的入场假设，也不继承其评测资格。
- 择时线（`zero_dte_timing`）入场不依赖固定时刻或价格；收盘前 15 分钟（`flatten_before_close_minutes`）禁止买入，默认日内模式必须退出；`buy_only` 仅撤销未成交买单并保留已成交仓位。
- **保证入场线**（`open_hold_*`，2026-09-20 用户决定）：开盘 1 小时内必须买入一单，时刻与方式可调（固定时刻 `open_hold`，或择时 + `must_enter_by_minute` 兜底）。不适用「无信号可以不交易」，也不按「优于对照组」的门槛（G3 / G5 / G7–G10 / G12）和随机入场对照（G13）判定，看自身盈亏平衡命中率（[STANDARD](../docs/STANDARD.md)）。
- 盈亏只按期权成交价算；禁止用正股收益折算、删除失败 case、看完结果改标准。

## 数据

- 只用 [DATA](../docs/DATA.md) 登记的数据集；每个 case 是真 0DTE（expiry = trade_date），有同日完整常规时段的正股 1m 和期权 1m，文件由 SHA256 固定，不一致直接报错。
- 新数据集每个（标的, 交易日）必须同时有 **CALL 和 PUT**（同一行权价：开盘第一根 1m 开盘价最近的挂牌行权价），不按收益、成交量或事后标签挑方向。只有单边的数据集只能做诊断，结论最高 PROVISIONAL。
- 每个交易日收盘后当天 `custody freeze`（过期周权补不回来）；发布 Release 前必须通过 `python3 -m custody check`。

## 策略与评测

- 策略 = `engines/<engine>.py` + 不可变参数文件。改参数用新 `strategy_id` 和新文件，在 [strategies/index.json](strategies/index.json) 登记 SHA256；小改动升小版本（v6 → v6.1）。
- 2026-10-14 用户澄清：后续对外使用「策略名称 + 统一版本 + selective/required mode」，同一新版本同时包含两种 mode 的冻结配置和评价；模式不同不能用两条版本号冒充版本先后。现有历史 ID、SHA 和分配置资格保留，不通过改名传递 live 资格。组合信号需按空仓/同向持仓/反向持仓定义动作、按完整交易配对评价；设计及尚未实现的边界见 [统一版本与组合评价](../docs/STRATEGY_MODES_AND_SIGNALS.md)。
- 状态只写在 `index.json`，只有评测 ACCEPT 才能改 `accepted`。不留废弃策略、旧报告或兼容分支；历史查 Git，不复活已删除的策略。
- 候选用完整标准（含 G8–G10）评测：先比未通过门槛数，再比综合分（判为优于基线还要求上游命中率 60% 时综合分也更高）；选择做留一天交叉验证并报告样本外估计；全部候选与失败记入 [STRATEGY](../docs/STRATEGY.md)。
- 唯一评测入口：`python3 -m custody evaluate --strategy <id> --dataset <目录> --out reports/<id>/<dataset>/`。主口径方向对称加权、主指标盈亏比；结论只看门槛；比较版本用综合分（收益分 80%、完成分 20%，见 [STANDARD](../docs/STANDARD.md) 第 10 节）；整体比较保留全部 case，未入场按 0 收益计。
- 两边不全、场景不足或样本外交易日不足 20 个都不能 ACCEPT。
- 2026-10-14 用户要求：后续日内新机制同时预登记、评测自由择时（`selective`，无信号可不买）和必须交易（`required`，有入场及日内退出兜底），各自只做一次买入、一次卖出；必须分别报告 CALL/PUT、完整买卖覆盖、入场/退出原因和持有时长。不能用一个 mode 或一个方向的收益掩盖另一个的失败。两者是策略研究口径，不等于执行环境或 `trade-action`；基线及账户一天一笔尚需固定上游选择的边界见 [R29](../studies/archive/us_0dte_picks/R29_BASELINES_CN.md)。未成交和到期结算不算完成卖出，不删亏损 case，不重复扣减已反映在真实期权价格里的时间损耗。

## 运行

`custody dryrun` 只读、只记意图和模拟成交；`custody run` 下单（`paper` 模拟、`live` 真钱且只接受 `accepted` 策略或带上限的智能单）。细节见 [RUNTIME](../docs/RUNTIME.md)。

## 修改

- `futu-api` 只在 freeze / dryrun / run 需要。
- 改策略行为或参数：重新生成受影响的报告一起提交。改评测口径（常量、成交模型、标签、权重、门槛）：同步 `evaluate.py`、[STANDARD](../docs/STANDARD.md) 和测试，重跑所有已注册策略的报告。只改文案不重跑。
