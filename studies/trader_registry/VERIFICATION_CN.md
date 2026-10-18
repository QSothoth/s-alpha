# 整合核对记录（2026-10-18）

基于 main `5bd4c16d73a9ca7b2b2d2c94b145b4949e2eb339`，仅增加本目录和两个既有文档的导航链接（studies/AGENTS.md、skills/trader-replication/SKILL.md）。全部既有策略、配置、报告与测试保持原字节；未合并历史研究分支。

## 覆盖核对

- 35条独立人物记录：原33人 + Qullamaggie/Oliver Kell两位参考；另44名字仅原报告附录
- 35个独立档案路径、身份与别名无跨人冲突
- 245个去重来源URL入口，包含不同阅读状态；数量不代表245份独立验证
- 69个资料包文件 + MANIFEST，逐文件大小/哈希核对；中国README移除未随包发布的中间摘录指引并更新对应清单值，两份CSV统一LF换行；其余档案保持资料包内容
- 所有main代码/报告路径验证存在；19条历史分支实现仅保留固定提交链接，不虚构main路径；13条来源不足、2条新增参考保留未实现；Martin记录当前main局部研究
- ADR/R版本、新增自动字幕整理与研究者最终配置在 MAIN_SOURCE_ADDENDUM_CN 分层记录

## 本次实际运行

使用云端Python环境，不访问券商、不下载行情，不跑新回测。通过：

- 注册表测试9项：人数、别名、模式与非法输入、路径、状态/代码约束、来源清单、生成索引同步、JSON CLI、不可变数据类
- custody/tests：194项
- studies/trader_replication/tests：30项
- studies/martin_luk/tests：47项
- watch/test_watch.py：38项

共318项通过。另执行Python编译、git diff --check、内部绝对路径扫描及本地Markdown链接核对。这里报告的是测试和资料完整性，不是策略盈利或收益复现验收。
