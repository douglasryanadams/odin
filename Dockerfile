FROM python:3.12-slim AS base

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock README.md ./

FROM base AS production

COPY config/gunicorn.conf.py ./
COPY src/ src/

RUN uv sync --frozen --no-dev

# Bundled Chromium with hardened launch args from main.py:lifespan. The other
# anti-fingerprinting measures (--disable-blink-features=AutomationControlled,
# navigator.webdriver init script, viewport jitter, locale/timezone,
# Accept-Language) all work identically on Chromium. Swap to a real-Chrome
# channel here once Google ships a native arm64 build.
RUN uv run playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# Shared storage_state lives here; compose mounts a named volume on top so the
# directory persists across container restarts.
RUN mkdir -p /var/lib/odin/playwright-state

EXPOSE 8000

CMD ["gunicorn", "-c", "gunicorn.conf.py", "odin.main:app"]


FROM production AS development

RUN apt-get update && apt-get install -y --no-install-recommends git libatomic1 \
    && rm -rf /var/lib/apt/lists/*

RUN uv sync --frozen

COPY . .

CMD ["uvicorn", "odin.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
