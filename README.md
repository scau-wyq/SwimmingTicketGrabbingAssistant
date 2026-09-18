# 游泳馆自动预约助手

Windows 任务计划程序每天 **23:58（电脑本地时间）** 启动 Python。程序启动本地抓包代理、临时切换系统代理、打开微信「奥冠体育」、捕获本次登录 token，恢复代理后等待零点预约。

适用条件：电脑开机、桌面解锁、微信已登录、时间和时区正确。需要预先信任 mitmproxy CA（原脚本能抓包的环境可继续使用）。微信扫码登录、验证码、授权弹窗需要人工处理。

## 当前实现与验证范围

- 已实现模块化流程、窗口选择、代理恢复、每日任务安装脚本及离线回归测试。
- 已根据现场观察配置本机微信路径和「奥冠体育」入口；面板的“最近使用”和“我的常用”中均存在该小程序。
- 已现场跑通独立微信测试：激活微信、打开小程序面板、识别入口、打开「奥冠体育」，用户已确认看到目标窗口。
- **尚未完成真实微信自动取 token 的端到端联调，也未安装每日计划任务。** 离线测试不会操作桌面或创建订单。启用正式计划任务前，先运行下文 `--test` 验证。
- 关闭再打开小程序不保证每次触发新的登录响应。如果 `--test` 超时，需确认当前微信版本的缓存行为，或在 `wechat.steps` 增加进入门票页面的操作。不能把打开窗口当作获取 token 成功。

## 项目结构

```text
auto_grab.py                 兼容原命令的薄入口
swim_assistant/
  cli.py                    参数、日志、退出码
  config.py                 TOML 配置、路径和数值检查
  runner.py                 单次任务业务编排
  timing.py                 不可变的放票时间、等待
  api.py                    只读校验、票种校验、下单 API
  capture.py                mitmdump 生命周期与 token 等待
  process_tree.py           Windows Job Object，回收抓包进程及所有子进程
  interrupts.py             Ctrl+C 与资源回收保护
  token_addon.py            仅提取指定登录响应，原子写入临时 token
  proxy.py                  Windows 用户代理保存、设置、恢复
  wechat.py                 微信主窗口、面板及小程序导航
  ui_worker.py              独立 UI 进程，强制超时与失败回传
  locking.py                系统释放的跨进程锁
config.example.toml         可提交的配置模板
config.toml                 本机配置（不提交）
scripts/                    每日计划任务安装/卸载
tests/                      unittest 离线回归测试
runtime/                    日志与短暂采集文件（不提交）
```

`grab.py`、`extract_token.py`、`analyze*.py` 是原有研究脚本，保留用于对照，不参与新自动化流程。建议从 `cli.main → runner.run → acquire_token` 顺序阅读；业务 API 和 Windows 适配层分开，便于替换与单独测试。

用户级锁和代理恢复快照统一放在 `%LOCALAPPDATA%\SwimmingTicketAssistant`，不随配置文件变化，防止两个不同配置的任务同时修改系统代理。

## 环境与启动

推荐 Python 3.12。当前项目 Conda 环境已安装 requests、mitmproxy、pywinauto。新环境运行：

```powershell
conda activate SwimmingTicketGrabbingAssistant
python -m pip install -r requirements-ui.txt
# 仅首次没有本机配置时执行，不要覆盖已经调好的配置：
Copy-Item config.example.toml config.toml
python auto_grab.py --doctor
```

`--doctor` 只检查环境、文件和端口，不打开微信、不改代理、不调用预约服务。CA 文件存在不表示证书信任已验证。所有相对配置路径均相对于配置文件，避免任务计划程序默认工作目录导致文件找错。

本机不激活 Conda 也可以：

```powershell
& 'C:\Users\wang3\anaconda3\envs\SwimmingTicketGrabbingAssistant\python.exe' auto_grab.py --doctor
```

## 微信入口

默认 `wechat.mode = "panel"`：

1. 如果「奥冠体育」窗口已打开，关闭它以便重新进入。
2. 优先复用小程序面板；没有面板时启动/聚焦微信，点击已配置的小程序侧栏入口。
3. 在面板的可访问性文本中查找「奥冠体育」并点击，不依赖它排列在第几个。
4. 等待小程序窗口出现，按可选的 `wechat.steps` 继续操作，最后等待抓包结果。

主窗口和面板的标题都可能为「微信」，代码额外匹配 `Weixin.exe` / `WeChatAppEx.exe`。首次侧栏点击使用本机观察到的窗口相对坐标 `[31, 430]`，参考窗口尺寸 `[1060, 778]`。窗口尺寸或缩放变化时会拒绝点击：最简单的处理是提前打开小程序面板；也可重新校准配置。不会自动调整你的桌面或窗口布局。

顶层窗口使用 `win32` 后端查找（支持 64 位 Windows），避免全桌面 UIA 枚举阻塞。仅在目标面板内使用 UIA 查找文字控件。坐标检查使用 DWM 可见边界，排除 Win32 窗口的透明边框。整个 UI 操作运行在独立进程中，超过 `capture.timeout_seconds` 的共享期限会被停止，不会无限卡住父流程。

如有小程序快捷方式，可改成 `mode = "shortcut"` 并填写 `shortcut`。需要进入门票页时，可以配置 `wait`、`click`、`keys` 步骤，见模板中的示例。控件名必须来自实际界面，示例中的“门票”不是已验证选择器。七张二维码目前不参与自动化；订单日期和票种由 API 参数选择。

## 验证与正式运行

