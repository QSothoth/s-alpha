# Sam Miesse 否定登记表

每个没被带入的候选一行（自动写入）；“当时的配置”一列是那一轮的基础配置报告。下游大改后，用 `negations` 动作列出依赖旧配置的行，在新配置上重测。

| 轮次 | 环节 | 候选 | 改了什么 | 当时的配置 | 带入 | 否定依据 | 状态 |
|---|---|---|---|---|---|---|---|
| R1 | entry / filter / stop | RUN | `{"run": 0.5}` | :base | G50 | objective below G50；全区间 +7%（带入 -25%） | open |
| R1 | entry / filter / stop | S40 | `{"stop": 0.4}` | :base | G50 | objective below G50；全区间 -22%（带入 -25%） | open |
| R1 | entry / filter / stop | SPIKE | `{"spike": 0.1}` | :base | G50 | objective below G50；全区间 -1%（带入 -25%） | open |
| R1 | entry / filter / stop | SPIKES40 | `{"spike": 0.1, "stop": 0.4}` | :base | G50 | objective below G50；全区间 -13%（带入 -25%） | open |
| R2 | timing / parabolic | D2 | `{"gap": -1.0, "d2": 0.5}` | r1.json:chosen | G50SP | objective below G50SP；全区间 -10%（带入 +29%） | open |
| R2 | timing / parabolic | D2SP | `{"gap": -1.0, "d2": 0.5, "spike": 0.1}` | r1.json:chosen | G50SP | objective below G50SP；全区间 -23%（带入 +29%） | open |
| R2 | timing / parabolic | G20SP20 | `{"gap": 0.2, "spike": 0.2, "stop": 0.3}` | r1.json:chosen | G50SP | objective below G50SP；全区间 -13%（带入 +29%） | open |
| R2 | timing / parabolic | G50SP20 | `{"spike": 0.2, "stop": 0.3}` | r1.json:chosen | G50SP | objective below G50SP；全区间 +0%（带入 +29%） | open |
| R3 | width / size | G30SP | `{"gap": 0.3}` | r2.json:chosen | R4 | objective below R4；全区间 +15%（带入 +56%） | open |
| R3 | width / size | G30SPR4 | `{"gap": 0.3, "rule_opts": {"risk": 0.04, "max_position": 0.4}}` | r2.json:chosen | R4 | objective below R4；全区间 +20%（带入 +56%） | open |
| R3 | width / size | G40SP | `{"gap": 0.4}` | r2.json:chosen | R4 | objective below R4；全区间 +29%（带入 +56%） | open |
| R3 | width / size | SP15 | `{"spike": 0.15}` | r2.json:chosen | R4 | objective below R4；全区间 +26%（带入 +56%） | open |
| R4 | size / width | R4G40 | `{"gap": 0.4}` | r3.json:chosen | R4S30 | objective below R4S30；全区间 +53%（带入 +26%） | open |
| R4 | size / width | R4N3 | `{"max_new": 3}` | r3.json:chosen | R4S30 | objective below R4S30；全区间 +56%（带入 +26%） | open |
| R4 | size / width | R6 | `{"rule_opts": {"risk": 0.06, "max_position": 0.5}}` | r3.json:chosen | R4S30 | objective below R4S30；全区间 +77%（带入 +26%） | open |
| R4 | size / width | R6G40 | `{"gap": 0.4, "rule_opts": {"risk": 0.06, "max_position": 0.5}}` | r3.json:chosen | R4S30 | objective below R4S30；全区间 +69%（带入 +26%） | open |
| R5 | size x stop | R6S20 | `{"stop": 0.2, "rule_opts": {"risk": 0.06, "max_position": 0.5}}` | r4.json:chosen | R8S30 | objective below R8S30；全区间 +77%（带入 +38%） | open |
| R5 | size x stop | R6S30 | `{"rule_opts": {"risk": 0.06, "max_position": 0.5}}` | r4.json:chosen | R8S30 | objective below R8S30；全区间 +35%（带入 +38%） | open |
| R5 | size x stop | R6S30G40 | `{"gap": 0.4, "rule_opts": {"risk": 0.06, "max_position": 0.5}}` | r4.json:chosen | R8S30 | objective below R8S30；全区间 +28%（带入 +38%） | open |
| R5 | size x stop | R8S20 | `{"stop": 0.2, "rule_opts": {"risk": 0.08, "max_position": 0.6}}` | r4.json:chosen | R8S30 | objective below R8S30；全区间 +90%（带入 +38%） | open |
| R6 | upstream: gap definition | G20 | `{"gap": 0.2, "spike": 0.0}` | r5.json:chosen | R8S30 | gates: placebo, years；全区间 -91%（带入 +38%） | open |
| R6 | upstream: gap definition | G20SP | `{"gap": 0.2}` | r5.json:chosen | R8S30 | gates: years；全区间 -50%（带入 +38%） | open |
| R6 | upstream: gap definition | G20SPP50 | `{"gap": 0.2, "price": [1.0, 50.0]}` | r5.json:chosen | R8S30 | gates: placebo, years；全区间 -63%（带入 +38%） | open |
| R6 | upstream: gap definition | G20SPR4 | `{"gap": 0.2, "rule_opts": {"risk": 0.04, "max_position": 0.3}}` | r5.json:chosen | R8S30 | gates: years；全区间 -18%（带入 +38%） | open |
| R6 | upstream: gap definition | G30SP | `{"gap": 0.3}` | r5.json:chosen | R8S30 | gates: years；全区间 -6%（带入 +38%） | open |
| R7 | data layer + extension entry | G10E50 | `{"gap": 0.1, "spike": 0.0, "ext": 0.5}` | r5.json:chosen | R8S30 | gates: years；全区间 -8%（带入 +77%） | open |
| R7 | data layer + extension entry | G20E30 | `{"gap": 0.2, "spike": 0.0, "ext": 0.3}` | r5.json:chosen | R8S30 | gates: years；全区间 -31%（带入 +77%） | open |
| R7 | data layer + extension entry | G20E50 | `{"gap": 0.2, "spike": 0.0, "ext": 0.5}` | r5.json:chosen | R8S30 | gates: years；全区间 +17%（带入 +77%） | open |
| R7 | data layer + extension entry | G20E50R4 | `{"gap": 0.2, "spike": 0.0, "ext": 0.5, "rule_opts": {"risk": 0.04, "max_position": 0.3}}` | r5.json:chosen | R8S30 | gates: years；全区间 +60%（带入 +77%） | open |
| R7 | data layer + extension entry | G20E75 | `{"gap": 0.2, "spike": 0.0, "ext": 0.75}` | r5.json:chosen | R8S30 | gates: years；全区间 +33%（带入 +77%） | open |
| R8 | count on v2 | G30SP | `{"gap": 0.3}` | r7.json:chosen | G30S5 | objective below G30S5；全区间 +75%（带入 +247%） | open |
| R8 | count on v2 | G30SPR6 | `{"gap": 0.3, "rule_opts": {"risk": 0.06, "max_position": 0.45}}` | r7.json:chosen | G30S5 | gates: years；全区间 +80%（带入 +247%） | open |
| R8 | count on v2 | G40SP | `{"gap": 0.4}` | r7.json:chosen | G30S5 | objective below G30S5；全区间 +58%（带入 +247%） | open |
| R8 | count on v2 | G50S5 | `{"spike": 0.05}` | r7.json:chosen | G30S5 | gates: years；全区间 +585%（带入 +247%） | open |
| R9 | count on v2 (gap <= 300% hygiene) | G20S5 | `{"gap": 0.2}` | r8.json:chosen | G25S5 | gates: years；全区间 -41%（带入 +77%） | open |
| R9 | count on v2 (gap <= 300% hygiene) | G25S5R6 | `{"gap": 0.25, "rule_opts": {"risk": 0.06, "max_position": 0.45}}` | r8.json:chosen | G25S5 | objective below G25S5；全区间 +95%（带入 +77%） | open |
| R9 | count on v2 (gap <= 300% hygiene) | G30S0 | `{"spike": 0.0}` | r8.json:chosen | G25S5 | gates: years；全区间 +287%（带入 +77%） | open |
| R9 | count on v2 (gap <= 300% hygiene) | G30S3 | `{"spike": 0.03}` | r8.json:chosen | G25S5 | gates: years；全区间 +412%（带入 +77%） | open |
| R10 | risk per trade vs his worst day | R4 | `{"rule_opts": {"risk": 0.04, "max_position": 0.3}}` | r9.json:chosen | G25S5 | gates: years；全区间 +82%（带入 +77%） | open |
| R10 | risk per trade vs his worst day | R4MX3 | `{"max_new": 3, "rule_opts": {"risk": 0.04, "max_position": 0.3}}` | r9.json:chosen | G25S5 | gates: years；全区间 +83%（带入 +77%） | open |
| R10 | risk per trade vs his worst day | R6 | `{"rule_opts": {"risk": 0.06, "max_position": 0.45}}` | r9.json:chosen | G25S5 | objective below G25S5；全区间 +95%（带入 +77%） | open |
| R10 | risk per trade vs his worst day | R6G3 | `{"rule_opts": {"risk": 0.06, "max_position": 0.45, "max_gross": 1.5}}` | r9.json:chosen | G25S5 | objective below G25S5；全区间 +95%（带入 +77%） | open |
| R10 | risk per trade vs his worst day | R6S20 | `{"stop": 0.2, "rule_opts": {"risk": 0.06, "max_position": 0.45}}` | r9.json:chosen | G25S5 | gates: years；全区间 -20%（带入 +77%） | open |
| R11 | his stop and his names, at his worst-day risk | ATR2 | `{"stop_atr": 2.0}` | r9.json:chosen | G25S5R4 | gates: placebo, years；全区间 -53%（带入 +82%） | open |
| R11 | his stop and his names, at his worst-day risk | ATR3 | `{"stop_atr": 3.0}` | r9.json:chosen | G25S5R4 | gates: years；全区间 -25%（带入 +82%） | open |
| R11 | his stop and his names, at his worst-day risk | ATR3TO20 | `{"stop_atr": 3.0, "turnover_max": 20000000.0}` | r9.json:chosen | G25S5R4 | gates: years；全区间 -2%（带入 +82%） | open |
| R11 | his stop and his names, at his worst-day risk | MX3 | `{"max_new": 3}` | r9.json:chosen | G25S5R4 | gates: years；全区间 +83%（带入 +82%） | open |
| R11 | his stop and his names, at his worst-day risk | TO20 | `{"turnover_max": 20000000.0}` | r9.json:chosen | G25S5R4 | gates: years；全区间 +99%（带入 +82%） | open |
| R12 | parabolic / hyperextension at his worst-day risk | D220 | `{"d2": 0.2}` | r11.json:chosen | PRUN | gates: years, behav；全区间 -6%（带入 +84%） | open |
| R12 | parabolic / hyperextension at his worst-day risk | PRUNMX3 | `{"priority": "run", "max_new": 3}` | r11.json:chosen | PRUN | gates: years；全区间 +66%（带入 +84%） | open |
| R12 | parabolic / hyperextension at his worst-day risk | RUN30 | `{"run": 0.3}` | r11.json:chosen | PRUN | gates: years, behav；全区间 +21%（带入 +84%） | open |
| R12 | parabolic / hyperextension at his worst-day risk | RUN50 | `{"run": 0.5}` | r11.json:chosen | PRUN | gates: years, behav；全区间 -14%（带入 +84%） | open |
