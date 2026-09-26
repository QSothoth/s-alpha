# S22审计派生数据发布

状态：**已发布并回下载验签。** 2026-09-26，新[Release：or-s22-audit-20260926-v1](https://github.com/QSothoth/s-alpha/releases/tag/or-s22-audit-20260926-v1)；远端恰有ZIP与sidecar，ZIP SHA与本地一致，精确7成员集合、逐成员SHA及CRC全部通过，无源码。锚定既有远端提交`45d0b620c6c05729adbe19daecb8cffe0fb218e3`，未推送工作区代码。下文准备过程与包内“未发布”为创建时状态，原冻结字节不回改。

本包是 [S22旧口径审计](../reports/S22_AUDIT_CN.md) 的已暴露派生材料：旧选择及原验证CLI显示字段均`MATCH`，不是新增验证、方向优势或期权净收益证明。2696条候选事件存在重叠，不能当作独立标的日。原输入包、原数据、代码和既有报告均未改写。

## 本地附件

| 项 | 值 |
|---|---|
| 已发布tag | `or-s22-audit-20260926-v1` |
| 冻结目录 | `data/or-s22-audit-20260926-work` |
| ZIP | `data/or-s22-audit-20260926-v1.zip` |
| ZIP字节 | 312355 |
| ZIP SHA256 | `45ee76f214e2e0d36665d107f884da61acd0944a23e527435ddaf917778f42f0` |
| sidecar | `data/or-s22-audit-20260926-v1.zip.sha256` |
| sidecar SHA256 | `87821ce9108a64d0d28166a244df8708d06c1ef10a75bfe7b9d4043371ff8ed0` |
| manifest SHA256 | `4932fd254fd6251422043e24955d3b3ffd0575bc7b24321332b6672015606606` |
| CHECKSUMS SHA256 | `66e62b927bde7705e5cc410d6b6ebf1d2f70f689dab656f73920edf37b9c650b` |
| ZIP成员／展开字节 | 7／1560054 |

所有成员均在单一顶层目录`or-s22-audit-20260926-work/`下，保留仓库相对路径，使三份审计文档、JSON及事件之间的相对链接保持可用：

```text
manifest.json
CHECKSUMS.sha256
data/s22-audit-20260926.jsonl
studies/us_opening_range/reports/s22_audit.json
studies/us_opening_range/reports/S22_AUDIT_CN.md
studies/us_opening_range/notes/S22_AUDIT_PLAN.md
studies/us_opening_range/notes/S22_AUDIT_RUN_RECORD.md
```

只复制这五个已冻结派生文件的原字节。manifest保存它们的SHA、原输入包的manifest／CHECKSUMS、原预登记／原报告指纹，以及审计器／测试／归档实现／打包器的代码SHA；**源码仅以指纹出现，包内没有`.py`／`.pyc`，也没有原始行情、账户、持仓或交易数据**。本说明不在包内，以免未来发布状态更新改变冻结数据。

## 已完成校验与边界

使用一次性标准库数据生成器，逐文件1 MiB流式复制并核对源／目标SHA；没有新增通用准备框架。复用`package_data.verified_files`精确核验目录成员及全覆盖CHECKSUMS，再调用`package_data.package`打包。ZIP生成后未解包到工作区，直接逐成员流式读取：成员集合／数量及每个SHA与目录全部一致，sidecar内容与ZIP SHA一致。打包器版本SHA：`e70bcc301a67fa57cdf8749ccf852030f12d18a10c3afa28de42fc26d677b544`。

包内manifest和原报告中的“尚未发布”均是本地准备时的事实快照；后续上传不回改这些冻结字节，实际发布状态写本说明及`docs/DATA.md`。manifest的`new_validation=false`不会因发布而改变。

准备后再次只读核对中文报告／运行记录／JSON与原两份CLI，独立审查确认四组样本数、指标显示值、实际09/23边界、2696条重叠语义、所有相关SHA及文档相对链接一致。未重算标签。打包器12项测试、custody149项测试通过。

主控已确认tag未重名后上传，并由独立审查者回下载验证。不要把tag锚定提交误写成该代码已能完整重现采集；复算需要报告固定的原行情包与匹配的Git代码。生成／打包程序本身不自动执行远端发布。
