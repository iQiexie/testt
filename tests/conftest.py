import os

# Интеграционные тесты работают в отдельной базе, чтобы не трогать данные запущенного стека.
# Выставляем до импорта приложения: pydantic-settings читает переменные окружения раньше .env
os.environ["POSTGRES_DB"] = os.environ.get("TEST_POSTGRES_DB", "payments_test")
os.environ.setdefault("LOGS_IS_JSON", "False")
