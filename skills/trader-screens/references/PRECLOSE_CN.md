# 尾盘单图发布

用户于 2026-10-22 授权的盘中发布任务。沿用 `intraday-board` 工作树的盘中快照实现和系统配置，未将研究分支合入 main。行情只在内存中追加到前一交易日的面板，不写入正式日线或收盘看板。

## 时间与内容

以下均为北京时间，发送到现有 QQ 频道，每个市场每天一张图：

| 市场 | 启动取数 | 目标发送 | 当次最晚发送 |
|---|---|---|---|
| A 股 | 14:42 | 14:45 | 14:49 |
| 港股全日市 | 15:44 | 15:45 | 15:49 |
| 港股半日市 | 11:44 | 11:45 | 11:49 |

周一至周五触发后先查 OpenD 交易日历。非交易日跳过；港股全日市的上午触发跳过，半日市下午只核对已有回执。定时器使用 `Persistent=false`，重启不补发过时信号。

港股按连续交易时段的 16:00 / 半日 12:00 提前十五分钟，之后仍有收市竞价，见 [港交所交易时段](https://www.hkex.com.hk/Services/Trading-hours-and-Severe-Weather-Arrangements/Trading-Hours/Securities-Market?sc_lang=en)。

图中保留市场、日期、行情取得时间和“盘中”，逐股列交易员、动作、价格、开仓比例及止损。买入红色、卖空蓝色、卖出橙色、回补紫色。A 股涨停买入不列为可执行信号，显示跳过笔数。没有买卖时仍发一张空信号图。盘中信号可能在收盘时变化；正式日报仍由原 `trader-board-qq.timer` 在次日 08:30 发布。

## 入口与依赖

- 发布：`research/trader_preclose_to_qq.py`，使用已有 QQ 发送、回执核对和单图渲染实现。
- 计算：`research/trader_preclose_worker.py`，通过 `/opt/futu-opend/venv/bin/python` 导入 `/opt/opend-us-options/.claude/worktrees/intraday-board/studies/trader_screens/intraday.py`。
- 调度：`/etc/systemd/system/trader-preclose-{cn,hk}.timer`、`trader-preclose@.service`、`trader-preclose-failure@.service`。
- 状态与结果：`data/trader-screens/qq/preclose/<cn|hk>/<日期>/`；包括交易日历、`board.json`、图片、发布回执和失败通知回执。每个市场的面板缓存隔离在自身 `panel-cache/` 下。
- 前一天日线由原收盘更新流程准备。缺少上一交易日时本任务拒绝运行，不在盘中自动拉全量历史。

工作树必须保留，并带有 `captured_at`、`coverage` 等行情验证元数据。更换工作树或移除代码前先更新发布入口并验证。`research/` 脚本及运行数据按现有约定留在本机，不进入 Git。

```bash
systemctl status trader-preclose-cn.timer trader-preclose-hk.timer
journalctl -u trader-preclose@cn.service -n 60 --no-pager
journalctl -u trader-preclose@hk.service -n 60 --no-pager
python3 research/trader_preclose_to_qq.py preview cn --input <真实盘中结果.json> --output <预览目录>
python3 -m unittest research.test_trader_preclose research.test_trader_board_scheduler
```

`preview` 只生成本地图片。`run cn` / `run hk` 在对应窗口内会真实发送；窗口外只跳过或核对已有回执。

## 失败处理

发布前验证当日、市场、盘中模式、取得及生成时间、源行情时间、至少 95% 的上一交易日活跃标的覆盖率。源行情最新时间距离取得时间不超过三分钟，发布时快照不超过五分钟；超过发送窗口拒绝发送。无效报价被隔离，涉及持仓或买卖时停止当次运行。

与日报共用进程锁，避免同时计算或发布。可用内存不足 1.6 GB 时在剩余窗口内等待；服务内存上限 1400 MB，计算单线程。图片超过一张时拒绝发布，不截掉信号。

系统服务失败后间隔 45 秒重试，二十分钟内最多启动三次；最终失败触发 QQ 异常通知。超过窗口后不重新取数发旧信号。每次发送前保存回执，响应丢失时只查远端核对，不直接重发；每日每市场独立回执，避免和正式日报互相覆盖。

2026-10-22 已验证真实交易日历查询、窗口外真实服务跳过、已有真实盘中结果的单图渲染，以及模拟发布响应丢失后的回执恢复。首次按新计划实时取数并发布需在后续交易日观察，不将上述验证当作已完成定时实发。
