"""加载非敏感 TOML 配置；相对路径统一相对于配置文件。"""

from dataclasses import dataclass, field
from pathlib import Path
import os
import sys
import tomllib

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PRODUCTS = {0: 25294, 1: 25293, 2: 25292, 3: 25291, 4: 25289, 5: 25288, 6: 25287}


@dataclass(frozen=True)
class Settings:
    state_dir: Path = field(default_factory=lambda: Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local' / 'state'))) / 'SwimmingTicketAssistant')
    runtime_dir: Path = ROOT / 'runtime'
    mitmdump: Path = Path(sys.executable).parent / 'Scripts' / 'mitmdump.exe'
    proxy_port: int = 8080
    token_timeout: float = 90
    shortcut: str = ''
    wechat_mode: str = 'panel'
    wechat_executable: Path = Path('C:/Program Files/Tencent/Weixin/Weixin.exe')
    miniprogram_name: str = '奥冠体育'
    main_size: tuple[int, int] = (1060, 778)
    panel_button: tuple[int, int] = (31, 430)
    steps: list[dict] = field(default_factory=list)
    api_base: str = 'https://api.wesais.com'
    business_id: str = '10000863'
    stadium_id: str = '11617'
    products: dict[int, int] = field(default_factory=lambda: DEFAULT_PRODUCTS.copy())
    burst_count: int = 30
    burst_interval: float = 0.1
    request_timeout: float = 3
    prewarm_seconds: float = 10


def load_settings(path: Path) -> Settings:
    path = path.resolve()
    with path.open('rb') as stream:
        data = tomllib.load(stream)
    unknown = data.keys() - {'runtime', 'capture', 'wechat', 'booking'}
    if unknown:
        raise ValueError(f'未知配置分组: {sorted(unknown)}')
    runtime = data.get('runtime', {})
    capture = data.get('capture', {})
    wechat = data.get('wechat', {})
    booking = data.get('booking', {})

    def resolve(value: str) -> Path:
        candidate = Path(value).expanduser()
        return candidate.resolve() if candidate.is_absolute() else (path.parent / candidate).resolve()

    defaults = Settings()
    settings = Settings(
        runtime_dir=resolve(runtime.get('directory', 'runtime')),
        mitmdump=resolve(capture['mitmdump']) if capture.get('mitmdump') else defaults.mitmdump,
        proxy_port=int(capture.get('port', 8080)),
        token_timeout=float(capture.get('timeout_seconds', 90)),
        shortcut=str(resolve(wechat['shortcut'])) if wechat.get('shortcut') else '',
        wechat_mode=wechat.get('mode', 'panel'),
        wechat_executable=resolve(wechat['executable']) if wechat.get('executable') else defaults.wechat_executable,
        miniprogram_name=wechat.get('miniprogram_name', '奥冠体育'),
        main_size=tuple(wechat.get('main_size', [1060, 778])),
        panel_button=tuple(wechat.get('panel_button', [31, 430])),
        steps=wechat.get('steps', []),
        api_base=booking.get('api_base', defaults.api_base).rstrip('/'),
        business_id=str(booking.get('business_id', defaults.business_id)),
        stadium_id=str(booking.get('stadium_id', defaults.stadium_id)),
        products={int(k): int(v) for k, v in booking.get('products', defaults.products).items()},
        burst_count=int(booking.get('attempts', 30)),
        burst_interval=float(booking.get('interval_seconds', 0.1)),
        request_timeout=float(booking.get('request_timeout_seconds', 3)),
        prewarm_seconds=float(booking.get('prewarm_seconds', 10)),
    )
    if not 1 <= settings.proxy_port <= 65535:
        raise ValueError('代理端口必须在 1..65535 之间')
    if set(settings.products) != set(range(7)):
        raise ValueError('products 必须包含星期 0..6')
    if not 1 <= settings.burst_count <= 30:
        raise ValueError('attempts 必须在 1..30 之间')
    if settings.burst_interval < 0.1:
        raise ValueError('interval_seconds 不能小于 0.1')
    if min(settings.token_timeout, settings.request_timeout, settings.prewarm_seconds) <= 0:
        raise ValueError('超时和预热秒数必须为正数')
    if settings.wechat_mode not in ('panel', 'shortcut'):
        raise ValueError('wechat.mode 必须为 panel 或 shortcut')
    for pair in (settings.main_size, settings.panel_button):
        if len(pair) != 2 or any(type(value) is not int or value <= 0 for value in pair):
            raise ValueError('main_size 和 panel_button 必须为两个正整数')
    return settings
