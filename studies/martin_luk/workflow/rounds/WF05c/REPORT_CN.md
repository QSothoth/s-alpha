# WF05c 开轮证据刷新

WF05 状态的 `can_start_round` 为 **true**；g1=通过、whitelist_approved=通过、datasets=通过、capital_rules=通过、registered_unchanged=通过、cache_consistent=通过、rule_fingerprints=通过。档案检查返回 0。本次是证据修补，没有开启 WF06 或重新判定既有候选。

三份已批准的数据集均重新核验通过，[新数据证据](logs/datasets_evidence.json)绑定当前配置。[资金审计](capital_audit.json)核对了资本规则、版本和所有原回放及引用的 SHA，保留原始审计和 WF05b 审计的来源链，只刷新配置指纹；没有重新回放。完整前后指纹和证据路径在 [completion.json](completion.json)。

## 测试

| 测试组 | 数量 | 返回码 | 跳过 | 预期失败 |
|---|---:|---:|---:|---:|
| custody/tests | 238 | 0 | 0 | 0 |
| studies/trader_replication/tests | 1197 | 0 | 0 | 1 |
| studies/martin_luk/tests | 377 | 0 | 1 | 0 |
| studies/trader_screens/tests | 102 | 0 | 1 | 0 |

Martin 测试组首次有 1 项失败：测试读取了仍绑定旧配置的真实数据证据。先完成真实数据集检查后，该组重新运行并通过；[首次记录](logs/tests_initial.json)和[重跑日志](logs/studies_martin_luk_tests_retry.log)均保留。测试证据同时绑定了当前判定代码及其测试的 SHA。

## 保留的流程问题

- 旧测试证据检查未强制绑定判定代码，代码变化后可能误认旧测试仍有效；本次新证据已绑定，问题见 [复现记录](work/test_evidence_gap.json)。
- 上述回归测试对真实工作区的证据状态有隐含依赖，需要在后续获准修改时隔离。
- 13 份缓存的内容和不可变来源记录均未变；其中 12 份已登记缓存的数据指纹前后一致。未登记的 IE9 此前刷新时还更新了旧数据指纹和多项代码指纹，其旧数据集身份尚未证明与新指纹等同，未来登记前需核对血缘。[清单核对](work/frozen_manifest_check.json)。

[受保护文件核对](work/protected_check.json)：309 个文件均未改变。原有判定、版本文件、冻结缓存内容、登记版、看板及 WF06 任务书未改；未提交或推送。
