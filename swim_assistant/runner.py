"""一次任务的应用编排：准备、采集、验证、等待、预约。"""

from datetime import datetime, timedelta
import logging
import time
import uuid

from .api import ApiClient, classify
from .capture import start_capture
from .config import Settings
from .proxy import managed_proxy, restore_pending
from .timing import RunTarget, wait_until
from .wechat import open_miniprogram, validate_entry

log = logging.getLogger(__name__)


def acquire_token(settings: Settings, target: RunTarget, manual: bool, test_only: bool) -> str:
    if not manual:
        validate_entry(settings)
    budget = settings.token_timeout
    if not test_only:
        target.require_preparation_time(datetime.now())
        budget = min(budget, (target.release_at - datetime.now()).total_seconds() - settings.prewarm_seconds)
    if budget <= 0:
        raise TimeoutError('距离放票时间过近，无法完成准备')
    deadline = time.monotonic() + budget
    with start_capture(settings) as capture:
        with managed_proxy(f'127.0.0.1:{settings.proxy_port}', settings.state_dir / 'proxy-recovery.json'):
            if manual:
                log.info('请打开小程序并进入门票页面；程序会自动检测 token，无需按 Enter')
            else:
                log.info('打开微信小程序并触发登录')
                open_miniprogram(settings, deadline)
            token = capture.wait(deadline)
            log.info('已获取本次登录 token，恢复代理并关闭抓包')
            return token


def run(settings: Settings, *, test_only: bool = False, manual: bool = False,
        date_override: str | None = None, scheduled: bool = False) -> int:
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    if restore_pending(settings.state_dir / 'proxy-recovery.json'):
        log.warning('已恢复上次异常中断遗留的代理设置')
    now = datetime.now()
    if scheduled and (now.hour != 23 or now.minute < 58):
        raise TimeoutError('计划任务启动时间不在 23:58–23:59，本次不补跑')
    target = RunTarget.create(now, date_override)
    log.info('本次放票时间=%s，预约日期=%s，模式=%s', target.release_at, target.date_str,
             '仅获取并验证 token' if test_only else '正式预约')
    if not test_only:
        preparation_at = target.release_at - timedelta(minutes=2)
        if now < preparation_at:
            log.info('等待至 %s 开始准备；等待期间不启动抓包、不启用临时代理、不打开微信。Ctrl+C 可取消',
                     preparation_at)
            wait_until(preparation_at)
        # 休眠或时钟跳变后仍使用本次固定目标，不能顺延到下一天。
        target.require_preparation_time(datetime.now())
        log.info('已到准备时段，开始获取本次 token')
    token = acquire_token(settings, target, manual, test_only)
    client = ApiClient(settings, token)
    try:
        if not client.validate_token():
            raise RuntimeError('token 验证请求失败；未发送下单请求')
        if test_only:
            log.info('测试完成：获取 token、恢复代理及只读验证成功；未发送下单请求')
            return 0
        target.require_preparation_time(datetime.now())
        product = client.verify_product(settings.products[target.weekday], target.date_str)
        target.require_preparation_time(datetime.now())
        log.info('票种=%s，等待本次放票时间', product)
        wait_until(target.release_at - timedelta(seconds=settings.prewarm_seconds))
        if not client.validate_token():
            raise RuntimeError('放票前 token 验证失败，本次任务终止')
        target.require_preparation_time(datetime.now())
        wait_until(target.release_at)
        # 电脑意外休眠/时间跳变时，不在很久以后补下单。
        if (datetime.now() - target.release_at).total_seconds() > 5:
            raise TimeoutError('唤醒时已错过放票窗口，本次任务终止')
        return submit_orders(settings, client, product, target.date_str)
    finally:
        client.close()


def submit_orders(settings: Settings, client: ApiClient, product: int, date_str: str) -> int:
    """只重试服务端明确拒绝的订单；未知响应可能已经创建订单。"""
    for attempt in range(1, settings.burst_count + 1):
        result = client.send_order(product, date_str, uuid.uuid4().hex)
        status = classify(result)
        log.info('第 %d 次预约：%s (code=%s)', attempt, status, result.get('code'))
        if status == 'success':
            log.info('预约成功，请在小程序查看订单')
            return 0
        if status in ('unknown', 'uncertain'):
            raise RuntimeError('下单响应不确定，停止重试以避免重复订单，请在小程序核对')
        if status == 'token_expired' or (status == 'sold_out' and attempt >= 6):
            break
        if attempt < settings.burst_count:
            time.sleep(settings.burst_interval)
    log.warning('本次未预约成功')
    return 2
