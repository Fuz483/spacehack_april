# Используем максимально легкий образ Python 3.10
FROM python:3.10-slim

# Рабочая директория
WORKDIR /app

# Копируем requirements и ставим зависимости (кэшируем слой)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем остальной код
COPY . .

# Пробрасываем порт
EXPOSE 8001

# Команда запуска FastAPI сервера
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]