from faststream.rabbit import RabbitBroker

from app.config.config import Config
from app.external.gateway import PaymentGatewayEmulator
from app.external.webhook import WebhookClient


class Adapters:
    def __init__(self, config: Config):
        self.config = config

        self.broker = RabbitBroker(url=config.rabbit.dsn)
        self.gateway = PaymentGatewayEmulator(config=config.gateway)
        self.webhook = WebhookClient(config=config.webhook)
