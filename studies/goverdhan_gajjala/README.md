# Goverdhan Gajjala 独立研究

实现的是来源约束的5分钟需求腿/自然缩量回调假设，不是日线突破替代品，也不是本人完整冠军算法。原有Martin代码未改。

- A1本人Q&A：5m为主、动量与自然回调、偏好低float；未披露完整数值算法
- B1原采访方：9/21EMA、上攻放量/回调缩量、枢轴突破、加仓
- C1课程二手笔记：两阳线、回调前bar高/低作为触发/止损；这是次级材料，不能称已认证精确冠军规则
- H：3%、1–3bar、50%回撤、价格与成交额门槛、0.1%风险、5%仓位、时段、现金上限、费用等均为独立封闭假设

[结果与限制](reports/RESULTS.md) · [R1预登记](notes/PREREG_R1.md) · [R2预登记](notes/PREREG_R2.md)

运行：
```
python3 studies/goverdhan_gajjala/replay.py --data /path/klines_1m.csv.gz
python3 studies/goverdhan_gajjala/replay_smallcap.py --data /path/kaggle-v59
python3 -m unittest discover -s studies/goverdhan_gajjala/tests -v
```

源数据不进入Git。重跑应另设输出位置/保留既有结果，避免把已使用数据称首次验证。R2脚本默认写本研究reports/r2，运行前自行保存既有工件。

完整压力复算：`python3 studies/goverdhan_gajjala/stress.py --minute /path/klines_1m.csv.gz --smallcap /path/kaggle-v59`。输出全部81格而非最佳组合。
