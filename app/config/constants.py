POSTGRES_TIMEOUT = 60
BROKER_PUBLISH_TIMEOUT = 10

# Request-body keys whose value is replaced before the body is logged. Matched case-insensitively
# as a substring of the JSON key, so "password" also covers "old_password"/"passwordHash".
LOGGING_SENSITIVE_FIELDS = (
    "password",
    "token",
    "authorization",
    "x-api-key",
)

LOGGING_SENSITIVE_REPLACEMENT = "******"

LOGGING_DISABLED_ENDPOINTS = ("/health",)

# Заголовок сообщения с номером попытки обработки (1 — первая доставка)
HEADER_ATTEMPT = "x-attempt"
# Заголовок с текстом последней ошибки — виден в DLQ и retry-очередях
HEADER_LAST_ERROR = "x-last-error"
