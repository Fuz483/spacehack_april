import os
import io
import httpx
import uvicorn
from datetime import datetime
from fastapi import FastAPI, File, UploadFile, HTTPException
from pydantic import BaseModel
from PIL import Image
from minio import Minio

app = FastAPI(title="Bitrix Helper")

BITRIX_WEBHOOK_URL = os.getenv("BITRIX_WEBHOOK_URL")
MINIO_URL = os.getenv("MINIO_URL", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ROOT_USER", "admin")
MINIO_SECRET_KEY = os.getenv("MINIO_ROOT_PASSWORD", "password")
MINIO_BUCKET = "print-mockups"

minio_client = Minio(
    MINIO_URL.replace("http://", "").replace("https://", ""),
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False
)

try:
    if not minio_client.bucket_exists(MINIO_BUCKET):
        minio_client.make_bucket(MINIO_BUCKET)
except Exception as e:
    print(f"Ошибка MinIO: {e}")


class TransferRequest(BaseModel):
    chat_id: str
    user_id: int


class MessageRequest(BaseModel):
    chat_id: str
    message: str
    system: str = "N"


# --- Эндпоинты для Оркестратора (Маршрутизация CRM) ---

@app.post("/transfer")
async def transfer_chat(req: TransferRequest):
    # Добавляем лог перед отправкой
    print(f"--- ПОПЫТКА ПЕРЕВОДА ЧАТА {req.chat_id} НА USER {req.user_id} ---", flush=True)

    async with httpx.AsyncClient() as client:
        # Используем params для надежности (Битрикс это любит)
        resp = await client.post(
            f"{BITRIX_WEBHOOK_URL}imopenlines.operator.transfer",
            params={
                "CHAT_ID": req.chat_id,
                "TRANSFER_ID": req.user_id
            }
        )

        result = resp.json()
        # Логируем ответ от Битрикса
        print(f"--- ОТВЕТ БИТРИКСА: {result} ---", flush=True)

        return result


@app.post("/send_message")
async def send_message(req: MessageRequest):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BITRIX_WEBHOOK_URL}im.message.add",
            json={"CHAT_ID": req.chat_id, "MESSAGE": req.message, "SYSTEM": req.system}
        )
        return resp.json()


# --- Эндпоинты для Vision и файлов ---

@app.post("/analyze")
async def vision_analyze(file: UploadFile = File(...)):
    file_data = await file.read()

    # Сохранение в MinIO
    safe_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
    minio_client.put_object(
        MINIO_BUCKET, safe_filename, io.BytesIO(file_data),
        length=len(file_data), content_type="application/octet-stream"
    )

    # Анализ
    img = Image.open(io.BytesIO(file_data))
    width, height = img.size
    dpi = img.info.get('dpi', (72, 72))
    dpi_val = int(dpi[0]) if isinstance(dpi, tuple) else int(dpi)

    warnings = []
    if dpi_val < 300: warnings.append(f"Низкое разрешение: {dpi_val} DPI")
    if img.mode != "CMYK": warnings.append(f"Цветовая модель: {img.mode} (нужна CMYK)")

    return {
        "file_url": f"http://localhost:9000/{MINIO_BUCKET}/{safe_filename}",
        "width": width, "height": height, "dpi": dpi_val,
        "is_ok": len(warnings) == 0, "warnings": warnings
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)