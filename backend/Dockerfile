# Production image for the API and worker. Build with the repo root as
# context: `docker build -f backend/Dockerfile .` (docker-compose.prod.yml
# does this for you). Multi-stage so build tools (needed for
# ortools/lightgbm/pymc's compiled dependencies) don't end up in the final
# image.
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY backend/pyproject.toml ./backend/
COPY backend/app ./backend/app
COPY backend/policies ./backend/policies
COPY sim ./sim
COPY ml ./ml

RUN pip install --no-cache-dir --prefix=/install ./backend

FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 valet

COPY --from=builder /install /usr/local
WORKDIR /app
COPY backend/app ./app
COPY backend/policies ./policies
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
COPY sim /sim
COPY ml /ml
ENV PYTHONPATH=/:/app

USER valet
EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
