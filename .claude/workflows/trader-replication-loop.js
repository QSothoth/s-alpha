export const meta = {
  name: 'trader-replication-loop',
  description: 'Replication loop over regime layer × selection / trading / conversion lines with merge acceptance and drift checks',
  whenToUse: 'Continue replicating a trader (default martin_luk) round by round until a checkpoint needs the user',
  phases: [
    { title: 'Bootstrap', detail: 'WF00 infra via Codex; new traders stop for user sign-off' },
    { title: 'Measure', detail: 'rules pin + line × state status table' },
    { title: 'Plan', detail: 'pick one cell, diagnose, design, write PLAN', model: 'opus' },
    { title: 'Preflight', detail: 'independent review; revise at most twice', model: 'opus' },
    { title: 'Run', detail: 'one Codex systemd unit at a time' },
    { title: 'Verify', detail: 'process and numbers' },
    { title: 'Record', detail: 'line acceptance rule, ledger and state' },
    { title: 'Report', detail: 'plain Chinese checkpoint report' },
  ],
}

const A = args || {}
const TRADER = A.trader || 'martin_luk'
const WT = A.worktree || '/opt/opend-us-options/.claude/worktrees/gap-review'
const MAX_ROUNDS = A.rounds || 3
const RULES = `${WT}/skills/trader-replication/references/WORKFLOW_CN.md`
const DIR = `${WT}/studies/${TRADER}/workflow`
const JUDGE = ['pipeline.py', 'funnel.py', 'mainleg.py'].map((f) => `${WT}/studies/trader_replication/${f}`).join(' ')
const UNIT = TRADER.replace(/_/g, '-')
const PIN_CMD = `命令 /opt/opend-us-options/.venv/bin/python -c "import hashlib,json,sys;r=open(sys.argv[1],'rb').read();c=json.load(open(sys.argv[2],encoding='utf-8'));code=b''.join(open(f,'rb').read() for f in sys.argv[3:]);print('+'.join(hashlib.sha256(x).hexdigest()[:16] for x in (r,json.dumps({k:c.get(k) for k in ('goal','hard_lines','accept','checkpoint','datasets')},sort_keys=True,ensure_ascii=False).encode(),code)))" ${RULES} ${DIR}/config.json ${JUDGE}`
const BASE = [
  `工作区 ${WT}（git worktree，不提交、不推送）。交易员 ${TRADER}，流程目录 ${DIR}。`,
  `规则以 ${RULES} 为准，先读它；与它冲突的做法一律不做。`,
  '项目铁律：只用日 K 与已有冻结数据，不拉新数据；策略侧不读他的台账、票名、日期、段表；不改登记版与看板；只读 config 中 datasets 白名单的数据，不新增或修改数据集与 schema、不引用未登记的数据路径（需要就进检查点等用户同意）；轮次中不改尺子和判定代码（studies/trader_replication/pipeline.py、funnel.py、mainleg.py，要改就是改规则，交给用户）；同一时间只跑一个重计算；文档中文。',
].join('\n')
const OPUS = { model: 'opus' }
const CHEAP = { model: 'sonnet', effort: 'low' }

const STR = { type: 'string' }
const NUM = { type: 'number' }
const BOOL = { type: 'boolean' }
const obj = (props, required) => ({ type: 'object', properties: props, required: required || Object.keys(props) })
const arr = (items) => ({ type: 'array', items })

const BOOT = obj({ ready: BOOL, ran_codex: BOOL, needs_user: BOOL, reason: STR, rules_sha: STR, goal: STR, datasets_approved: BOOL })
const CELL = obj({ line: STR, scope: STR, metric: STR, value: STR, target: STR, upper_bound: STR, frozen_version: STR })
const MEASURE = obj({ round_id: STR, status_path: STR, rules_sha: STR, hard_gate_failed: BOOL, success_met: BOOL, regime_frozen: BOOL, pending_merge: BOOL, cells: arr(CELL), summary: STR })
const PLAN = obj({
  line: STR, scope: STR, plan_path: STR, candidates: arr(STR),
  why_this_cell: STR, similar_attempts: arr(STR), why_different: STR,
  checkpoint: BOOL, checkpoint_reason: STR,
})
const REVIEW = obj({ fatal: arr(STR), minor: arr(STR) })
const RUN = obj({ finished: BOOL, unit: STR, report_path: STR, tests_passed: BOOL, note: STR })
const VERIFY = obj({ ok: BOOL, problems: arr(STR) })
const RECORD = obj({
  verdict: STR, chosen: STR, main_metric: STR, compare_metric: STR, returns: STR,
  holdout_loss: BOOL, success_met: BOOL, pending_merge: BOOL, reasons: arr(STR),
})

