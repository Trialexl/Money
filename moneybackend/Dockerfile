FROM python:3.10-slim-bookworm

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
        sleep 5; \
    done

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файл с зависимостями
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir gunicorn

# Копируем код приложения
COPY . .

# Копируем и делаем исполняемым entrypoint скрипт
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Открываем порт
EXPOSE 8000

# Устанавливаем entrypoint
ENTRYPOINT ["/docker-entrypoint.sh"]

# Команда по умолчанию для запуска
CMD ["gunicorn", "lk.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]
