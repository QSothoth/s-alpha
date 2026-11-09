# WF00：动态流程起步（行情层 + 三条线的工具与基线）

先读 `skills/trader-replication/references/WORKFLOW_CN.md`，流程规则以它为准。本轮只搭工具、量基线：不开策略候选，不改登记版（R74+S7 等）和看板，不拉新数据。

## 1. 共享工具（`studies/trader_replication/`）

### 1.1 `funnel.py`：合并验收用的持仓漏斗

- 把 `studies/martin_luk/p4_research.py`、`p5_research.py` 里的 `funnel` / `split_funnel` 收拢成交易员无关的共享实现。
- 层：L0–L6，每段按最早丢失的层只计一次；L0–L1 归选股线，L2–L3 归衔接线，L4–L5 归交易线。
- 合格窗口、首锚点和“剩余涨幅 ≥ 一半”沿用 `mainleg.py` 与 S0 的现有定义；K=3 新点名、10 晚冷却沿用 S0 的 `signal_coverage_budget`。
- 输出按年、按状态给出：
  - 各层段数、早买、峰前持有；
  - 峰前持有段的仓位占权益比例（中位数与合计）；
  - 每年收益、笔数、胜率、盈亏比、平均持有天数，以及与他的行为记分卡差距（只比有出处的数字）；
  - 逐段明细。
- CLI：`.venv/bin/python -m studies.trader_replication.funnel --study martin_luk --system <名字> --out <路径>`。
- 一致性单测：逐位复现 P4/P5 报告的早买和峰前持有。

  | 系统 | 早买 | 峰前持有 |
  |---|---|---|
  | master | 12/48 | 11/48 |
  | X1_OPEN | 18/48 | 6/48 |
  | S1_NOBLOCK | 22/48 | 7/48 |
  | S2_CLOSESTOP | 15/48 | 9/48 |
  | S3_BOTH | 20/48 | 13/48 |

  复现不了先查原因并写进报告，不许改段表或旧报告去凑数。

### 1.2 三条线的尺子（选股复用 `mainleg.py`，衔接复用 1.1 的漏斗，只有交易测试台是新的，也放在 `funnel.py`）

- **选股线**：只读点名，不跑账户。
  - 主尺：S 口径下他的段早期被点到的段数。
  - 护栏：不限 K 平均每晚新点名、每年不同票数。
  - 分状态报告。
  - 复用 S0 的实现，S0 已报的水位须复现（IE9 为 3/9、14/22、11/17）。
- **交易线测试台**：把他的每一段的票，在 [首锚点−3, 峰前1日] 内每晚当作“已点名”，交给某个执行（`system.Rules` 加上 allocate 配置）。同一晚我们点名里不是他的票作对照，用同一执行一起跑。
  - 主尺：他的段峰前持有、他的段盈亏比与平均 R。
  - 护栏：对照票合计收益、行为记分卡。
  - 测试台读他的段只用于评测；执行代码不得读取。用单测保证执行侧拿不到段表。
- **衔接线**：给定冻结的点名和执行，报“点到 → 早买 → 峰前持有”的转化，以及每层的阻挡原因（沿用 P4 A1、P5 A0 的归因）。

### 1.3 `pipeline.py` 新增判定函数

- `accept(line, candidate, compare, cfg)`：按 WORKFLOW_CN 第四节各线接受条件，返回 `accepted / branch`，附逐条原因和数字。阈值只从 `config.json` 读，代码里不写死数字。
- `checkpoint(history, latest, cfg)`
- `freeze_switch(stability, split, cfg)`

以上都配合成数据单测。原有 G0–G6 函数保留；`allowed_actions` 改为 G0、G1 仍阻断，G2、G3 不再阻断下游。旧轮次兼容逻辑不变。

### 1.4 `datasets.py`：数据集白名单

- `check(config)`：对 `config.datasets` 登记的每个数据集逐项核对，任一不符返回失败并写明原因：
  - 本地路径存在；
  - `CHECKSUMS.sha256` 本身的 SHA 与登记值相同，且其中每个文件逐个校验通过；
  - schema 一致：文件清单、各文件列名与类型（读 csv/csv.gz 表头和前若干行推断）、市场、日期范围、标的数。
