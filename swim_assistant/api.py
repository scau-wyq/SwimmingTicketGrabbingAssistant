"""预约服务适配器。只在 send_order 中执行创建订单操作。"""

import json
import logging
import uuid
import requests
from .config import Settings

log = logging.getLogger(__name__)
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 '
    'MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI '
    'MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) '
    'UnifiedPCWindowsWechat(0xf2541518) XWEB/17127 miniProgram/wxdd062848'
)


def classify(result: dict) -> str:
    code = result.get('code')
    message = str(result.get('message', ''))
    if code == 200:
        return 'success'
    if code in (401, 403, 40101) or any(word in message.lower() for word in ('登录', 'token', '认证')):
        return 'token_expired'
    if '不足' in message:
        return 'sold_out'
    if code == 40004007 or '不合法' in message or '超出预售天数' in message:
        return 'not_open'
    if code == -1:
        return 'uncertain'
    return 'unknown'


class ApiClient:
    def __init__(self, settings: Settings, token: str):
        self.settings = settings
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({
            'Authorization': token, 'User-Agent': USER_AGENT,
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/x-www-form-urlencoded', 'AuthRouter': '',
            'Origin': 'https://xcx.wesais.com', 'Referer': 'https://xcx.wesais.com/',
            'Sec-Fetch-Site': 'same-site', 'Sec-Fetch-Mode': 'cors', 'Sec-Fetch-Dest': 'empty',
        })

    def close(self) -> None:
        self.session.close()

    def _post(self, path: str, body: dict) -> dict:
        try:
            response = self.session.post(self.settings.api_base + path, data=body,
                                         timeout=self.settings.request_timeout)
            if response.status_code in (401, 403):
                return {'code': response.status_code}
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                return {'code': -1}
            return result
        except (requests.RequestException, ValueError):
            # 不记录异常的请求信息，避免 Authorization 或服务端敏感内容进入日志。
            return {'code': -1}

    def validate_token(self) -> bool:
        result = self._post('/cfg/cfgCommon/getByCode', {
            'business_id': self.settings.business_id, 'stadium_id': '0',
            'cfg_code': 'footer_set', 'request_id': uuid.uuid4().hex,
        })
        # 配置接口只能验证当前请求成功；不能证明下单权限。
        return result.get('code') == 200

    def verify_product(self, product_id: int, date_str: str) -> int:
        result = self._post('/ticket/wxTicketSale/getTicketOne', {
            'business_id': self.settings.business_id, 'stadium_id': self.settings.stadium_id,
            'date': date_str, 'ticket_product_id': str(product_id), 'request_id': uuid.uuid4().hex,
        })
        data = result.get('data') or {}
        if result.get('code') != 200 or not isinstance(data, dict) or str(data.get('product_id')) != str(product_id):
            raise RuntimeError('票种校验未通过；请核对目标日期和 products 配置')
        return product_id

    def send_order(self, product_id: int, date_str: str, request_id: str) -> dict:
        return self._post('/shop/order/create', {
            'business_id': self.settings.business_id, 'stadium_id': self.settings.stadium_id,
            'sys_id': '12', 'sku_slice': f'121000{product_id}{date_str}:1',
            'business_type': '1201', 'order_from': '2',
            'handle_info': json.dumps({'date_str': date_str}),
            'sales_id': '0', 'request_id': request_id,
        })
