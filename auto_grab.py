"""兼容原启动命令；实现位于 swim_assistant 包。"""
from swim_assistant.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
