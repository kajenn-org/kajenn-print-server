# syntax=docker/dockerfile:1
# kajenn-print-server: the print API (HTML -> PDF) on kajenn.

ARG PYTHON_VERSION=3.13

FROM python:${PYTHON_VERSION}-slim AS build
WORKDIR /src
RUN python -m pip install --no-cache-dir build
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src
RUN python -m build --wheel --outdir /dist

FROM python:${PYTHON_VERSION}-slim
# Pango renders the text; the fonts give documents without web fonts a usable default.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        weasyprint \ 
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
        fonts-dejavu-core fonts-liberation2 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /dist/*.whl /tmp/
RUN python -m pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

RUN useradd --system --create-home --home-dir /home/kajenn --uid 10001 kajenn \
    && mkdir -p /data /app \
    && chown kajenn:kajenn /data
COPY examples/print_server/config.py /app/config.py

ENV PYTHONUNBUFFERED=1 \
    KAJENN_HOME=/home/kajenn/.kajenn \
    KAJENN_PRINT_HOME=/data \
    PRINT_AUTH=token

USER kajenn
WORKDIR /app
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/print/health', timeout=4)"]

CMD ["kajenn", "serve", "/app/config.py", "--host", "0.0.0.0", "--port", "8000"]
