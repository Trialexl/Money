FROM python:3.10-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Устанавливаем системные зависимости
RUN set -eux; \
    for attempt in 1 2 3; do \
        apt-get update && \
        apt-get install -y --no-install-recommends --fix-missing \
            postgresql-client \
            build-essential \
            libpq-dev \
            netcat-openbsd && \
        rm -rf /var/lib/apt/lists/* && \
        break; \
        echo "apt install failed on attempt ${attempt}, retrying..."; \
        rm -rf /var/lib/apt/lists/*; \
        if [ "$attempt" = "3" ]; then exit 1; fi; \
        sleep 5; \
    done

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файл с зависимостями
COPY requirements.txt .

# Устанавливаем Python зависимости. Docker Hub/PyPI иногда отвечают медленно,
# поэтому явно задаем retries/timeout для воспроизводимой сборки.
RUN pip install --no-cache-dir --retries 10 --timeout 120 -r requirements.txt

# Копируем код приложения
COPY . .

# Копируем и делаем исполняемым entrypoint скрипт
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Открываем порт
EXPOSE 8000

# Устанавливаем entrypoint
ENTRYPOINT ["/docker-entrypoint.sh"]

# Один ASGI-процесс обслуживает Django и OAuth MCP.
CMD ["uvicorn", "mcp_gateway.combined:application", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=*"]
