"""真实进程清理集成测试；代理使用内存替身，不改系统网络、不打开微信。

覆盖正常退出、真实 SIGINT、异常、代理恢复失败以及启动器先退出。
"""
from dataclasses import replace
import os
from pathlib import Path
import signal
import socket
import sys
from tempfile import TemporaryDirectory
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from swim_assistant.capture import start_capture, port_in_use
from swim_assistant.config import Settings
from swim_assistant.interrupts import cleanup_safe_interrupts
from swim_assistant.process_tree import ProcessTree
from swim_assistant.proxy import managed_proxy


class MemoryProxy:
    def __init__(self, fail_restore=False):
        self.original = {'ProxyEnable': [0, 4], 'ProxyServer': None}
        self.current = self.original.copy()
        self.fail_restore = fail_restore

    def snapshot(self):
        return self.current.copy()

    def enable(self, address):
        self.current = {'ProxyEnable': [1, 4], 'ProxyServer': [address, 1]}

    def restore(self, values):
        if self.fail_restore:
            raise OSError('simulated registry failure')
        self.current = values


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def check_exit(mode):
    with TemporaryDirectory() as directory:
        port = free_port()
        settings = replace(Settings(), runtime_dir=Path(directory), proxy_port=port)
        proxy = MemoryProxy(fail_restore=mode == 'restore-error')
        recovery = Path(directory) / 'recovery.json'
        expected = {'normal': None, 'ctrl-c': KeyboardInterrupt, 'error': RuntimeError, 'restore-error': OSError}[mode]
        caught = None
        try:
            with cleanup_safe_interrupts(), start_capture(settings) as capture:
                with managed_proxy(f'127.0.0.1:{port}', recovery, proxy):
                    if mode == 'ctrl-c':
                        signal.raise_signal(signal.SIGINT)
                    if mode == 'error':
                        raise RuntimeError('simulated task error')
        except BaseException as exc:
            caught = type(exc)
        assert caught is expected, (mode, caught)
        assert capture.process.poll() is not None
        assert not port_in_use(port), mode
        assert recovery.exists() == (mode == 'restore-error')
        if mode != 'restore-error':
            assert proxy.current == proxy.original
        print('PASS:', mode, 'process tree stopped; proxy restored or recovery retained')


def check_orphan_child():
    port = free_port()
    child = f"import socket,time; s=socket.socket(); s.bind(('127.0.0.1',{port})); s.listen(); time.sleep(60)"
    parent = f"import subprocess,sys; subprocess.Popen([sys.executable,'-c',{child!r}], creationflags=subprocess.CREATE_NO_WINDOW)"
    with open(os.devnull, 'wb') as output:
        tree = ProcessTree([sys.executable, '-c', parent], env=dict(os.environ), output=output)
        try:
            deadline = time.monotonic() + 10
            while (tree.poll() is None or not port_in_use(port)) and time.monotonic() < deadline:
                time.sleep(0.1)
            assert tree.poll() is not None, 'parent must have exited'
            assert port_in_use(port), 'child must still be running before cleanup'
        finally:
            tree.close()
        # Windows TCP 清理可能稍晚于 Job 的 ActiveProcesses 归零。
        deadline = time.monotonic() + 5
        while port_in_use(port) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not port_in_use(port), 'job must stop children even after parent exits'
    print('PASS: parent already exited; remaining child stopped by Job Object')


if __name__ == '__main__':
    for case in ('normal', 'ctrl-c', 'error', 'restore-error'):
        check_exit(case)
    check_orphan_child()
