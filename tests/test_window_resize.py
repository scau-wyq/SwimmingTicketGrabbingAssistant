"""模拟窗口尺寸变化，不操作真实微信。"""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from swim_assistant.wechat import ensure_main_window_size


def rect(left, top, width, height):
    return SimpleNamespace(left=left, top=top, right=left + width, bottom=top + height)


class WindowResizeTests(unittest.TestCase):
    def make_window(self, width, height, left=100, top=50):
        window = Mock()
        window.is_minimized.return_value = False
        window.is_maximized.return_value = False
        current = [rect(left, top, width, height)]
        window.rectangle.side_effect = lambda: rect(current[0].left - 7, current[0].top,
                                                   current[0].right - current[0].left + 14,
                                                   current[0].bottom - current[0].top + 7)
        def resize(*, x, y, width, height, repaint):
            current[0] = rect(x + 7, y, width - 14, height - 7)
        window.move_window.side_effect = resize
        return window, current

    def adjust(self, window, current, area=(0, 0, 1920, 1040), deadline=float('inf')):
        with patch('swim_assistant.wechat.visible_window_bounds', side_effect=lambda _: current[0]), patch('swim_assistant.wechat.window_work_area', return_value=area), patch('swim_assistant.wechat.time.sleep'):
            return ensure_main_window_size(window, (1060, 778), deadline)

    def test_resize_large_and_small_windows_with_invisible_borders(self):
        for width, height in ((800, 600), (1500, 950)):
            with self.subTest(width=width):
                window, current = self.make_window(width, height)
                result = self.adjust(window, current)
                self.assertEqual((result.right - result.left, result.bottom - result.top), (1060, 778))
                window.move_window.assert_called_once_with(x=93, y=50, width=1074, height=785, repaint=True)

    def test_maximized_window_is_restored_before_resizing(self):
        window, current = self.make_window(1500, 950)
        window.is_maximized.return_value = True
        self.adjust(window, current)
        self.assertEqual(window.method_calls[2][0], 'restore')
        window.restore.assert_called_once()

    def test_matching_size_is_unchanged(self):
        window, current = self.make_window(1059, 777)
        self.adjust(window, current)
        window.move_window.assert_not_called()

    def test_offscreen_position_is_clamped_on_negative_coordinate_monitor(self):
        window, current = self.make_window(1200, 800, left=-2500, top=-80)
        result = self.adjust(window, current, area=(-1920, 0, 0, 1040))
        self.assertEqual((result.left, result.top), (-1920, 0))

    def test_resize_refusal_is_bounded_and_never_clicks(self):
        window, current = self.make_window(800, 600)
        window.move_window.side_effect = None
        with self.assertRaises(RuntimeError):
            self.adjust(window, current)
        self.assertEqual(window.move_window.call_count, 3)
        window.click_input.assert_not_called()

    def test_small_monitor_fails_before_move_or_click(self):
        window, current = self.make_window(800, 600)
        with self.assertRaises(RuntimeError):
            self.adjust(window, current, area=(0, 0, 800, 600))
        window.move_window.assert_not_called()
        window.click_input.assert_not_called()

    def test_expired_deadline_does_not_resize(self):
        window, current = self.make_window(800, 600)
        with self.assertRaises(TimeoutError):
            self.adjust(window, current, deadline=0)
        window.move_window.assert_not_called()
