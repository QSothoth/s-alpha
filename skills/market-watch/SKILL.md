---
name: market-watch
description: 使用仓库看板盯港股、A 股和美股的盘中行情，解释 B/S 结构标注、强度档、日线背景、余下振幅和数据异常。用于“盯这几只”“看板怎么看”“为什么一直是 B/S”；只读，不负责选股、日 K 买点或期权下单。
---

# 盘中盯盘

工程根目录 `/opt/opend-us-options`，先读根规范与 [watch 规范](../../watch/AGENTS.md)。完整字段、数据源、规则和验证数字见 [看板说明](references/BOARD_CN.md)；仅在解释相应字段或排错时读取所需章节。相对引用按 skill 真实路径解析。

## 使用

沿用用户指定的标的和市场。未给标的时先确定观察范围，不把代码中的默认名单当作用户的选择。启动持续盯盘须已有用户授权；说明标的、运行方式和截止时间，不能因读取本 skill 自动启动后台或定时采集。

从仓库根目录运行；以下为显式指定标的的示例：

```bash
cd /opt/opend-us-options
/opt/futu-opend/venv/bin/python watch/smc_watch.py HK.00700 US.AAPL SH.600519
```

脚本按所选市场最晚收盘后的截止时间结束；TTY 展示看板，非 TTY 每行一个 JSON，日志在 `watch/logs/`。港美走 OpenD，A 股走腾讯。脚本直接将位置参数视为代码，没有 `--help` 解析器；需要参数说明读源码和看板说明。

## 解读与异常

- 先核对 `data` 时间、市场交易时段与 `STALE` / `RECOVERED`；陈旧数据不描述成当前行情，没有节假日日历自动保证。
- `B` / `S` 是结构事件；1–5 档描述发生时的力度，不代表胜率、买卖许可或仓位依据。`?` 为必要输入尚缺；`#n` 是连续同方向计数。
- `left` 是港股余下振幅估计及区间，不预测方向，不保证价格可达；A 股、美股未验证。`ref` 是结构参考位，不能直接当止损；`~` 和 `D±` 的含义及证据按看板说明解释。
- 缺日线、指数或报价时报告具体缺口，不自行拉新标的历史 K 线补额度；可选背景缺失不隐藏原标注。不为解释某个 case 修改触发或强度阈值。

单股日 K 计划交给 [daily-technical-review](../daily-technical-review/SKILL.md)，期权会话交给 [near-expiry-session](../near-expiry-session/SKILL.md)。修改信号需遵循 `watch/AGENTS.md` 的预登记与验证要求，研究记录在 [watch_signal](../../studies/watch_signal/README.md)。
