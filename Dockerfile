# syntax=docker/dockerfile:1
# Stage 1: build the database (simulator + dbt)
FROM python:3.13-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /src
COPY requirements.txt requirements-build.txt ./
RUN pip install -r requirements-build.txt
COPY sim ./sim
COPY dbt_project ./dbt_project
COPY scripts ./scripts
RUN python -m scripts.build_data

# Stage 2: slim runtime image (no dbt)
FROM python:3.13-slim
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PLANTOPS_DB=/srv/data/plantops.duckdb PORT=8000
RUN useradd --create-home --uid 10001 appuser
WORKDIR /srv
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY app ./app
COPY sim ./sim
COPY config ./config
COPY --from=build /src/data/plantops.duckdb ./data/plantops.duckdb
USER appuser
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.server:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
