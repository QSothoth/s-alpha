# 云端离线复现

> 公开出版版请先读 [REDISTRIBUTION_CN.md](REDISTRIBUTION_CN.md)。Release只包含SEC冻结子集及允许公开的研究明细，不包含全部85个行情/资料输入；仅下载Release不能完整重放。详细结果ZIP在仓库根解压，SEC ZIP在data-root解压。

代码基线9c02ed482fae06db435e0a3ba80c3989505dfaad。只需Python3.12及numpy；不需要Mac、VPS、SSH、OpenD、券商账号、API密钥或付费额度。原Martin目录不改。所有输出是研究，不授权交易。

1. 从代码包解压仓库；原始数据单独放置，按DATA_INPUTS.json的relative_path保留目录。data-root可放任意云端目录
2. 在仓库根运行 `python -m studies.trader_common.reproduce --data-root /your/extracted/shared-root`。先验证全部输入哈希，然后只打印逐项命令
3. 加 `--run` 实际执行各已运行研究；整个程序会写各研究reports，先复制你要保留的输出。固定随机种子，非下载器，无网络或交易行为
4. 若只需要单项，可从打印命令中选对应module；每个study README给更细的校验和图表/分布步骤。E0档案没有虚构回测命令
5. 测试：`python -m unittest discover -s studies/trader_common/tests`；逐目录tests同理；`python -m unittest discover -s custody/tests`；`python watch/test_watch.py`

公开输入来源和精确哈希在DATA_INPUTS.json及原来源manifest。新下载的公开数据/派生CSV为LOCAL_RESEARCH_NOT_RELEASED，不是新增已注册GitHub Release，原始行情不进Git。SEC原始响应可从download_manifest对应官方URL取得或单独输入包恢复；缺某文件必须校验失败，不能静默换数据版本。

分钟UTC/美东语义：eval-v2原整数编码的是美东墙钟，已导出为带偏移datetime_et且时间为bar结束；Kaggle v59是真UTC bar开始，要转换美东并加5分钟。不能混用。QFQ/因子调整单位不是原始历史股份，完整执行资格详各study限制。

已废弃的中间结果保留在superseded目录；当前报告和汇总以最终SOURCE_AND_RESULTS_SHA256.txt及最新结果为准。git提交哈希以交付说明为准，逐次run_manifest/source_sha256才是代码内容的权威身份；提交本身会改变HEAD，不能据此前基线字段认为使用旧源码。
