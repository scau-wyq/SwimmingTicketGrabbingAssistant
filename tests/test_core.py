import importlib.util
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('swim_assistant'), '需要模块化应用包')

    def test_target_stays_fixed_after_midnight(self):
        from swim_assistant.timing import RunTarget
        target = RunTarget.create(datetime(2026, 9, 18, 23, 58))
        self.assertEqual(target.release_at, datetime(2026, 9, 19))
        with self.assertRaises(TimeoutError):
            target.require_preparation_time(datetime(2026, 9, 19, 0, 1))
        self.assertEqual(target.release_at, datetime(2026, 9, 19))

    def test_date_override_controls_product_weekday(self):
        from swim_assistant.timing import RunTarget
        target = RunTarget.create(datetime(2026, 9, 18, 23, 58), '20260921')
        self.assertEqual(target.weekday, 0)
        self.assertEqual(target.release_at, datetime(2026, 9, 19))

    def test_test_mode_never_places_order(self):
        from swim_assistant.runner import run
        from swim_assistant.config import Settings
        with TemporaryDirectory() as directory:
            settings = Settings(runtime_dir=Path(directory), state_dir=Path(directory) / 'state')
            client = Mock()
            client.validate_token.return_value = True
            with patch('swim_assistant.runner.acquire_token', return_value='secret'), patch('swim_assistant.runner.ApiClient', return_value=client):
                self.assertEqual(run(settings, test_only=True), 0)
            client.send_order.assert_not_called()

    def test_failed_validation_never_places_order(self):
        from swim_assistant.runner import run
        from swim_assistant.config import Settings
        with TemporaryDirectory() as directory:
            client = Mock()
            client.validate_token.return_value = False
            with patch('swim_assistant.runner.acquire_token', return_value='secret'), patch('swim_assistant.runner.ApiClient', return_value=client):
                with self.assertRaises(RuntimeError):
                    run(Settings(runtime_dir=Path(directory), state_dir=Path(directory) / 'state'))
            client.send_order.assert_not_called()

    def test_proxy_restores_after_failure(self):
        from swim_assistant.proxy import managed_proxy
        backend = Mock()
        backend.snapshot.return_value = {'ProxyEnable': [0, 4]}
        with TemporaryDirectory() as directory:
            recovery = Path(directory) / 'proxy.json'
            with self.assertRaises(RuntimeError):
                with managed_proxy('127.0.0.1:8080', recovery, backend):
                    raise RuntimeError('login failed')
            backend.restore.assert_called_once_with({'ProxyEnable': [0, 4]})
            self.assertFalse(recovery.exists())

    def test_capture_rejects_previous_run(self):
        from swim_assistant.capture import read_captured_token
        import json
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'capture.json'
            path.write_text(json.dumps({'run_id': 'old', 'token': 'secret'}))
            self.assertIsNone(read_captured_token(path, 'current'))
            path.write_text(json.dumps({'run_id': 'current', 'token': 'secret'}))
            self.assertEqual(read_captured_token(path, 'current'), 'secret')


if __name__ == '__main__':
    unittest.main()
