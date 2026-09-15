#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
华农游泳馆免费票抢票脚本
Swimming Pool Free Ticket Grabber

使用方法:
    python grab.py                        # 正式抢票：等待0点后自动批量发送
    python grab.py --dry-run              # 干跑模式：只打印请求内容，不发送
    python grab.py --test                 # 测试模式：立即发送一次请求
    python grab.py --check                # 仅检查token有效性
    python grab.py --all-days             # 尝试所有7天的 product_id
    python grab.py --product-id 25293     # 手动指定 product_id
    python grab.py --date 20260916        # 手动指定日期

前提条件:
    1. 打开微信小程序，用 mitmproxy 抓包保存为 traffic.log
    2. 运行 python extract_token.py 保存 token 到 token.txt
    3. 运行本脚本（token 寿命约30-60分钟，建议临抢前才抓包）

重要提示:
    - Token 有短生命周期，服务器通过会话黑名单管理，约30-60分钟后失效
    - 服务器返回 code=40101 "系统繁忙 ^_^" 表示 token 已失效
    - 建议在 23:50 左右重新抓包获取新 token，然后等待 0:00 抢票
    - 不要提前太久获取 token，否则等到0点时已失效

脚本流程:
    1. 读取 token.txt 中的 JWT token，解码显示创建时间
    2. 根据星期几计算今天的 product_id
    3. 用轻量接口验证 token 是否仍然有效
    4. 校准时钟（对比服务器 Date 头）
    5. 在 23:59:59.500 预热连接
    6. 在 0:00:00.000 开始批量发送请求
    7. 每次间隔 100ms，共发送 30 次
    8. 成功即停止，token 失效则提前退出