```powershell
# 不触碰电脑和服务的单元测试
python -m unittest discover -s tests -v

# 单独验证 mitmdump 及插件启停；临时端口，不修改代理或打开微信
python scripts/check-capture.py

# 清理集成测试：真实 mitmdump + 内存代理替身，不改系统网络
python scripts/check-cleanup.py

# 只打开微信小程序；不修改代理、不抓包、不调用预约 API
python auto_grab.py --wechat-only

# 会打开微信、临时切换代理和获取 token，但绝不下单
python auto_grab.py --test

# 便于排查：你自行打开小程序，程序负责代理和 token 等待
python auto_grab.py --test --manual

# 正式预约：获取 token 后等待下一个零点
python auto_grab.py

# 显式预约日期；放票时刻仍是本次运行的下一个零点
python auto_grab.py --date 20260921
```

`--test`（也叫 `--capture-only`）只调用原配置读取接口验证请求成功，**不调用创建订单接口，不能证明下单权限有效**。原来的 `--keep` 已移除，抓包统一自动关闭。旧 `token.txt` 不再更新，token 默认仅保留在内存和短暂的本次采集文件中，采集结束删除临时文件。

## 安装每日 23:58 任务

先通过一次 `--test`，再在项目目录执行：

```powershell
.\scripts\install-task.ps1 -PythonPath 'C:\Users\wang3\anaconda3\envs\SwimmingTicketGrabbingAssistant\python.exe'
```

安装脚本会先运行 `--doctor`；使用当前用户交互式登录，不保存密码；固定 Python 和工作目录；禁止任务重叠，不启用错过后的补跑。任务参数还含 `--scheduled`，若启动时已过零点会退出，避免重新等待一天。执行时间上限为 8 分钟。安装脚本不自动触发当晚任务。

可使用 `-WhatIf` 预览安装，或 `-TestOnly` 创建每天仅获取 token 的任务。已有同名任务时拒绝覆盖，先检查再卸载：

```powershell
Get-ScheduledTask -TaskName SwimmingTicketAssistant
Get-ScheduledTaskInfo -TaskName SwimmingTicketAssistant
.\scripts\uninstall-task.ps1
```

Windows PowerShell 5.1 读取带中文的 `.ps1` 需要 UTF-8 BOM，本项目脚本按此编码保存。若系统执行策略限制脚本运行，使用组织允许的执行方式，不需要修改全局策略。

## 故障与恢复

日志在 `runtime/assistant.log`，按大小轮转；mitmdump 错误在 `runtime/mitmdump.log`。日志不记录 token、账户信息或完整 HTTP 流量。

微信操作的详细阶段日志和异常堆栈在 `runtime/wechat.log`。`--wechat-only` 成功仅表示目标窗口已出现，不表示已获取 token 或验证预约接口。

| 情况 | 行为/处理 |
|---|---|
| 8080 被占用 | 退出，不杀其他进程；关闭占用程序或修改端口 |
| 获取 token 超时 | 恢复代理并退出；检查证书、代理和小程序登录是否触发 |
| 窗口尺寸不匹配 | 先打开小程序面板，或重新校准坐标 |
| 未找到奥冠体育 | 将它保留在面板最近使用/我的常用中 |
| 准备过程已跨零点 | 退出，不顺延一天 |
| HTTP 下单结果不确定 | 停止重试，请人工查看订单，避免重复提交 |
| 正常结束、任务失败或 Ctrl+C | 先恢复代理，再回收本次 mitmproxy 整个进程树；连续 Ctrl+C 不打断清理 |
| 代理原先已指向本次 127.0.0.1:端口（或 localhost:端口） | 退出时关闭这个残留代理，避免指向已经停止的抓包端口 |
| 代理恢复失败 | 仍然回收抓包进程树，报错并保留恢复文件，不宣称清理成功 |
| 进程被强杀、断电 | 无法保证代理恢复代码执行；Job Object 在拥有者退出时回收抓包子进程，代理需要下次启动恢复或手动恢复 |

```powershell
python auto_grab.py --restore-proxy
```

恢复操作使用 `%LOCALAPPDATA%\SwimmingTicketAssistant\proxy-recovery.json` 中保存的恢复值。如果异常后你已经手动改过代理，应先检查快照再恢复。除上述指向本次抓包端口的残留代理外，原有代理设置会恢复。本程序不会按进程名称或端口杀其他人的程序；旧版本遗留进程或其他程序占用端口时仍会提示并停止启动。

清理日志会分别打印“系统代理已恢复…”和“mitmproxy 进程树已停止，端口…已释放”。抓包启动器在挂起状态加入 Windows Job Object 后才允许运行，因此其子进程也受同一个 Job 管理，即使启动器提前退出也能一起回收。

退出码：`0` 成功（测试成功/预约成功），`1` 配置或流程错误，`2` 本次预约未成功，`130` 用户中断。

## 与旧脚本的差异

- 去掉两处 Enter 交互，抓包直接写出本次 token，不再反复扫描整个流量文件。
- 日期与星期按预约日期计算；固定本次放票时间，避免跨零点错位。
- 校验只接受明确成功；票种不匹配时退出，不再扫描其他星期猜测票种。
- 预热提前 10 秒进行，不在零点前 0.5 秒才发送多个可能耗时 3 秒的请求。
- 使用 Windows 本地时间，不再用精度仅到秒的 HTTP Date 改写触发时刻。请保持 Windows 自动校时。
- 仍保持最多 30 次、间隔至少 0.1 秒的原请求规模；成功即停，响应不确定时停。
- 用户原有 token 和流量文件不被改动。它们若已被 Git 跟踪，新增 `.gitignore` 不会移除历史记录；不要将这些文件推送到公开仓库。
