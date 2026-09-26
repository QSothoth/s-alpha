# 数据规范（DATA）

实现：`custody/dataset.py`（读取与校验）、`custody/freeze.py`（每日冻结）。总则见 [custody 数据](../custody/AGENTS.md#数据) 与根规范的 [数据](../AGENTS.md#数据)。

## 1. Release 是什么

- 数据只通过 GitHub 仓库 `QSothoth/s-alpha` 的 **Release** 发布：一个 git tag + 一个 zip 附件（附 SHA256）。
- Release **不可变**：发布后不改文件、不换附件。数据有任何变化都发新 tag。
- 代码不走 Release；代码只在 git 分支里。
- 解压后的 Release 目录就是一个**数据集**，评测直接读取它。

## 2. 数据集布局

```text
<dataset>/
  manifest.json          数据集名、角色、窗口、跳过记录等元数据
  cases.json             {"cases": [ 每个期权合约一条 ]}
  CHECKSUMS.sha256       每个数据文件一行 "<sha256>  <相对路径>"
  underlying/<SYMBOL>.csv   正股 1m K 线（可包含多个交易日）
  option/<CONTRACT>.csv     期权 1m K 线
```

CSV 列：`code,close_time,interval,open,high,low,close,volume`。`close_time` 是带美东时区偏移的 ISO-8601 K 线**收盘**时间（第一根常规时段 K 线是 `09:31:00-04:00`）。
Release 里可能同时有 parquet 副本；本项目只读 CSV。

`cases.json` 每条 case 的字段：

| 字段 | 必需 | 说明 |
|---|---|---|
| `symbol` | 是 | 例如 `US.SPY` |
| `contract` | 是 | Futu 期权代码，例如 `US.SPY260914C600000` |
| `trade_date` | 是 | 交易日，必须等于合约到期日 |
| `right` / `direction` | 否 | 如有，必须与合约代码一致（CALL = LONG，PUT = SHORT） |
| `prev_close` | V5 起必需 | 正股上一交易日收盘价，用于评测形态标签，禁止传给策略；freeze 未取到时写 null |
| `session_close` | V5 起必需 | 当日收盘时间（提前收盘日为 13:00） |
| `selection` | V5 起必需 | 合约选择方式；V5 起必须是 `both_sides_atm_at_open` |

### CALL 和 PUT 必须一起验证（统一要求）

训练集和验证集都适用：

- 每个 (标的, 交易日) 同时包含**同一行权价**的 CALL 和 PUT 两张 0DTE 合约（行权价取开盘第一根 1m 开盘价最近的挂牌行权价），各算一个 case；
- 方向不得由当天结果挑选。两边都评测，当天无论涨跌，方向对和方向错的合约各占一半，结果与上游选方向的能力无关；这时「方向对错各半」的加权与简单平均完全一致；
- 两边不全的数据集只能做诊断，评测报告会标出「两边不全」，结论最高 PROVISIONAL；
- 发布前必须通过 `python3 -m custody check --dataset <目录>`：哈希全部一致、每个 case 行情完整、两边齐全，否则退出码非 0。

### 训练集必须排除验证集（硬隔离）

验证集是留出集，绝不参与拟合；训练集绝不能包含任何验证交易日或验证的 `(标的, 交易日)` 会话：

- 训练集 manifest 角色为 `train/custody`，验证集为 `validation/custody`，两者不可相同；
- `set(训练 trade_date) ∩ set(验证 trade_date) == ∅`；
- `set(训练 (symbol, trade_date)) ∩ set(验证 (symbol, trade_date)) == ∅`。

发布训练集前，除单数据集检查外还必须运行隔离检查（任一角色不对、或任何日期/会话重叠都会使退出码非 0，从而阻止发布）：

```bash
python3 -m custody check --dataset <训练目录> --validation <验证目录>
```

单侧 `custody check` 只保证一个目录自身合法；`--validation` 才会把「训练不得混入留出验证日」变成发布前的自动门槛。脚本可用 `custody.dataset.isolation_report` 复用同一判定。

读取时的强制检查（元数据和哈希在打开目录时检查，行情在加载 case 时检查；失败直接报错）：

1. 每个数据文件都有 SHA256：`CHECKSUMS.sha256`，或（验证集 Release 的布局）`manifest.json` 里 `series` 条目逐文件的 `sha256`；全部一致，且案例读取的文件必须在其中；
2. 每个 case 都是真 0DTE，合约属于该标的，存储的方向与合约一致；
3. 没有重复的 (合约, 交易日)；
4. 正股 K 线覆盖开盘到收盘的每一分钟；
5. 合约在交易时段内至少有一根成交量和收盘价均大于 0 的 K 线。

`check` 校验上述项目及同一行权价的两边是否存在；它不能仅凭数据文件证明行情来源真实或行权价确为挂牌最近值。合约选择必须使用 freeze 流程，不能把检查通过当成对任意外部数据的背书。

## 3. 可用数据集

| 名称 | 角色 | 用途 |
|---|---|---|
| `custody-0dte-v6.1`（V6.1） | `train/custody` | 当前唯一训练数据 |
| `custody-eval-2026-09-18-v2` | `validation/custody` | 当前唯一留出验证，只评测，绝不调参 |

只使用此处登记的数据集。新数据按下文流程冻结并发布，训练集 tag 从 `custody-0dte-v6` 起递增。`custody check --dataset data/custody-0dte-v6.1 --validation data/custody-eval-2026-09-18-v2` 通过（无重叠交易日或会话）。

### V6.1 详情

- zip SHA256 `49032a1b9f8cc5fef3c9a7d7fee9fef99e220e06e12c7f89d849ce70fddc04c1`
- `CHECKSUMS.sha256` 的 SHA256 `38b2d5d8b852deae9bc1aa599b41fb57410274c283834ea86367177960656206`
- 21 个交易日（2026-08-18 → 2026-09-16），146 个 case，73 组 CALL / PUT 两边齐全：SPY 40、QQQ 14、META 12、MSFT 12、AAPL 10、IWM 10、AMD 8、NVDA 8、TSLA 8、MU 6、AMZN 6、AVGO 6、GOOGL 4、INTC 2
- 与 V5 的区别：吸收了原验证集 `custody-eval-2026-09-16-v2` 的 2026-09-16（20 个 case），并给每个 case 加了事后标签
- 事后标签（`cases.json` 的 `labels` 与 `case_labels.json`，`ex_post: true`）：`path_scenario`、`market_shape`/`gap`、`range_bucket`、`orb15`、日内分段、成交量占比。**只用于统计和报告，禁止传给策略**
- 场景分布：顺势单边 51、逆势单边 51、震荡 20、先逆后顺 12、先顺后逆 12
- `custody check` 通过；`manifest.json` 的 `window.end`（2026-09-15）和 `underlyings`（缺 INTC）没有随吸收的 09-16 更新，以 `sessions` 和 `cases.json` 为准
- 取代 `custody-0dte-v6`（同样 146 个 case，无标签）

2026-09-25研究审计补充：V6.1追加的09-16共20个case缺`selection=both_sides_atm_at_open`及显式`session_close`，仅有旧near-ATM选择说明。现有`custody check`允许这些字段缺省，双边/行情/哈希检查通过不等于验证了开盘最近ATM；OR1更严格的研究准入因此拒绝该日，改用V5＋09-18作旧数据诊断。未修改Release、默认数据或策略注册状态，详见 [运行前更正](../studies/us_opening_range/notes/OR1_PREREG.md#运行前数据审计更正同日收益计算前)。

### 验证集 custody-eval-2026-09-18-v2

- zip SHA256 `8bf9eb37d7372dce30c4ca37188e11c45a5fddb744ef0c5de120a61f3d139253`
- `CHECKSUMS.sha256` 的 SHA256 `fba36ab960189e6fe80660629455774627915d1b8982361a324ec203892fc2c0`
- 2026-09-18 一个交易日，14 个标的各一组 CALL / PUT（共 28 个 case）：AAPL、AMD、AMZN、GOOGL、INTC、IWM、META、MSFT、MU、NVDA、QQQ、SNDK、SPY、TSLA；`custody check` 通过，与 V6.1 没有重叠交易日或会话
- 场景分布：顺势单边 8、逆势单边 8、震荡 4、先逆后顺 4、先顺后逆 4；一个交易日无法判定 G8 / G9，场景样本也不足，结论最高 PROVISIONAL
- 带与 V6.1 同样的事后标签（`ex_post`，不得进入策略）
- 取代 `custody-eval-2026-09-18`（同样 28 个 case，无标签）

### 已被取代的数据集

- `custody-0dte-v5`（train，126 case / 20 日）和 `custody-eval-2026-09-16-v2`（validation，20 case）：2026-09-20 起分别由 V6.1 和 `custody-eval-2026-09-18-v2` 取代。09-16 这一天已并入训练集，不再是留出验证；两个 Release 本身仍然有效，只是不再是登记的训练 / 验证数据。
- `custody-0dte-v6` 和 `custody-eval-2026-09-18`：内容与 v6.1 / -v2 的行情相同，只差事后标签，不再单独登记。

### 已停用的数据集

旧 tag `custody-train-0dte`（V4，单边 36 个 case）和 `custody-eval-2026-09-16`（单边 10 个 CALL）的附件在 2026-09-17 被原地替换，与原登记的哈希（`65398673…`、`58f0af99…`）不再一致，已停用；原内容与结论查 Git 历史。今后不得原地替换附件，数据变化一律发新 tag，也不以本地目录代替 Release。

### 下载并校验

以下 Bash 步骤遇错即停止；使用尚未下载、解压的目标目录，已有 Release 不覆盖。

训练集：

```bash
set -euo pipefail
test ! -e data/custody-0dte-v6.1
mkdir -p data
gh release download custody-0dte-v6.1 --repo QSothoth/s-alpha --pattern 'custody-0dte-v6.1.zip' --dir data
echo "49032a1b9f8cc5fef3c9a7d7fee9fef99e220e06e12c7f89d849ce70fddc04c1  data/custody-0dte-v6.1.zip" | sha256sum -c
python3 -m zipfile -e data/custody-0dte-v6.1.zip data      # -> data/custody-0dte-v6.1/
```

验证集：

```bash
set -euo pipefail
test ! -e data/custody-eval-2026-09-18-v2
mkdir -p data
gh release download custody-eval-2026-09-18-v2 --repo QSothoth/s-alpha --pattern 'custody-eval-2026-09-18-v2.zip' --dir data
echo "8bf9eb37d7372dce30c4ca37188e11c45a5fddb744ef0c5de120a61f3d139253  data/custody-eval-2026-09-18-v2.zip" | sha256sum -c
python3 -m zipfile -e data/custody-eval-2026-09-18-v2.zip data
```


## 4. 每日冻结（V5 起的数据来源）

先配置 [OpenD 环境](OPEND_SETUP.md)。OpenD 很快就会丢弃过期周权的历史，期权历史配额也有限，所以**每个交易日收盘 20 分钟后当天就要冻结**：

```bash
python3 -m custody freeze --dataset data/custody-0dte-work
python3 -m custody check --dataset data/custody-0dte-work
```

每个 (标的, 交易日) 的处理：

1. 读取完整的常规时段正股 1m（不完整则跳过并记录原因）；
2. 读取日线得到昨收；
3. 查当日到期的期权链，没有当日到期则跳过并记录；
4. 取离第一根 K 线开盘价最近的行权价，**CALL 和 PUT 两边**都拉 1m，各写一个 case；
5. 追加写入 CSV（按时间去重）、更新 `cases.json` / `manifest.json`、重算 `CHECKSUMS.sha256`，最后重新校验哈希与 case 元数据；完整行情和两边要求仍须运行 `custody check`。

重复运行同一天不会重复添加已有 case，但会重写行情、更新时间并追加跳过记录，不保证字节不变。默认标的见 `custody/freeze.py` 的 `DEFAULT_SYMBOLS`，可用 `--symbols` 覆盖。

工作目录 `data/custody-0dte-work` **不是** Release，可以一直追加；不要指向任何已解压的 Release；命令无法自动识别所有已发布目录。训练和验证使用不同工作目录，角色不能混用。

### 生成验证集

验证集和训练集用同一个命令、同样两边一起冻结，只是角色不同、交易日要晚于策略的开发截止日，并且绝不用来调参：

```bash
set -euo pipefail
python3 -m custody freeze --dataset data/custody-eval-2026-09-17 --date 2026-09-17 --role validation/custody \
  --symbols US.INTC,US.AMD,US.TSLA,US.NVDA,US.MU,US.AVGO,US.AMZN,US.GOOGL,US.META,US.MSFT
python3 -m custody check --dataset data/custody-eval-2026-09-17
```

OpenD 保留过期周权的时间很短，最好当天收盘 20 分钟后就冻结；多天的验证集就对同一个目录每天追加一次。

## 5. 发布新 Release

攒够一批交易日（建议至少 20 个新交易日，才够做样本外判定），并且 `custody check` 通过后：

先停止向工作目录追加数据，选择未使用的新 tag。以下以 V6 为例，目录或附件已存在就停止，避免复制嵌套或更新旧 zip：

```bash
set -euo pipefail
test ! -e data/custody-0dte-v6
test ! -e data/custody-0dte-v6.zip
test ! -e data/custody-0dte-v6.zip.sha256
cp -r data/custody-0dte-work data/custody-0dte-v6
python3 -m custody check --dataset data/custody-0dte-v6      # 必须 "ok": true（含 CALL/PUT 两边齐全）
sha256sum data/custody-0dte-v6/CHECKSUMS.sha256
(cd data && python3 -m zipfile -c custody-0dte-v6.zip custody-0dte-v6 && sha256sum custody-0dte-v6.zip > custody-0dte-v6.zip.sha256)
cat data/custody-0dte-v6.zip.sha256
```

核对检查结果、窗口、标的、case 数和上面两个 SHA256，将它们填写到发布说明后再执行发布：

```bash
gh release create custody-0dte-v6 data/custody-0dte-v6.zip data/custody-0dte-v6.zip.sha256 \
  --repo QSothoth/s-alpha --title "Custody 0DTE dataset V6 (both sides)" --notes "<窗口、标的、case 数、两个 SHA256>"
```

发布后只在本文件登记 tag、角色、窗口和两个 SHA256（zip 与 `CHECKSUMS.sha256`）。若正式替换当前训练集，再更新 `custody/AGENTS.md` 的可用数据约束；发布验证集不会自动使它成为训练集。

## 附录：港股近月流量研究数据（非 custody Release）

与上文 0DTE custody 冻结/Release 流程无关。港股正股期权排行与异动研究切片放在仓库内：

[`studies/hk_near_expiry_flow/dataset/`](../studies/hk_near_expiry_flow/dataset/)（`manifest.json` + CSV）。不走 `data/` Release 规则；仅供后续自行筛选，不接入 `custody check`。


## 附录：开盘区间研究数据与 Release

仅用于 [us_opening_range](../studies/us_opening_range/README.md) 研究；不更改上文 custody 当前数据集和默认策略。原目录名中的 `validation` 不代表它对后续反复研究仍是未见样本，使用历史见 [审计](../studies/us_opening_range/notes/RESEARCH_AUDIT.md)。

| 本机工作目录 | 身份与内容 | 状态 |
|---|---|---|
| `data/or-alpha-2026-09-25-holdout-work` | OpenD当日期权链、26标的依盘后链与当日开盘价选择ATM双边共52个0DTE合约、正股完整1m与期权成交1m；`validation/custody`（不是09:30链的PIT存档） | 2026-09-25盘后有限采集，0历史请求；106个文件校验通过，未评测。CHECKSUMS.sha256哈希 `e729dd3c11f61328e2cf996bd2eb0592baed733ad35a89c75ce20a5a67fbf1af` |
| `data/or-option-history-pilot-20260918-work` | 已知真实SPY09-18到期CALL/PUT原始分钟及元数据；仅接口质量试验，不是新验证 | 另获最多1条期权历史链额度许可，两腿各405根/1页；成功、不评测。CHECKSUMS.sha256哈希 `4da443f830cbbcd86290bc085cca02bbe55c635f879ce406089191e084d239c7`，边界见 [试验记录](../studies/us_opening_range/notes/OPTION_HISTORY_PILOT.md) |
| `data/or-context-etf-k5-2018-2026-retry1-work` | 获准12个ETF的OpenD QFQ常规5m，发布时角色`holdout/underlying-context`；实际2018-09-20→2026-09-25，每只2,014日，总1,877,760根 | 25文件哈希通过。RG1于09/26评测XLV/XLI/XLY截至09/24；另九ETF分钟及全部09/25仍未评测。CHECKSUMS.sha256哈希 `5ac28d322f91c5877349a2d1021bfabecce98c74e09f83cb45192d1f35cc66ee`；请求前缀缺12交易日，[质量记录](../studies/us_opening_range/notes/DATA_QUALITY_CHECK.md) |

以上三个目录已按原字节发布，数据未进 Git。ZIP 内仍以各自原工作目录名为顶层，manifest、CHECKSUMS 及原角色均未修改；对应发布如下：

| Release tag | 对应目录 | ZIP SHA256 |
|---|---|---|
| [or-alpha-20260925-v1](https://github.com/QSothoth/s-alpha/releases/tag/or-alpha-20260925-v1) | `or-alpha-2026-09-25-holdout-work` | `9e7d30740fef01792ac433e6e4121d1ec217dcd98a2cb9b4bbea12bbcb912cd5` |
| [or-option-history-pilot-20260918-v1](https://github.com/QSothoth/s-alpha/releases/tag/or-option-history-pilot-20260918-v1) | `or-option-history-pilot-20260918-work` | `77e956cd14f75b49c60138680117b569b095ef86c2a41585fc1fb8dfa65de490` |
| [or-context-etf-k5-2018-2026-v1](https://github.com/QSothoth/s-alpha/releases/tag/or-context-etf-k5-2018-2026-v1) | `or-context-etf-k5-2018-2026-retry1-work` | `7a11094d6841e316d2a6b789aa09866a69204c248e46b4b8f5bd4715355902a8` |

各 Release 附 ZIP 与同名 `.zip.sha256`；已从 GitHub 回下载，逐包 SHA256 及包内所有成员哈希均与原数据一致。共约49MiB，打包器 [package_data.py](../studies/us_opening_range/package_data.py) 采用流式复制、精确校验和覆盖及拒绝覆盖已有附件；它只生成本地包，不自动上传。遵守「发布后不替换、变化另发 tag」的项目协议；GitHub 当前返回 `immutable: false`，不宣称服务端已锁定。

三个 tag 均锚定远端既有提交 `45d0b620c6c05729adbe19daecb8cffe0fb218e3`，仅作数据快照锚点。采集发生于本地工作树，provenance 以原 manifest 与 SHA 为准，**不宣称该 tag 的代码可重现采集**；未推送本地未发布提交或工作区代码。

保存及完整性检查不等于验证 Alpha；单日不足独立验证门槛。12 ETF 分钟数据发布时未评测，但共享旧市场日期，其中9个标的有旧日线研究暴露，不能称全新时间或全新资产验证。订阅已释放，未启动后台采集。12个ETF采集恰新增12个普通历史额度、剩余72；期权pilot另获独立许可，具体范围/未用身份见 [研究计划](../studies/us_opening_range/notes/ALPHA_PLAN.md)。原 `or-context-etf-k5-2018-2026-work` 是零行情/零新额度的启动失败目录，保留原因，不作数据集使用。

### 固定旧日来源复核

[or-source-recheck-spy-20240530-v1](https://github.com/QSothoth/s-alpha/releases/tag/or-source-recheck-spy-20240530-v1) 保存 `data/or-source-recheck-spy-20240530-work` 的 8 个原始／审计文件：SPY 2024-05-30 的 OpenD 5m、日 K、延长 30m，以及 Yahoo／腾讯日线原始响应、manifest、比较报告与校验和。仅质量抽查，不是新验证数据；3 次历史请求没有新增额度，前后剩余均为72。

ZIP SHA256 `94b137be27757635c4271a299c59d14b0750580610435d7b6ccb8ae29c2488e7`；CHECKSUMS SHA256 `0abc2178327c1b0c4db7281cb03e261e31b0fc273758c78434976771b4b12ee3`。已回下载核对 ZIP、sidecar、全部成员和哈希。tag 同样使用远端既有 `45d0b620...` 作快照锚点，不代表该提交已含采集脚本。单日同源重取一致不能替全部历史背书；跨源复权、跨周期量与零量平价条目（成因未确认）的限制见 [复核记录](../studies/us_opening_range/notes/DATA_RECHECK_20260926.md)。

### 近期分钟跨源复核

[or-recent-crosscheck-20260924-v1](https://github.com/QSothoth/s-alpha/releases/tag/or-recent-crosscheck-20260924-v1)另保存三ETF在09/24的Yahoo原始5m响应、已固定OpenD当日摘录及比较manifest，共8文件；仅3次HTTP，没有历史额度。ZIP SHA256 `99310665c4b8a5223dd14d2ce2fd38e952eb0e779a5ddf9acefe7c6d1fdee703`，17100字节；CHECKSUMS `7be5369bde6b50bde44ab55d0406895d3c2b24adc261c0b8c18769d76bf70ce1`。已回下载核验ZIP、sidecar、精确成员与逐文件SHA，原响应仅按字节验签未提取越界行情。主+5分钟标签对齐下，929/936个OHLC相对误差≤1e-6，226/234根成交量仍不同；不能替全部历史背书。请求虽止于09/25零点，Yahoo每份额外返回09/25 16:00条目：原字节保留，但按时间戳跳过，未用于比较、特征或收益。完整边界见[复核说明](../studies/us_opening_range/notes/RECENT_CROSSCHECK_20260924.md)。

### 冻结的派生信号／标签快照

推荐使用纯数据[or-signal-research-20260926-v2](https://github.com/QSothoth/s-alpha/releases/tag/or-signal-research-20260926-v2)：`data/or-signal-research-20260926-v2-work`，5报告＋5预登记＋5事件文件＋manifest/CHECKSUMS，共17成员；不含源码，代码仅校验并保存SHA。15个研究文件与v1原字节一致，研究结论及7373条重叠记录不变。ZIP SHA256 `35b40250ae5489feff669a1b8cd5bd84b12567ec21fbcf49d64bc025d2adb92c`，2591768字节；CHECKSUMS `09c24fee70e550fc9c71414e8e825aa1221fce343216ef30e50730240231f8bb`。远端回下载、sidecar、精确成员／逐成员SHA／CRC均通过。

已撤下的`or-signal-research-20260926-v1`本地备份保留于 `data/or-signal-research-20260926-work`及同名v1 ZIP／sidecar：DS1、DS2、PERSISTENCE、AH1、RG1首次运行的5份机器报告、5份预登记、5个事件／标签文件及合并去重的实现指纹源码，共31文件。**流程偏差：其中14份源码不符合本文“代码只走Git”的约定；已另发纯数据v2，并于2026-09-26获用户同意后删除旧v1 Release、两个附件及同名远端tag，回读确认均不存在；其他Release不变。打包器已修正为仅保存数据及代码SHA。** 7373行派生记录包含重复候选和跨期限描述，不是7373个独立样本；没有原始行情重发，不接入custody交易。

旧ZIP SHA256 `eb42661f10192bd2ce69f85786c5787889376bfc139fe85619052258076f7b1f`，2,652,364字节；CHECKSUMS SHA256 `9e7867f9f6902288361e338abf0d960a3227365c038add93a8d1531974755d2f`。本地31成员在删除远端前重新通过逐SHA／CRC校验，可恢复包内容，不承诺恢复远端对象ID或下载统计；不自动重发。旧tag原锚定`45d0b620c6c05729adbe19daecb8cffe0fb218e3`。已暴露标签不能恢复留出身份，重新生成还需固定原行情与匹配源码；角色及处置见[发布说明](../studies/us_opening_range/notes/SIGNAL_RESEARCH_RELEASE.md)。

[or-rg1-cards-20260926-v1](https://github.com/QSothoth/s-alpha/releases/tag/or-rg1-cards-20260926-v1)为全部118个RG1提示提供因果SVG图卡、绘图输入与独立事后标签表，共123文件。ZIP SHA256 `337f11771d1aadfb30f68a12c022351f1da6cba0db1d23442a50d332ee60c739`，349349字节；CHECKSUMS `ac50dd50fe0b354149c629e29d6af9629d81154ddccec2e2941f7b2e41776d21`。解压后直接打开index.html，无CDN；只画提示之前的日K/早盘，不挑赢家、不改变原NOT_PASSED状态。见[图卡说明](../studies/us_opening_range/notes/RG1_CARDS_RELEASE.md)。派生快照及图卡都已回下载核验ZIP、sidecar、精确成员与逐文件SHA。

### S22旧口径复现、日K来源质量与OM1图卡

[or-s22-audit-20260926-v1](https://github.com/QSothoth/s-alpha/releases/tag/or-s22-audit-20260926-v1)保存旧选择／原验证的审计报告、计划、运行记录及2696条重叠派生事件，共7成员，无源码／原行情。原CLI显示字段逐行MATCH，不是新增验证；实际原验证日线截至09/23。ZIP SHA256 `45ee76f214e2e0d36665d107f884da61acd0944a23e527435ddaf917778f42f0`，312355字节；CHECKSUMS `66e62b927bde7705e5cc410d6b6ebf1d2f70f689dab656f73920edf37b9c650b`。范围和指纹见[发布说明](../studies/us_opening_range/notes/S22_AUDIT_RELEASE.md)。

[or-daily-source-check-20260926-v1](https://github.com/QSothoth/s-alpha/releases/tag/or-daily-source-check-20260926-v1)保存三ETF当前日K只读返回与质量manifest，共8成员；截至09/24的20日、240个OHLC及21项历史levels精确一致，60项volume均不同。6次有限行情调用、0历史请求；09/25附带返回只原始留存，不提取比较其价格。ZIP SHA256 `7646483bbf15f8b3fdc722adde02bf14fef1977474c0648de84bd499379dd7a2`，18627字节；CHECKSUMS `51a21afa5c9e09f3a081c7a045e79225bdb928158f9888f19f12d6e7add54bee`。仍保留全局来源等价性未验证，详见[发布说明](../studies/us_opening_range/notes/DAILY_SOURCE_RELEASE.md)。

[or-om1-cards-20260926-v1](https://github.com/QSothoth/s-alpha/releases/tag/or-om1-cards-20260926-v1)保存OM1全部7个独立提示的因果图卡、绘图输入、原231候选记录、机器报告及预登记，共14成员，无源码。期权6个有效毛标价、1个缺端点，不是购买胜率或净收益验证；图只含当时已知历史／早盘，已有事后标签另表。ZIP SHA256 `807107c5fdda318764a8ddad13ede873ff7e96883324503e90a0f28eee29d729`，40997字节；CHECKSUMS `b548a56a6356a770edd8ea7c750a355f5d612530a22e849acd54580c8af9966e`。本机初版仍保留，本包只修复文字遮挡而未改行情、规则或标签；远端回下载的ZIP／sidecar、精确14成员及逐文件SHA／CRC均通过，见[发布说明](../studies/us_opening_range/notes/OM1_CARDS_RELEASE.md)。

上述三包均已独立回下载核验远端ZIP/sidecar、精确成员、逐文件SHA和CRC；tag仍锚定既有远端提交，不代表该tag包含后续研究实现。代码另由Git提交保存，不重指向数据tag；包内“未发布”是创建时的事实快照，发布后不回改字节。

## 附录：盯盘信号研究数据（非 custody Release）

`studies/watch_signal/`（盯盘 `watch/` 的信号研究）的数据，按用途分成 6 个 Release。只供该研究使用，**不接入 `custody check` / `evaluate`**，
也不受上文 0DTE 冻结流程约束；但同样不可变，变化发新 tag。每个 zip 内有 `manifest.json`（来源、窗口、行数、字段说明）和 `CHECKSUMS.sha256`。

| tag | 角色 | 内容 | zip SHA256 | CHECKSUMS.sha256 的 SHA256 |
|---|---|---|---|---|
| `watch-hk1m-train-v1` | 训练 / 选择 | 140 只港股通 1m（QFQ），2025-12-01 → 2026-08-14，172 天，774.9 万行 | `cd1af1ab66a6591f33b3b230e047a94c6a5fc010fd0ef8122e6b443618ab49ce` | `93b010478ea49b474de4b5352ba8e3884967808db455ce32748b217aeb4aab26` |
| `watch-hk1m-valid-v1` | 验证（只评测） | 同 140 只，2026-08-17 → 09-23，28 天，129.8 万行 | `ffc9cc3f0be2197cfd67d681aef22d3e9f5a4e94dbccf9d530cb4576d7045ad8` | `0283e569bb34d9b0dcfda12b7e80e0b9c2d84c92a54ff2c2b29a1afcdd5d3c6a` |
| `watch-hk-index1m-v1` | 大盘参照 | 恒指 2025-12-01 → 2026-09-23；恒生科技、盈富 2026-06-01 → 09-23 | `f140204d499ac8ee389cd8ffdbd43f97aab3a659fb9fd7b597059db911f5500d` | `30a6c836373c2564f94c5d5f349d5b408b35336bcbfe549187a74eef44d1183d` |
| `watch-hk1m-holdout-2025h2-v1` | 第二留出段（W9–W11） | 同批港股通 1m（QFQ），2025-06-02 → 11-28，126 天，560 万行；当时已上市的 135 只 | `a67cee50306aef78d427ea098b05113fa9e53ae1daca987911f85f6b43a46b32` | `dbc9d965bed45c4fd894c92889c7b4684c1add23e9592556177d03df631f57a5` |
| `watch-hk-daily-v1` | 日线背景（W6） | 140 只 + 恒指日 K（QFQ），2024-06-03 → 2026-09-23，569 天，7.7 万行 | `e40e5e6c417059da7e2f35f3fe595afedb57a54a7666faa51c1a6355f7aa8e8f` | `d12bb68a266fa1a7e9b783848813fe09e2b36f3a42f7eec84a16952c1ce9d4f2` |
| `watch-hk-flow-2026-09-24-partial` | 资金流单日测试 | 140 只分钟资金流 + 同日 1m，**只到 13:53 HKT（未收盘）** | `0ed5c3c13801954e0b07ae3b7f1d5178891b7a77dd3fe12c8462d310bcd0be50` | `b2c7d6c5f11fd01bf7d023e5e139d0979785e8002cd969e265e777ba5584b387` |

```bash
gh release download watch-hk1m-train-v1 --repo QSothoth/s-alpha --dir data
cd data && sha256sum -c watch-hk1m-train-v1.zip.sha256 && unzip watch-hk1m-train-v1.zip
```

全部为只读行情；1m K 线只拉了 30 天内已扣费的标的，没有消耗新的历史 K 线额度。


## 附录：开盘方向预判研究数据（非 custody Release）

[归档研究 studies/archive/us_preopen_bias/](../studies/archive/us_preopen_bias/README.md)（T 日开盘时判断各标的开盘 → 收盘方向，给 0DTE 上游选边）的数据。全部来自本机 OpenD、一次性拉取，
不需要逐日采集；历史 K 线只拉 30 天内已扣费的标的（S10 新标的的日 K 走订阅接口）。只用技术面 / 交易数据，不含财报、宏观日历。
**不接入 `custody check` / `evaluate`**；同样不可变，变化发新 tag。每个 zip 内有 `manifest.json`（来源、窗口、行数、字段说明）和 `CHECKSUMS.sha256`。

| tag | 角色 | 内容 | zip SHA256 | CHECKSUMS.sha256 的 SHA256 |
|---|---|---|---|---|
| `preopen-us-train-v1` | 选择段 | 16 只：日 K（2022-06 起）、单标的期权成交量 / Put/Call / 持仓与 IV / HV（2023-06 起）、每日卖空量（2022-05 起）、全市场期权统计，全部截止 2025-06-30 | `5cb028da09d597f2cf5301a59496c7dfbc06a25760b4fed9fa40440eda0934e8` | `dca1d6241507d48a1bf917af483acee6ca130afac72895f1c319955458d5f3bb` |
| `preopen-us-valid-v1` | 验证段（S1–S5 已用过一次，之后只作选择） | 同样的表 2025-07-01 → 2026-09-23，另含日级资金流（只有 2025-09-24 起）；特征热身需与训练 Release 一起加载 | `851a3efa588226e3228409c4a79d1b45040fee767abc5099987e0c4d17203bbc` | `6be1052129e17dfdb94e6a6a93e67b7035d4b1315f11ae511e90a278b271fbf4` |
| `preopen-us-holdout-2016-v1` | 日 K 留出段 | 14 只日 K 2015-06-01 → 2022-05-31（2020-02 → 2023-07 已被 S9 留出段用过一次；2016-01 → 2020-01 未用） | `86be1b66851c522f2af9c3ab7fbc3cc11eaf9a761d60e8018e21c37599a757d0` | `64383dc75c60e3bf8eef6c87b96a319e86b67e32d61849f9e82d4742225912d7` |
| `preopen-us-ext30-select-v1` | 选择段 | 16 只延长时段 30 分钟 K 线（只含盘前 ≤ 09:30、盘后 > 16:00，time_key 为 K 线收盘，美东），2023-06-01 → 2026-09-23 | `f36b7985cc37b9dad17bf877b2edb723a93aae070c0e4b1390b300852ef792ba` | `2360ff1584010aeede834a8d011a72944e129338190803fef0738fbb27b63df7` |
| `preopen-s21-select-v1` | 每日多空名单选择段（S21 / S22） | 34 只热门中小盘（AI / 创新药 / 资源，规则见 `notes/universe_smallmid.json`）：日 K、期权统计、IV / HV、卖空量、资金流、盘前盘后 30 分钟 K、不复权日 K，2025-01-01 之前；日收盘与 Yahoo / 腾讯交叉核对一致 | `762850fb79ec7b95f10cb87be99452b624d45d01e5b3df8acf22bac915fe85ff` | `9fd9ece38757cfe115512b7c94d78ee7da2930ef3cdbf1448072484587e7f1a0` |
| `preopen-s21-valid-v1` | 每日多空名单验证段（S22 已用一次） | 声明窗口2025-01-01→2026-09-24；daily／option_stats实际01/02→09/23共432日，部分辅助表到09/24；09/26旧口径审计未补齐或新增验证 | `f200246fb99bbc729f9b12b16c3990c471d86e89592fe10b09d90f215c097d74` | `42b8a0b53c69cac1152696de25e61660ff79f036b4e1534b343ec2b88c55e677` |
| `preopen-s23-select-v1` | 全市场名单选择段（S23） | 期权成交量排行前 120 中的 114 个（剔除杠杆 / 反向 ETF 与 VXX）：日 K（前复权与不复权，订阅接口、不扣历史 K 线额度）、期权统计、IV / HV，2025-01-01 之前；与 Yahoo（部分含腾讯）核对，NOK、SPCX 不达标、评测时剔除 | `b10c7e73d51c0b266d05518b8c2a84720bd67e2965aec4fe1f5e3c25ef741138` | `49fb68958ce4bd72d025dd624308c9ac62ddb4435d215d80877ff84c1a59098c` |
| `preopen-s23-valid-v1` | 全市场名单验证段（未用） | 同样的表 2025-01-01 → 2026-09-24 | `0477edd1ac22c86befe9cbe2813057e6d63c7a45ae5927e1d1b35c72bde260c8` | `397771322a5b3c2d901b3c2313d4165e86548cd5e7e4f2132cb971672fb263cd` |
| `preopen-s24-select-v1` | 个股多空 Top N 选择段（S24–S26） | 期权成交量排行前 300 只股价 ≥ 3 美元的个股：日 K（前复权与不复权，订阅接口分批、不扣历史 K 线额度）、期权统计、IV / HV，2025-01-01 之前；与 Yahoo 核对，BRK、SPCX、B 剔除 | `f1f0244a63e3e28990d5ee8254b0f9991bd6f7a6bd9a613a8943e9010c3ed1ed` | `79a7a4830c9aa924ac7dacb4ce39b2a2461eeda1e70c2bb0271c00716ef9b2bf` |
| `preopen-s24-valid-v1` | 个股多空 Top N 验证段（S26 已用一次） | 同样的表 2025-01-01 → 2026-09-24 | `8de2e76dddd3fc966b1761e85d409825074f1521d55e726dd56225ad97ab3b10` | `1ee2292985bce9d407203d151126b0015c38dc0c380fd57666224670897191c3` |
| `preopen-s27-holdout-v1` | 个股多空 Top N 截面留出（S27 已用一次） | 同一排名日紧接前 300 只之后的第 301–600 名个股：同样的表，2022-09 → 2026-09-24 不切段；与 Yahoo 核对 300 只全部通过；历史 K 线额度前后 216 / 84 | `0a709367405828d48ba4c2a142f0e36f189bae412b58953dd910eb5dd5cb9817` | `4cfaa0ca3f19599a8eb08e34e5ddb80a9d20de72989b6e8dc382eed97ee4e4f6` |
| `preopen-us-xsec-v1` | 截面新检验（S10 已用一次） | 2026-09-23 期权成交量排行里原 16 只以外的前 40 只：日 K 最近 1000 根（`get_cur_kline` 订阅接口，不扣历史 K 线额度，订阅随后释放）+ 资金流 2025-09-24 → 2026-09-23 | `cb4a0dfc0e7cd09ed9f28d790e0223898c506ddbb266cae3f44366d2293b6495` | `0584d9361b77b9870cb78ffb10de73264407ddf3358931fa46b73635b106691f` |
| `preopen-us-ext30-holdout-v1` | 留出段（S9 已用一次） | 14 只同样的 K 线，2019-12-02 → 2023-07-31（盘前成交量 2020-01 起才有） | `badfb8d2e1972a69b09b061d3f06d6efafaf1f6566bb240294490018d69eb21a` | `990ce3293d24dda71eb9ea82668c39f5aa4fa071445e2846cdf6b57d6450ce2c` |

**已删除的 Release（2026-09-25，用户决定）**：`preopen-us-k5-select-v1`（`e096594f…6e38`）、`preopen-us-k5-valid-v1`（`dfa2f591…7f24`）、
`preopen-us-k1-o4-select-v1`（`6bfc744e…ab9d`）、`preopen-us-k5-2019-holdout-v1`（`f2a28315…316a`）、`preopen-s20-select-v1`（`98e3d658…e8f6`）、
`preopen-s20-valid-v1`（`60b1d55b…2230`）（括号内为 zip SHA256 首尾）。这是已撤掉的日内规则（S11–S20）的 5 分钟 / 1 分钟 K；S28 / S29 用过其中 k5 与 s20 四个，
**这两轮结果不能再从 Release 复现**，只有本机 `data/` 的副本（可按上面的哈希核对）。

```bash
gh release download preopen-us-train-v1 --repo QSothoth/s-alpha --dir data
cd data && sha256sum -c preopen-us-train-v1.zip.sha256 && unzip preopen-us-train-v1.zip
```
