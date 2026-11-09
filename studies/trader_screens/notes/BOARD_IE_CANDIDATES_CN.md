工作树接入已完成；**完整 live 候选池的数据尚未齐备**。最近交易晚 2026-11-02 的完整 leader 比较范围为 1290 只，当晚期权成交量仅覆盖 140 只，缺 1150 只。按固定规则、缺失不通过，当前部分结果为 0 只；不能把它解释为完整候选池为空。

候选池作为独立观察区接入，没有改变 Martin 登记系统、持仓、买卖、交集或横向比对。没有修改生产主目录、定时任务或任务书，没有取数、调用交易接口、扣 K 线额度、提交或推送。

唯一任务书为 [PLAN_BOARD_IE_CN.md](../../martin_luk/notes/PLAN_BOARD_IE_CN.md)。本记录中的“完成”指任务书允许先完成的计算、展示与核对，不表示已补齐实时期权输入或部署生产。

**改动文件**

| 文件 | 改动 |
| --- | --- |
| [martin_candidates.py](../martin_candidates.py) | 完整 leader 比较范围、六因子、IE8 过滤、IE9 排名、覆盖率与缺失状态；只读 |
| [scan.py](../scan.py) | 正式美股日报单列 `martin_candidates`；盘中与其他市场不运行这一观察池；原账户记录不参与改写 |
| [board.py](../board.py) | 独立观察章节；名称在前，名称缺失明确写“名称未缓存”；完整英文名及中文行业沿用已有缓存；仅展开前 5 |
| [test_martin_candidates.py](../tests/test_martin_candidates.py) | 合成因果与缺失用例、正式/盘中接入隔离、三个真实交易晚逐值与完整顺序对照 |
| [README.md](../README.md) | 入口、字段与数据边界 |
| `research/trader_board_cards.py` | 从生产脚本复制到本工作树后修改：QQ 独立观察卡片、独立正文章节、本地 HTML 与完整 JSON；该目录按既有约定不入 Git |
| [BOARD_IE_QQ_RENDER.patch](BOARD_IE_QQ_RENDER.patch) | 上述本机渲染脚本的可审阅补丁，供之后明确授权部署时使用；本次未应用到主目录 |
| 本记录 | 交付状态与待确认事项 |

`scan run us` 沿用原先的刷新流程，本改动没有扩大其取数名单。候选计算在原行情面板释放前完成，不重复回放任何账户；结果位于日报顶层，不进入 `traders`、`common`、`presentation.stocks` 或交易聚合。

**固定计算口径**

过滤条件仍为完整 leader 比较范围内的有限值百分位：`h4_history ≥ 60%`、`adr20 ≥ 70%`、`option_volume ≥ 80%`、`low20 ≥ 50%`。并列取平均百分位，缺失不通过，保留研究代码的浮点边界容差。

排名严格沿用 IE9：`after_inside` 是前一日内包事件，直接用 0/1；`near_ema9` 在过滤后小池内重新排百分位；两项各占一半，缺失按 0.5，同分代码升序。没有把离散事件另改成百分位，也没有采用 IE11 的放松条件。

H4 是研究方案的历史强势组，不是四小时 K 线。保留原活动范围、滞后、序数并列规则、原始收盘与当时复权事件的快速波动统计。只重建其中所需的历史组；按 64 只股票分块，仅保留 250 晚的活动排名窗口，不构建股票之间的矩阵。

**live 输入核对：2026-11-02**

| 输入 | 完整 leader 内有效 / 总数 | 现有通路与结论 |
| --- | --- | --- |
| h4_history | 298 / 1290 | `trader_data` 日 K 面板、`Dataset.rows()` 与 `actions()` 可每天推导；其余 992 只是原研究活动范围外的结构性缺失，照旧不通过，不填补 |
| adr20 | 1290 / 1290 | 当晚及以前复权日 K；与研究归一化、float32 缓存边界一致 |
| option_volume | 140 / 1290 | `trader-options-v1/us/stat` 加 `trader-options-live/us/stat`；当晚值不足，属于本次实际接入缺口 |
| low20 | 1290 / 1290 | 当晚收盘相对包含当晚的 20 日最低收盘；不是最低价 |
| after_inside | 1290 / 1290 | 前一晚高低点均在再前一晚范围内；边界包含相等 |
| near_ema9 | 1290 / 1290 | 负的收盘距 EMA9 的相对绝对距离 / 当晚 ADR20 |

冻结期权统计目录有 3433 只文件，文件末日为 2026-10-23；live 目录有 141 只文件，既有 `scan refresh us` 只为 Holguin 名单调用期权更新。141 份文件不等于每晚完整 leader 的覆盖：本例当晚只有 140 个有效值。

程序不取旧日期顶替、不前填、不把缺值改成零或中性过滤值。百分位仍以完整 leader 比较范围内的有限值计算；由于期权有效范围不足，JSON 标为 `partial`，正文明确写“当前结果不能视为完整候选池”。

最小补齐办法：用户同意后，沿用既有 OpenD `get_option_underlying_his_statistic` 接口，在现有前台日报准备流程为**完整 leader 范围**补齐当晚 `option_volume`，存入现有 `trader-options-live/us/stat`，保留失败和缺失记录；不需要小时线、历史 K 线额度、新数据源或独立后台。本次没有实现或启动这项扩大取数，尤其没有修改 QQ 定时任务。

