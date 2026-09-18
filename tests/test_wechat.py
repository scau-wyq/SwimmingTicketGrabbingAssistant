"""窗口选择只使用假对象，不触碰真实桌面。"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from swim_assistant.config import Settings, load_settings
from swim_assistant import wechat


class WechatTests(unittest.TestCase):
    def test_top_level_enumeration_uses_native_windows_not_desktop_uia(self):
        desktop = Mock()
        desktop.return_value.windows.side_effect = RuntimeError('stop after backend selection')
        with patch.dict('sys.modules', {'pywinauto': SimpleNamespace(Desktop=desktop),
                                       'pywinauto.application': SimpleNamespace(process_module=Mock())}):
            with self.assertRaises(RuntimeError):
                wechat._open_from_panel(Settings(), float('inf'))
        desktop.assert_called_once_with(backend='win32')

    def test_select_window_distinguishes_same_title_processes(self):
        main, panel = Mock(), Mock()
        for window, pid in ((main, 1), (panel, 2)):
            window.window_text.return_value = '微信'
            window.process_id.return_value = pid
        lookup = lambda pid: {1: r'C:\Tencent\Weixin.exe', 2: r'C:\Plugin\WeChatAppEx.exe'}[pid]
        self.assertTrue(hasattr(wechat, 'select_window'), '需要按进程区分微信和面板')
        self.assertIs(wechat.select_window([main, panel], '微信', 'WeChatAppEx.exe', lookup), panel)

    def test_ambiguous_window_fails_before_click(self):
        self.assertTrue(hasattr(wechat, 'select_window'))
        window = Mock()
        window.window_text.return_value = '微信'
        with self.assertRaises(RuntimeError):
            wechat.select_window([window, window], '微信', 'Weixin.exe', lambda _: 'Weixin.exe')
        window.click_input.assert_not_called()

    def test_changed_layout_rejects_coordinate_click(self):
        self.assertTrue(hasattr(wechat, 'panel_button_coordinates'))
        with self.assertRaises(RuntimeError):
            wechat.panel_button_coordinates(1600, 900, (1060, 778), (31, 430))
        self.assertEqual(wechat.panel_button_coordinates(1060, 778, (1060, 778), (31, 430)), (31, 430))

    def test_panel_mode_does_not_require_shortcut(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            path.write_text('[wechat]\nmode = "panel"\nexecutable = "Weixin.exe"\n', encoding='utf-8')
            settings = load_settings(path)
            self.assertEqual(getattr(settings, 'wechat_mode', None), 'panel')
            self.assertEqual(settings.wechat_executable, Path(directory) / 'Weixin.exe')


if __name__ == '__main__':
    unittest.main()
