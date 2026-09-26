# S22旧口径审计运行记录

## 标签重算前冻结（2026-09-26 05:43 UTC）

本次是旧暴露证据的实现审计，不是新验证。计划见 [S22_AUDIT_PLAN.md](S22_AUDIT_PLAN.md)。不联网、不申请历史额度、不读新ETF／09月25日期权，不改原数据、归档实现或报告。

| 新文件 | 运行前SHA256 |
|---|---|
| s22_audit.py | `c1fee5cd2ea4f824c1d8714bb468d4294d630c19efbbd8e5dea867675c906c79` |
| tests/test_s22_audit.py | `04e2e158bdd68bc9c8b64d0dc1a3dad2a72fbea975f291c02a6690aaf4dda070` |
| notes/S22_AUDIT_PLAN.md | `daa5315e59fbc37283326920fabdf5ee675bb8b2c64cb9d141267ab4e6a9d1ce` |

原代码／原预登记／原报告／数据manifest与CHECKSUMS精确指纹见计划，包装器内同值强校验。标签重算前独立运行 `verify_inputs()`：选择包203个、验证包244个文件的SHA256全部通过，固定34只daily文件集合一致；这些检查不计算标签。

测试：新审计9项合成测试包含逐symbol构建与全池构建等价、原统计、分母含自身且事件加权、精确前日期权缺失不回退、PM历史15个正观测准入、并列排序、当日标签可用性门禁、拒绝覆盖／低内存、差异后不进入下一段；研究目录274项、归档旧研究23项、custody149项全部通过。

运行前 `free -m`：总3927 MiB、已用1414 MiB、可用2513 MiB，swap已用651 MiB。包装器再次检查MemAvailable≥512 MiB后才进入标签计算；原表按symbol载入，跨symbol仅保存紧凑日记录，不构造全池分钟矩阵。独立只读审查已请求；确认无阻断后才执行下列唯一命令。

```sh
python3 -m studies.us_opening_range.s22_audit \
  --out studies/us_opening_range/reports/s22_audit.json \
  --events-out data/s22-audit-20260926.jsonl
```

输出必须原先不存在。选择段与原验证段各运行一次，任一原CLI显示字段不匹配立即停止，不通过改规则补齐。后续Release仅可含派生数据／报告／指纹，不含源码；本任务不发布。

独立审查（archive_audit，运行前）：完整审阅计划、新包装器与9项测试、归档picks／preopen，另跑9项合成测试通过，未见阻断。逐symbol会改变未使用的PCR横截面／SPY派生字段，但M1／M2与compact不引用它们；保留字段均逐股，按日重新按symbol排序恢复旧池顺序。该审查未运行真实标签。

## 唯一实际运行完成

运行前记录（含独立审查）的SHA256为 `962bc983d82c9c1195cfb42770b483bb28a2f7500131260990feef3ef7eb935e`；本节为运行结束后追加，不改上述代码／测试／计划指纹。

实际开始2026-09-26 05:46:15.972537 UTC，结束05:47:18.007468 UTC，总62.035秒；选择段23.434秒、原验证段38.418秒。进程峰值RSS136228 KiB（约133 MiB），执行入口MemAvailable2558020 KiB。输出状态`AUDIT_MATCH`：选择和原验证各执行一次，原CLI全部显示字段逐行一致；没有差异后改算法或第二次执行。

| 产物 | SHA256 |
|---|---|
| reports/s22_audit.json | `a8d45d90392d8a383b705554357ca1db467e07868de87bbf0248b81331567dac` |
| data/s22-audit-20260926.jsonl（2696条，两个候选有重叠） | `bd97fc3b5d3c5dd20b74c74e80e51e98409596a71409bd8466b14f6bb1d0987c` |

实际选择准入2023-08-01→2024-12-31，358日／4139标的日；原验证准入2025-01-02→2026-09-23，432日／10115标的日。请求末日09/24没有daily标签，未补数据或改队列。详细对照和局限见 [中文审计报告](../reports/S22_AUDIT_CN.md)。所有数据／旧报告保持不变，未发布Release。
