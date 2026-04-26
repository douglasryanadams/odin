FROM python:3.12-slim AS base

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml uv.lock ./


FROM base AS production

RUN uv sync --frozen --no-dev

COPY main.py gunicorn.conf.py ./

EXPOSE 8000

CMD ["gunicorn", "-c", "gunicorn.conf.py", "main:app"]


FROM production AS development

RUN apt-get update && apt-get install -y --no-install-recommends git libatomic1 \
    && rm -rf /var/lib/apt/lists/*

RUN uv sync --frozen

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
