"""单独测试微信入口必须与代理、抓包、下单流程隔离。"""
import unittest
import importlib.util
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from swim_assistant import cli
from swim_assistant.config import Settings


def stalled_worker(settings, deadline, connection):
    time.sleep(60)


def successful_worker(settings, deadline, connection):
    connection.send(('ok', ''))
    connection.close()


class WechatOnlyTests(unittest.TestCase):
    def test_worker_timeout_is_enforced_outside_ui_calls(self):
        self.assertIsNotNone(importlib.util.find_spec('swim_assistant.ui_worker'))
        from swim_assistant.ui_worker import run_ui_task
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            run_ui_task(Settings(), started + 0.5, worker=stalled_worker)
        self.assertLess(time.monotonic() - started, 5)

    def test_worker_reports_success(self):
        self.assertIsNotNone(importlib.util.find_spec('swim_assistant.ui_worker'))
        from swim_assistant.ui_worker import run_ui_task
        run_ui_task(Settings(), time.monotonic() + 10, worker=successful_worker)

    def test_wechat_only_skips_booking_and_proxy_recovery(self):
        with TemporaryDirectory() as directory:
            settings = Settings(runtime_dir=Path(directory), state_dir=Path(directory) / 'state')
            with patch.object(cli, 'load_settings', return_value=settings), patch.object(cli, 'configure_logging'), patch.object(cli, 'run') as booking, patch.object(cli, 'restore_pending') as restore, patch('swim_assistant.wechat.open_miniprogram') as launch:
                try:
                    result = cli.main(['--wechat-only'])
                except SystemExit as exc:
                    self.fail(f'需要独立微信测试命令，当前退出码 {exc.code}')
                self.assertEqual(result, 0)
                launch.assert_called_once()
                booking.assert_not_called()
                restore.assert_not_called()
