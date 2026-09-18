"""当前 Windows 用户代理的事务管理；恢复文件支持异常终止后修复。"""

from contextlib import contextmanager
import ctypes
import json
import logging
from pathlib import Path
from .interrupts import uninterrupted_cleanup

REG_PATH = r'Software\Microsoft\Windows\CurrentVersion\Internet Settings'
PROXY_KEYS = ('ProxyEnable', 'ProxyServer', 'ProxyOverride', 'AutoConfigURL')


class WindowsProxy:
    def snapshot(self) -> dict:
        import winreg
        values = {}
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH) as key:
            for name in PROXY_KEYS:
                try:
                    value, kind = winreg.QueryValueEx(key, name)
                    values[name] = [value, kind]
                except FileNotFoundError:
                    values[name] = None
        return values

    def _write(self, values: dict) -> None:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
            for name, entry in values.items():
                if name not in PROXY_KEYS:
                    raise ValueError('恢复文件包含未知代理字段')
                if entry is None:
                    try:
                        winreg.DeleteValue(key, name)
                    except FileNotFoundError:
                        pass
                else:
                    winreg.SetValueEx(key, name, 0, entry[1], entry[0])
        internet_set_option = ctypes.WinDLL('wininet', use_last_error=True).InternetSetOptionW
        for option in (39, 37):  # SETTINGS_CHANGED / REFRESH
            if not internet_set_option(None, option, None, 0):
                raise ctypes.WinError(ctypes.get_last_error())

    def enable(self, address: str) -> None:
        import winreg
        self._write({'ProxyEnable': [1, winreg.REG_DWORD],
                     'ProxyServer': [address, winreg.REG_SZ],
                     'ProxyOverride': ['<local>', winreg.REG_SZ], 'AutoConfigURL': None})

    def restore(self, values: dict) -> None:
        self._write(values)


def restore_pending(path: Path, backend=None) -> bool:
    if not path.exists():
        return False
    backend = backend or WindowsProxy()
    with uninterrupted_cleanup():
        backend.restore(json.loads(path.read_text(encoding='utf-8')))
        path.unlink()
    return True


@contextmanager
def managed_proxy(address: str, recovery: Path, backend=None):
    backend = backend or WindowsProxy()
    if recovery.exists():
        raise RuntimeError('存在待恢复代理快照，请先运行 --restore-proxy')
    values = backend.snapshot()
    server = values.get('ProxyServer')
    enabled = values.get('ProxyEnable')
    if server and enabled and enabled[0] and str(server[0]).lower().replace('localhost:', '127.0.0.1:') == address.lower():
        # 捕获启动前已验证此端口空闲；不能恢复成指向本次已关闭端口的残留代理。
        values = {**values, 'ProxyEnable': [0, enabled[1]]}
        logging.getLogger(__name__).warning('原代理指向本次抓包端口，退出时将关闭该残留代理')
    recovery.parent.mkdir(parents=True, exist_ok=True)
    with recovery.open('x', encoding='utf-8') as stream:
        json.dump(values, stream)
    try:
        backend.enable(address)
        yield
    finally:
        with uninterrupted_cleanup():
            backend.restore(values)
            recovery.unlink()
            logging.getLogger(__name__).info('系统代理已恢复到运行前的设置')
