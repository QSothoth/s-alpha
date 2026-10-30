# 例子：Sean Ryan（第二波，2026-10-20）

第一个非“动量 / 成长股波段”主流程的美股对象（价格循环 / 第二波），B 级。结论与数字见 [studies/sean_ryan/reports/FINAL_CN.md](../../../studies/sean_ryan/reports/FINAL_CN.md)，逐轮记录见 `studies/sean_ryan/notes/PROGRESS.md`。

## 做了什么

- 一份长访谈逐段摘原话（RULES_CN），台账只有 2 笔有日期，行为保真改用他公布的年度统计（`his_behaviour`）。
- 第一次在本流程里把**时间切分**落到每一轮：模块 `full = SELECT`（2024–2025），安慰剂、行为、收益都只在选择段；`validate` 对带入版本在 2026 段只评一次；空头轮用 `shorts_round.py` 把区间换成选择段，不经 `systems.py`。
- 在 `study.py` 加了带容差的行为门槛 `behaviour+X`（默认的 `behaviour` 不变）。

## 学到什么

- **盘中入场在日 K 上的口径**会决定成败：悲观口径（当天最低碰到止损就算止损）让基线一年亏 65%；收盘买与安慰剂执行对等，先改执行层再谈选股。
- **严格单调的行为门槛**会因 0.01 量级的差距挡掉成倍的收益差；但看了结果再放宽门槛，后面几轮的选择就有过拟合风险。这一次验证段（2026）−43.6%、排位 0.00，说明选择段 +207% 不可外推。以后的预登记应在 R0 就定好容差。
- **台账少时**，“像他”只能量统计；“平均赚”这类统计要先核对口径（他可能把分批卖出算成多笔）。
- 他的空头主要是反向 ETF，个股替代品在“空单 ≤ 多头 1/4”下没有稳定 Alpha。

## 怎么运行

```bash
PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/opend-us-options/.venv/bin/python"
$PY -m studies.sean_ryan.replicate round R8
$PY -m studies.sean_ryan.replicate diagnose r5.json      # 区间自动前移到 2023-03，看他的 2023 交易
$PY -m studies.sean_ryan.shorts_round S2
$PY -m studies.sean_ryan.replicate validate r8.json
$PY -m studies.sean_ryan.final_window r8.json
$PY -m studies.sean_ryan.gate_check r8.json chosen window
```
