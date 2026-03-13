FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    build-essential \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install poetry==2.1.3

WORKDIR /app

COPY pyproject.toml poetry.lock* ./

RUN poetry install --only main --no-root

COPY . .
