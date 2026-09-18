"""仅管理本程序启动的 mitmdump，并等待本次运行的 token。"""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import logging
import time
import uuid

from .config import Settings
from .interrupts import uninterrupted_cleanup
from .process_tree import ProcessTree

log = logging.getLogger(__name__)


def port_in_use(port: int) -> bool:
    with socket.socket() as connection:
        connection.settimeout(0.3)
        return connection.connect_ex(('127.0.0.1', port)) == 0


def read_captured_token(path: Path, run_id: str) -> str | None:
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
        if record.get('run_id') == run_id and isinstance(record.get('token'), str):
            return record['token'] or None
    except (OSError, ValueError, AttributeError):
        pass
    return None


class Capture:
    def __init__(self, process, path: Path, run_id: str):
        self.process, self.path, self.run_id = process, path, run_id

    def wait(self, deadline: float) -> str:
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError('mitmdump 提前退出，请检查 runtime/mitmdump.log')
            token = read_captured_token(self.path, self.run_id)
            if token:
                return token
            time.sleep(0.2)
        raise TimeoutError('未在准备期限内获取 token；请确认小程序重新触发登录和证书信任')


@contextmanager
def start_capture(settings: Settings):
    if port_in_use(settings.proxy_port):
        raise RuntimeError(f'端口 {settings.proxy_port} 已被占用；不会终止其他进程')
    if not settings.mitmdump.is_file():
        raise FileNotFoundError(f'找不到 mitmdump: {settings.mitmdump}')
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    path = settings.runtime_dir / f'capture-{run_id}.json'
    environment = dict(os.environ, SWIM_CAPTURE_FILE=str(path), SWIM_RUN_ID=run_id)
    command = [str(settings.mitmdump), '--listen-host', '127.0.0.1', '--listen-port', str(settings.proxy_port),
               '--set', 'flow_detail=0', '--set', 'termlog_verbosity=error',
               '-s', str(Path(__file__).with_name('token_addon.py'))]
    with (settings.runtime_dir / 'mitmdump.log').open('ab') as output:
        process = None
        try:
            process = ProcessTree(command, env=environment, output=output)
            ready_deadline = time.monotonic() + 15
            while True:
                if process.poll() is not None:
                    raise RuntimeError('mitmdump 启动失败，请检查 runtime/mitmdump.log')
                if port_in_use(settings.proxy_port):
                    break
                if time.monotonic() >= ready_deadline:
                    raise TimeoutError('mitmdump 未在 15 秒内就绪')
                time.sleep(0.2)
            yield Capture(process, path, run_id)
        finally:
            with uninterrupted_cleanup():
                try:
                    if process is not None:
                        process.close()
                        release_deadline = time.monotonic() + 5
                        while port_in_use(settings.proxy_port) and time.monotonic() < release_deadline:
                            time.sleep(0.1)
                        if port_in_use(settings.proxy_port):
                            raise RuntimeError('抓包进程树已停止，但端口仍被占用，请检查其他进程')
                        log.info('mitmproxy 进程树已停止，端口 %d 已释放', settings.proxy_port)
                finally:
                    path.unlink(missing_ok=True)
                    path.with_suffix('.tmp').unlink(missing_ok=True)
