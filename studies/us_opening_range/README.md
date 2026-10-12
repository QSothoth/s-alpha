# us_opening_range：仅保留收盘采集工具

日 K／早盘突破研究已结束，结论见 [archive](../archive/README.md)。这里只留 SV1 仍在使用的收盘采集：

- [capture.py](capture.py)：收盘后经 OpenD 订阅接口抓当天正股与平值近到期期权 1m（不扣历史额度），输出可被 `custody check` 校验的目录；SV1 按 [预登记](../us_0dte_picks/notes/SV1_PREREG.md) 用一次性 systemd 定时器调用 `python -m studies.us_opening_range.capture`。
- [scan.py](scan.py)、[signals.py](signals.py)：`capture.py` 依赖的平值合约选择与已完成 bar 判断。

模块路径被已登记的定时任务引用，SV1 结束前不要改名或移动。

```bash
python3 -m unittest discover -s studies/us_opening_range/tests
```
