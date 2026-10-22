"""创建项目虚拟环境并安装依赖；只使用 Python 标准库作为引导依赖。"""

import argparse
import os
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def run(*command):
    """直接传递参数，支持带空格路径；任一步失败立即停止。"""
    subprocess.run([str(arg) for arg in command], cwd=ROOT, check=True)


def install():
    if os.name != 'nt':
        raise RuntimeError('此项目的自动化环境仅支持 Windows。')
    if sys.version_info < (3, 12) or struct.calcsize('P') != 8:
        raise RuntimeError('请使用 64 位 Python 3.12 或更高版本运行；推荐 Python 3.12。')

    environment = ROOT / '.venv'
    python = environment / 'Scripts' / 'python.exe'
    if environment.exists():
        if not (environment / 'pyvenv.cfg').is_file() or not python.is_file():
            raise RuntimeError('.venv 已存在但不是完整虚拟环境；请先检查该目录，不会自动删除。')
        print('复用已有 .venv。', flush=True)
    else:
        print('创建项目专用 .venv……', flush=True)
        run(sys.executable, '-m', 'venv', environment)

    # 检查复用的环境，而非只检查引导 Python，防止修改错误的环境。
    run(python, '-c',
        'import pathlib, struct, sys; '
        'assert sys.version_info >= (3, 12), "Python 3.12+ required"; '
        'assert struct.calcsize("P") == 8, "64-bit Python required"; '
        'assert pathlib.Path(sys.prefix).resolve() == pathlib.Path(sys.argv[1]).resolve(), '
        '"Unexpected virtual environment"', environment)
    run(python, '-m', 'pip', 'install', '-r', ROOT / 'requirements-ui.txt')
    run(python, '-m', 'pip', 'check')
    run(python, '-c', 'import requests, mitmproxy, pywinauto, win32api')

    config = ROOT / 'config.toml'
    try:
        # 独占创建，重复安装绝不覆盖本机已校准的配置。
        with config.open('x', encoding='utf-8') as stream:
            stream.write((ROOT / 'config.example.toml').read_text(encoding='utf-8'))
        print('已从模板创建 config.toml，请核对微信路径。', flush=True)
    except FileExistsError:
        print('已保留现有 config.toml。', flush=True)

    print('依赖安装完成，开始检查运行条件……', flush=True)
    result = subprocess.run([str(python), str(ROOT / 'auto_grab.py'), '--doctor'], cwd=ROOT)
    print(r'后续运行：.\.venv\Scripts\python.exe auto_grab.py --wechat-only', flush=True)
    if result.returncode:
        print('依赖已安装，但运行条件检查未通过，请处理上面的 FAIL 后重新运行 --doctor。', flush=True)
        return 2
    return 0


def main():
    argparse.ArgumentParser(description='创建/复用 .venv、安装依赖、初始化配置并检查环境。').parse_args()
    try:
        return install()
    except KeyboardInterrupt:
        print('安装已中断；再次运行可继续安装依赖。', file=sys.stderr)
        return 130
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'安装失败：{exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
