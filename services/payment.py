"""可插拔支付网关抽象与本地演示网关（F5 商业化收尾）。

网关接口约束 create_order / verify_callback / parse_callback 三个契约方法；
本地演示网关在支付宝未配置时兜底，保证升级流程端到端可走通。
"""
from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod

from utils import config

logger = logging.getLogger(__name__)


class PaymentGateway(ABC):
    """支付网关抽象基类：定义创建订单、校验回调和解析回调三类契约方法。"""

    name: str = "base"

    @abstractmethod
    def create_order(self, order_id: str, amount_cents: int, subject: str) -> str:
        """创建支付订单并返回用户跳转的支付 URL。"""

    @abstractmethod
    def verify_callback(self, params: dict) -> bool:
        """校验支付回调参数签名/令牌是否合法。"""

    @abstractmethod
    def parse_callback(self, params: dict) -> dict:
        """从回调参数提取订单号与成功状态，返回含 order_id/success 的字典。"""


def _demo_token(order_id: str) -> str:
    """派生本地演示回调令牌：订单号单向哈希，演示场景无需保密。"""
    return hashlib.sha256(f"demo:{order_id}".encode("utf-8")).hexdigest()


class LocalDemoGateway(PaymentGateway):
    """本地演示网关：支付宝未配置时回退，支付链接直接指向本服务确认回调。"""

    name = "demo"

    def create_order(self, order_id: str, amount_cents: int, subject: str) -> str:
        """返回本地演示支付链接：确认回调地址带订单号与派生令牌。"""
        base = config.PAY_RETURN_URL.rsplit("/api/pay/return", 1)[0]
        return f"{base}/api/pay/demo/confirm?order_id={order_id}&token={_demo_token(order_id)}"

    def verify_callback(self, params: dict) -> bool:
        """本地令牌校验：订单号派生令牌与回调令牌一致即通过。"""
        order_id = params.get("order_id") or ""
        token = params.get("token") or ""
        return bool(order_id) and token == _demo_token(order_id)

    def parse_callback(self, params: dict) -> dict:
        """本地回调解析：校验通过后直接返回成功状态与订单号。"""
        return {"order_id": params.get("order_id"), "success": True}


def get_active_gateway() -> PaymentGateway:
    """返回当前生效网关：支付宝配置齐全时用沙箱网关，否则回退本地演示网关。

    支付宝配置缺失属预期场景（本地演示），仅记日志不抛错；初始化异常同样回退演示。
    """
    from services.alipay_gateway import AlipaySandboxGateway

    if AlipaySandboxGateway.is_configured():
        try:
            gateway: PaymentGateway = AlipaySandboxGateway()
        except RuntimeError as exc:
            logger.warning("支付宝沙箱网关初始化失败，回退本地演示网关: %s", exc)
            gateway = LocalDemoGateway()
        logger.info("当前支付网关: %s（支付宝沙箱）", gateway.name)
        return gateway
    logger.info("当前支付网关: %s（本地演示，支付宝未配置）", LocalDemoGateway.name)
    return LocalDemoGateway()
