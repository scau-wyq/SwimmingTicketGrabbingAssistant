#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 traffic.log 中提取最新的 JWT token 并保存到 token.txt

使用方法:
    python extract_token.py

流程:
    1. 读取 traffic.log (mitmproxy 抓包文件)
    2. 找到所有 /member/wxMember/exToken 响应
    3. 取最新的一个 JWT token
    4. 解码 JWT 显示创建时间
    5. 保存到 token.txt
"""
import sys
import os
import json
import base64
from datetime import datetime

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from mitmproxy import io

LOG_FILE = 'traffic.log'
TOKEN_FILE = 'token.txt'


def decode_jwt_payload(token):
    """解码 JWT 的 payload 部分"""
    parts = token.split('.')
    if len(parts) < 2:
        return None
    payload_b64 = parts[1]
    # 补齐 base64 填充
    payload_b64 += '=' * (4 - len(payload_b64) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return None


def main():
    if not os.path.exists(LOG_FILE):
        print(f"[错误] 找不到 {LOG_FILE}")
        print("请先用 mitmproxy 抓包，保存为 traffic.log")
        return

    print(f"正在读取 {LOG_FILE} ...")

    latest_token = None
    latest_ts = 0
    token_count = 0

    with open(LOG_FILE, 'rb') as f:
        for fl in io.FlowReader(f).stream():
            if isinstance(fl, dict):
                continue
            if fl.request.host == 'api.wesais.com' and fl.request.path == '/member/wxMember/exToken':
                ts = fl.request.timestamp_start
                if fl.response:
                    try:
                        resp = json.loads(fl.response.text)
                        token = resp.get('data', {}).get('token', '')
                        if token and token.startswith('eyJ'):
                            token_count += 1
                            if ts > latest_ts:
                                latest_token = token
                                latest_ts = ts
                    except Exception:
                        pass

    print(f"找到 {token_count} 个 exToken 响应")

    if not latest_token:
        print("[错误] traffic.log 中未找到 JWT token")
        print("请确保抓包时包含了小程序登录流程（miniLogin + exToken）")
        return

    # 保存 token
    with open(TOKEN_FILE, 'w') as f:
        f.write(latest_token)

    # 解码并显示信息
    payload = decode_jwt_payload(latest_token)

    print(f"\n{'='*50}")
    print(f"✅ Token 已保存到 {TOKEN_FILE}")
    print(f"   Token 长度: {len(latest_token)} 字符")

    if latest_ts:
        ts_dt = datetime.fromtimestamp(latest_ts)
        print(f"   抓取时间: {ts_dt.strftime('%Y-%m-%d %H:%M:%S')}")

    if payload:
        ct = payload.get('ct', 0)
        if ct:
            ct_dt = datetime.fromtimestamp(ct)
            print(f"   JWT创建时间: {ct_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        params = payload.get('params', '')
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except Exception:
                pass
        if params:
            print(f"   账户ID: {params.get('account_id', '?')}")
            print(f"   会员ID: {params.get('member_id', '?')}")
            print(f"   公司ID: {params.get('company_id', '?')}")

    print(f"\nToken 预览: {latest_token[:60]}...")
    print(f"\n{'='*50}")
    print(f"下一步: python grab.py --test   # 测试模式，验证token有效")
    print(f"       python grab.py --dry-run # 干跑模式，查看请求内容")
    print(f"       python grab.py           # 正式抢票，等待0点")


if __name__ == '__main__':
    main()
