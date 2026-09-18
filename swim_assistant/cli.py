"""命令行入口和日志配置；导入包不会修改代理或发送网络请求。"""

import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys

from .capture import port_in_use
from .config import ROOT, load_settings
from .locking import single_instance
from .proxy import restore_pending
from .runner import run
from .wechat import validate_entry


def configure_logging(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    handlers = [logging.StreamHandler(), RotatingFileHandler(
        directory / 'assistant.log', maxBytes=2_000_000, backupCount=5, encoding='utf-8')]
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s',
                        handlers=handlers, force=True)


def doctor(settings, manual: bool) -> int:
    checks = [('Windows', os.name == 'nt'), ('mitmdump', settings.mitmdump.is_file()),
              (f'代理端口 {settings.proxy_port} 可用', not port_in_use(settings.proxy_port)),
              ('mitmproxy CA 已生成', (Path.home() / '.mitmproxy' / 'mitmproxy-ca-cert.cer').is_file()),
              ('没有待恢复代理快照', not (settings.state_dir / 'proxy-recovery.json').exists())]
    if not manual:
        try:
            validate_entry(settings)
            checks.append(('微信入口及 UI 配置', True))
        except (ValueError, RuntimeError) as exc:
            checks.append((str(exc), False))
    for name, ok in checks:
        print(f'{"OK" if ok else "FAIL"}  {name}')
    print('说明：CA 文件存在不代表已受 Windows/微信信任；微信登录和页面操作需用 --test 验证。')
    return 0 if all(ok for _, ok in checks) else 1


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Windows 微信小程序自动预约助手')
    parser.add_argument('--config', type=Path, default=ROOT / 'config.toml', help='TOML 配置文件')
    parser.add_argument('--date', help='预约日期 YYYYMMDD；放票时间仍是本次下一个零点')
    parser.add_argument('--test', '--capture-only', dest='test_only', action='store_true', help='只获取并只读验证 token，绝不下单')
    parser.add_argument('--manual', action='store_true', help='由用户打开小程序，其余步骤自动执行')
    parser.add_argument('--doctor', action='store_true', help='仅检查配置和环境，不修改系统设置')
    parser.add_argument('--restore-proxy', action='store_true', help='恢复异常终止前保存的代理设置')
    parser.add_argument('--scheduled', action='store_true', help='计划任务专用：只允许 23:58–23:59 启动')
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config)
        if args.doctor:
            return doctor(settings, args.manual)
        if os.name != 'nt':
            raise RuntimeError('自动采集只支持 Windows')
        configure_logging(settings.runtime_dir)
        with single_instance(settings.state_dir / 'assistant.lock'):
            if args.restore_proxy:
                restored = restore_pending(settings.state_dir / 'proxy-recovery.json')
                logging.info('代理已恢复' if restored else '没有待恢复的代理设置')
                return 0
            return run(settings, test_only=args.test_only, manual=args.manual, date_override=args.date,
                       scheduled=args.scheduled)
    except KeyboardInterrupt:
        logging.warning('用户中断，已执行资源清理')
        return 130
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        logging.error('%s', exc)
        return 1
    except Exception as exc:
        # pywinauto 的窗口/COM 异常类型不统一；资源已由上下文管理器清理。
        logging.error('任务失败 (%s)，请检查微信窗口、配置和运行环境', type(exc).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
