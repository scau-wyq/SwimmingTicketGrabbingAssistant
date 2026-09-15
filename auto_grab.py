#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
游泳馆免费票全自动抢票脚本
Auto Ticket Grabber (Full Automation)

流程:
  1. 自动启动 mitmdump 抓包 (traffic_new.log)
  2. 你只需打开微信小程序一次（触发登录获取新 token）
  3. 脚本自动检测新 token 并保存
  4. 验证 token 有效性
  5. 等待 0:00:00
  6. 批量发送抢票请求
  7. 自动清理 mitmdump 进程

使用方法:
  python auto_grab.py              # 全自动（今天 0:00 抢票）
  python auto_grab.py --date 20260917  # 指定日期
  python auto_grab.py --test      # 只测试 token 获取，不抢票
  python auto_grab.py --keep      # 运行结束后保留 mitmdump 进程

前提条件:
  - mitmproxy 已安装（conda env: SwimmingTicketGrabbingAssistant）
  - 系统代理已配置为指向 mitmproxy (127.0.0.1:8080)
  - Windows 已安装 mitmproxy 的 CA 证书
"""

import time
import os
import sys
import json
import hashlib
import base64
import subprocess
import socket
from datetime import datetime, timedelta

# Windows 控制台 UTF-8 支持
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import requests

# ============ 配置区 ============

# mitmdump 配置
MITMDUMP_PATH = r'C:\Users\wang3\anaconda3\envs\SwimmingTicketGrabbingAssistant\Scripts\mitmdump.exe'
NEW_LOG_FILE = 'traffic_new.log'       # 新的抓包文件
TOKEN_FILE = 'token.txt'              # token 保存位置

# API 配置
API_BASE = 'https://api.wesais.com'
BUSINESS_ID = '10000863'
STADIUM_ID = '11617'
SYS_ID = '12'
BUSINESS_TYPE = '1201'
ORDER_FROM = '2'

# 星期 → product_id 映射 (0=周一, 6=周日)
PRODUCT_ID_MAP = {
    0: 25294,  # 周一
    1: 25293,  # 周二
    2: 25292,  # 周三
    3: 25291,  # 周四
    4: 25289,  # 周五
    5: 25288,  # 周六
    6: 25287,  # 周日
}

DAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

# 请求头
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
BURST_COUNT = 30
BURST_INTERVAL = 0.1
PREWARM_BEFORE = 0.5

# 文件监控参数
POLL_INTERVAL = 2          # 文件轮询间隔（秒）
TOKEN_WAIT_TIMEOUT = 600  # 等待 token 最长（秒），10分钟
POLL_INTERVAL = 2

# ================================


# ============ 工具函数 ============

def decode_jwt_payload(token):
    """解码 JWT payload"""
    parts = token.split('.')
    if len(parts) < 2:
        return None
    payload_b64 = parts[1]
    payload_b64 += '=' * (4 - len(payload_b64) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return None


def generate_request_id():
    """生成随机 32 位十六进制 request_id"""
    return hashlib.md5(os.urandom(16)).hexdigest()


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


def check_result(result):
    """分析结果"""
    code = result.get('code', '?')
    msg = result.get('message', '')
    data = result.get('data', '')

    if code == 200:
        return 'success', f'成功! data={data}'
    if '不合法' in msg:
        return 'invalid_sku', f'SKU未开放: {msg}'
    if '不足' in msg:
        return 'sold_out', f'已售罄: {msg}'
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
        'success': '>>>',
        'invalid_sku': '...',
        'sold_out': 'XXX',
        'token_expired': 'KEY',
        'network_error': 'NET',
        'parse_error': 'PARSE',
        'unknown': '???',
    }
    icon = icons.get(status, '???')
    print(f"{prefix}[{ts}] [{icon}] pid={product_id} -> {desc}")


# ============ mitmdump 管理 ============

def is_port_in_use(port):
    """检查端口是否被占用"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    result = s.connect_ex(('127.0.0.1', port))
    s.close()
    return result == 0


def start_mitmdump(log_file):
    """启动 mitmdump 抓包"""
    if os.path.exists(log_file):
        os.remove(log_file)

    print(f"启动 mitmdump，抓包到 {log_file} ...")
    cmd = [
        MITMDUMP_PATH,
        '-w', log_file,
    ]

    try:
        # Windows: CREATE_NO_WINDOW 隐藏控制台窗口
        kwargs = {}
        if os.name == 'nt':
            kwargs['creationflags'] = 0x08000000  # CREATE_NO_WINDOW
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )
        print(f"mitmdump PID: {proc.pid}")
        time.sleep(2)
        if proc.poll() is not None:
            print(f"mitmdump 启动后立即退出 (exit code: {proc.returncode})")
            return None
        return proc
    except FileNotFoundError:
        print(f"错误: 找不到 {MITMDUMP_PATH}")
        return None
    except Exception as e:
        print(f"错误: 启动 mitmdump 失败: {e}")
        return None


