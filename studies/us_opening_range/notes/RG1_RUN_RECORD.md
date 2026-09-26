# RG1 首次资产迁移运行记录

2026-09-26 04:54 UTC，首次三ETF价格解析与真实标签前冻结。主控与独立agent只读审查通过：只保留原G首事件并翻转方向，peer按原方向开盘状态固定，09/25先按日期停止再解析价格。

- 预登记SHA256：`ea4c155d698d853e6cfbe91444134c8ddd665ecf186a3fbaa95a232f3f853d54`。
- `reverse_replay.py`：`ceaf7333badaf8764507cc96bd8b77ce1d5946a824fae2244f3f8c6eafa32f73`。
- `tests/test_reverse_replay.py`：`a475319447d90dbe765555c04fb22201ca022d7152e7259616106593b0b2bb5a`。
- RG1合成测试14项、研究全套234项与custody149项通过。冻结DS1/DS2/PERSISTENCE依赖指纹未变。

最近内存检查可用2518MiB；仅三股当日和前20日摘要，按日流式，不构造全量分钟矩阵。只验签三个已登记价格文件、它们及DIA的coverage和固定CHECKSUMS；文件全字节哈希不计算09/25特征/标签。

新输出 `reports/rg1_asset_transfer.json` 与 `data/rg1-asset-transfer-signals-20260926.jsonl`。运行开始即登记XLV/XLI/XLY截至2026-09-24为已暴露，不因失败/稀疏而恢复留出身份；另外九ETF分钟价格和全部09/25仍不解析。它是看过DS2后提出的反向新假设，不是DS2胜出或独立时间验证。

## 首次完成

04:54 UTC启动，22.53秒，峰值115664KiB（约113MiB），118条／99个活跃日期。raw胜率55.93%、平均盈亏比1.898、均值+22.95bp、单侧下限+1.20bp；但paired仅64条／54.24%，均值+3.44bp、下限−2.09bp，两项门槛未满足，正式状态仍为NOT_PASSED。不得事后降低对照覆盖要求，也不能把raw的局部正证据抹成完全无信息。

JSON报告SHA256 `a3b2c9b5ba771dfc179c17851c607c05aac28d181375e0cb17d271f107315464`；118行事件SHA256 `8bbb1a564c2b403916b40ed5c6f0b7c4be01e6882a535784ee0b4c6569929be4`。只暴露上述三资产至09/24；其它九ETF分钟和09/25价格/期权收益仍未解析，原Release字节与发布时角色不改。
