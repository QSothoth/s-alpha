# IE11 计算前登记：放松四条件与行业、题材强弱

唯一任务书为 [PLAN_IE11_CN.md](PLAN_IE11_CN.md)，运行期间不改任务书、旧登记及旧结果。本登记先于本段任何条件留住率、描述和方案评测；后续只追加轮次与冻结记录。

## 数据与一次性查询

一次性查询名单取 trader-data-v1/v2 美股 universe、现有行业快照与 IE5 日线缓存代码的并集，不按他的交易挑名单。仅调用本机 OpenD 的 get_owner_plate，每批至多200只，请求间隔3.5秒，不重试失败批次，不调用其他行情业务接口、交易接口、历史K线。开始前写一次性执行凭据；已有凭据即拒绝再取。记录每批时间、返回码、原始行、无返回代码；权限或连接错误即停止，以现有行业快照补行业，概念没有则如实空缺。原始数据与SDK日志都存 ie11_work/plates/，不进git。

成员是本次静态快照，行业与概念分开计算，均不冒称历史点时成员。已有行业只补本次缺失股票，不与本次成功行业重复。日线优先复用IE5的3433股、951日复权收盘面板；新增缓存成员只流式读取v2已缓存前复权日线，截到原研究日历，不新增交易日。两份缓存的复权终点差异是继承限制。所有窗口只用本晚及以前价格，不前填缺失。

## 固定18个板块因子

以下9项各做行业、概念两个版本，共18项，之后不增删。每个板块每晚每个窗口至少5个有效成员才有值；这条也用于行业，以免微小组失真。收益为端点均有限且价格正数的成员等权收益。成员不足不填0；没有有效所属板块时股票因子缺失。

| 后缀 | 公式和白话理由 |
| --- | --- |
| heat5 | 板块成员5日收益均值在同类全部有效板块中的百分位，衡量近期热度；股票取所属有效板块最大值。 |
| heat20 | 同上，20日，衡量一月行业或题材是否强势。 |
| heat60 | 同上，60日，衡量中期趋势是否强势。 |
| diffusion_pot | 所属板块有当晚收盘的成员中，进入当晚leader范围且pot_count20全范围百分位≥70%的比例，衡量强势扫描的扩散；多板块取最大。 |
| diffusion_history | 同上，改为h4_history全范围百分位≥60%，衡量反复强势的扩散。 |
| leader20 | 本股20日收益在所属板块有效成员中的百分位，多板块取最大，衡量是否领头。 |
| leader60 | 同上，60日，衡量中期是否领头。 |
| heat_change5 | 同一个板块heat20本晚减五个交易日晚前的值，再对股票取最大，衡量板块刚开始升温。 |
| hot_count | 所属有效板块中heat20≥80%的个数，衡量同时属于多少个热门方向；有有效板块但无热门取0，无有效板块缺失。 |

板块百分位及成员内百分位均有限值平均同分；唯一有效对象记0.5。行业、概念不混排。扩散的分母是有收盘的成员，分子明确要求进入当晚leader范围，范围外成员表示未进入该扫描，不把未知H4数值当成已知分数。板块可重叠，各板块分别等权，非按股票市值加权。

板块因子在放松后的上游池内转成当晚有限值百分位，再描述过滤条件；常见阈值固定为0.3/0.5/0.7/0.8/0.9，正反方向各测，反向条件为1−百分位≥阈值。高热度/扩散/领先代表顺势，低热度/领先代表回调或提前布局的对照，不能看2026后翻方向。每个条件分别列四半年：主目标数、上游保留数、新保留数、两种分母留住率、池宽中位、宽度保留比例。只允许四半年留住率严格大于宽度保留比例的条件进组合；该描述是准入而非显著性证明。

## 第一层：放松四条件

百分位沿用IE7完整leader范围，缺失不通过。h4_history只准0.6或0.5，adr20只准0.7或0.6，option_volume只准0.8或0.7，low20只准0.5或0.4；至多删掉其中一条，不新增上游条件。最多2轮、每轮至多5组合。

先看四个半年范围内大赢家留住率最小值，合格须每半年≥90%；同时报全部主目标分母。合格者按2024–25合并每晚宽度中位最小、分年较大的中位最小、条件少、登记顺序选。没有合格者时取最低留住率较高者再比宽度，明确标注未达到上游目标；不得声称搜索过全部可能组合。

第一轮在看结果前固定：