phase('Bootstrap')
const boot = await agent(
  `${BASE}\n\nrules_sha 填 ${PIN_CMD} 的原样输出（config 不存在时填 none）；goal 填 config.goal 原文。\n` +
  `先看 ${DIR}/rounds/WF00/PLAN_CN.md 是否存在。不存在（新交易员）：参照 ${WT}/studies/martin_luk/workflow/rounds/WF00/PLAN_CN.md 和规则，` +
  `为 ${TRADER} 起草 WF00 任务书和 config.json 草稿（goal 只摘 studies/${TRADER}/notes 与记忆里的用户原话并标出处，拿不准的写“待用户确认”），` +
  '然后 ready=false、needs_user=true 返回，不启动 Codex。\n' +
  `存在时看 ${DIR}/state.json 是否 bootstrap_done=true；是则 ready=true、ran_codex=false 返回（datasets_approved 照实填 config.datasets.approved_by_user 是否有日期）。否则若 ${DIR}/rounds/WF00/APPROVED 不存在（用户尚未确认任务书和 config），ready=false、needs_user=true 返回，不启动 Codex。` +
  `否则按规则第七节启动单元 codex-${UNIT}-wf00（轮次目录 ${DIR}/rounds/WF00），用 tail --pid 方式等结束，` +
  '读 REPORT_CN.md 与 completion.json：一致性是否逐位复现、测试是否全过、bootstrap_done 是否为 true；不满足就 ready=false 写原因。',
  { label: 'bootstrap', phase: 'Bootstrap', schema: BOOT, ...CHEAP },
)
if (!boot || !boot.ready) {
  return { status: boot && boot.needs_user ? 'needs_user' : 'blocked', stage: 'bootstrap', reason: boot ? boot.reason : 'bootstrap agent failed' }
}
let PIN = boot.rules_sha
let GOAL = boot.goal
if (boot.ran_codex) {
  const bv = await agent(
    `${BASE}\n\n独立核对 WF00 产出，默认怀疑：funnel 与各线测试台对 PLAN 列出的系统是否逐位复现旧报告数字（自己重跑）；` +
    'attempts.jsonl 抽 5 行与原报告比对；accept/checkpoint/freeze_switch 是否与规则第四、五节一致；登记版与看板是否未改（git diff）。',
    { label: 'bootstrap:verify', phase: 'Bootstrap', schema: VERIFY, ...OPUS },
  )
  if (!bv || !bv.ok) return { status: 'blocked', stage: 'bootstrap-verify', problems: bv ? bv.problems : ['verify agent failed'] }
  const pin = await agent(
    `${BASE}\n\nrules_sha 填 ${PIN_CMD} 的原样输出；goal 填 config.goal 原文；datasets_approved 填 config.datasets.approved_by_user 是否已有日期；其余字段照实填。`,
    { label: 'pin', phase: 'Bootstrap', schema: BOOT, ...CHEAP },
  )
  if (!pin) return { status: 'blocked', stage: 'pin' }
  PIN = pin.rules_sha
  GOAL = pin.goal
  if (!pin.datasets_approved) return { status: 'needs_user', stage: 'datasets', reason: `WF00 已登记数据集草案，请确认 ${DIR}/config.json 的 datasets 节并填 approved_by_user` }
} else if (!boot.datasets_approved) {
  return { status: 'needs_user', stage: 'datasets', reason: `datasets 节未经用户确认（${DIR}/config.json 的 approved_by_user）` }
}
const ANCHOR = `\n用户目标（逐条对照，说明本轮怎样更接近；不得改尺子、放宽阈值、把底线参照当底座、混评两条线）：${GOAL}`

const history = []
let stop = null

