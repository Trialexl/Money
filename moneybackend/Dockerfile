FROM postgres:14 AS postgres14-client

FROM python:3.14-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/usr/lib/postgresql/14/bin:${PATH}"

# Keep pg_dump/pg_restore on the same major version as the production database.
# Debian Trixie currently ships a newer client whose archives cannot be restored
# by PostgreSQL 14.
COPY --from=postgres14-client /usr/lib/postgresql/14/bin /usr/lib/postgresql/14/bin

# Устанавливаем системные зависимости
RUN set -eux; \
    for attempt in 1 2 3; do \
        apt-get update && \
        apt-get install -y --no-install-recommends --fix-missing \
            libpq5 \
            netcat-openbsd && \
        rm -rf /var/lib/apt/lists/* && \
        break; \
        echo "apt install failed on attempt ${attempt}, retrying..."; \
        rm -rf /var/lib/apt/lists/*; \
        if [ "$attempt" = "3" ]; then exit 1; fi; \
        sleep 5; \
    done

RUN pg_dump --version | grep -E '^pg_dump \(PostgreSQL\) 14\.' && \
    pg_restore --version | grep -E '^pg_restore \(PostgreSQL\) 14\.'

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файл с зависимостями
COPY requirements.txt .

# Устанавливаем Python зависимости. Docker Hub/PyPI иногда отвечают медленно,
# поэтому явно задаем retries/timeout для воспроизводимой сборки.
RUN python -m pip install --no-cache-dir --retries 10 --timeout 120 -r requirements.txt && \
    python -m pip check

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
