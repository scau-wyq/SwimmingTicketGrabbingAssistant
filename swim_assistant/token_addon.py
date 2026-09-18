"""由 mitmdump 单独加载。只提取目标登录响应，不保存完整 HTTP 流量。"""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def response(flow):
    if flow.request.host != 'api.wesais.com':
        return
    if urlsplit(flow.request.path).path != '/member/wxMember/exToken' or not flow.response:
        return
    try:
        result = flow.response.json()
        data = result.get('data')
        token = data.get('token') if isinstance(data, dict) else None
        if not isinstance(token, str) or not token.startswith('eyJ'):
            return
        path = Path(os.environ['SWIM_CAPTURE_FILE'])
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps({'run_id': os.environ['SWIM_RUN_ID'], 'token': token}), encoding='utf-8')
        temp.replace(path)
    except (ValueError, AttributeError, OSError):
        return