for (let i = 0; i < MAX_ROUNDS && !stop; i++) {
  phase('Measure')
  const m = await agent(
    `${BASE}\n\nrules_sha 填 ${PIN_CMD} 的原样输出。\n读 state.json 取 next_round 作本轮 id，建 ${DIR}/rounds/<id>/。` +
    '不跑重计算：读上一轮（首轮为 WF00）目录里 Codex 写好的 STATUS.json，按格抄出 cells（线 × 状态：当前值、目标、可达上限、冻结版本），' +
    '另运行 datasets check（规则第七节命令），不通过即 hard_gate_failed=true。G0/G1、成功标准、pending_merge 以 STATUS.json 与 state.json 为准；STATUS.json 缺失或代码/数据指纹与当前不符则 hard_gate_failed=true 并在 summary 写明。',
    { label: `measure:${i + 1}`, phase: 'Measure', schema: MEASURE, ...CHEAP },
  )
  if (!m) { stop = { reason: 'measure agent failed' }; break }
  if (m.rules_sha !== PIN) { stop = { reason: '规则漂移：规则文件或 config 用户节在运行中被改，需用户确认', round: m.round_id, pinned: PIN, now: m.rules_sha }; break }
  if (m.hard_gate_failed) { stop = { reason: 'G0/G1 失败', round: m.round_id }; break }
  if (m.success_met) { stop = { reason: '合并验收达到成功标准', round: m.round_id }; break }
  const rid = m.round_id
  const RD = `${DIR}/rounds/${rid}`
  const forced = m.pending_merge ? '上一轮有线被接受，本轮必须是 line=merge 的合并验收。' : ''

  phase('Plan')
  let plan = await agent(
    `${BASE}${ANCHOR}\n\n本轮 ${rid}。现状表：${JSON.stringify(m.cells)}。近几轮：${JSON.stringify(history)}。${forced}\n` +
    `按规则第五节“定格 + 设计”：挑一格（线 × 状态或 common；行情层未冻结时不得做 by_state 修正），逐段看 ${m.status_path} 指向的漏斗与测试台明细找共同机制；` +
    `读 ${DIR}/attempts.jsonl 列出同线同机制旧轮次并写清差别，说不清就 checkpoint=true；方案若需要白名单以外的数据或要改数据，checkpoint=true 并写明需要什么、为什么；` +
    `从他的原话（studies/${TRADER}/notes/RULES_CN.md、TRANSLATION_CN.md，按情境全听/听一半/看场合）和漏斗数据两个角度出方案，` +
    `写 ${RD}/PLAN_CN.md 给 Codex：最多 5 个候选，只改这一格，另两条线用冻结版本；先只读诊断再预登记；按该线接受条件选；只对选中者测留出一次；参照账户和比较对象写死；先写执行时点单测；` +
    `报告 ${RD}/REPORT_CN.md 含该线主尺与护栏（分状态）、合并漏斗变化、每年收益；结尾用 pipeline.accept（阈值只读 config）把判定写进 completion.json 的 decision，` +
    `再按新冻结版本重出 ${RD}/STATUS.json 供下一轮。`,
    { label: `plan:${rid}`, phase: 'Plan', schema: PLAN, ...OPUS },
  )
  if (!plan) { stop = { reason: 'plan agent failed', round: rid }; break }
  if (plan.checkpoint) { stop = { reason: plan.checkpoint_reason, round: rid }; break }
  if (m.pending_merge && plan.line !== 'merge') { stop = { reason: '该做合并验收却选了别的线', round: rid, line: plan.line }; break }

  phase('Preflight')
  let passed = false
  let lastFatal = []
  for (let k = 0; k < 3; k++) {
    const rv = await agent(
      `${BASE}${ANCHOR}\n\n独立审查任务书 ${plan.plan_path}（声明 line=${plan.line}，scope=${plan.scope}），尽力找会让本轮白跑或结论无效的问题。` +
      `按规则第五节审查清单逐条查，并对照 ${DIR}/attempts.jsonl 判断是否实质重复已失败轮次。只把真会导致结论无效的写进 fatal。`,
      { label: `preflight:${rid}:${k + 1}`, phase: 'Preflight', schema: REVIEW, ...OPUS },
    )
    if (!rv) break
    lastFatal = rv.fatal
    if (!lastFatal.length) { passed = true; break }
    if (k === 2) break
    plan = await agent(
      `${BASE}\n\n按以下致命问题修改 ${plan.plan_path}，只改相关段落，不换格子：${JSON.stringify(lastFatal)}`,
      { label: `plan:revise:${rid}:${k + 1}`, phase: 'Preflight', schema: PLAN, ...OPUS },
    ) || plan
  }
  if (!passed) { stop = { reason: '审查两次未过', round: rid, fatal: lastFatal }; break }

  phase('Run')
  const run = await agent(
    `${BASE}\n\n按规则第七节启动单元 codex-${UNIT}-${rid.toLowerCase()}，轮次目录 ${RD}，任务书 ${plan.plan_path}。` +
    '先确认没有别的 codex-* 单元在跑（有就等）。用 tail --pid 方式等结束，每次顺带看磁盘，低于 800MB 只清本轮重复中间文件。' +
    `结束后确认 ${RD}/REPORT_CN.md 与 completion.json 存在、测试是否全过。`,
    { label: `run:${rid}`, phase: 'Run', schema: RUN, ...CHEAP },
  )
  if (!run || !run.finished) { stop = { reason: 'Codex 未正常结束', round: rid, note: run ? run.note : '' }; break }

  phase('Verify')
  const ver = await agent(
    `${BASE}\n\n独立核对 ${rid}（报告 ${run.report_path}），默认怀疑。` +
    '流程：用文件时间与日志核对预登记早于选择早于留出、只用选择年、留出只测一次、只改了声明的格子、登记版与看板未改（git diff）、自己重跑 trader_replication 与 custody 测试；datasets check 与 datasets scan --git-diff 都通过。' +
    `数字：从 ${RD} 的 json 复算报告里的主尺、护栏、漏斗分层之和等于段数、每年收益；抽 3 段逐段明细对成交台账；` +
    '自己重跑 pipeline.accept 核对 completion.json 的 decision；STATUS.json 已按新冻结版本重出。',
    { label: `verify:${rid}`, phase: 'Verify', schema: VERIFY, model: 'sonnet' },
  )
  if (!ver || !ver.ok) { stop = { reason: '核对未过', round: rid, problems: ver ? ver.problems : ['verify agent failed'] }; break }

  phase('Record')
  const rec = await agent(
    `${BASE}\n\n照抄 ${RD}/completion.json 的 decision（已核对，不重新判定）。main_metric、compare_metric、returns 只填选择年；留出年结果只决定 holdout_loss，不写进这三项。` +
    `写一行进 ${DIR}/attempts.jsonl（含 line、scope），更新 state.json：accepted 则更新该线冻结版本，非 merge 线被接受时 pending_merge=true，merge 轮结束后置 false；next_round 加一。` +
    `判定写进 ${RD}/DECISION_CN.md；有留出结果时 holdout_loss 照实填。`,
    { label: `record:${rid}`, phase: 'Record', schema: RECORD, ...CHEAP },
  )
  if (!rec) { stop = { reason: 'record agent failed', round: rid }; break }
  history.push({ round: rid, line: plan.line, scope: plan.scope, verdict: rec.verdict, main: rec.main_metric, compare: rec.compare_metric, returns: rec.returns })
  log(`${rid} ${plan.line}/${plan.scope}: ${rec.verdict}，主尺 ${rec.main_metric}（对比 ${rec.compare_metric}），收益 ${rec.returns}`)

  if (rec.success_met) { stop = { reason: '合并验收达到成功标准', round: rid }; break }
  if (rec.holdout_loss) { stop = { reason: '留出年一次检验亏钱', round: rid }; break }
  const n = history.length
  const same = n >= 2 && history[n - 1].line === history[n - 2].line && history[n - 1].scope === history[n - 2].scope
  if (same && history[n - 1].verdict !== 'accepted' && history[n - 2].verdict !== 'accepted') {
    stop = { reason: `同一格 ${plan.line}/${plan.scope} 连续两轮无进步`, round: rid }
  }
}
if (!stop) stop = { reason: `已跑满 ${MAX_ROUNDS} 轮` }

phase('Report')
const report = await agent(
  `${BASE}\n\n本次运行停在检查点：${JSON.stringify(stop)}。各轮：${JSON.stringify(history)}。` +
  `写 ${DIR}/CHECKPOINT_CN.md 给用户：先结论、白话、少术语；各线和行情层现在在哪、离目标多远；每轮一句话（改了哪条线哪个状态、主尺、收益、判定）；停下原因；下一步最多两条建议和需要用户定的事。返回同样正文。`,
  { label: 'report', phase: 'Report', model: 'sonnet' },
)
return { status: 'checkpoint', stop, history, report }