| ID | h4_history | adr20 | option_volume | low20 | 理由 |
| --- | --- | --- | --- | --- | --- |
| U1A | 0.6 | 0.7 | 0.8 | 0.5 | 原四条件参照。 |
| U1B | 0.5 | 0.6 | 0.7 | 0.4 | 四条各低一档，检查可达上限。 |
| U1C | 0.5 | 0.7 | 0.8 | 0.5 | 只放松反复强势。 |
| U1D | 0.6 | 0.6 | 0.8 | 0.5 | 只放松日内波动。 |
| U1E | 0.6 | 0.7 | 0.7 | 0.5 | 只放松期权活跃。 |

第二轮只依据第一轮的半年聚合留住率与宽度登记，最多5项；不得按单笔/代码加例外。两轮结束冻结上游，再做板块描述与方案。

## 第二层、选择与账户

最多3轮，每轮行业、概念及共同参照合计至多5方案，不给两个分支分别增加预算；每方案至多3条新增过滤条件、至多4个等权排名因子。排名只准after_inside、near_ema9及对应版本的板块因子。允许IE10已描述合格条件作过滤候选，但本段优先板块，不预留额外数据类型。新增条件在放松后的上游池算百分位，交集过滤；连续排名因子在最终过滤后池重算百分位，事件after_inside用0/1，排名缺失记中性0.5，同分按缓存代码升序。池子≤5只全部选入；前1/3/10仍由同一完整排名给出。

板块排名的名称与方向也须有四半年合格描述，after_inside和near_ema9作为任务书允许的基准搭配不重新筛选。方案在运行前逐项写入轮次JSON并追加本登记，登记快照与摘要写入结果。下一轮据漏斗聚合损失改过滤或排名，不看2026。

行业、概念分别选择冻结版本；共同无板块参照可供两者回退，不由2026选择分支。主分数为四半年大赢家前五覆盖率最小值；每个半年必须严格高于四晚并集随机期望。账户沿用现金六仓H4不分批与既有杠杆账户、已修正的开盘加仓保护逻辑，2024和2025每年开仓≥52、已结束胜率≤35%，只作否决，收益不参与选择。平手先新增条件少、再排名因子少、再全部入场前五覆盖高、再登记顺序。无合格方案则只报描述性最高者和资格失败，不能偷偷放宽。

评价标签、28/32训练分母与23/49既有2026分母、入场前四交易晚口径均继承IE10。每方案报前1/3/5/10、年/半年、主/全部、范围→放松上游→新增过滤→前五漏斗、宽度与空夜、账户笔数/已结束胜率/收益/回撤/实际买到。范围外损失保留在完整分母，不算过滤误伤。

## 消融、对照与冻结

每个分支从合格最优者开始，先逐条试删新增过滤条件、再试删排名因子；四半年min不降且仍符合随机和账户资格就删，每次接受从头重试。冻结上游不再调整，但另报逐条去掉上游条件的诊断，不拿诊断改上游。每个留下的条件/因子保留去掉它的代价。

同池同宽度每晚无放回随机排名30次，种子2026111100至2026111129；四晚并集理论期望为逐笔1−Π(1−min(1,5/当晚池宽))之和，只有该目标当晚通过条件才给概率。排位为1＋随机中严格更高次数，同值单列；训练段与2026均报期望、均值、范围与排位，随机名单不回放账户。

一次标签打乱，种子20261111：在已冻结放松上游内，同晚共享置换，重复披露共享映射，上游外夜晚不挪进池。重新做板块描述，按真实候选在同类合格条件/名称方向清单中的位置映射同结构方案，走资格、选择、消融；不可用结构如实计数，全部不可用则用共同参照，标退化。该对照只针对冻结上游后的搜索，不重做上游两轮人工设计；不能提供完整搜索p值。

两个分支及源码、输入、因子文件均冻结后，2024–25与2026正式回放各一次。2026已看过六次，不是干净考试；行业版、概念版2026单列，不能按结果加轮次。概念快照可能包含后来才火的票，成员关系有未来信息，所有概念回测均有该风险，2026也不能视为独立验证；行业分类也有静态成员偏差。

## 执行边界与验证

一次一个研究进程；先查内存，ionice -c3 nice -n19，OPENBLAS_NUM_THREADS=1，PYTHONUTF8=1，PYTHONDONTWRITEBYTECODE=1，使用项目现有venv。CPU只由外层控制；不新增CPU守卫。逐股/逐板块处理、memmap存盘，不构造股票×股票矩阵、不无界加载CSV。临时目录与SDK日志限定在ie11_work，计算阶段禁止网络及子进程，只读data与旧产物。

不提交、不推送、不改登记版/custody/工作区外文件。现有密钥钩子及扫描器已配置，本段不重装或改写工作区外Git配置。新增合成测试至少覆盖板块未来价格截断、成员不足5、并列/缺值、多板块聚合、过滤和排名边界、随机种子与源码无本人证券/入场日期常量。最终跑custody/tests、trader_replication、martin_luk和git diff --check，并核查真实产物及旧文件摘要。

