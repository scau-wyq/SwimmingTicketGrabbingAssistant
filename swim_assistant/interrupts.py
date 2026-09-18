"""第一次 Ctrl+C 取消任务，后续 Ctrl+C 不再打断资源回收。"""

from contextlib import contextmanager
import signal


@contextmanager
def cleanup_safe_interrupts():
    previous = signal.getsignal(signal.SIGINT)

    def cancel(signum, frame):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, cancel)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)


@contextmanager
def uninterrupted_cleanup():
    """正常结束或异常退出的清理也不能被新的 Ctrl+C 截断。"""
    previous = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)
