"""使用模拟时钟和窗口验证恢复流程，不操作桌面或网络。"""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from swim_assistant import wechat
from swim_assistant.config import Settings


class PanelRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.clock = patch.object(wechat.time, 'monotonic', side_effect=lambda: self.now)
        self.sleep = patch.object(wechat.time, 'sleep', side_effect=self.advance)
        self.clock.start()
        self.sleep.start()
        self.addCleanup(self.clock.stop)
        self.addCleanup(self.sleep.stop)
        self.panel = Mock(handle=42)
        self.panel.is_minimized.return_value = False
        self.entry = Mock()
        self.entry.window_text.return_value = '奥冠体育'
        self.entry.is_visible.return_value = True

    def advance(self, seconds):
        self.now += seconds

    def test_transient_blank_is_allowed_and_wrapper_is_refreshed(self):
        blank, ready = Mock(), Mock()
        blank.descendants.return_value = []
        ready.descendants.return_value = [self.entry]
        wrap = Mock(side_effect=[blank, ready])
        find = Mock(return_value=self.panel)
        self.assertIs(wechat._wait_panel_entry(find, wrap, '奥冠体育', 12), self.entry)
        self.assertEqual(wrap.call_count, 2)
        self.panel.close.assert_not_called()

    def test_disappearing_window_and_uia_error_can_recover(self):
        ready = Mock()
        ready.descendants.return_value = [self.entry]
        find = Mock(side_effect=[None, self.panel, self.panel])
        wrap = Mock(side_effect=[OSError('stale'), ready])
        self.assertIs(wechat._wait_panel_entry(find, wrap, '奥冠体育', 12), self.entry)

    def test_hidden_entry_is_not_clicked_and_deadline_is_respected(self):
        self.entry.is_visible.return_value = False
        wrapper = Mock()
        wrapper.descendants.return_value = [self.entry]
        self.assertIsNone(wechat._wait_panel_entry(lambda: self.panel, lambda _: wrapper,
                                                 '奥冠体育', 1))
        self.assertAlmostEqual(self.now, 1)
        self.entry.click_input.assert_not_called()

    def test_ambiguous_window_error_is_not_swallowed(self):
        with self.assertRaises(RuntimeError):
            wechat._wait_panel_entry(Mock(side_effect=RuntimeError('ambiguous')), Mock(), '', 12)

    def run_recovery(self, results, deadline=100, close_works=True):
        present = [True]
        main, target = Mock(), Mock()
        def close():
            if close_works:
                present[0] = False
        self.panel.close.side_effect = close
        main.click_input.side_effect = lambda **kw: present.__setitem__(0, True)
        launched = [False]
        self.entry.click_input.side_effect = lambda: launched.__setitem__(0, True)
        def select(windows, title, exe, lookup):
            if title == '奥冠体育':
                return target if launched[0] else None
            if exe == 'WeChatAppEx.exe':
                return self.panel if present[0] else None
            return main
        def wait(*args):
            result = next(results)
            if result is None:
                self.now = args[-1]
            return result
        modules = {'pywinauto': SimpleNamespace(Desktop=Mock()),
                   'pywinauto.application': SimpleNamespace(process_module=Mock())}
        bounds = SimpleNamespace(left=0, top=0, right=1060, bottom=778)
        with patch.dict('sys.modules', modules), patch.object(wechat, 'select_window', side_effect=select), \
                patch.object(wechat, '_wait_panel_entry', side_effect=wait), \
                patch.object(wechat, 'ensure_main_window_size', return_value=bounds), \
                patch.object(wechat.os, 'startfile', create=True):
            wechat._open_from_panel(Settings(), deadline)

    def test_blank_panel_is_reopened_then_entry_clicked_once(self):
        self.run_recovery(iter([None, self.entry]))
        self.panel.close.assert_called_once()
        self.entry.click_input.assert_called_once()

    def test_persistent_blank_stops_after_two_reopens(self):
        with self.assertRaises(TimeoutError):
            self.run_recovery(iter([None, None, None]))
        self.assertEqual(self.panel.close.call_count, 2)
        self.entry.click_input.assert_not_called()

    def test_global_deadline_prevents_reopening(self):
        with self.assertRaises(TimeoutError):
            self.run_recovery(iter([None]), deadline=1)
        self.panel.close.assert_not_called()

    def test_panel_that_will_not_close_aborts_recovery(self):
        with self.assertRaisesRegex(TimeoutError, '未关闭'):
            self.run_recovery(iter([None]), close_works=False)
        self.panel.close.assert_called_once()
        self.entry.click_input.assert_not_called()
