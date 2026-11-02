# 本地 OpenD

`custody freeze`、`custody dryrun`、`custody run` 需要一个已登录、有美股期权行情权限的 Futu / moomoo OpenD：

无桌面 Linux 用**命令行 OpenD**（`FutuOpenD`），不要装 GUI AppImage。

- 程序目录 `/opt/futu-opend`，配置 `/opt/futu-opend/FutuOpenD.xml`，入口命令 `FutuOpenD`
- API 默认 `127.0.0.1:11111`，telnet 验证码口 `127.0.0.1:22222`
- 启动后走交互登录；首次通常要手机验证码，用 `input_phone_verify_code -code=......` 打进 telnet
- 不要把账号密码写进 xml 或 git；记住密码后下次可用 `FutuOpenD -login_account=账号 -login_by_remember=1`
- GUI 版的"记住密码"CLI 读不到：`-login_by_remember=1` 报 "Unable to find remembered password"；CLI 首次必须用 `-login_pwd_md5=$(printf %s "$FUTU_LOGIN_PASSWORD" | md5sum | cut -d" " -f1)` 或交互密码登录（密码只走环境变量，不进 xml/git），之后才能 remember。GUI 版 API 禁用 unlock_trade，真实下单必须用 CLI。
- Python：`/opt/opend-us-options/.venv/bin/python`（已装 `futu-api`，不进 git；版本钉在 `requirements.lock`，重建用 `python3 -m venv .venv && .venv/bin/pip install -r requirements.lock`，升级依赖后同步更新这个文件）；评测和单元测试不需要。`custody freeze` / `dryrun` / `run` 用这个解释器。这是全机唯一的项目环境，定时 QQ 推送和 Paseo 会话都用它。端口也可用 `FUTU_HOST` / `FUTU_PORT` 或 `--host` / `--port` 覆盖。

本机 `research/trader_board_to_qq.py` 和 `research/trader_preclose_to_qq.py` 启动时自动切换到项目 `.venv`，覆盖日报、盘中发布及异常通知；systemd 原有的 `/usr/bin/python3` 命令也通过这两个入口切换。主任务在刷新前调用 `scripts/check_runtime.py` 的检查，核对解释器、锁定依赖版本、实际导入及本机绘图和发布工具。该检查不联网、不取数、不发帖。修改或重建环境后先运行：

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python scripts/check_runtime.py --publisher
python3 research/trader_board_to_qq.py --check-runtime
```

本机 `research/` 发布脚本不入 Git，环境迁移时必须一起检查。发布端按交易日保存请求和回执；请求结果不明时保留 `pending`，只通过远端核对恢复，不盲目重发。CLI 返回值及有长度上限的标准输出、错误输出写入本机权限为 `0600` 的回执，供故障定位；外部接口失败仍可能需要人工核对。

失败后重跑成功还会同步编辑对应日期的异常通知：正式看板经远端核验后，将旧通知更新为“已恢复”及看板链接。验收须检查频道列表中的通知状态和目标帖子，不能只检查本机退出码。

- `freeze` / `dryrun` 只用 `OpenQuoteContext`。只有 `custody run` 通过 `custody/broker.py` 使用 `OpenSecTradeContext` 下单，账户需要美股期权交易权限；其他模块不得出现 `OpenSecTradeContext`、`unlock_trade`、`place_order`、`modify_order`（测试静态扫描）。
- `run --mode paper` 用 OpenD 模拟账户，不需要解锁；`--mode live` 用真实账户，**必须**提供 `FUTU_TRADE_PASSWORD` / `FUTU_TRADE_PASSWORD_MD5`（启动时校验；进程内在每次下单前会再 unlock，解锁相关失败会重试一次）。不要依赖 GUI 解锁长期有效。账户 id 填 `--acc-id`，填错时报错信息会列出 OpenD 里的可用账户。

配额提醒：

- 历史 K 线接口限速 60 次 / 30 秒，`freeze` 自带 50 次 / 30 秒的限速；
- 期权历史按 (标的, 到期日) 计入配额，过期周权的历史很快就取不到，所以每个交易日收盘后当天就要 `freeze`。

不要把 OpenD 程序、配置、登录凭据和交易密码提交进 git。
