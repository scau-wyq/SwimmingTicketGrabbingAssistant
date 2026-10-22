"""启动已配置的小程序入口；可选 UIA 操作由本机配置明确指定。"""

import os
from pathlib import Path, PureWindowsPath
import time
import logging

from .config import Settings

log = logging.getLogger(__name__)


def validate_entry(settings: Settings) -> None:
    if settings.wechat_mode == 'panel':
        if not settings.wechat_executable.is_file():
            raise ValueError('wechat.executable 指定的微信程序不存在')
    else:
        if not settings.shortcut or not Path(settings.shortcut).is_file():
            raise ValueError('请在 config.toml 的 wechat.shortcut 配置小程序快捷方式')
        if Path(settings.shortcut).suffix.lower() not in ('.lnk', '.exe'):
            raise ValueError('微信入口必须是本地 .lnk 快捷方式或 .exe')
    for step in settings.steps:
        if step.get('action') not in ('wait', 'click', 'keys'):
            raise ValueError('wechat.steps.action 只支持 wait、click、keys')
        if step['action'] == 'wait':
            if not 0 <= float(step.get('seconds', 1)) <= 30:
                raise ValueError('单次 UI 等待必须在 0..30 秒内')
        elif not step.get('window_title_re'):
            raise ValueError('click/keys 操作必须指定 window_title_re，避免操作错误窗口')
        elif step['action'] == 'keys' and not isinstance(step.get('keys'), str):
            raise ValueError('keys 操作必须指定 keys 字符串')
        elif step['action'] == 'click' and not step.get('control') and not {'x', 'y'} <= step.keys():
            raise ValueError('click 需要 control 选择器或相对于窗口的 x/y 坐标')
    if settings.wechat_mode == 'panel' or any(step['action'] != 'wait' for step in settings.steps):
        import importlib.util
        if importlib.util.find_spec('pywinauto') is None:
            raise RuntimeError('UI 操作需要 pywinauto，请安装 requirements-ui.txt')


def select_window(windows, title: str, executable: str, process_path):
    """微信主窗口与小程序面板同名，必须同时匹配进程名。"""
    matches = []
    for window in windows:
        if window.window_text() != title:
            continue
        try:
            name = PureWindowsPath(process_path(window.process_id())).name
        except OSError:
            continue  # 枚举之后进程可能已经退出。
        if name.casefold() == executable.casefold():
            matches.append(window)
    if len(matches) > 1:
        raise RuntimeError(f'发现多个 {title}/{executable} 窗口，无法确定操作目标')
    return matches[0] if matches else None


def panel_button_coordinates(width, height, reference, button):
    """仅允许已观察到的窗口尺寸；尺寸变化时拒绝盲点坐标。"""
    if abs(width - reference[0]) > 4 or abs(height - reference[1]) > 4:
        raise RuntimeError('微信主窗口尺寸与配置不符；请先打开小程序面板，或重新校准 main_size/panel_button')
    return tuple(button)


def visible_window_bounds(window):
    """DWM 可见边界不包含 Win32 GetWindowRect 的透明缩放边框。"""
    import ctypes
    from ctypes import wintypes
    bounds = wintypes.RECT()
    get_bounds = ctypes.windll.dwmapi.DwmGetWindowAttribute
    get_bounds.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    get_bounds.restype = ctypes.c_long
    if get_bounds(window.handle, 9, ctypes.byref(bounds), ctypes.sizeof(bounds)) != 0:
        raise RuntimeError('无法取得微信可见窗口边界，停止坐标操作')
    return bounds


def window_work_area(window):
    """使用窗口所在屏幕的工作区，兼容副屏和负坐标，避开任务栏。"""
    import win32api
    monitor = win32api.MonitorFromWindow(window.handle, 2)
    return win32api.GetMonitorInfo(monitor)['Work']


