import uuid

import httpx
import structlog

from app.config.config import WebhookConfig

logger = structlog.stdlib.get_logger()


class WebhookDeliveryError(Exception):
    pass


class WebhookClient:
    def __init__(self, config: WebhookConfig):
        self.config = config

    async def send(self, url: str, payload: dict, payment_id: uuid.UUID) -> None:
        """Успех — только 2xx. Сетевая ошибка, таймаут или любой другой код — WebhookDeliveryError."""
        headers = {
            # Получатель может дедуплицировать: при ретраях мы шлём одно и то же событие
            "X-Payment-Id": str(payment_id),
            "X-Event-Id": f"{payment_id}:{payload['status']}",
        }

        try:
            async with httpx.AsyncClient(timeout=self.config.WEBHOOK_TIMEOUT) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as e:
            raise WebhookDeliveryError(f"{type(e).__name__}: {e}") from e

        if not response.is_success:
            raise WebhookDeliveryError(f"Webhook responded with HTTP {response.status_code}")

        logger.info("Webhook delivered", payment_id=str(payment_id), status_code=response.status_code)
