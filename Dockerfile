# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 VAULT_DATA_DIR=/data
COPY requirements.txt .
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then PIP_CERT=/run/secrets/proxy_ca pip install --no-cache-dir -r requirements.txt; \
    else pip install --no-cache-dir -r requirements.txt; fi
COPY app ./app
COPY custom_nodes ./custom_nodes
RUN useradd --uid 10001 --create-home vault && mkdir /data && chown -R vault:vault /app /data
USER vault
EXPOSE 8088
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8088/api/health', timeout=2)"
CMD ["python", "-m", "app", "--host", "0.0.0.0"]