- `scan(config, files | git_diff)`：静态扫描给定代码或本轮 git diff 里出现的 `data/<名字>` 路径，不在白名单、也不是 `studies.trader_data` 派生缓存的，判失败。
- CLI：`.venv/bin/python -m studies.trader_replication.datasets check|scan --config <路径> [--git-diff]`。
- 单测（合成数据）需覆盖四种情况：改一个字节、删一列、多一个文件、引用未登记路径，都必须被拦下。
- **起草白名单**：用 `sys.addaudithook` 记录 `open` 事件，重放第 3 节注册表里的全部系统，列出它们实际读到的 `data/` 下文件，按数据集归并。预计是 trader-data-v1、trader-options-v1、trader-hourly-v1、martin-luk-benchmarks-v1，再加 `studies.trader_data` 的派生缓存；超出这四个的单独列出并写明是哪个系统读的。
- 据此写 `config.datasets` 草案，含 schema 与 SHA，`approved_by_user: null`。**不许为了凑白名单改数据、补数据或新建数据集**；评测输入（`notes/trades.csv`、`notes/legs_frozen.json`）也登记 SHA，并标明只给评测用。

## 2. 分行情配置

- 在 `config.py` 中，各线配置支持 `common` + `by_state.<状态>` 两部分。
  - 未冻结行情时，`by_state` 必须为空，否则报错。
  - 每条线每个状态最多 2 项修正，超出报错。
  - 旧扁平配置的读取逐位不变，用 R74 等登记系统的回放单测证明。
- `regime.py` 接入 B4_PCT2 作为市场级开关候选，状态最多 3 种。题材级本轮不做。

## 3. Martin 的流程目录 `studies/martin_luk/workflow/`

### `config.json`

- `goal`：用户原话，逐条带日期，从记忆与会话核对过：
  - 2026-11-08：不要收益最高，要在框架内最像他，各项差距 ≤20%，每年不亏，收益也不能差太多（尤其 2025）；
  - 2026-11-07：大资金一定要花在他的票上；
  - 2026-11-08：只用日 K，不能撒网，瞄准盈亏比和低胜率；
  - 2026-11-08：最终追求对他持仓的覆盖；
  - 2026-11-08：可以放入单看是负向、但更像他的人性条件；
  - 2026-11-05：一套画像套所有行情不算拟合，要分行情，并且对得上他的原话、作为策略讲得通；
  - 2026-11-09：选股和交易要拆开各自做成立，再合并。
- `datasets`：按 1.4 起草，等用户确认后由用户填 `approved_by_user`；
- `hard_lines`：每年不亏、胜率 ≤35%、每年 ≥52 笔、行为 ±20%、收益 |log| ≤0.3。
- `accept`：各线接受条件（+3 段等）。
- `checkpoint`：检查点规则（每次运行跑几轮由 workflow 参数定，不写在这里）。
- 其余：选择年 2024、2025，留出年 2026（标“留出*”）；段表路径与 SHA（af4618772ad79596afbae54809f8180e34f73a8e81fbfe4f48eebfe1ec32bdf2）；底线参照 master（只作比较，不作底座）；参照账户 master、M3B。
- 系统注册表：给出 master、M3B、X1_OPEN、S1/S2/S3、IE9 点名 + master 执行（P4 X3）、C062、K2 怎样重放或读取现成台账。

### `state.json`

- 各线冻结版本：
  - `regime`：B4_PCT2 能通过 `freeze_switch` 就写 frozen，否则写 candidate 并附原因；
  - `selection`：IE9；
  - `trading`：本轮测试台上最好的现成执行，见第 4 节，按交易线接受条件排；
  - `conversion`：master 的分配配置；
  - `merge`：null。
- `bar: "master"`，`pending_merge: false`，`next_round: "WF01"`。
- `bootstrap_done`：全部完成才设为 true。

### `attempts.jsonl` 总账回填

