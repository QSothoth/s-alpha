# P1 任务书（给 Codex）：复刻流水线框架——接口、行情 Switch、七道卡子

工作目录 /opt/opend-us-options/.claude/worktrees/gap-review。先读：

- 根 AGENTS.md、studies/AGENTS.md
- **`studies/martin_luk/notes/PI_PIPELINE_ADVICE_20261108_CN.md`**：本任务的设计蓝本，除下面"用户已定的改动"外都照它做
- `notes/PI_PIPELINE_BRIEF_20261108_CN.md`
- `skills/trader-replication/SKILL.md`、`references/METHOD_CN.md`、`docs/TRADER_PROTOCOL_CN.md`
- `studies/trader_replication/{study,systems,runner,gate,success,mainleg,system,simulate}.py`、`studies/martin_luk/` 的 `build_system` 所在模块
- `reports/S0_CN.md`（S 口径和 `mainleg.py` 里的限宽覆盖函数）

约束：
- 用 .venv 的 python；重计算用 `systemd-run --scope -p CPUQuota=60% -p MemoryMax=900M -q`，单进程单线程。
- 不联网、不拉新数据、不提交 git。
- 不改登记版和看板的行为：所有已登记系统（`systems.py` 里每一个）和看板输出必须逐位不变。
- 旧报告的数字一个不改。
- 本轮**不做任何策略研究、不跑任何新候选**。

## 用户已定的改动（覆盖 pi 建议中的对应部分）

1. **G5 账户卡 / G4 行为卡的数字**：
   - 硬线：每年不亏，已平仓胜率 ≤35%（≥30 笔），每年 ≥52 笔。
   - 像他：盈亏比、持有天数、每年笔数，和他公开的数字差在 ±20% 以内（只比他有出处的项）。
   - 收益：他在数据期内有成绩的每一年，|log((1+我们)/(1+他))| ≤ 0.3。
   - 资金纯度、毛利纯度、段吃到：只报告，不设门槛。
2. **删掉随机对照**：`success.py` 第 5、6、7 条（同池随机入场中位数、验证段随机、去两笔后仍跑赢随机）不再是成功标准。函数可以保留作诊断，但 `judge` 不再要求它们。`fidelity`、`edge` 里的随机基线和 10 天超额同样只作诊断，不作否决。旧报告里写下的判定不回改。
3. **没观测到他样本的行情状态**（例如 2024–25 的弱势期）：不因样本不足就取消 Switch。这个状态的行为按他的原话设规则，报告里标"未观测"，冻结后由前向记录检验。G2 改为逐状态判断：有样本的状态用数据检验，没样本的状态按原话设并标"未观测"。
4. 流程要**尽可能简单**，以后复刻其他交易员时容易照着做。SKILL 正文控制在现在的篇幅左右；细节放 METHOD。

## 要做的

1. **接口（facade）**：在 `studies/trader_replication/study.py` 的 `Study` 上加：
   - `universe(A, cfg)`
   - `signal(A, pool, cfg)`：返回每晚有序点名，含空夜，作为唯一的点名真源
   - `allocate(...)`：共享实现，负责名额、10 日冷却、同时持仓上限、换仓，把两种 daily cap 统一到这里
   - `trade(cfg)`：返回 Rules
   - `regime(A, cfg)`：可选
   
   `build()` 改为这几块的组合。现有交易员模块覆盖了 `build()` 的，保持原样，标 legacy。配置支持分节（universe / signal / allocate / trade / switch），旧的扁平键作为只读别名。

   **把 Martin 迁移过去**：`build_system` 的 priority 排序 + max_new 截断，拆成 signal + allocate。验证登记 R74 + S7、M1B / M2A / M3B 原台账逐位不变（用现有的 check / runner check）。

   写一个约 20 行的 dummy 交易员一致性测试：固定池、按 ADR 排序、固定风险，走通整条接口。
2. **行情 Switch**：新建 `studies/trader_replication/regime.py`，只读市场数据，不读台账和段表。
   - 输出：每天的离散状态（up / pullback / weak）、episode 表、各状态的天数和段数、spec 的 SHA。不输出概率。
   - 三种 label producer，接口相同、不叠加：
     - `idx_ema`（默认，QQQ / IWM 或池等权指数相对 EMA21 / 50）
     - `breadth`（领涨与落后名单只数）
     - `smc`（指数上 10 日分形摆动点、BOS / CHoCH 映射成三态）
   - 参数取常见值，写进 spec 并冻结。
   - 状态数组经 `Study.named()` 暴露，让 `gate.check_lookahead` 自动覆盖。
   - 交易员的映射表放在配置的 switch 节：每人最多 2 个开关，每个开关必须引用 RULES_CN 的一句原话。
   - 状态只决定"做不做、做多大、启用哪类形态、做不做空"，不决定同一类里买哪只。
   - 单测：无未来函数（截断一致）、episode 构造、确定性、扰动稳定性计算。
3. **卡子 G0–G6**：
   - 在 `studies/trader_replication/` 加一个轻量的 `pipeline.py`（或同等位置），每道卡子一个检查函数，返回（通过 / 不过 / 未观测，原因，数字）。
   - G3 用 S0 的限宽覆盖函数：K=3、留出段、早期合格夜，达标线 80%；按年份留一，三折全报。
   - G2 / G4 / G5 的检验按 episode 留一。
   - 写清"上游不过不许动下游"的允许动作表。
   - 新的 round JSON 要带 `layer` 字段，加一个校验函数检查候选只改了该层（`paired: true` 例外，需写明机制）。旧 round 不受影响。
4. **文档**：
   - 改 `skills/trader-replication/SKILL.md`：10 步压成 G0–G6 七道卡子；"复刻成功标准"并入 G4 / G5，用上面用户定的数字；写明 facade 要填的几块和信号期 / 交易期 / 行情 Switch 的分工。
   - 改 `references/METHOD_CN.md`：主尺子只留三把（信号覆盖 S 口径、交易行为、账户）；`C_signal`、`net_share`、`forward`、`precision`、`C_trig`、`P_opp`、`E` 降为诊断列；旧覆盖口径（§11.6 等）移到附录或归档链接；留一规则（信号按年，Switch / 交易按 episode）；行情 Switch 规则；弱势"未观测"规则。
   - `docs/TRADER_PROTOCOL_CN.md` 只改与门禁、成功标准相关的句子。
   - 只写已经实现的内容。
5. **测试**：custody、trader_replication、martin_luk，以及 `studies/` 下其他有 tests 的切片里受影响的（至少 trader_screens），全部跑过。

## 输出

- 报告 `studies/martin_luk/reports/P1_CN.md`：中文、先写结论、白话。内容：
  - 接口长什么样、新交易员要填什么；
  - 七道卡子各测什么、通过线；
  - 行情 Switch 三种定义在 2024–2026 上各自分出几段、每种状态多少天（只描述，不评好坏）；
  - 逐位不变的核对结果；
  - 改了哪些文件。
- 工件放 `reports/p1_work/`，包含 completion.json 和测试结果。
- 终端最后用不超过 10 行写摘要。
