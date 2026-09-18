# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目是什么

Windows 本地自动抢票助手：每天 23:58 由 Windows 任务计划程序启动 Python，本地抓包获取微信小程序（奥冠体育 / `api.wesais.com`）的登录 token，等到本地零点后批量下单预约游泳票。代码注释、README、配置均为中文，请沿用中文注释与日志风格。

## 常用命令

Python 3.11+（推荐 conda 环境 `SwimmingTicketGrabbingAssistant`）；`pip install -r requirements-ui.txt` 安装全部依赖（requests、mitmproxy、pywinauto）。没有 lint/typecheck 配置。

本机终端里的 `python` 会解析到 `WindowsApps\python.exe` 存根并直接退出 49，需显式用 conda 解释器，例如
`C:/Users/wang3/anaconda3/envs/SwimmingTicketGrabbingAssistant/python.exe -m unittest discover -s tests -v`（22 项全部通过），或在 PowerShell 里先 `conda activate SwimmingTicketGrabbingAssistant`。

```powershell
python -m unittest discover -s tests -v      # 离线回归测试：不碰桌面、网络、代理、计划任务
python -m unittest tests.test_core -v         # 单个测试文件
python scripts/check-capture.py               # 真实启停 mitmdump（临时端口，不改代理、不开微信）
python auto_grab.py --doctor                  # 只检查环境/文件/端口
python auto_grab.py --wechat-only             # 只打开小程序：不动代理、不抓包、不调 API
python auto_grab.py --test                    # 取 token + 只读验证，绝不下单；--manual 表示自己打开小程序
python auto_grab.py [--date 20260921]         # 正式预约
python auto_grab.py --restore-proxy           # 恢复异常中断遗留的代理
.\scripts\install-task.ps1 -PythonPath '...'  # 安装每日任务（-WhatIf 预览 / -TestOnly 只做取 token）
.\scripts\uninstall-task.ps1
```

退出码：`0` 成功，`1` 配置或流程错误，`2` 本次未抢到，`130` 用户中断。`pyproject.toml` 还注册了 `swim-assistant` 入口（需先 `pip install -e .`），与 `auto_grab.py` 等价。

## 架构

阅读顺序：`auto_grab.py → cli.main → runner.run → acquire_token`。业务 API 与 Windows 适配层刻意分开，便于替换和单独测试。

- `cli.py` 参数/日志/退出码；`runner.py` 单次任务编排（准备 → 采集 → 验证 → 等待 → 预约）；`config.py` TOML + 取值范围校验。
- `api.py`：`classify()` 把服务端 code 归一化为状态；`ApiClient.send_order()` 是**唯一**创建订单的调用。`session.trust_env = False` 必须保留（否则请求会走抓包代理）。
- `timing.RunTarget`（frozen）：`release_at` 固定为本地下一个零点，登录后不允许跨零点顺延；`require_preparation_time()` 一旦发现已过零点就抛 `TimeoutError`。
- `capture.start_capture()`：只管理本程序启动的 mitmdump，端口被占用直接退出、不杀其他进程；`token_addon.py` 由 mitmdump 独立加载，只把目标登录响应原子写入 `runtime/capture-<run_id>.json`（用 `run_id` 校验，用完删除）。
- `proxy.managed_proxy()`：写快照 → 设系统代理 → yield → 恢复 + 删快照。快照留在 `%LOCALAPPDATA%\SwimmingTicketAssistant\proxy-recovery.json` 以支持强杀/断电后恢复；存在待恢复快照时拒绝启动（提示先 `--restore-proxy`）。
- `wechat.open_miniprogram()` 在**独立 spawn 进程**（`ui_worker.py`）中执行，UIA 阻塞调用可用共享的 monotonic deadline 超时掉，不会卡死父流程。顶层窗口查找用 `win32` 后端（避免全桌面 UIA 枚举阻塞），只在目标面板内用 `uia` 找文字控件；坐标用 DWM 可见边界。

用户级锁和代理快照统一在 `%LOCALAPPDATA%\SwimmingTicketAssistant`（`Settings.state_dir`），不随配置文件变化，防止两个不同配置的任务同时改系统代理。配置中的相对路径一律相对**配置文件**解析（任务计划程序的默认工作目录不可靠）。

## 必须保持的安全不变量

- 绝不用真实下单验证改动；`--test` 只调用只读配置接口，无法证明下单权限。
- 订单响应为 `unknown`/`uncertain` 时必须停止重试（可能已创建订单），不要改成继续重试。
- 日志不得记录 token、账户信息或完整 HTTP 流量；`_post()` 出错静默返回 `{'code': -1}` 是有意为之。
- 8080 被占用时退出而非杀进程；强杀残留的 mitmdump/代理由端口检查提示 + `--restore-proxy` 处理。
- 抓包只接受本次 `run_id` 的 token；`token.txt` 和旧流量文件不再更新，token 只留在内存和本次临时文件。
- UI 选择器与坐标（`wechat.main_size`、`panel_button`、`steps`）只能来自用户或现场确认，不能猜测；窗口尺寸不匹配要拒绝点击而不是继续点。
- `scripts/*.ps1` 必须保存为 UTF-8 BOM（PowerShell 5.1 读中文脚本）。
- `config.toml`、`token.txt`、`traffic*.log`、`runtime/` 已在 `.gitignore` 中（含 token 等敏感信息），不要提交。

## 不在流程内

`script/grab.py`、`script/analyze*.py`、`extract_token.py` 是早期研究脚本，保留作对照，不参与新自动化流程，新功能不要加在上面。`auto_grab.py` 只是兼容旧命令的薄入口。`docs/implementation-plan.md` 记录已实现/待联调清单。

## 测试约定

用 `unittest`（无 pytest 配置）。测试必须离线：用 `Mock`/`patch` 替换 `acquire_token`、`ApiClient`、proxy 后端和 mitmdump 进程，用 `TemporaryDirectory` 提供 runtime/state 目录。新增涉及安全或时序的行为时，同步补离线回归测试——`tests/test_safety.py` 已覆盖 UI 失败时代理恢复顺序、未知响应不重试、定时任务跨零点拒绝补跑等场景。
