# Bilshenz Binance bridge — Ubuntu 24.04 / DigitalOcean
FROM python:3.12-slim-bookworm

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8766 \
    LOG_DIR=/var/log/bilshenz

RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY binance_trading_system/python/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY binance_trading_system/python/ /app/

RUN mkdir -p /var/log/bilshenz

EXPOSE 8766

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8766/health || exit 1

CMD ["python", "main.py"]
