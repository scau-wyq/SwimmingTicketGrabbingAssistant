"""启动已配置的小程序入口；可选 UIA 操作由本机配置明确指定。"""

import os
from pathlib import Path, PureWindowsPath
import time

from .config import Settings


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


def _open_from_panel(settings: Settings, deadline: float) -> None:
    from pywinauto import Desktop
    from pywinauto.application import process_module
    desktop = Desktop(backend='uia')

    def find(title, executable):
        return select_window(desktop.windows(), title, executable, process_module)

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
        existing.close()
        while find(settings.miniprogram_name, 'WeChatAppEx.exe') is not None:
            if time.monotonic() >= deadline:
                raise TimeoutError('目标小程序未关闭')
            time.sleep(0.2)

    panel = find('微信', 'WeChatAppEx.exe')
    if panel is None:
        os.startfile(str(settings.wechat_executable))
        main = wait_window('微信', settings.wechat_executable.name)
        if main.is_minimized():
            main.restore()
        main.set_focus()
        bounds = main.rectangle()
        coords = panel_button_coordinates(bounds.width(), bounds.height(), settings.main_size, settings.panel_button)
        main.click_input(coords=coords)
        panel = wait_window('微信', 'WeChatAppEx.exe')
    if panel.is_minimized():
        panel.restore()
    panel.set_focus()
    while time.monotonic() < deadline:
        # 已观察到“最近使用”和“我的常用”均有奥冠体育；同名项打开的是同一小程序。
        entries = [item for item in panel.descendants(control_type='Text')
                   if item.window_text() == settings.miniprogram_name and item.is_visible()]
        if entries:
            entries[0].click_input()
            wait_window(settings.miniprogram_name, 'WeChatAppEx.exe')
            return
        time.sleep(0.3)
    raise TimeoutError('小程序面板中未找到奥冠体育；请将它保留在最近使用或我的常用中')


def open_miniprogram(settings: Settings, deadline: float) -> None:
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
