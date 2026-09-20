"""用可控时钟测试全天等待；不启动微信、代理或真实预约请求。"""
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from swim_assistant.config import Settings
from swim_assistant.runner import run


class PreparationScheduleTests(unittest.TestCase):
    def test_daytime_run_waits_until_2358_then_orders_at_midnight(self):
        current = [datetime(2026, 9, 20, 12)]
        events = []
        def wait(target):
            events.append(('wait', target))
            current[0] = target
        def capture(*args):
            events.append(('capture', current[0]))
            return 'fake-token'
        client = Mock()
        client.validate_token.return_value = True
        client.verify_product.return_value = 25294
        def order(*args):
            events.append(('order', current[0]))
            return {'code': 200}
        client.send_order.side_effect = order
        with TemporaryDirectory() as directory:
            settings = Settings(runtime_dir=Path(directory), state_dir=Path(directory) / 'state')
            with patch('swim_assistant.runner.datetime') as clock, patch('swim_assistant.runner.wait_until', side_effect=wait), patch('swim_assistant.runner.acquire_token', side_effect=capture), patch('swim_assistant.runner.ApiClient', return_value=client):
                clock.now.side_effect = lambda: current[0]
                self.assertEqual(run(settings), 0)
        self.assertEqual(events[0], ('wait', datetime(2026, 9, 20, 23, 58)))
        self.assertEqual(events[1], ('capture', datetime(2026, 9, 20, 23, 58)))
        self.assertEqual(events[-1], ('order', datetime(2026, 9, 21)))

    def test_cancel_while_waiting_never_starts_preparation(self):
        with TemporaryDirectory() as directory:
            settings = Settings(runtime_dir=Path(directory), state_dir=Path(directory) / 'state')
            with patch('swim_assistant.runner.datetime') as clock, patch('swim_assistant.runner.wait_until', side_effect=KeyboardInterrupt), patch('swim_assistant.runner.acquire_token') as capture, patch('swim_assistant.runner.ApiClient'):
                clock.now.return_value = datetime(2026, 9, 20, 12)
                with self.assertRaises(KeyboardInterrupt):
                    run(settings)
                capture.assert_not_called()

    def test_wake_after_midnight_does_not_start_capture(self):
        with TemporaryDirectory() as directory:
            settings = Settings(runtime_dir=Path(directory), state_dir=Path(directory) / 'state')
            with patch('swim_assistant.runner.datetime') as clock, patch('swim_assistant.runner.wait_until'), patch('swim_assistant.runner.acquire_token') as capture, patch('swim_assistant.runner.ApiClient'):
                clock.now.side_effect = [datetime(2026, 9, 20, 12), datetime(2026, 9, 21, 0, 1)]
                with self.assertRaises(TimeoutError):
                    run(settings)
                capture.assert_not_called()

    def test_test_mode_and_late_start_do_not_wait_for_preparation(self):
        for test_only, start in ((True, datetime(2026, 9, 20, 12)), (False, datetime(2026, 9, 20, 23, 59))):
            with self.subTest(test_only=test_only), TemporaryDirectory() as directory:
                settings = Settings(runtime_dir=Path(directory), state_dir=Path(directory) / 'state')
                client = Mock()
                client.validate_token.return_value = False
                with patch('swim_assistant.runner.datetime') as clock, patch('swim_assistant.runner.wait_until') as wait, patch('swim_assistant.runner.acquire_token', return_value='fake'), patch('swim_assistant.runner.ApiClient', return_value=client):
                    clock.now.return_value = start
                    with self.assertRaises(RuntimeError):
                        run(settings, test_only=test_only)
                    wait.assert_not_called()
