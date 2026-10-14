from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class _BaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent.parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="allow",
    )


class AuthConfig(_BaseSettings):
    AUTH_API_KEY: str


class PostgresConfig(_BaseSettings):
    POSTGRES_HOST: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_POOL_SIZE: int = 5
    POSTGRES_MAX_OVERFLOW: int = 10
    POSTGRES_ECHO: bool | None = None
    POSTGRES_SSL: bool | None = False
    POSTGRES_ISOLATION_LEVEL: str = "READ COMMITTED"

    @property
    def dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@"
            f"{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


class RabbitConfig(_BaseSettings):
    RABBITMQ_HOST: str
    RABBITMQ_PORT: int = 5672
    RABBITMQ_USER: str
    RABBITMQ_PASSWORD: str
    RABBITMQ_VHOST: str = "/"

    @property
    def dsn(self) -> str:
        vhost = "" if self.RABBITMQ_VHOST == "/" else self.RABBITMQ_VHOST
        return (
            f"amqp://{self.RABBITMQ_USER}:{self.RABBITMQ_PASSWORD}@{self.RABBITMQ_HOST}:{self.RABBITMQ_PORT}/{vhost}"
        )


class LogsConfig(_BaseSettings):
    LOGS_IS_ENABLED: bool = True
    LOGS_LEVEL: str = "INFO"
    LOGS_IS_JSON: bool = True


class OutboxConfig(_BaseSettings):
    # Как часто relay проверяет outbox, если в прошлый раз ничего не нашёл
    OUTBOX_POLL_INTERVAL: float = 0.5
    OUTBOX_BATCH_SIZE: int = 100


class ConsumerConfig(_BaseSettings):
    # Всего попыток обработать сообщение, включая первую. После последней — DLQ
    CONSUMER_MAX_ATTEMPTS: int = 3
    # Задержка перед повтором N: base * 2^(N-1) секунд -> 2s, 4s
    CONSUMER_RETRY_BASE_DELAY: float = 2.0
    CONSUMER_PREFETCH_COUNT: int = 10


class GatewayConfig(_BaseSettings):
    """Эмуляция платёжного шлюза: обработка 2-5 сек, 90% успех."""

    GATEWAY_MIN_DELAY: float = 2.0
    GATEWAY_MAX_DELAY: float = 5.0
    GATEWAY_SUCCESS_RATE: float = 0.9


class WebhookConfig(_BaseSettings):
    WEBHOOK_TIMEOUT: float = 10.0


class Config(_BaseSettings):
    auth: AuthConfig
    postgres: PostgresConfig
    rabbit: RabbitConfig
    logs: LogsConfig
    outbox: OutboxConfig
    consumer: ConsumerConfig
    gateway: GatewayConfig
    webhook: WebhookConfig


def get_config() -> Config:
    return Config(
        auth=AuthConfig(),
        postgres=PostgresConfig(),
        rabbit=RabbitConfig(),
        logs=LogsConfig(),
        outbox=OutboxConfig(),
        consumer=ConsumerConfig(),
        gateway=GatewayConfig(),
        webhook=WebhookConfig(),
    )
