# 期权/涡轮期限匹配（option_horizon）

独立研究切片：在已知标的方向与「价格何时可能动」之后，把机会兑现时间尺度映射到期权或港股涡轮的到期档，避免方向对、到期太近被 theta 吃掉。

独立入口：[option-horizon-match 技能](skills/option-horizon-match/SKILL.md)。

## 边界

- **做什么**：按短线技术位 / 中线 / 长线事件，给出可执行的 DTE 或到期窗口建议、不该买什么、与买点关系（未触发不付权利金）。
- **不做什么**：不做收益认证、不回测最优、不下单、不替代 opportunity-research 或 daily-technical-review。
- **协作约定**：短/中/长 → DTE 档写死在 skill 里，是代理协作约定，不是样本外最优。

## 衔接

- 上游：`opportunity-research`（方向、兑现节点、失效条件）+ `daily-technical-review`（介入条件与触发价）。
- 下游：执行确认句须带 DTE/到期；`near-expiry-session` 仅固定池最近到期，中长线机会不塞进去。

## 反例（为何需要本切片）

海力士解禁前一周用近月空：叙事是数周事件，合约却是近到期——方向即便对，也可能先被时间损耗打穿。本 skill 强制先判时间尺度再选期限。
