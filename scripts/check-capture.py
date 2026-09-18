"""手动集成检查：仅启停临时端口，不改代理、不打开微信、不下单。

运行 python scripts/check-capture.py；与离线 unittest 分开。
"""
from dataclasses import replace
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from swim_assistant.capture import port_in_use, start_capture
from swim_assistant.config import Settings


def main():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    with TemporaryDirectory() as directory:
        settings = replace(Settings(), runtime_dir=Path(directory), proxy_port=port)
        with start_capture(settings) as capture:
            assert capture.process.poll() is None
            assert port_in_use(port)
        assert capture.process.poll() is not None
        assert not port_in_use(port), 'mitmdump 退出后端口必须释放'
    print('PASS: mitmdump/addon startup, process cleanup, port release')


if __name__ == '__main__':
    main()