def ensure_main_window_size(window, reference, deadline):
    """恢复普通窗口并校准可见尺寸，验证成功后才允许坐标点击。"""
    if window.is_minimized() or window.is_maximized():
        window.restore()
    window.set_focus()
    for attempt in range(4):
        if time.monotonic() >= deadline:
            raise TimeoutError('调整微信窗口超过准备期限')
        bounds = visible_window_bounds(window)
        width, height = bounds.right - bounds.left, bounds.bottom - bounds.top
        left, top, right, bottom = window_work_area(window)
        size_ok = abs(width - reference[0]) <= 4 and abs(height - reference[1]) <= 4
        fits = bounds.left >= left and bounds.top >= top and bounds.right <= right and bounds.bottom <= bottom
        if size_ok and fits:
            return bounds
        if attempt == 3:
            raise RuntimeError(f'微信未接受自动调整后的尺寸（当前 {width}x{height}，目标 {reference[0]}x{reference[1]}），停止点击')
        if reference[0] > right - left or reference[1] > bottom - top:
            raise RuntimeError('当前屏幕工作区不足以容纳配置的微信窗口尺寸，停止点击')
        outer = window.rectangle()
        # move_window 接受含透明边框的外框尺寸，而配置使用 DWM 可见尺寸。
        outer_width = outer.right - outer.left + reference[0] - width
        outer_height = outer.bottom - outer.top + reference[1] - height
        visible_left = max(left, min(bounds.left, right - reference[0]))
        visible_top = max(top, min(bounds.top, bottom - reference[1]))
        log.info('[微信] 自动调整可见窗口：%dx%d → %dx%d', width, height, *reference)
        window.move_window(x=visible_left + outer.left - bounds.left,
                           y=visible_top + outer.top - bounds.top,
                           width=outer_width, height=outer_height, repaint=True)
        time.sleep(min(0.2, max(0, deadline - time.monotonic())))


def _open_from_panel(settings: Settings, deadline: float) -> None:
    log.info('[微信 1] 加载 pywinauto')
    from pywinauto import Desktop
    from pywinauto.application import process_module
    log.info('[微信 2] 使用 Win32 枚举顶层窗口，避免全桌面 UIA 阻塞')
    desktop = Desktop(backend='win32')

    def find(title, executable):
        log.info('[微信] 枚举窗口，目标=%s/%s', title, executable)
        result = select_window(desktop.windows(), title, executable, process_module)
        log.info('[微信] 目标窗口%s', '已找到' if result is not None else '未找到')
        return result

    def wait_window(title, executable):
        while time.monotonic() < deadline:
            window = find(title, executable)
            if window is not None:
                return window
            time.sleep(0.2)
        raise TimeoutError(f'未找到窗口：{title}/{executable}')

    # 关闭目标小程序窗口后重新打开，避免复用已经展示的旧页面。
    existing = find(settings.miniprogram_name, 'WeChatAppEx.exe')
    if existing is not None:
        log.info('[微信] 关闭已有目标小程序窗口以便重新打开')
        existing.close()
        while find(settings.miniprogram_name, 'WeChatAppEx.exe') is not None:
            if time.monotonic() >= deadline:
                raise TimeoutError('目标小程序未关闭')
            time.sleep(0.2)

    def open_panel():
        log.info('[微信 3] 启动/激活微信主程序')
        os.startfile(str(settings.wechat_executable))
        main = wait_window('微信', settings.wechat_executable.name)
        log.info('[微信 4] 自动恢复并校准微信窗口尺寸')
        bounds = ensure_main_window_size(main, settings.main_size, deadline)
        width, height = bounds.right - bounds.left, bounds.bottom - bounds.top
        log.info('[微信] 可见窗口尺寸=%dx%d', width, height)
        coords = panel_button_coordinates(width, height, settings.main_size, settings.panel_button)
        main.click_input(coords=(bounds.left + coords[0], bounds.top + coords[1]), absolute=True)
        log.info('[微信 5] 已点击小程序侧栏入口')

    # 正常加载也可能短暂空白：每轮允许 12 秒，最多重开两次。
    for attempt in range(3):
        if time.monotonic() >= deadline:
            break
        if find('微信', 'WeChatAppEx.exe') is None:
            open_panel()
        entry = _wait_panel_entry(
            lambda: find('微信', 'WeChatAppEx.exe'),
            lambda panel: Desktop(backend='uia').window(handle=panel.handle).wrapper_object(),
            settings.miniprogram_name, min(deadline, time.monotonic() + 12))
        if entry is not None:
            if time.monotonic() >= deadline:
                raise TimeoutError('点击小程序入口前已超过准备期限')
            log.info('[微信 7] 找到可见小程序入口，点击')
            entry.click_input()
            wait_window(settings.miniprogram_name, 'WeChatAppEx.exe')
            log.info('[微信 8] 目标小程序窗口已出现')
            return
        if attempt == 2 or time.monotonic() >= deadline:
            break
        log.warning('[微信] 面板持续未出现目标入口，重开面板（恢复 %d/2）', attempt + 1)
        # 只关闭精确标题和进程匹配的窗口；多个候选仍拒绝操作。
        panel = find('微信', 'WeChatAppEx.exe')
        if panel is not None:
            panel.close()
            close_deadline = min(deadline, time.monotonic() + 3)
            while find('微信', 'WeChatAppEx.exe') is not None:
                if time.monotonic() >= close_deadline:
                    raise TimeoutError('异常小程序面板未关闭，停止恢复')
                time.sleep(0.2)
    raise TimeoutError('小程序面板持续未就绪或未找到目标入口；已用尽恢复次数或准备时间，'
                       '请检查微信网络，并将小程序保留在最近使用/我的常用中')


