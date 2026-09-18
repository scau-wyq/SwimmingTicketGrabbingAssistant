"""固定一次运行的放票时刻，避免登录耗时导致跨零点顺延。"""

from dataclasses import dataclass
from datetime import datetime, timedelta
import time


@dataclass(frozen=True)
class RunTarget:
    release_at: datetime
    date_str: str
    weekday: int

    @classmethod
    def create(cls, now: datetime, date_override: str | None = None):
        release = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        date = datetime.strptime(date_override, '%Y%m%d') if date_override else release
        return cls(release, date.strftime('%Y%m%d'), date.weekday())

    def require_preparation_time(self, now: datetime) -> None:
        if now >= self.release_at:
            raise TimeoutError('本次放票时间已过，终止本次任务；不会自动顺延到下一天')


def wait_until(target: datetime) -> None:
    """使用短睡眠等待本地系统时钟；不采用 HTTP Date 的秒级时间校准。"""
    while (remaining := (target - datetime.now()).total_seconds()) > 0:
        time.sleep(min(remaining, 0.05 if remaining < 1 else 1))