def stop_mitmdump(proc):
    """停止 mitmdump 进程"""
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
        print("mitmdump 已停止")
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)
        print("mitmdump 强制终止")
    except Exception as e:
        print(f"停止 mitmdump 时出错: {e}")


def extract_token_from_log(log_file):
    """从抓包文件中提取最新 token"""
    from mitmproxy import io

    if not os.path.exists(log_file):
        return None, 0

    latest_token = None
    latest_ts = 0
    token_count = 0

    try:
        with open(log_file, 'rb') as f:
            for fl in io.FlowReader(f).stream():
                if isinstance(fl, dict):
                    continue
                if (fl.request.host == 'api.wesais.com'
                        and fl.request.path == '/member/wxMember/exToken'
                        and fl.response):
                    ts = fl.request.timestamp_start
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
    except Exception as e:
        print(f"读取日志文件错误: {e}")

    return latest_token, token_count


def watch_for_token(log_file, timeout=TOKEN_WAIT_TIMEOUT):
    """
    监控抓包文件，等待新 token 出现。
    返回 (token, found)
    """
    start_time = time.time()
    last_size = 0
    attempts = 0

    print(f"等待新 token 出现 (最长 {timeout} 秒)...")
    print("请按提示操作小程序！")
    print()

    while time.time() - start_time < timeout:
        attempts += 1

        if os.path.exists(log_file):
            current_size = os.path.getsize(log_file)

            # 文件大小有变化时尝试读取
            if current_size > last_size:
                last_size = current_size
                token, count = extract_token_from_log(log_file)

                if token and count > 0:
                    # 检查是否是"新"token（时间戳更新）
                    payload = decode_jwt_payload(token)
                    if payload:
                        ct = payload.get('ct', 0)
                        ct_str = datetime.fromtimestamp(ct).strftime('%H:%M:%S') if ct else '?'
                        age = time.time() - ct if ct else 999
                        if age < 300:  # 5分钟内视为新token
                            print(f"\n发现新 token! (JWT创建时间: {ct_str}, 年龄: {age:.0f}秒)")
                            return token, True
                        else:
                            print(f"  发现 token 但太旧 (年龄 {age:.0f}秒)，继续等待...")
                elif count > 0:
                    print(f"  发现 {count} 个 token 但都太旧，继续等待...")

        remaining = timeout - (time.time() - start_time)
        print(f"\r  已等待 {time.time() - start_time:.0f}s / {timeout}s  (尝试 {attempts} 次)", end='', flush=True)
        time.sleep(POLL_INTERVAL)

    print(f"\n超时！未检测到新 token")
    return None, False


# ============ Token 验证 ============

def make_session():
    """创建绕过系统代理的 HTTP Session（脚本请求直连，不走 mitmdump）"""
    s = requests.Session()
    s.trust_env = False  # 忽略系统代理设置
    return s

def validate_token(session, token):
    """验证 token 有效性（POST 方式，与小程序一致）"""
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
        print(f"  [调试] HTTP状态: {resp.status_code}")
        result = resp.json()
        code = result.get('code', '?')
        msg = result.get('message', '')
        print(f"  [调试] API返回: code={code} msg={msg}")
        if code == 40101 or '繁忙' in msg:
            return False
        return True
    except Exception as e:
        print(f"  [调试] validate_token 异常: {type(e).__name__}: {e}")
        return False


