"""异常边界回归：不连接业务服务、不改变系统代理。"""
from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from swim_assistant.api import ApiClient
from swim_assistant.config import Settings
from swim_assistant.proxy import managed_proxy
from swim_assistant.runner import acquire_token, run
from swim_assistant.timing import RunTarget
from swim_assistant import token_addon


class SafetyTests(unittest.TestCase):
    def test_unknown_order_response_is_not_retryable(self):
        from swim_assistant import runner
        self.assertTrue(hasattr(runner, 'submit_orders'))
        client = Mock()
        client.send_order.return_value = {}
        with self.assertRaises(RuntimeError):
            runner.submit_orders(Settings(), client, 25288, '20260919')
        client.send_order.assert_called_once()

    def test_state_directory_is_shared_between_runtime_configurations(self):
        first = Settings(runtime_dir=Path('a'))
        second = Settings(runtime_dir=Path('b'))
        self.assertIsNotNone(getattr(first, 'state_dir', None))
        self.assertEqual(first.state_dir, second.state_dir)

    def test_missed_scheduled_start_does_not_capture(self):
        with TemporaryDirectory() as directory, patch('swim_assistant.runner.acquire_token') as capture:
            with patch('swim_assistant.runner.datetime') as clock:
                clock.now.return_value = datetime(2026, 9, 19, 0, 1)
                with self.assertRaises(TimeoutError):
                    run(Settings(runtime_dir=Path(directory), state_dir=Path(directory) / 'state'), scheduled=True)
            capture.assert_not_called()

    def test_proxy_enable_failure_restores_original_settings(self):
        backend = Mock()
        backend.snapshot.return_value = {'ProxyServer': ['old:7890', 1]}
        backend.enable.side_effect = OSError('notification failed')
        with TemporaryDirectory() as directory:
            with self.assertRaises(OSError):
                with managed_proxy('127.0.0.1:8080', Path(directory) / 'recovery.json', backend):
                    self.fail('不能进入采集流程')
        backend.restore.assert_called_once_with({'ProxyServer': ['old:7890', 1]})

    def test_failed_restore_keeps_recovery_file(self):
        backend = Mock()
        backend.snapshot.return_value = {'ProxyEnable': [0, 4]}
        backend.restore.side_effect = OSError('registry unavailable')
        with TemporaryDirectory() as directory:
            recovery = Path(directory) / 'recovery.json'
            with self.assertRaises(OSError):
                with managed_proxy('127.0.0.1:8080', recovery, backend):
                    pass
            self.assertEqual(json.loads(recovery.read_text()), {'ProxyEnable': [0, 4]})

    def test_ui_failure_restores_proxy_before_stopping_capture(self):
        events = []
        @contextmanager
        def capture(_):
            events.append('capture-start')
            try:
                yield Mock()
            finally:
                events.append('capture-stop')
        @contextmanager
        def proxy(*_):
            events.append('proxy-on')
            try:
                yield
            finally:
                events.append('proxy-restore')
        with patch('swim_assistant.runner.start_capture', capture), patch('swim_assistant.runner.managed_proxy', proxy), patch('swim_assistant.runner.validate_entry'), patch('swim_assistant.runner.open_miniprogram', side_effect=RuntimeError('UI failed')):
            with self.assertRaises(RuntimeError):
                acquire_token(Settings(), RunTarget.create(datetime.now()), False, True)
        self.assertEqual(events, ['capture-start', 'proxy-on', 'proxy-restore', 'capture-stop'])

    def test_readonly_validation_requires_explicit_success(self):
        client = ApiClient(Settings(), 'fake')
        try:
            for result in ({'code': 403}, {'code': 500}, {}, {'code': -1}):
                with patch.object(client, '_post', return_value=result):
                    self.assertFalse(client.validate_token())
            with patch.object(client, '_post', return_value={'code': 200}):
                self.assertTrue(client.validate_token())
        finally:
            client.close()

    def test_addon_only_writes_expected_login_response(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / 'capture.json'
            environment = {'SWIM_CAPTURE_FILE': str(output), 'SWIM_RUN_ID': 'this-run'}
            flow = SimpleNamespace(request=SimpleNamespace(host='unrelated.example', path='/member/wxMember/exToken'), response=Mock())
            flow.response.json.return_value = {'data': {'token': 'eyJ.fake.signature'}}
            with patch.dict('os.environ', environment):
                token_addon.response(flow)
                self.assertFalse(output.exists())
                flow.request.host = 'api.wesais.com'
                token_addon.response(flow)
            self.assertEqual(json.loads(output.read_text())['run_id'], 'this-run')
            self.assertFalse(output.with_suffix('.tmp').exists())


if __name__ == '__main__':
    unittest.main()