## 上游第二轮计算前追加

第一轮全部低一档仍只留2024H2的5/6，瓶颈不是交集内轻微阈值。第二轮逐条删除原条件，另给尚未单独检验的low20删除配合其余三项低一档的边界对照；只按半年聚合结果设计，不识别股票。

- U2A：adr20≥0.7、option_volume≥0.8、low20≥0.5。
- U2B：h4_history≥0.6、option_volume≥0.8、low20≥0.5。
- U2C：h4_history≥0.6、adr20≥0.7、low20≥0.5。
- U2D：h4_history≥0.6、adr20≥0.7、option_volume≥0.8。
- U2E：h4_history≥0.5、adr20≥0.6、option_volume≥0.7。

## 上游冻结，板块描述之前

两轮10项完成，唯一四半年范围内留住率均≥90%的U2A胜出：删除h4_history，保留adr20≥0.7、option_volume≥0.8、low20≥0.5。四半年范围内分别5/5、6/6、4/4、11/11；全部主目标分母分别5/5、6/6、4/4、11/13，合并26/28。合并每晚中位69只，后续不得改上游，未运行本段2026覆盖或账户。

## 板块第一轮计算前追加

18因子共180条件，31个通过四半年描述；未使用2026标签。上游范围内26笔全部留住，先解决排名。行业反复强势扩散、板块内20日领先，概念近期热度及20日领先均有四半年合格方向；每种先比较只排名与一条过滤，外加共同参照。heat20两类都未通过准入，不用于方案。

- {"id": "R1A", "kind": "reference", "filters": [], "factors": [{"name": "after_inside", "direction": 1}, {"name": "near_ema9", "direction": 1}]}
- {"id": "R1B", "kind": "industry", "filters": [], "factors": [{"name": "after_inside", "direction": 1}, {"name": "near_ema9", "direction": 1}, {"name": "industry.diffusion_history", "direction": 1}, {"name": "industry.leader20", "direction": 1}]}
- {"id": "R1C", "kind": "industry", "filters": [{"name": "industry.diffusion_history", "kind": "percentile", "direction": 1, "cutoff": 0.5}], "factors": [{"name": "after_inside", "direction": 1}, {"name": "near_ema9", "direction": 1}, {"name": "industry.leader20", "direction": 1}]}
- {"id": "R1D", "kind": "concept", "filters": [], "factors": [{"name": "after_inside", "direction": 1}, {"name": "near_ema9", "direction": 1}, {"name": "concept.heat5", "direction": 1}, {"name": "concept.leader20", "direction": 1}]}
- {"id": "R1E", "kind": "concept", "filters": [{"name": "concept.heat5", "kind": "percentile", "direction": 1, "cutoff": 0.3}], "factors": [{"name": "after_inside", "direction": 1}, {"name": "near_ema9", "direction": 1}, {"name": "concept.leader20", "direction": 1}]}

## 板块第二轮计算前追加

第一轮行业最优R1B漏斗28→26→26→26→17，主要排名丢9笔；先分别去掉一个板块排名，另用留住率更宽的leader20≥0.3替换误伤扩散过滤。题材最优R1E为28→26→26→18→15，过滤丢8笔最大；R2D直接删热度过滤而保留原排名，R2E从同轮无过滤结构替换领先为扩散，检查硬切与等权信息的差别。

- {"id": "R2A", "kind": "industry", "filters": [], "factors": [{"name": "after_inside", "direction": 1}, {"name": "near_ema9", "direction": 1}, {"name": "industry.leader20", "direction": 1}]}
- {"id": "R2B", "kind": "industry", "filters": [], "factors": [{"name": "after_inside", "direction": 1}, {"name": "near_ema9", "direction": 1}, {"name": "industry.diffusion_history", "direction": 1}]}
- {"id": "R2C", "kind": "industry", "filters": [{"name": "industry.leader20", "kind": "percentile", "direction": 1, "cutoff": 0.3}], "factors": [{"name": "after_inside", "direction": 1}, {"name": "near_ema9", "direction": 1}, {"name": "industry.diffusion_history", "direction": 1}]}
- {"id": "R2D", "kind": "concept", "filters": [], "factors": [{"name": "after_inside", "direction": 1}, {"name": "near_ema9", "direction": 1}, {"name": "concept.leader20", "direction": 1}]}
- {"id": "R2E", "kind": "concept", "filters": [], "factors": [{"name": "after_inside", "direction": 1}, {"name": "near_ema9", "direction": 1}, {"name": "concept.heat5", "direction": 1}, {"name": "concept.diffusion_history", "direction": 1}]}

