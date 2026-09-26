# 冻结信号标签与研究指纹快照

## 推荐下载：纯数据v2

[or-signal-research-20260926-v2](https://github.com/QSothoth/s-alpha/releases/tag/or-signal-research-20260926-v2)已发布并回下载验签：17成员，包含5份原机器报告、5份原预登记、5个原事件文件、manifest及CHECKSUMS，不含源码。15个研究文件与v1原字节一致，7373条重叠派生记录的数值和曝光身份不变。全部实现仍校验SHA并在manifest留指纹，代码由独立Git提交保存，不借数据Release分发。

- ZIP：2,591,768字节，SHA256 `35b40250ae5489feff669a1b8cd5bd84b12567ec21fbcf49d64bc025d2adb92c`。
- CHECKSUMS SHA256：`09c24fee70e550fc9c71414e8e825aa1221fce343216ef30e50730240231f8bb`。
- manifest SHA256：`3de4382e6b3180597690fab7a06087cd661a79c8122bbf148ec1caeb3f86e3ac`。
- 独立回下载核对远端恰有ZIP及sidecar、ZIP与本地一致、精确成员集合／逐成员SHA／CRC均通过，无Python源码或字节码。tag锚点仍是既有远端提交，不代表该提交包含后续研究实现；不会把数据tag重新指向代码提交。

## 发布流程偏差（2026-09-26复核）

下述v1附件包含14个实现源码文件，与[DATA](../../../docs/DATA.md)“代码只走Git”的约定不符。这是发布流程疏漏，不改变已保存标签的数值。另发纯数据v2后，用户于2026-09-26明确同意撤下旧v1并清理过期资源；已删除该Release、两个远端附件及同名远端数据tag，回读确认Release不存在、tag返回404。未修改v2或其他Release，没有覆盖旧附件。

本地`data/or-signal-research-20260926-v1.zip`、sidecar及`data/or-signal-research-20260926-work/`全部保留，删除前再次核对精确31成员、逐SHA、CRC及sidecar一致。旧tag原指向`45d0b620c6c05729adbe19daecb8cffe0fb218e3`；源数据与原包可恢复，远端Release对象ID及下载计数不承诺可恢复。不自动重发已撤下tag。

当前打包器已改成只复制事件、机器报告和预登记，仍校验全部实现SHA但不复制源码；另加Python源码／字节码拒绝打包测试。下面保留v1实际内容及指纹作为历史事实，不将其当作今后发布模板。

## v1实际内容

`or-signal-research-20260926-v1` 保存DS1、DS2、PERSISTENCE、AH1、RG1各自首次运行的原字节机器报告、预登记、派生事件／标签及报告记录的实现源码。没有重跑挑选更好的版本，也没有原始行情重发；事件总行数7373，包含不同候选重叠及同一提示的跨期限审计，**不是7373个独立样本**。

所有标签均已暴露；DS1／DS2／AH1没有晋级，RG1局部raw为正但整体门槛未过，PERSISTENCE仅描述。这不是Alpha认证、期权盈利或可交易0DTE身份数据。RG1仅使用XLV／XLI／XLY截至09/24，其余九ETF分钟与全部09/25未纳入评测。

本包用于直接复核、再利用已保存的事件字段，不能恢复留出身份。重新从分钟行情生成标签仍需机器报告固定的原数据包与匹配源码；本包不是包含全部依赖的完整可执行仓库。数据不进入Git，新版本另发tag，不替换已有附件。

- ZIP顶层：`or-signal-research-20260926-work`，31个文件，2,652,364字节。
- ZIP SHA256：`eb42661f10192bd2ce69f85786c5787889376bfc139fe85619052258076f7b1f`。
- CHECKSUMS SHA256：`9e7867f9f6902288361e338abf0d960a3227365c038add93a8d1531974755d2f`。
- manifest SHA256：`20d8b21faf676654be68240f557c06024e245ebc4bc2e4e91365147b167666f1`。

tag使用远端既有提交`45d0b620c6c05729adbe19daecb8cffe0fb218e3`作为快照锚点；实际本地实现另以包内源码及SHA记录，不宣称锚点提交已经包含本研究，也不推送未发布工作区代码。发布时未启动任何长期采集。
