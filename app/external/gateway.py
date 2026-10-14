import asyncio
import random
import uuid
from decimal import Decimal

import structlog

from app.config.config import GatewayConfig

logger = structlog.stdlib.get_logger()


class PaymentGatewayEmulator:
    """Эмуляция внешнего платёжного шлюза: отвечает за 2-5 сек, 90% платежей проходят."""

    def __init__(self, config: GatewayConfig):
        self.config = config

    async def charge(self, payment_id: uuid.UUID, amount: Decimal, currency: str) -> bool:
        delay = random.uniform(self.config.GATEWAY_MIN_DELAY, self.config.GATEWAY_MAX_DELAY)
        await asyncio.sleep(delay)

        succeeded = random.random() < self.config.GATEWAY_SUCCESS_RATE
        logger.info(
            "Gateway charge finished",
            payment_id=str(payment_id),
            amount=str(amount),
            currency=currency,
            succeeded=succeeded,
            delay=round(delay, 3),
        )
        return succeeded