def _wait_panel_entry(find_panel, wrap_panel, name, deadline):
    """以可见入口判断可操作状态；重新获取窗口和 UIA 包装器以应对页面重建。"""
    previous_state = None
    focused_handle = None
    while time.monotonic() < deadline:
        panel = find_panel()  # 歧义窗口错误必须向上传递。
        entries = []
        if panel is None:
            state = ('窗口消失或尚未出现',)
        else:
            try:
                if focused_handle != panel.handle:
                    if panel.is_minimized():
                        panel.restore()
                    panel.set_focus()
                    focused_handle = panel.handle
                controls = wrap_panel(panel).descendants(control_type='Text')
                entries = [item for item in controls
                           if item.window_text() == name and item.is_visible()]
                state = (panel.handle, len(controls), len(entries))
            except Exception as exc:
                # COM/UIA 异常随控件生命周期变化，仅重试读取，不吞掉点击错误。
                state = (panel.handle, 'UIA 读取失败', type(exc).__name__)
                focused_handle = None
        if state != previous_state:
            log.info('[微信 6] 面板状态（句柄/文字数/入口数或异常类型）=%s', state)
            previous_state = state
        if entries:
            return entries[0]
        time.sleep(min(0.3, max(0, deadline - time.monotonic())))
    return None


def open_miniprogram(settings: Settings, deadline: float) -> None:
    """公共入口：隔离桌面接口的阻塞，超时后父流程可以正常清理。"""
    from .ui_worker import run_ui_task
    validate_entry(settings)
    run_ui_task(settings, deadline)


def _open_miniprogram(settings: Settings, deadline: float) -> None:
    validate_entry(settings)
    if settings.wechat_mode == 'panel':
        _open_from_panel(settings, deadline)
    else:
        os.startfile(settings.shortcut)
    for step in settings.steps:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('微信自动操作超过准备期限')
        action = step['action']
        if action == 'wait':
            time.sleep(min(float(step.get('seconds', 1)), remaining))
            continue
        from pywinauto import Desktop
        window = Desktop(backend='uia').window(title_re=step['window_title_re'])
        window.wait('visible enabled', timeout=min(remaining, 10))
        window.set_focus()
        if action == 'keys':
            window.type_keys(step['keys'], with_spaces=True, pause=0.1)
        elif step.get('control'):
            window.child_window(**step['control']).wait('visible enabled', timeout=min(remaining, 10)).click_input()
        else:
            window.click_input(coords=(int(step['x']), int(step['y'])))
