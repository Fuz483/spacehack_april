FROM python:3.10-slim

# Устанавливаем системные зависимости для Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код сервиса
COPY . .

# Запускаем сервер на порту 8002 (как в docker-compose)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]