- 范围：R1–R108 可按 REPLICATION_CN 与 POSTMORTEM 分组成段；IE*、E*、Y1、D1、M1–M3、F1–F4、U1、T1、H1、H2、S0、P1–P5 逐轮。
- 每行字段：`id`、`date`、`line`（regime / selection / trading / conversion / merge / metric / infra）、`scope`、`sections_changed`、`mechanism`、`his_words`、`main_result`、`returns`、`verdict`、`report`、`lesson`（包括任务书写错的地方）。
- 数字只抄报告原文，没有的写 null。

### 流程问题账起头

按 WORKFLOW_CN 第八节的字段，从回填总账的 `lesson` 里挑出属于流程本身的（例如尺子换过、底座回到参照系统、选股和交易混评、任务书写错），追加进 `skills/trader-replication/references/workflow_issues.jsonl`，`status` 写 open，`general` 照实判断。已经被 WORKFLOW_CN 吸收的写 applied，并注明对应条款。本轮做工具时遇到的流程问题同样追加。

## 4. 基线（放 `rounds/WF00/`，写 `REPORT_CN.md`，白话，先结论）

1. **他的台账分状态画像**：按年、按月、按 B4_PCT2 状态，列他做多/做空、票档（成交额分位、ADR 分位）、形态。不比笔数密度。再对照 master、M3B 的月度盈亏。
2. **行情层**：B4_PCT2 的稳定性、参照账户分状态收益、冻结判定；2026 年 7–8 月逐日状态。
3. **选股线**：IE9、IE47、P3 C2、P2B B3 的主尺和护栏，按年、按状态。
4. **交易线测试台**：master 执行、C062、K2、X1、S3 的执行，各自在“他的票”和“对照票”上的结果，按年、按状态。要回答：现有执行里，有没有哪个在他的票上能赚钱、拿到峰前，又不在对照票上大亏。
5. **衔接与合并**：用第 1.1 节的漏斗跑注册表里的全部系统，给出各层丢段和峰前持有段的仓位占比。
6. **S3_BOTH 2025 年 −56% 拆账**：他的 22 段相关交易与其余票，分别按笔数、平均 R、对权益的贡献报，再列亏得最多的前 10 只。回答是他的票本身亏，还是其他票拖垮了账户。X1_OPEN 同样拆一次。
7. **一致性单测结果**，以及按 WORKFLOW_CN 定格规则，第一轮应该挑哪一格、为什么（只建议，不跑）。
8. **写 `rounds/WF00/STATUS.json`**：各线 × 各状态（含 common）的当前值、目标、可达上限、冻结版本，并附代码与数据指纹。以后每轮由 Codex 在结尾重出，workflow 的“量”只读它。提供 CLI：`funnel status --study martin_luk --out <路径>`。

## 5. 文档

- `skills/trader-replication/SKILL.md`：把“按顺序过 G0–G6”改成“固定卡 + 行情层 + 三条线 + 合并验收”，入口指向 WORKFLOW_CN 和 `.claude/workflows/trader-replication-loop.js`。行数尽量不增加。
- `references/METHOD_CN.md` 第 13 节同步改写。新标准不回改旧报告的判定。
- 改动前核对代码，不把约定写成尚未实现的自动保证。

## 6. 约束与验证

- 只用 frozen 数据，不扣新额度。
- 4GB 内存：按标的分块，重计算用 `systemd-run --scope -p CPUQuota=60% -p MemoryMax=900M -q`，同时只跑一个，并设置 `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1`。磁盘低于 800MB 只删本轮重复中间文件。
- Python 一律用 `/opt/opend-us-options/.venv/bin/python`。
- 跑以下测试，失败先修：
  - `custody/tests`
  - `studies/trader_replication/tests`
  - `studies/martin_luk/tests`（如有）
  - `studies/dan_zanger/tests`
  - 改动涉及的其他切片测试
- 不提交、不推送。
- 最后在 `rounds/WF00/completion.json` 写明：完成项、单测数、一致性是否逐位复现、`bootstrap_done`。
