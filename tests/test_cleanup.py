import importlib.util
import signal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from swim_assistant.proxy import managed_proxy


class CleanupTests(unittest.TestCase):
    def test_previous_proxy_to_this_capture_port_is_disabled_on_exit(self):
        backend = Mock()
        backend.snapshot.return_value = {'ProxyEnable': [1, 4], 'ProxyServer': ['127.0.0.1:8080', 1]}
        with TemporaryDirectory() as directory:
            with managed_proxy('127.0.0.1:8080', Path(directory) / 'proxy.json', backend):
                pass
        self.assertEqual(backend.restore.call_args.args[0]['ProxyEnable'], [0, 4])

    def test_ctrl_c_restores_original_proxy(self):
        backend = Mock()
        backend.snapshot.return_value = {'ProxyEnable': [0, 4], 'ProxyServer': None}
        with TemporaryDirectory() as directory:
            recovery = Path(directory) / 'proxy.json'
            with self.assertRaises(KeyboardInterrupt):
                with managed_proxy('127.0.0.1:8080', recovery, backend):
                    raise KeyboardInterrupt()
            backend.restore.assert_called_once_with(backend.snapshot.return_value)
            self.assertFalse(recovery.exists())

    def test_second_ctrl_c_does_not_interrupt_cleanup(self):
        self.assertIsNotNone(importlib.util.find_spec('swim_assistant.interrupts'))
        from swim_assistant.interrupts import cleanup_safe_interrupts
        previous = signal.getsignal(signal.SIGINT)
        cleaned = []
        with self.assertRaises(KeyboardInterrupt):
            with cleanup_safe_interrupts():
                try:
                    signal.raise_signal(signal.SIGINT)
                finally:
                    signal.raise_signal(signal.SIGINT)
                    cleaned.append(True)
        self.assertEqual(cleaned, [True])
        self.assertEqual(signal.getsignal(signal.SIGINT), previous)

    def test_capture_tree_closed_even_when_body_interrupts(self):
        from swim_assistant import capture
        self.assertTrue(hasattr(capture, 'ProcessTree'))
        process = Mock()
        process.poll.return_value = None
        with TemporaryDirectory() as directory:
            from swim_assistant.config import Settings
            executable = Path(directory) / 'mitmdump.exe'
            executable.touch()
            settings = Settings(runtime_dir=Path(directory), mitmdump=executable)
            with patch.object(capture, 'ProcessTree', return_value=process), patch.object(capture, 'port_in_use', side_effect=[False, True, False, False]):
                with self.assertRaises(KeyboardInterrupt):
                    with capture.start_capture(settings):
                        raise KeyboardInterrupt()
            process.close.assert_called_once()
