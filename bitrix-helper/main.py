import os
import io
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, File, UploadFile, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from PIL import Image
from minio import Minio
from minio.error import S3Error
import httpx

# --- НАСТРОЙКА ЛОГИРОВАНИЯ ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- ИНИЦИАЛИЗАЦИЯ FASTAPI ---
app = FastAPI(
    title="Bitrix-Vision Helper",
    description="Сервис для анализа макетов (Vision) и создания сделок (CRM)",
    version="1.0.0"
)

# Настройка CORS (очень важно для связи с другими сервисами в сети Docker)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Для хакатона можно так
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- ПОДКЛЮЧЕНИЕ К MINIO ---
# Берем настройки из переменных окружения, которые вы задали в docker-compose.yml
MINIO_URL = os.getenv("MINIO_URL", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ROOT_USER", "admin")
MINIO_SECRET_KEY = os.getenv("MINIO_ROOT_PASSWORD", "password")
MINIO_BUCKET = "print-mockups"  # Название корзины для макетов

# Создаем клиент для MinIO
minio_client = Minio(
    MINIO_URL.replace("http://", "").replace("https://", ""),
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False  # Внутри Docker-сети используем HTTP
)

# При запуске проверяем, существует ли наша корзина, и создаем ее, если нет.
try:
    if not minio_client.bucket_exists(MINIO_BUCKET):
        minio_client.make_bucket(MINIO_BUCKET)
        logger.info(f"✅ Bucket '{MINIO_BUCKET}' создан в MinIO")
    else:
        logger.info(f"✅ Bucket '{MINIO_BUCKET}' уже существует")
except S3Error as e:
    logger.error(f"❌ Ошибка подключения к MinIO: {e}")
    logger.warning("⚠️ Сервис запустится, но работа с файлами будет недоступна!")

# --- PYDANTIC МОДЕЛИ (для валидации данных) ---
class AnalyzeResponse(BaseModel):
    """Структура ответа от /analyze"""
    is_ok: bool
    dpi: Optional[int] = None
    color_mode: Optional[str] = None
    width: int
    height: int
    format: str
    warnings: List[str] = []

class DealRequest(BaseModel):
    """Структура запроса на создание сделки от AI Gateway"""
    client_phone: str = Field(..., example="+79123456789")
    client_name: Optional[str] = Field(None, example="Иван Петров")
    description: str = Field(..., example="500 визиток, матовая ламинация")
    file_link: Optional[str] = Field(None, example="http://minio:9000/print-mockups/file.jpg")
    total_price: Optional[float] = Field(0, example=4500.0)

class DealResponse(BaseModel):
    """Структура ответа на создание сделки"""
    status: str = Field(..., example="created")
    deal_id: Optional[str] = Field(None, example="B24_5566")
    crm_url: Optional[str] = Field(None, example="https://...")
    message: str

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

async def save_to_minio(file_data: bytes, filename: str) -> str:
    """Сохраняет файл в MinIO и возвращает его публичный URL."""
    try:
        # Генерируем уникальное имя, чтобы файлы не перезаписывались
        safe_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
        # Сохраняем файл в корзину
        minio_client.put_object(
            MINIO_BUCKET,
            safe_filename,
            io.BytesIO(file_data),
            length=len(file_data),
            content_type="application/octet-stream"
        )
        # Возвращаем URL для доступа к файлу (он будет доступен внутри сети Docker)
        file_url = f"http://minio:9000/{MINIO_BUCKET}/{safe_filename}"
        logger.info(f"✅ Файл сохранен в MinIO: {file_url}")
        return file_url
    except S3Error as e:
        logger.error(f"❌ Ошибка сохранения в MinIO: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка MinIO: {str(e)}")

def analyze_image(image_data: bytes) -> AnalyzeResponse:
    """Анализирует изображение: DPI, цвет, размеры, предупреждения."""
    try:
        img = Image.open(io.BytesIO(image_data))
        width, height = img.size
        img_format = img.format or "unknown"
        color_mode = img.mode
        
        # Попытка получить DPI
        dpi = img.info.get('dpi', (72, 72))
        if isinstance(dpi, tuple):
            dpi = int(dpi[0])
        else:
            dpi = int(dpi)
        
        # Формируем предупреждения для типографии
        warnings = []
        if dpi < 300:
            warnings.append(f"Низкое разрешение: {dpi} DPI (нужно минимум 300 DPI)")
        if color_mode != "CMYK":
            warnings.append(f"Неправильная цветовая модель: {color_mode} (нужна CMYK для печати)")
        if width < 500 or height < 500:
            warnings.append(f"Слишком маленькое изображение: {width}x{height} пикселей")
        
        is_ok = len(warnings) == 0
        
        logger.info(f"📊 Анализ: {width}x{height}, {color_mode}, {dpi} DPI, OK={is_ok}")
        return AnalyzeResponse(
            is_ok=is_ok,
            dpi=dpi,
            color_mode=color_mode,
            width=width,
            height=height,
            format=img_format,
            warnings=warnings
        )
    except Exception as e:
        logger.error(f"❌ Ошибка анализа изображения: {e}")
        raise HTTPException(status_code=400, detail=f"Не удалось обработать изображение: {str(e)}")

async def create_bitrix_deal(deal_info: DealRequest) -> DealResponse:
    """СОЗДАЕТ РЕАЛЬНУЮ СДЕЛКУ В BITRIX24 через Webhook."""
    # !!! ВАЖНО: Замените этот URL на ваш реальный Webhook из Bitrix24 !!!
    # Вы можете получить его, создав входящий вебхук в вашем портале Bitrix24.
    # Пока это демо-заглушка, которая ИМИТИРУЕТ создание сделки,
    # чтобы вы могли протестировать работу прямо сейчас.
    # Для перехода на реальный Bitrix24, просто раскомментируйте нужные строки.
    
    BITRIX_WEBHOOK_URL = os.getenv("BITRIX_WEBHOOK_URL", "")
    
    # Если вебхук НЕ ЗАДАН, работаем в демо-режиме (для хакатона)
    if not BITRIX_WEBHOOK_URL:
        logger.warning("🎭 [DEMO] BITRIX_WEBHOOK_URL не задан. Работаю в демо-режиме.")
        return DealResponse(
            status="created",
            deal_id=f"DEMO_{datetime.now().timestamp()}",
            crm_url="https://demo.bitrix24.ru/crm/deal/",
            message="Сделка создана в ДЕМО-режиме. Подключите реальный Bitrix24."
        )
    
    # --- Реальная интеграция с Bitrix24 ---
    try:
        # Данные для создания сделки в Bitrix24
        deal_data = {
            "fields": {
                "TITLE": f"Заказ от {deal_info.client_name or deal_info.client_phone}",
                "COMMENTS": deal_info.description,
                "OPPORTUNITY": deal_info.total_price,
                "CURRENCY_ID": "BYN",
                "UF_CRM_FILE": deal_info.file_link,  # Кастомное поле для ссылки
                "PHONE": [{"VALUE": deal_info.client_phone, "VALUE_TYPE": "WORK"}],
            }
        }
        
        async with httpx.AsyncClient() as client:
            # Отправляем запрос к Bitrix24
            response = await client.post(
                f"{BITRIX_WEBHOOK_URL}/crm.deal.add.json",
                json=deal_data,
                timeout=30.0
            )
            response.raise_for_status()
            result = response.json()
            
            if "result" in result:
                deal_id = result["result"]
                logger.info(f"✅ Сделка в Bitrix24 создана! ID: {deal_id}")
                return DealResponse(
                    status="created",
                    deal_id=str(deal_id),
                    crm_url=f"https://b24-moawpx.bitrix24.ru/crm/deal/details/{deal_id}/",
                    message="Сделка успешно создана в Bitrix24."
                )
            else:
                error_msg = result.get("error_description", "Неизвестная ошибка")
                logger.error(f"❌ Ошибка Bitrix24: {error_msg}")
                return DealResponse(
                    status="error",
                    message=f"Ошибка Bitrix24: {error_msg}"
                )
    except Exception as e:
        logger.error(f"❌ Ошибка при запросе к Bitrix24: {e}")
        return DealResponse(
            status="error",
            message=f"Ошибка сети или API: {str(e)}"
        )

# --- API ЭНДПОИНТЫ ВАШЕГО СЕРВИСА ---

@app.get("/health", tags=["System"])
async def health_check():
    """Простая проверка, жив ли сервис."""
    return {"status": "ok", "service": "bitrix-helper"}

@app.post("/analyze", response_model=AnalyzeResponse, tags=["Vision"])
async def vision_analyze(file: UploadFile = File(...)):
    """
    Эндпоинт для AI Gateway.
    1. Принимает файл макета.
    2. Сохраняет его в MinIO.
    3. Анализирует на DPI и цветовую модель.
    4. Возвращает результат анализа.
    """
    logger.info(f"🔍 Получен запрос на анализ файла: {file.filename}")
    
    # Читаем содержимое файла
    file_data = await file.read()
    
    # 1. Сохраняем файл в MinIO
    file_url = await save_to_minio(file_data, file.filename)
    
    # 2. Анализируем файл
    analysis_result = analyze_image(file_data)
    
    # 3. Возвращаем результат анализа
    # (AI Gateway сам решит, что делать с этой информацией)
    return analysis_result

@app.post("/create_deal", response_model=DealResponse, tags=["CRM"])
async def crm_create_deal(deal_data: DealRequest):
    """
    Эндпоинт для AI Gateway.
    Принимает детали заказа и создает сделку в Bitrix24.
    """
    logger.info(f"📝 Получен запрос на создание сделки для {deal_data.client_phone}")
    result = await create_bitrix_deal(deal_data)
    return result

@app.get("/", tags=["System"])
async def root():
    """Корневой эндпоинт."""
    return {
        "message": "Bitrix-Vision Helper Service is running!",
        "endpoints": {
            "/health": "GET - Проверка состояния сервиса",
            "/analyze": "POST - Анализ файла макета (требует multipart/form-data с файлом)",
            "/create_deal": "POST - Создание сделки в CRM (требует JSON с данными клиента)"
        }
    }