"""

import time
import os
import sys
import json
import hashlib
import base64
from datetime import datetime, timedelta

# Windows 控制台 UTF-8 支持
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import requests

# ============ 配置区（可修改） ============

# Token 文件路径
TOKEN_FILE = 'token.txt'

# API 配置
API_BASE = 'https://api.wesais.com'
BUSINESS_ID = '10000863'
STADIUM_ID = '11617'
SYS_ID = '12'
BUSINESS_TYPE = '1201'
ORDER_FROM = '2'

# 星期 → product_id 映射 (0=周一, 6=周日)
# 通过抓包验证的映射关系:
#   周一=25294, 周二=25293, 周三=25292, 周四=25291
#   周五=25289, 周六=25288, 周日=25287
PRODUCT_ID_MAP = {
    0: 25294,  # 周一 Monday
    1: 25293,  # 周二 Tuesday
    2: 25292,  # 周三 Wednesday
    3: 25291,  # 周四 Thursday
    4: 25289,  # 周五 Friday
    5: 25288,  # 周六 Saturday
    6: 25287,  # 周日 Sunday
}

DAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

# 请求头（必须和小程序一致）
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 '
    'MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI '
    'MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) '
    'UnifiedPCWindowsWechat(0xf2541518) XWEB/17127 '
    'miniProgram/wxdd062848'
)
REFERER = 'https://xcx.wesais.com/'
ORIGIN = 'https://xcx.wesais.com'

# 抢票参数
BURST_COUNT = 30          # 发送请求总数
BURST_INTERVAL = 0.1      # 请求间隔（秒），0.1 = 100ms
PREWARM_BEFORE = 0.5      # 提前预热连接（秒），提前500ms建立连接

# Token 年龄阈值（秒），超过此值警告
TOKEN_WARN_AGE = 1800     # 30 分钟警告
TOKEN_FAIL_AGE = 3600     # 60 分钟标记高风险

# ================================


def decode_jwt_payload(token):
    """解码 JWT 的 payload 部分"""
    parts = token.split('.')
    if len(parts) < 2:
        return None
    payload_b64 = parts[1]
    payload_b64 += '=' * (4 - len(payload_b64) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return None


def get_token():
    """从 token.txt 读取 JWT token"""
    if not os.path.exists(TOKEN_FILE):
        print(f"[错误] 找不到 {TOKEN_FILE}")
        print("请先运行: python extract_token.py")
        print("或者手动将 JWT token 保存到 token.txt")
        sys.exit(1)
    with open(TOKEN_FILE, 'r') as f:
        token = f.read().strip()
    if not token or not token.startswith('eyJ'):
        print(f"[错误] {TOKEN_FILE} 中的 token 无效")
        print("Token 应以 'eyJ' 开头（JWT 格式）")
        sys.exit(1)
    return token


def generate_request_id():
    """生成随机 32 位十六进制 request_id"""
    return hashlib.md5(os.urandom(16)).hexdigest()


def build_body(product_id, date_str):
    """构建下单请求体"""
    return {
        'business_id': BUSINESS_ID,
        'stadium_id': STADIUM_ID,
        'sys_id': SYS_ID,
        'sku_slice': f'121000{product_id}{date_str}:1',
        'business_type': BUSINESS_TYPE,
        'order_from': ORDER_FROM,
        'handle_info': json.dumps({"date_str": date_str}),
        'sales_id': '0',
        'request_id': generate_request_id(),
    }


def build_headers(token):
    """构建请求头（与小程序实际请求一致）"""
    return {
        'Authorization': token,
        'User-Agent': USER_AGENT,
        'Accept': 'application/json, text/plain, */*',
        'Content-Type': 'application/x-www-form-urlencoded',
        'AuthRouter': '',
        'Origin': ORIGIN,
        'Sec-Fetch-Site': 'same-site',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Dest': 'empty',
        'Referer': REFERER,
    }


def make_session():
    """创建绕过系统代理的 HTTP Session（脚本请求直连，不走 mitmdump）"""
    s = requests.Session()
    s.trust_env = False  # 忽略系统代理设置
    return s

def validate_token(session, token):
    """
    用轻量只读接口验证 token 是否有效。
    返回 True 表示有效，False 表示失效。
    使用 /cfg/cfgCommon/getByCode POST（与小程序实际请求一致）。
    """
    try:
        body = {
            'business_id': BUSINESS_ID,
            'stadium_id': '0',
            'cfg_code': 'footer_set',
            'request_id': hashlib.md5(os.urandom(16)).hexdigest(),
        }
        resp = session.post(
            f'{API_BASE}/cfg/cfgCommon/getByCode',
            data=body,
            headers=build_headers(token),
            timeout=3
        )
        print(f"  [调试] HTTP状态: {resp.status_code}, 代理忽略: {not session.trust_env}")
        result = resp.json()
        code = result.get('code', '?')
        msg = result.get('message', '')
        print(f"  [调试] API返回: code={code} msg={msg}")
        # 40101 "系统繁忙" = token 已失效（服务器伪装错误码）
        # 200 = token 有效
        if code == 40101 or '繁忙' in msg:
            return False
        return True
    except Exception as e:
        print(f"  [调试] validate_token 异常: {type(e).__name__}: {e}")
        return False


def check_token_age(token):
    """
    检查 token 年龄（从 JWT ct 字段）。
    返回 (age_seconds, warning_str) 或 (None, None)。
    """
    payload = decode_jwt_payload(token)
    if not payload:
        return None, '无法解码 JWT'

    ct = payload.get('ct', 0)
    if not ct:
        return None, None

    age = time.time() - ct
    if age > TOKEN_FAIL_AGE:
        return age, f"token 已存在 {age/60:.0f} 分钟，极可能失效！建议重新抓包。"
    elif age > TOKEN_WARN_AGE:
        return age, f"token 已存在 {age/60:.0f} 分钟，可能即将失效。"
    elif age > 600:
        return age, f"token 已存在 {age/60:.0f} 分钟，建议尽快使用。"
    else:
        return age, f"token 年龄 {age:.0f} 秒，状态良好。"


def send_order(session, token, product_id, date_str):
    """发送下单请求，返回响应 JSON"""
    body = build_body(product_id, date_str)
    headers = build_headers(token)
    try:
        resp = session.post(
            f'{API_BASE}/shop/order/create',
            data=body,
            headers=headers,
            timeout=3
        )
        return resp.json()
    except requests.exceptions.RequestException as e:
        return {'code': -1, 'message': f'网络错误: {e}'}
    except (json.JSONDecodeError, ValueError) as e:
        return {'code': -2, 'message': f'响应解析失败: {e}'}


def check_result(result):
    """分析结果，返回 (状态, 描述)"""
    code = result.get('code', '?')
    msg = result.get('message', '')
    data = result.get('data', '')

    if code == 200:
        return 'success', f'成功! data={data}'
    if '不合法' in msg:
        return 'invalid_sku', f'SKU未开放: {msg}'
    if '不足' in msg:
        return 'sold_out', f'已售罄: {msg}'
    # 40101 是服务器伪装错误码，实际表示 token 失效
    if code == 40101 or '繁忙' in msg:
        return 'token_expired', f'Token已失效(伪装码40101): {msg}'
    if code in (401, 403) or '登录' in msg or 'token' in msg.lower() or '认证' in msg:
        return 'token_expired', f'Token失效: {msg}'
    if code == -1:
        return 'network_error', f'网络错误: {msg}'
    if code == -2:
        return 'parse_error', f'响应解析失败: {msg}'
    return 'unknown', f'未知 code={code} msg={msg}'


def print_result(result, product_id, date_str, prefix='  '):
    """打印单次请求结果"""
    ts = datetime.now().strftime('%H:%M:%S.%f')[:12]
    status, desc = check_result(result)

    icons = {
        'success': '🎉',
        'invalid_sku': '⏳',
        'sold_out': '❌',
        'token_expired': '🔑',
        'network_error': '🌐',
        'parse_error': '📄',
        'unknown': '❓',
    }
    icon = icons.get(status, '❓')
    print(f"{prefix}[{ts}] {icon} pid={product_id} -> {desc}")


def calibrate_clock(session, token):
    """校准时钟：返回服务器与客户端的时间差（秒）"""
    t1 = time.time()
    try:
        resp = session.get(
            f'{API_BASE}/cfg/cfgCommon/getByCode',
            params={'code': 'common', 'business_id': BUSINESS_ID},
            headers=build_headers(token),
            timeout=2
        )
        t2 = time.time()
        if 'Date' in resp.headers:
            from email.utils import parsedate_to_datetime
            server_time = parsedate_to_datetime(resp.headers['Date']).timestamp()
            client_mid = (t1 + t2) / 2
            offset = server_time - client_mid
            print(f"  服务器时间偏移: {offset:+.3f} 秒")
            return offset
        else:
            print("  [警告] 服务器响应无 Date 头，跳过校准")
    except Exception as e:
        print(f"  [警告] 校准失败: {e}")
    return 0.0


def prewarm(session, token):
    """预热连接（建立 TCP+TLS 连接，减少0点时的握手延迟）"""
    try:
        resp = session.get(
            f'{API_BASE}/cfg/cfgCommon/getByCode',
            params={'code': 'common', 'business_id': BUSINESS_ID},
            headers=build_headers(token),
            timeout=2
        )
        code = resp.json().get('code', '?')
        if code == 40101:
            print("  [错误] 预热时发现 token 已失效！")
            return False
        print(f"  连接预热成功 (响应码: {code})")
        return True
    except Exception as e:
        print(f"  [警告] 预热失败: {e}")
        return False


def grab_burst(token, product_id, date_str, clock_offset=0.0):
    """批量抢票模式"""
    print(f"\n{'='*60}")
    print(f"批量抢票模式")
    print(f"{'='*60}")
    print(f"  product_id: {product_id}")
    print(f"  日期:       {date_str}")
    print(f"  SKU:        121000{product_id}{date_str}:1")
    print(f"  请求次数:   {BURST_COUNT}")
    print(f"  请求间隔:   {BURST_INTERVAL*1000:.0f}ms")
    print(f"  时钟偏移:   {clock_offset:+.3f}s")

    # 计算目标时间：下一个0点
    now = datetime.now()
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    if now >= midnight:
        midnight += timedelta(days=1)

    # 考虑时钟偏移
    adjusted_midnight = midnight - timedelta(seconds=clock_offset)

    prewarm_time = adjusted_midnight - timedelta(seconds=PREWARM_BEFORE)
    start_time = adjusted_midnight

    wait_sec = (prewarm_time - datetime.now()).total_seconds()
    if wait_sec > 0:
        print(f"\n等待到 {prewarm_time.strftime('%H:%M:%S.%f')} (0点前{PREWARM_BEFORE}s)...")
        print(f"   还需等待: {wait_sec:.1f} 秒")
        # 分段等待，避免长时间无输出
        remaining = wait_sec
        while remaining > 5:
            chunk = min(10, remaining - 5)
            time.sleep(chunk)
            remaining = (prewarm_time - datetime.now()).total_seconds()
            if remaining > 0:
                print(f"   剩余: {remaining:.0f} 秒", end='\r')
        # 最后几秒精确等待
        final_wait = (prewarm_time - datetime.now()).total_seconds()
        if final_wait > 0.05:
            time.sleep(final_wait - 0.05)
    else:
        print(f"\n[注意] 目标时间已过，立即开始抢票")

    # 开始抢票
    with make_session() as session:
        # 预热连接
        prewarm_ok = prewarm(session, token)
        if not prewarm_ok:
            print("\n[中止] Token 可能已失效，建议重新抓包获取新 token")
            print("   运行: python extract_token.py")
            return False

        # 最后验证 token
        if not validate_token(session, token):
            print("\n[中止] Token 验证失败！请重新抓包获取新 token")
            return False

        # 忙等到开始时间
        while datetime.now() < start_time:
            pass

        print(f"\n开始抢票！时间: {datetime.now().strftime('%H:%M:%S.%f')}")

        success = False
        for i in range(BURST_COUNT):
            result = send_order(session, token, product_id, date_str)
            print_result(result, product_id, date_str,
                         prefix=f"  [{i+1:2d}/{BURST_COUNT}] ")

            status, _ = check_result(result)

            if status == 'success':
                print(f"\n{'='*60}")
                print(f"抢票成功！第 {i+1} 次请求成功")
                print(f"{'='*60}")
                success = True
                break

            if status == 'token_expired':
                print(f"\n{'='*60}")
                print(f"Token 已失效！请重新抓包获取 token")
                print(f"   运行: python extract_token.py")
                print(f"{'='*60}")
                break

            if status == 'sold_out' and i >= 5:
                print(f"\n{'='*60}")
                print(f"已售罄（已尝试 {i+1} 次）")
                print(f"{'='*60}")
                break

            # 等待到下一个间隔
            target = time.time() + BURST_INTERVAL
            while time.time() < target:
                pass

        if not success:
            print(f"\n批量抢票结束，共发送 {BURST_COUNT} 次请求")

    return success


def grab_all_days(token, date_str):
    """尝试所有7天的 product_id"""
    print(f"\n{'='*60}")
    print(f"尝试所有7天的 product_id (date={date_str})")
    print(f"{'='*60}")

    with make_session() as session:
        for weekday, product_id in sorted(PRODUCT_ID_MAP.items()):
            day_name = DAY_NAMES[weekday]
            print(f"\n--- {day_name} (product_id={product_id}) ---")

            result = send_order(session, token, product_id, date_str)
            print_result(result, product_id, date_str)

            status, _ = check_result(result)
            if status == 'success':
                print(f"\n{day_name} 抢票成功！")
                return True
            if status == 'token_expired':
                print("\nToken 已失效！")
                return False

            time.sleep(0.2)

    print(f"\n所有7天都尝试过了，没有成功")
    return False


def check_token_mode(token, session):
    """仅检查 token 有效性模式"""
    print(f"\n检查 Token 有效性...")

    # 1. 年龄检查
    age, warn_msg = check_token_age(token)
    if warn_msg:
        if age is not None and age > TOKEN_WARN_AGE:
            print(f"  [警告] {warn_msg}")
        else:
            print(f"  [信息] {warn_msg}")

    # 2. JWT 详情
    payload = decode_jwt_payload(token)
    if payload:
        ct = payload.get('ct', 0)
        if ct:
            ct_dt = datetime.fromtimestamp(ct)
            print(f"  JWT 创建时间: {ct_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        params = payload.get('params', '')
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except Exception:
                pass
        if params:
            print(f"  账户ID: {params.get('account_id', '?')}")
            print(f"  会员ID: {params.get('member_id', '?')}")

    # 3. 在线验证
    valid = validate_token(session, token)
    if valid:
        print(f"  在线验证: Token 有效")
        print(f"\nToken 状态: OK，可用于抢票")
    else:
        print(f"  在线验证: Token 已失效 (code=40101)")
        print(f"\nToken 状态: 已失效")
        print(f"请重新打开微信小程序，用 mitmproxy 抓包")
        print(f"然后运行: python extract_token.py")

    return valid


def main():
    args = sys.argv[1:]
    dry_run = '--dry-run' in args
    test_mode = '--test' in args
    all_days = '--all-days' in args
    check_mode = '--check' in args

    # 解析 --product-id 和 --date 参数
    product_id_override = None
    date_override = None
    for i, arg in enumerate(args):
        if arg == '--product-id' and i + 1 < len(args):
            product_id_override = int(args[i + 1])
        if arg == '--date' and i + 1 < len(args):
            date_override = args[i + 1]

    token = get_token()

    now = datetime.now()

    # 正式模式下，抢票时间是下一个0点（明天），需要用明天的日期和星期
    is_normal_mode = not (dry_run or test_mode or check_mode or all_days)
    if is_normal_mode:
        # 计算下一个0点
        target_time = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        if now >= target_time:
            target_time += timedelta(days=1)
        target_weekday = target_time.weekday()
        target_date_str = target_time.strftime('%Y%m%d')
    else:
        target_weekday = now.weekday()
        target_date_str = now.strftime('%Y%m%d')

    # 确定 product_id
    if product_id_override:
        product_id = product_id_override
    else:
        product_id = PRODUCT_ID_MAP[target_weekday]

    # 确定日期
    if date_override:
        date_str = date_override
    else:
        date_str = target_date_str

    weekday = target_weekday
    day_name = DAY_NAMES[weekday]

    print(f"{'='*60}")
    print(f"游泳馆免费票抢票脚本")
    print(f"{'='*60}")
    print(f"  当前时间:   {now.strftime('%Y-%m-%d %H:%M:%S')}")
    if is_normal_mode:
        print(f"  目标时间:   {target_time.strftime('%Y-%m-%d %H:%M:%S')} (明天0点)")
    print(f"  星期:       {day_name} (目标日期)")
    print(f"  product_id: {product_id}")
    print(f"  日期:       {date_str}")
    print(f"  SKU:        121000{product_id}{date_str}:1")
    print(f"  Token:      {token[:40]}...{token[-20:]}")

    mode_str = ('干跑' if dry_run else '测试' if test_mode else '检查' if check_mode else '全天' if all_days else '正式')
    print(f"  模式:       {mode_str}")
    print(f"{'='*60}")

    # ---- 检查模式 ----
    if check_mode:
        with make_session() as session:
            check_token_mode(token, session)
        return

    # ---- 干跑模式 ----
    if dry_run:
        body = build_body(product_id, date_str)
        headers = build_headers(token)
        print(f"\n请求体 (form-urlencoded):")
        print(json.dumps(body, ensure_ascii=False, indent=2))
        print(f"\n请求头:")
        for k, v in headers.items():
            if k == 'Authorization':
                print(f"  {k}: {v[:40]}...{v[-20:]}")
            else:
                print(f"  {k}: {v}")
        print(f"\nSKU 编码规则: 121000 + product_id + date + :1")
        print(f"  121000 + {product_id} + {date_str} + :1 = 121000{product_id}{date_str}:1")

        # 也显示 token 信息
        age, warn_msg = check_token_age(token)
        if warn_msg:
            print(f"\nToken 信息: {warn_msg}")
        return

    # ---- 测试模式 ----
    if test_mode:
        print(f"\n测试模式 - 验证 token 并发送请求...")
        with make_session() as session:
            # 先检查 token
            age, warn_msg = check_token_age(token)
            if warn_msg:
                print(f"  Token 信息: {warn_msg}")

            if not validate_token(session, token):
                print(f"\nToken 已失效！请重新抓包获取新 token。")
                print(f"   运行: python extract_token.py")
                return

            print(f"  Token 有效，发送测试请求...")
            result = send_order(session, token, product_id, date_str)
            print_result(result, product_id, date_str)
            status, desc = check_result(result)
            if status == 'success':
                print("\n抢票成功！")
            elif status == 'invalid_sku':
                print("\nSKU 未开放（可能还没到0点，或 product_id 不对）")
                print("   请求格式正确，token 有效。")
            elif status == 'sold_out':
                print("\n票已售罄。")
            elif status == 'token_expired':
                print("\nToken 已失效（发送下单时失效）。")
            else:
                print(f"\n结果: {desc}")
        return

    # ---- 全天模式 ----
    if all_days:
        with make_session() as session:
            if not validate_token(session, token):
                print("\nToken 已失效！请重新抓包获取新 token。")
                return
            grab_all_days(token, date_str)
        return

    # ---- 正式模式 ----
    print(f"\n校准服务器时钟...")
    with make_session() as session:
        clock_offset = calibrate_clock(session, token)
        session.close()

    # 显示7天映射表
    target_label = "目标日" if is_normal_mode else "今天"
    print(f"\n星期 -> product_id 映射表:")
    for w, pid in sorted(PRODUCT_ID_MAP.items()):
        marker = f" <- {target_label}" if w == weekday else ""
        print(f"  {DAY_NAMES[w]}: {pid}{marker}")

    # Token 年龄检查
    age, warn_msg = check_token_age(token)
    if warn_msg:
        print(f"\nToken 检查: {warn_msg}")

    # 确认
    print(f"\n{'='*60}")
    print(f"即将进入等待模式，目标时间: 明天 0:00:00")
    print(f"按 Enter 开始等待，按 Ctrl+C 取消...")
    print(f"{'='*60}")
    try:
        input()
    except KeyboardInterrupt:
        print("\n已取消")
        return

    grab_burst(token, product_id, date_str, clock_offset)


if __name__ == '__main__':
    main()
