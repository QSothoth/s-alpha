# 交易员研究档案与风格注册表

截至 2026-10-18。先保存可追溯资料，再决定逐人实现。本次仅新增资料和查询代码，不修改任何既有策略或回测。实现状态以 main 的 5bd4c16d 版本实际文件为基准；此前研究分支的代码单独标为历史分支，不将其整包合并进 main。该 main 快照经共享模块、配置及文档核对，未定位到可归属于 Mark 的专用实现；其历史研究分支实现单独链接，用户使用反馈不据此改写为 main 代码事实。

- [35人风格索引](INDEX_CN.md)：33位原研究对象 + Qullamaggie、Oliver Kell 两位追加方法参考
- [完整资料入口](dossiers/README_CN.md)、[资料核查边界](dossiers/AUDIT_CN.md)、[全部来源链接](dossiers/LINK_INDEX.csv)
- [机器可读注册表](registry.json)：身份别名、市场、风格、周期、多空方法、证据等级、来源账本、规则缺口、下一步、实际代码状态与路径
- [历史研究分支33对象实验](https://github.com/QSothoth/s-alpha/blob/9bc6a6b29c577d4ad6d6d13312beaf15ae7ab1f2/studies/trader_common/README.md)：代码存在、局部假设运行和原方法完整复现是不同概念
- [另外44个名字的原报告附录](dossiers/remaining/COVERAGE_ONLY_APPENDIX_CN.md)：仅保留名单，不计入35份档案，也不是44套实现
- [Martin版本对照](dossiers/swing/MARTIN_VERSION_CROSSWALK.md)：ADR、R、价格幅度和账户风险不混用；保留冲突，不改历史代码或结果
- [2026-10-25不同流派补充研究](DISTINCT_STYLES_RESEARCH_20261025_CN.md)：新增期权、做空候选，核对官方比赛与公开结单；包含选标的价值、规则缺口和港股检索边界，不计入上述35份冻结档案
- [2026-10-25扩展研究](DISTINCT_STYLES_EXPANDED_20261025_CN.md)：继续核查79组人物或团队线索，展开个股期权、信息差、小盘反转、港股价值与事件、系统化方法；逐项区分赛事、结单、自报、基金与模拟，不计入35份冻结档案
- [2026-10-25流派与评分总表](TRADER_SCORECARD_20261025_CN.md)：合并上述79组线索及首轮／已有档案10组对照，共89组；逐行列流派、选股作用、年度收益口径、稳健分、复现分、证据分及理由，资料不足标待评，不计入35份冻结档案

## main 上的筛选代码

2026-10-18 起，Qullamaggie、Clement Ang、Christian Flanders、Oliver Kell、Mark Minervini 在 [studies/trader_screens](../trader_screens/README.md) 有按原话初版的日 K 筛选（[规则卡](../../skills/trader-screens/references/SCREENS_CN.md)），Martin Luk 有已复刻冻结的系统。初版未对照真实交易、未评测；registry.json 里的实现状态没有随之修改，以本节和代码为准。

## 代码查询

运行环境仅需 Python 3.10+ 标准库，在仓库根执行：

```sh
python3 -m studies.trader_registry.registry
python3 -m studies.trader_registry.registry Mark --json
python3 -m studies.trader_registry.registry --cohort additional_reference
python3 -m studies.trader_registry.registry --status SOURCE_INSUFFICIENT_NO_FAKE_IMPLEMENTATION
python3 -m unittest discover -s studies/trader_registry/tests
```

Python API：`load_registry()` 返回不可变 `Trader` / `Implementation` 数据类；`query(records, "关键词", status=..., cohort=...)` 按身份、市场、风格、周期及多空描述过滤。加载时严格验证字段、类型、状态枚举、别名唯一性、URL格式、仓库路径存在和未实现对象不得声明实现代码。不会联网、下载行情或执行策略。

`unknown` 或中文“未知/未披露”表示没有足够证据，不用相似交易员补齐。风格摘要是检索标签，原始证据、日期、已读/未读状态、原话归因与具体规则冲突以链接的个人档案及来源账本为准。来源等级不是策略评分、收益预测或资金配置建议。

## 来源与版本约定

常见渠道包括官方/赛事、本人网站与博客、第一手采访、X、YouTube、播客、GitHub、Reddit、论坛、书籍和媒体。各组资料保留原有来源分类和逐项 claim 映射；找不到或没读到正文的渠道明确留缺口，不为每人强凑所有渠道。本人观点、营销材料、第三方转述、论坛评论和独立账户审计不可互换。

档案采用原创归纳、必要短引文和原链接；“原始资料入库”指来源目录与证据记录，不是镜像整本书、付费课程或无授权全文。本目录按交付清单保存档案与来源账本（中国组 README 删除了一条未随包发布的中间摘录指引，并更新对应哈希；两份CSV统一LF换行），不包含资料制作脚本或旧报告的整段中间摘录。dossiers/MANIFEST.json 是资料包冻结时的清单，其“未推送”说明属于当时快照，当前入库状态以本目录提交为准。

新增规则应先核实人物、来源日期和版本，再预登记独立研究。用户对 Mark 现有实现的使用反馈不等于独立样本外 Alpha 证据。所有记录均未授予生产交易资格。

## main 中新增的 Martin 资料对照

详见 [2026-10-18来源版本补充](MAIN_SOURCE_ADDENDUM_CN.md)，区分自动字幕整理、原声核听、旧评论与研究者最终配置。

原档案的阅读状态保留其研究时点。当前 main 另有 [访谈字幕摘录](../martin_luk/notes/RULES_CN.md)、[逐笔台账](../martin_luk/notes/trades.csv) 和 [R19–R74研究报告](../martin_luk/reports/REPLICATION_CN.md)。这些资料提供不同来源日期的规则，不抹去较早 ADR/R 冲突，也不把后期版本倒填为全年恒定规则。注册表的具体状态及路径优先于历史资料包的交付描述。

## 证据标签含义

- primary_rules_partial：部分规则有本人来源，仍不完整
- primary_framework_partial：本人来源支持大致框架，精确规则缺失
- interview_framework_partial：采访支持框架，未获得完整方法
- secondary_framework_only：主要依赖第三方方法归纳
- candidate_framework_unverified：仅候选线索，框架尚未充分核实
- identity_and_results_only：只支持身份/比赛结果，不能推出交易方法

标签不代表独立审计级别；逐项主张的实际证据边界见来源账本。
