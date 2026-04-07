FROM python:3.10-slim
WORKDIR /app

# 1. Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. Копирование кода
COPY . .

# 3. Даем права на выполнение скрипту
RUN chmod +x run.sh

# 4. Запускаем ОДИН командный файл, который поднимет и API, и Бота
CMD ["./run.sh"]