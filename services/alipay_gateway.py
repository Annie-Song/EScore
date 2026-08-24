"""支付宝沙箱支付网关实现（F5）：懒导入 python-alipay-sdk，配置缺失或 SDK 未装时抛清晰错误。

配置项（utils/config 经 os.environ 读取，.env 注入）：
    ALIPAY_APP_ID / ALIPAY_PRIVATE_KEY / ALIPAY_PUBLIC_KEY / ALIPAY_GATEWAY_URL
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from services.payment import PaymentGateway
from utils import config

if TYPE_CHECKING:  # pragma: no cover - 仅类型标注用，避免运行时强制安装 SDK
    from alipay import AliPay

# 启用支付宝网关必需的三个配置项（网关地址有默认值，不纳入判定）
_REQUIRED_ENV = ("ALIPAY_APP_ID", "ALIPAY_PRIVATE_KEY", "ALIPAY_PUBLIC_KEY")


class AlipaySandboxGateway(PaymentGateway):
    """支付宝沙箱网关：创建支付链接并校验异步通知签名。"""

    name = "alipay"

    def __init__(self) -> None:
        """构造沙箱客户端；SDK 未安装或配置缺失抛 RuntimeError（消息含配置项名）。"""
        missing = [key for key in _REQUIRED_ENV if not getattr(config, key)]
        if missing:
            raise RuntimeError(
                "支付宝网关配置缺失: " + ", ".join(missing)
                + "，请在 .env 配置后重试"
            )
        try:
            from alipay import AliPay
        except ImportError as exc:
            raise RuntimeError(
                "python-alipay-sdk 未安装，无法使用支付宝网关；"
                "请 pip install python-alipay-sdk 或保持本地演示网关"
            ) from exc
        try:
            self._client: AliPay = AliPay(
                appid=config.ALIPAY_APP_ID,
                app_notify_url=None,
                app_private_key_string=config.ALIPAY_PRIVATE_KEY,
                alipay_public_key_string=config.ALIPAY_PUBLIC_KEY,
                sign_type="RSA2",
                debug=True,
            )
        except Exception as exc:  # noqa: BLE001 - SDK 内部错误统一转清晰 RuntimeError
            raise RuntimeError(f"支付宝网关客户端初始化失败: {exc}") from exc

    @classmethod
    def is_configured(cls) -> bool:
        """判断支付宝所需环境变量是否齐全（app_id 与公私钥均非空）。"""
        return all(getattr(config, key) for key in _REQUIRED_ENV)

    def create_order(self, order_id: str, amount_cents: int, subject: str) -> str:
        """用 alipay.direct_pay 生成支付链接，金额由分转元（两位小数）。"""
        order_string = self._client.direct_pay(
            subject=subject,
            out_trade_no=order_id,
            total_amount=f"{amount_cents / 100:.2f}",
            return_url=config.PAY_RETURN_URL,
            notify_url=config.PAY_NOTIFY_URL,
        )
        return f"{config.ALIPAY_GATEWAY_URL}?{order_string}"

    def verify_callback(self, params: dict) -> bool:
        """用支付宝公钥校验异步通知签名，返回签名是否合法。"""
        signature = params.get("sign", "")
        data = {key: value for key, value in params.items() if key not in ("sign", "sign_type")}
        return self._client.verify(data, signature)

    def parse_callback(self, params: dict) -> dict:
        """解析异步通知：订单号取 out_trade_no，交易成功标记为 success。"""
        return {
            "order_id": params.get("out_trade_no"),
            "success": params.get("trade_status") == "TRADE_SUCCESS",
        }
