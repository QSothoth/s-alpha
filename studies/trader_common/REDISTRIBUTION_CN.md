# 公开发布范围与复现边界（2026-10-17）

## 代码和结果放在哪里

本研究在独立分支 research/individual-trader-studies 发布，不改 main 或原 martin_luk 基线。代码、预登记、研究说明、最终结论、汇总指标和原始冻结哈希进入Git。逐笔模拟账本、NAV与逐行研究结果放在对应Release的 trader-studies-detailed-results-20261017-v1.zip；在仓库根解压以恢复相同相对路径。部分逐行行情复制文件因下述许可问题未公开，精确清单和原文件SHA256见 PUBLICATION_MANIFEST.json。未改写原研究指标或隐藏负面结果。

原云端交付提交8097f440471f6c6c14038423f0e72337a39226eb的Git对象未保留，因此本次以9c02ed482fae06db435e0a3ba80c3989505dfaad为父提交重建出版版；变更由原源代码补丁与原报告恢复。分支中的发布说明与打包范围是本次新增，不把新提交冒充旧提交。

## 数据许可分类

- Futu/OpenD市场数据：官方服务条款市场数据1.2要求事先获得数据提供者书面同意才能向第三方再分发。因此不再次公开原始价格文件或可替代行情的逐行原始报价导出。用户原有Release上已经公开不等于获得再分发许可。依据：https://www.futunn.com/about/services?lang=zh-cn
- 腾讯/新浪历史行情、Yahoo来源Kaggle v59、第三方GitHub行情CSV：本次未建立足够明确的底层行情再分发许可，按“许可未确认”留出，而不是断言全部违法。用户应直接向相应来源取得可用于其用途的数据并遵守来源条款；原数据来源URL、具体版本/选择、SHA256保留在输入清单/下载manifest。没有调用券商或消耗额度。
- SSE/基金公告等原始HTML/PDF：不随包复制全文；保留来源URL与研究者整理的事实记录。公开可读本身并非全文复制许可。
- SEC归一化事实子集：官方Website Dissemination政策允许标明SEC来源的复制分发；无SEC标志、不暗示SEC认可。作为 trader-studies-sec-inputs-20261017-v1.zip 单独发布8个冻结输入文件。https://www.sec.gov/about/privacy-information#dissemination
- 模拟成交、资金账本、净值和汇总统计是研究代码产生的结果，保留作为研究派生产物；不得据此宣称上游行情由本仓库MIT许可证授权，也不构成真实成交记录。

以上是本次保守发布审查及可核验政策依据，不是全面法律意见；未联系提供者、未代表用户接受新许可。

## 明确不能仅靠本Release完成什么

SEC子集没有原始raw响应与归一化脚本（上游README提到它们不代表本包含有），原始SHA256SUMS仅为来源记录。新增根目录校验文件仅针对实际打包文件。仅8个SEC文件不能重放依赖其余77个输入的日线、分钟、中国ETF、事件或完整组合研究。主复现器仍检查全部85个原输入并在缺失/哈希不符时退出；不下载、不替换、不补造。即便从原公开端点重新取得数据，今天的版本可能不同，必须逐文件核验，不能谎称精确复现。

所有输入发布状态、原因和直接来源见 INPUT_PUBLICATION_MANIFEST.json。原研究 SOURCE_AND_RESULTS_SHA256.txt / 各run_manifest 描述原研究快照，不是本次公开包的完整文件清单。公开包以Release SHA256SUMS和 PUBLICATION_MANIFEST.json 为准。取得合法原输入并恢复明细结果后，按 REPRODUCE_CN.md 执行；生产交易资格仍不存在。


## 用户批准的路径便携化

历史云端绝对路径已改成仓库相对路径；原研究仓库路径使用 ./studies/ 等，输入路径使用 data/ 前缀，建议将数据根置于仓库 data/。原归档未改。PATH_NORMALIZATION_MANIFEST.json逐项列出原始与公开文件SHA256；旧run_manifest、SOURCE_AND_RESULTS_SHA256与源码指纹仍描述历史研究快照，不能用来声称便携化后的文件字节未变。财务事实、回测参数与结果数值未改，少量旧审计脚本默认输入路径仅改为相对data/。SEC元数据中出现云端路径的文件也做了同样处理，原85输入校验器仍要求原冻结哈希；公开包的输入发布清单明确区分原始哈希与公开版本哈希。