def show_token_info(token):
    """显示 token 信息"""
    payload = decode_jwt_payload(token)
    print(f"\nToken 信息:")
    print(f"  长度: {len(token)} 字符")
    if payload:
        ct = payload.get('ct', 0)
        if ct:
            ct_dt = datetime.fromtimestamp(ct)
            age = time.time() - ct
            print(f"  JWT创建时间: {ct_dt.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"  Token年龄: {age:.0f} 秒")
        params = payload.get('params', '')
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except Exception:
                pass
        if params:
            print(f"  账户ID: {params.get('account_id', '?')}")
            print(f"  会员ID: {params.get('member_id', '?')}")


# ============ 抢票逻辑 ============

def send_order(session, token, product_id, date_str):
    """发送下单请求"""
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


def calibrate_clock(session, token):
    """校准时钟"""
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
    except Exception as e:
        print(f"  校准失败: {e}")
    return 0.0


def prewarm(session, token):
    """预热连接"""
    try:
        resp = session.get(
            f'{API_BASE}/cfg/cfgCommon/getByCode',
            params={'code': 'common', 'business_id': BUSINESS_ID},
            headers=build_headers(token),
            timeout=2
        )
        code = resp.json().get('code', '?')
        if code == 40101:
            print("  [错误] 预热时 token 已失效")
            return False
        print(f"  连接预热成功 (响应码: {code})")
        return True
    except Exception as e:
        print(f"  预热失败: {e}")
        return False


def grab_burst(token, product_id, date_str, clock_offset=0.0):
    """批量抢票"""
    print(f"\n{'='*60}")
    print(f"批量抢票模式")
    print(f"{'='*60}")
    print(f"  product_id: {product_id}")
    print(f"  日期:       {date_str}")
    print(f"  SKU:        121000{product_id}{date_str}:1")
    print(f"  请求次数:   {BURST_COUNT}")
    print(f"  请求间隔:   {BURST_INTERVAL*1000:.0f}ms")
    print(f"  时钟偏移:   {clock_offset:+.3f}s")

    # 计算下一个0点
    now = datetime.now()
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    if now >= midnight:
        midnight += timedelta(days=1)

    adjusted_midnight = midnight - timedelta(seconds=clock_offset)
    prewarm_time = adjusted_midnight - timedelta(seconds=PREWARM_BEFORE)
    start_time = adjusted_midnight

    wait_sec = (prewarm_time - datetime.now()).total_seconds()
    if wait_sec > 0:
        print(f"\n等待到 {prewarm_time.strftime('%H:%M:%S.%f')} ...")
        print(f"   还需等待: {wait_sec:.1f} 秒")
        remaining = wait_sec
        while remaining > 5:
            chunk = min(10, remaining - 5)
            time.sleep(chunk)
            remaining = (prewarm_time - datetime.now()).total_seconds()
            if remaining > 0:
                print(f"   剩余: {remaining:.0f} 秒", end='\r')
        final_wait = (prewarm_time - datetime.now()).total_seconds()
        if final_wait > 0.05:
            time.sleep(final_wait - 0.05)
    else:
        print(f"\n目标时间已过，立即开始抢票")

    # 开始抢票
    with make_session() as session:
        if not prewarm(session, token):
            print("\nToken 可能已失效，抢票中止")
            return False

        if not validate_token(session, token):
            print("\nToken 验证失败，抢票中止")
            return False

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
                print(f"抢票成功！第 {i+1} 次请求")
                print(f"{'='*60}")
                success = True
                break

            if status == 'token_expired':
                print(f"\nToken 已失效！")
                break

            if status == 'sold_out' and i >= 5:
                print(f"\n已售罄（已尝试 {i+1} 次）")
                break

            target = time.time() + BURST_INTERVAL
            while time.time() < target:
                pass

        if not success:
            print(f"\n批量抢票结束")

    return success


# ============ 主流程 ============

def main():
    args = sys.argv[1:]
    test_only = '--test' in args
    keep_mitmdump = '--keep' in args
    date_override = None

    for i, arg in enumerate(args):
        if arg == '--date' and i + 1 < len(args):
            date_override = args[i + 1]

    # 确定 product_id 和日期
    weekday = datetime.now().weekday()
    product_id = PRODUCT_ID_MAP[weekday]
    date_str = date_override or datetime.now().strftime('%Y%m%d')
    day_name = DAY_NAMES[weekday]

    print(f"{'='*60}")
    print(f"游泳馆免费票全自动抢票")
    print(f"{'='*60}")
    print(f"  时间:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  星期:     {day_name}")
    print(f"  product_id: {product_id}")
    print(f"  日期:     {date_str}")
    print(f"  SKU:      121000{product_id}{date_str}:1")
    print(f"  模式:     {'测试' if test_only else '全自动抢票'}")
    print(f"{'='*60}")

    # 检查 mitmdump 是否可用
    if not os.path.exists(MITMDUMP_PATH):
        print(f"\n错误: 找不到 mitmdump: {MITMDUMP_PATH}")
        print("请确保 mitmproxy 已安装在 conda env 中")
        return

    # 检查端口
    if is_port_in_use(8080):
        print(f"\n[信息] 端口 8080 已被占用（mitmdump 可能已在运行）")
        # 检查现有抓包文件
        if os.path.exists('traffic.log'):
            print(f"  发现 traffic.log，将监控该文件")
            log_file_to_watch = 'traffic.log'
        elif os.path.exists(NEW_LOG_FILE):
            log_file_to_watch = NEW_LOG_FILE
        else:
            print(f"  未发现现有抓包文件，将创建 {NEW_LOG_FILE}")
            log_file_to_watch = NEW_LOG_FILE
        mitmdump_proc = None
    else:
        log_file_to_watch = NEW_LOG_FILE
        print(f"\n[步骤 1/5] 启动抓包工具...")
        mitmdump_proc = start_mitmdump(log_file_to_watch)
        if not mitmdump_proc:
            print("\n启动 mitmdump 失败！请手动启动后再运行本脚本")
            print(f"命令: {MITMDUMP_PATH} -w {log_file_to_watch}")
            return
        time.sleep(2)  # 等待 mitmdump 初始化

    # 步骤 2: 提示用户打开小程序
    print(f"\n[步骤 2/5] 请打开微信小程序")
    print(f"{'='*60}")
    print(f"  操作提示:")
    print(f"  1. 打开华农游泳馆微信小程序")
    print(f"  2. 进入门票页面（任何操作都可触发登录）")
    print(f"  3. 等待约 10 秒确保登录完成")
    print(f"  4. 回到本窗口，按 Enter 继续")
    print(f"{'='*60}")
    print()
    try:
        input("  >> 完成后按 Enter 继续...")
    except (KeyboardInterrupt, EOFError):
        print("\n用户取消")
        if mitmdump_proc and not keep_mitmdump:
            stop_mitmdump(mitmdump_proc)
        return

    # 步骤 3: 监控并提取 token
    print(f"\n[步骤 3/5] 监控抓包文件，等待新 token...")
    token, found = watch_for_token(log_file_to_watch, timeout=TOKEN_WAIT_TIMEOUT)

    if not found or not token:
        print("\n未获取到新 token！")
        print("可能原因:")
        print("  - 小程序登录流程未触发")
        print("  - 系统代理未配置")
        print("  - mitmdump 未正确捕获流量")
        print(f"\n请检查 {log_file_to_watch} 是否有内容:")
        if os.path.exists(log_file_to_watch):
            size = os.path.getsize(log_file_to_watch)
            print(f"  {log_file_to_watch} 大小: {size} 字节")
            if size == 0:
                print("  文件为空！代理可能未配置")
        if mitmdump_proc and not keep_mitmdump:
            stop_mitmdump(mitmdump_proc)
        return

    # 步骤 4: 保存并验证 token
    print(f"\n[步骤 4/5] 保存并验证 token...")
    with open(TOKEN_FILE, 'w') as f:
        f.write(token)
    print(f"  Token 已保存到 {TOKEN_FILE}")

    show_token_info(token)

    with make_session() as session:
        if not validate_token(session, token):
            print(f"\n[错误] Token 验证失败！")
            print("可能原因:")
            print("  - 代理配置问题导致 token 获取异常")
            print("  - 小程序登录未完成")
            print(f"\n请重试，或使用 grab.py --check 单独验证")
            if mitmdump_proc and not keep_mitmdump:
                stop_mitmdump(mitmdump_proc)
            return
        print(f"  Token 验证通过！")

    # 测试模式到此结束
    if test_only:
        print(f"\n[测试完成] Token 获取和验证都成功！")
        print(f"下次正式抢票时运行: python auto_grab.py")
        if mitmdump_proc and not keep_mitmdump:
            stop_mitmdump(mitmdump_proc)
        return

    # 步骤 5: 抢票
    print(f"\n[步骤 5/5] 准备抢票...")
    with make_session() as session:
        clock_offset = calibrate_clock(session, token)

    # 显示7天映射表
    print(f"\n星期 -> product_id 映射表:")
    for w, pid in sorted(PRODUCT_ID_MAP.items()):
        marker = " <- 今天" if w == weekday else ""
        print(f"  {DAY_NAMES[w]}: {pid}{marker}")

    # 确认
    print(f"\n{'='*60}")
    print(f"即将等待到明天 0:00:00 开始抢票")
    print(f"按 Enter 开始，Ctrl+C 取消...")
    print(f"{'='*60}")
    try:
        input()
    except (KeyboardInterrupt, EOFError):
        print("\n已取消")
        if mitmdump_proc and not keep_mitmdump:
            stop_mitmdump(mitmdump_proc)
        return

    # 执行抢票
    success = grab_burst(token, product_id, date_str, clock_offset)

    # 清理
    if mitmdump_proc and not keep_mitmdump:
        stop_mitmdump(mitmdump_proc)
    elif mitmdump_proc:
        print(f"\n[信息] mitmdump 仍在运行 (PID: {mitmdump_proc.pid})")
        print(f"       如需停止: taskkill /PID {mitmdump_proc.pid}")

    print(f"\n{'='*60}")
    if success:
        print(f"抢票完成！请打开小程序查看订单")
    else:
        print(f"抢票未成功，请检查输出信息")
    print(f"{'='*60}")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n用户中断")
        sys.exit(0)
