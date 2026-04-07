import os
import asyncio
import logging
import httpx
from io import BytesIO
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, BufferedInputFile
from aiogram.exceptions import TelegramBadRequest
from dotenv import load_dotenv

# Настройка логов, чтобы видеть всё в консоли Docker
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Инициализация
bot = Bot(token="8538173347:AAH2oLjsCCr6Xh3sk5x0JwmQJM3Qpj7IFIk")
dp = Dispatcher()

# URL твоего FastAPI (через Docker-сеть это localhost, если в одном контейнере)
API_URL = "http://localhost:8000/webhook"

# Глобальный клиент с увеличенными таймаутами (ИИ иногда думает долго)
timeout = httpx.Timeout(60.0, connect=10.0)
async_client = httpx.AsyncClient(timeout=timeout)

@dp.message(F.text | F.photo | F.document)
async def handle_any_message(message: Message):
    user_id = str(message.from_user.id)
    prompt_text = message.text or message.caption or ""
    
    # Собираем данные для отправки
    payload = {"user_id": user_id, "text": prompt_text}
    files = None

    try:
        # Визуальный эффект: "Бот печатает..."
        if not (message.photo or message.document):
            await bot.send_chat_action(message.chat.id, action="typing")
        else:
            await bot.send_chat_action(message.chat.id, action="upload_document")

        # Если есть файл - скачиваем его в память
        if message.document or message.photo:
            file_id = message.document.file_id if message.document else message.photo[-1].file_id
            file_info = await bot.get_file(file_id)
            
            # Скачиваем прямо в байты (без сохранения на диск!)
            file_data = await bot.download_file(file_info.file_path)
            file_name = file_info.file_path.split('/')[-1]
            
            # Важно: создаем новый BytesIO для каждого запроса
            files = {"file": (file_name, file_data.getvalue(), "application/octet-stream")}

        # Отправляем запрос в наш AI Gateway
        logger.info(f"Sending request to Gateway for user {user_id}")
        response = await async_client.post(API_URL, data=payload, files=files)
        
        if response.status_code == 200:
            result = response.json()
            ai_answer = result.get("ai_answer", "🤖 Не удалось получить ответ от ИИ.")
            await message.answer(ai_answer, parse_mode="Markdown")
        else:
            logger.error(f"Gateway error: {response.status_code} - {response.text}")
            await message.answer("⚠️ Мой 'мозг' сейчас перегружен. Попробуй чуть позже!")

    except Exception as e:
        logger.exception("Критическая ошибка в боте:")
        await message.answer("❌ Произошла ошибка при связи с сервером. Проверь логи Docker.")

@dp.message()
async def unknown_content(message: Message):
    """Обработка стикеров, голосовых и прочего, что мы пока не умеем"""
    await message.answer("Я пока понимаю только текст и картинки с макетами. Пожалуйста, пришли ТЗ или файл!")

async def main():
    logger.info("🚀 Запуск Telegram интерфейса...")
    try:
        await dp.start_polling(bot, skip_updates=True)
    finally:
        await async_client.aclose()
        logger.info("🛑 Бот остановлен.")

if __name__ == "__main__":
    asyncio.run(main())