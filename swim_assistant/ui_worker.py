"""隔离可能阻塞的 UIA 调用；父进程始终能够超时并恢复代理。"""

import logging
from logging.handlers import RotatingFileHandler
import multiprocessing
import sys
import time

from .config import Settings


def _worker(settings: Settings, deadline: float, connection) -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    try:
        settings.runtime_dir.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s',
                            handlers=[logging.StreamHandler(), RotatingFileHandler(
                                settings.runtime_dir / 'wechat.log', maxBytes=1_000_000,
                                backupCount=2, encoding='utf-8')], force=True)
        from .wechat import _open_miniprogram
        _open_miniprogram(settings, deadline)
        connection.send(('ok', ''))
    except Exception as exc:
        logging.exception('微信操作失败')
        connection.send((type(exc).__name__, str(exc)[:2000]))
    finally:
        connection.close()


def run_ui_task(settings: Settings, deadline: float, *, worker=None) -> None:
    """deadline 是全流程共享的 monotonic 截止时间，不会重置 token 等待期限。"""
    if time.monotonic() >= deadline:
        raise TimeoutError('微信操作已超过准备期限')
    context = multiprocessing.get_context('spawn')
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=worker or _worker, args=(settings, deadline, sender),
                              name='wechat-ui-worker')
    started = False
    try:
        process.start()
        started = True
        sender.close()
        process.join(max(0, deadline - time.monotonic()))
        if process.is_alive():
            raise TimeoutError('微信操作超时；已停止 UI 工作进程，请查看 runtime/wechat.log 的最后一步')
        if process.exitcode != 0 or not receiver.poll():
            raise RuntimeError(f'微信操作进程意外退出 (exit={process.exitcode})')
        try:
            status, message = receiver.recv()
        except EOFError as exc:
            raise RuntimeError('微信操作进程未返回结果') from exc
        if status == 'TimeoutError':
            raise TimeoutError(message)
        if status != 'ok':
            raise RuntimeError(f'微信操作失败 ({status}): {message}')
    finally:
        if started and process.is_alive():
            process.terminate()
            process.join(2)
            if process.is_alive():
                process.kill()
                process.join(2)
        receiver.close()
        sender.close()
        if started and not process.is_alive():
            process.close()
