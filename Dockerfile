FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/usr/app \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /usr/app

RUN pip install --no-cache-dir poetry==2.5.1

COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root --no-interaction --no-ansi

COPY . ./

RUN useradd --system --no-create-home app
USER app