**最近交易晚示例与本地渲染**

只读现有 live 数据及原 2026-11-02 日报，写入本工作树 `.cache/board-ie/`。保留原日报全部字段，只附加候选池，并逐值核对原账户、买卖、持仓与逐股比较均未改变。

> Martin Luk 候选池 · 研究观察版、未验证
>
> 观察日期 2026-11-02；共 0 只。
>
> 当晚期权成交量覆盖 140/1290 只；缺失不通过，旧日期不顶替。期权输入未齐，当前结果不能视为完整候选池。
>
> 当晚没有可展示的候选。

本地文件（均不入 Git）：

- [完整美股日报 JSON](../../../.cache/board-ie/us_2026-11-02_1d.json)：包含 `martin_candidates`、六项有效/缺失计数和原日报。
- [三市场看板 HTML](../../../.cache/board-ie/qq-preview/board.html)、[Markdown](../../../.cache/board-ie/qq-preview/board.md)：由本工作树的 QQ 渲染函数与看板函数生成。
- [独立观察卡片 HTML](../../../.cache/board-ie/qq-preview/martin_candidates.html)、[完整候选 JSON](../../../.cache/board-ie/qq-preview/martin_candidates.json)。
- [2026-06-05 历史布局示例](../../../.cache/board-ie/qq-preview/historical_2026-06-05.html)：使用既有冻结真实数据的同一计算，57 只仅展开前 5；[完整名单](../../../.cache/board-ie/qq-preview/historical_2026-06-05.json)。仅用于核对有候选时的展示，不作为最新观察名单。
- [复现脚本](../../../.cache/board-ie/preview.py)、[渲染核对记录](../../../.cache/board-ie/preview_summary.json)。脚本拒绝网络访问和工作树外写入，不运行 QQ 发送脚本。

QQ 正文的原有部分和图片索引前缀保持一致，观察区另起标题，排在买卖和持仓图片之后；观察名单不加入“今天的买卖”。按本例真实分页计算共 8 张卡片、正文 533 个 UTF-16 单元，未超过既有 50 张 / 9000 单元限制；这是编排检查，不表示生成了图片。本地 HTML 与 Markdown 已生成，完整名单另附 JSON。

**PNG 尚未验证**：本机现有 Chromium 在原始日报卡片和 `about:blank` 上均以 SIGTRAP（退出码 -5）结束，故未生成新的 PNG，也未伪造图片产物。本次按任务书的本地渲染选项核对 HTML、Markdown 与 QQ 正文编排；没有修系统浏览器或改生产脚本。

**验证**

真实对照在 2026-01-09、2026-06-05、2026-10-16 三晚完成：leader 范围分别为 1231、1304、1259 只，候选数分别为 60、57、8。完整范围的四个过滤原值、`near_ema9` 原值、过滤后的事件值、过滤百分位、小池排名百分位、完整名单顺序与等权分数，均与既有 IE8/IE9 研究缓存及研究函数逐值一致。仅做数值接入核对，没有重新选择方案或运行账户评测。

合成测试覆盖：未来行情变化不改变截至当晚的输出、完整范围过滤与小池重排、0/1 事件、缺失过滤失败、缺失排名中性、代码平手顺序、期权 frozen/live 开关及准确日期、历史不足、无数据/部分缺失展示、与交易记录隔离。标准库渲染入口仍可在未安装 numpy 的 Python 下导入。

| 检查 | 结果 |
| --- | --- |
| `python3 -m unittest discover -s custody/tests` | 237 项通过 |
| `.venv/bin/python -m unittest discover -s studies/trader_screens/tests` | 102 项：101 通过、1 项既有跳过；三个真实晚的对照已实际执行 |
| `.venv/bin/python -m unittest discover -s studies/trader_replication/tests` | 735 项：734 通过、1 项既有预期失败 |
| `python3 watch/test_watch.py` | 41 项通过 |
| 新增单元用例最后复核 | 7 项通过 |
| `git diff --check` | 通过 |

日志位于 `.cache/board-ie/` 的 `custody.log`、`trader_screens_final.log`、`trader_replication.log`、`watch.log`、`candidate_final.log`。验证及示例使用既有 `.venv`，`OPENBLAS_NUM_THREADS=1`，临时文件固定在本工作树；共享 `data/` 仅只读访问，没有往它写缓存或示例。

**合进 main 前需用户确认**

1. 是否授权在既有前台期权统计通路中扩大到完整 leader 名单；未同意前只能保持显式披露缺失的部分结果，不能承诺每晚约 50 只。
2. 是否同时部署本机 QQ 渲染补丁。`research/` 不入 Git，仅合入跟踪代码不会自动更新生产 QQ 图片与 HTML 入口；补丁已在工作树内临时副本重放并逐字节核对，应用时使用 `git apply --unidiff-zero`。尚未写入主目录。
3. 浏览器故障修复后核对实际 PNG，再决定生产上线；HTML/Markdown 的核对不能冒充已经核对过图片排版。
