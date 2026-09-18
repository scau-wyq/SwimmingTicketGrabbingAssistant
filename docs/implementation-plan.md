# 每日自动抢票实施计划

目标：在 Windows 已登录且桌面解锁、微信已登录的条件下，于每日 23:58 获取新 token，固定本次零点目标并执行抢票。

设计：保留 `auto_grab.py` 命令入口；业务代码放入 `swim_assistant` 包。配置使用 TOML，敏感运行文件放入 runtime。Windows 计划任务仅调度一次运行，Python 负责完整生命周期。

## 实施顺序

- [x] 添加离线回归测试：跨零点不顺延、指定日期与星期一致、测试模式不下单、失败恢复代理、捕获只接受本次 token。
- [x] 拆分 config、api、timing、capture、proxy、wechat、runner、cli；保留原 API 参数与默认票种映射。
- [x] 用 mitmproxy addon 原子输出目标登录响应中的 token，避免解析正在写入的流量文件。
- [x] 实现代理原值快照、恢复和异常恢复文件；只管理本程序的 mitmdump，端口占用时退出。
- [x] 实现小程序面板入口、快捷方式启动及可配置 UI 操作，提供 doctor、capture-only、manual 模式。
- [x] 提供 Windows 每日 23:58 任务安装/卸载脚本；固定 Python 和工作目录，禁用重叠和错过后补运行。
- [x] 添加中文 README、示例配置、依赖和测试命令，运行离线测试与真实依赖启动检查。
- [ ] 现场联调 `--test`：确认自动打开后触发登录并取得可用 token。
- [ ] 联调成功后安装实际每日任务。目前仅执行 `-WhatIf`，没有安装。

验证：`python -m unittest discover -s tests -v`；`python auto_grab.py --help`；`python auto_grab.py --doctor`。端到端 token 获取只能在入口配置就绪后运行 `--test`，此模式绝不调用创建订单接口。不得通过真实下单检验重构。

用户已批准桌面解锁方案并授权实现。保留现有研究脚本及用户 token/抓包文件，不提交这些文件。真实小程序入口和 UI 路径必须由用户提供或现场确认，不能猜测。

## 本轮验证记录

- 18 项离线 unittest 通过，覆盖测试模式不下单、UI 失败恢复顺序、未知订单响应不重试、定时任务跨零点拒绝补跑、同名窗口选择等。
- `--help`、`--doctor` 通过；CA 信任与实际 UI 操作不属于 doctor 可验证范围。
- `scripts/check-capture.py` 通过：真实启动 mitmdump/addon，退出并确认临时端口释放，不切换系统代理。
- 计划任务 `-WhatIf` 预演通过（需要在可访问 Windows 任务服务的环境执行）。
- 独立代码审查发现并修复未知响应重试、用户级锁范围、配置示例模式问题。
- 用户暂停现场电脑操作后，本轮没有操作微信、没有调用真实订单接口。
