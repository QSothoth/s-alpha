# 统计机会研究与发现原型

归属 [opportunity-research](../../skills/opportunity-research/SKILL.md)，遵守 [studies 规范](../AGENTS.md)。当前是一次性发现原型和描述性复算，不接交易执行。统计结论、OpenD 实测与数据路线见[研究报告](reports/FEASIBILITY_20261027_CN.md)，EP0 定义见[预登记](notes/EP0_PLAN_CN.md)。

整体目标覆盖公司消息、资金供需、异常行情、价差收敛及经济联系，见[机制与实证初筛](reports/OPPORTUNITY_MAP_20261027_CN.md)。下面两个命令是已有的盘前实施例，未实现其他类别的自动发现或验证；解禁不作默认研究重点。

```bash
# 仅在美股盘前运行。上下各取十条、最多两只补新闻，不订阅或启动定时任务。
/opt/futu-opend/venv/bin/python -m studies.opportunity_events.research discover --count 10 --news 2 --output data/opportunity-events/discovery-new.json

# 固定历史诊断，使用已有本地数据，不联网。输出路径必须不存在。
python3 -m studies.opportunity_events.research pilot --output data/opportunity-events/ep0-new.json

python3 -m unittest discover -s studies/opportunity_events/tests
```

`--data` 可指定本地数据根目录。`discover` 输出原始榜单、快照、新闻和质量标记，候选方向为空。`pilot` 输出全部两项政策、日块区间及输入哈希。两种命令只创建一次新输出，不覆盖旧文件。盘前榜没有历史日期参数，离开盘前时段会拒绝把旧榜当当前观察。
