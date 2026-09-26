# 历史研究归档

当前美股研究入口是 [日K／早盘信号研究](../us_opening_range/README.md)。这里保留停止推进的研究代码、预登记、原始输出与测试，供审计和复现；失败结果不删除、不改写，归档不代表后来获得了有效性证明。

| 目录 | 归档原因与保留内容 |
|---|---|
| [us_preopen_bias](us_preopen_bias/README.md) | S1–S29：盘前方向、每日多空 Top N 及 09:45 固定时点选边未获得可交易的样本外结果；S22 仅支持大波动筛选，不能推出方向。保留现存代码、预登记、报告和测试；现有 Git 历史未保留 S11–S20 的完整代码与报告，不能承诺恢复或复现这些轮次，也不据此认定相应机制从未试过。 |
| [opend_probes](opend_probes/) | 单次已知过期期权取数试验的原执行脚本与原预登记；脚本从临时目录原字节归档，预登记由现存笔记前27行按旧SHA恢复，供核对已发布manifest指纹，不作为日常入口。执行会请求历史行情，原一次性授权不表示允许再次消耗额度。 |

S28 / S29 用过的 `preopen-us-k5-select-v1`、`preopen-us-k5-valid-v1`、`preopen-s20-select-v1`、`preopen-s20-valid-v1` 已按此前决定删除，不能从远端 Release 完整复现。现有本机副本的位置和历史哈希见 [DATA](../../docs/DATA.md)，不重新发布或篡改旧 tag。

归档前后保留了用户在 `daily_top.py` 中未提交的 `--dump` 修改，该文件内容 SHA256 均为 `284bc4f0d27af98097f8b1fc42b46509b94aec4c54b465e63d442eb087a9c834`。历史 `notes/` 和 `reports/` 内容原样保留。已有 `custody` 注册策略和根目录 `reports/` 仍被执行、测试及复现代码引用，因此保持原位；本次归档没有更改交易策略或注册状态。

从仓库根目录执行离线测试：

```bash
python3 -m unittest discover -s studies/archive/us_preopen_bias/tests
```

具体复现命令见各归档目录 README。已用过的验证段仍视为已用，不能因移动目录重新成为样本外数据。

机制去重、缺失记录及数据段污染审计见 [RESEARCH_AUDIT](../us_opening_range/notes/RESEARCH_AUDIT.md)。