## 板块第三轮计算前追加

第二轮行业R2A、题材R2D均为四半年min50%，无新增过滤误伤，主要仍是排名分别丢9、8笔。最后一轮只简化胜出排名：分别移除内包触发或近9日线，题材再给裸板块内领先对照；不翻方向，不增加因子，不使用2026。

- {"id": "R3A", "kind": "industry", "filters": [], "factors": [{"name": "after_inside", "direction": 1}, {"name": "industry.leader20", "direction": 1}]}
- {"id": "R3B", "kind": "industry", "filters": [], "factors": [{"name": "near_ema9", "direction": 1}, {"name": "industry.leader20", "direction": 1}]}
- {"id": "R3C", "kind": "concept", "filters": [], "factors": [{"name": "after_inside", "direction": 1}, {"name": "concept.leader20", "direction": 1}]}
- {"id": "R3D", "kind": "concept", "filters": [], "factors": [{"name": "near_ema9", "direction": 1}, {"name": "concept.leader20", "direction": 1}]}
- {"id": "R3E", "kind": "concept", "filters": [], "factors": [{"name": "concept.leader20", "direction": 1}]}

## 冻结前纠正平手规则（任务书优先）

初始登记及score向量多加了“排名因子少”这一平手项，任务书要求沿用IE10：四半年min→新增条件少→全部入场前五覆盖高→登记顺序。本次删去额外平手项，不改任何因子、条件、名单或账户。逐项核对三轮轮内胜出、两个真实分支初始胜出、两个打乱分支初始胜出，按任务书原规则均与已保存结果相同；消融只看min及资格也完全不受该项影响。原结果及四分量score向量保留，冻结结果规范化为三分量score，保存原源码及产物摘要，详情另存selection_tie_fix.json；2026尚未运行，不重新拟合或重算已保存评测。

## 两个分支最终冻结登记（2026评测前）

登记时间：2026-11-03T07:16:55.175664+00:00。上游维持U2A；正式评测时不改规则，两版本同时冻结，不按2026挑版本。

- {"kind": "industry", "scheme": {"id": "R2A", "kind": "industry", "filters": [], "factors": [{"name": "after_inside", "direction": 1}, {"name": "near_ema9", "direction": 1}, {"name": "industry.leader20", "direction": 1}]}, "halfyear": {"2024H1": {"n": 5, "top5": 4}, "2024H2": {"n": 6, "top5": 4}, "2025H1": {"n": 4, "top5": 2}, "2025H2": {"n": 13, "top5": 7}}, "primary": {"n": 28, "hits": {"1": 5, "3": 14, "5": 17, "10": 19}, "scope": 26, "gated": 26}, "accounts": {"cash6": {"2024": {"entries": 247, "closed": 247, "win": 0.17813765182186234}, "2025": {"entries": 281, "closed": 276, "win": 0.15217391304347827}}, "lever": {"2024": {"entries": 776, "closed": 776, "win": 0.09149484536082474}, "2025": {"entries": 768, "closed": 756, "win": 0.082010582010582}}}, "random_rank": 1}
- {"kind": "concept", "scheme": {"id": "R2D", "kind": "concept", "filters": [], "factors": [{"name": "after_inside", "direction": 1}, {"name": "near_ema9", "direction": 1}, {"name": "concept.leader20", "direction": 1}]}, "halfyear": {"2024H1": {"n": 5, "top5": 4}, "2024H2": {"n": 6, "top5": 4}, "2025H1": {"n": 4, "top5": 2}, "2025H2": {"n": 13, "top5": 8}}, "primary": {"n": 28, "hits": {"1": 4, "3": 10, "5": 18, "10": 20}, "scope": 26, "gated": 26}, "accounts": {"cash6": {"2024": {"entries": 216, "closed": 216, "win": 0.21296296296296297}, "2025": {"entries": 278, "closed": 272, "win": 0.13602941176470587}}, "lever": {"2024": {"entries": 774, "closed": 774, "win": 0.09689922480620156}, "2025": {"entries": 790, "closed": 777, "win": 0.09395109395109395}}}, "random_rank": 1}

两者无新增过滤条件，保留三个等权排名因子；逐项删除任意排名因子都降低四半年min。真实min均50%，未达80%；随机对照与一次标签打乱已完成。现有结果参与过描述/选择，不是独立留出。冻结后只做一次正式完整回放与对应30次名单随机，2026仍标已看六次、非干净考试；概念静态成员的未来信息风险单列。
