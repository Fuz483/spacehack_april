import os
import json
import logging
import httpx
from fastapi import FastAPI, UploadFile, File, Form
from redis.asyncio import Redis
from dotenv import load_dotenv
from contextlib import asynccontextmanager

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Код при запуске (Startup)
    yield
    # Код при завершении (Shutdown)
    await async_http_client.aclose()
    await redis_client.close()

app = FastAPI(title="Ollama Gateway", lifespan=lifespan)
redis_client = Redis(host='redis', port=6379, decode_responses=True)
async_http_client = httpx.AsyncClient(timeout=60.0)

# URL Ollama внутри сети Docker
OLLAMA_URL = "http://ollama:11434/api/generate"

MODEL_NAME = "gpt-oss:120b-cloud" 

SYSTEM_PROMPT = "Ты эксперт типографии. Уточни что печатаем, сколько и на чем. Будь краток."

@app.post("/webhook")
async def chat_endpoint(user_id: str = Form(...), text: str = Form(None)):
    # 1. Формируем запрос для Ollama
    payload = {
        "model": MODEL_NAME,
        "prompt": f"{SYSTEM_PROMPT}\n\nПользователь: {text}\nОтвет:",
        "stream": False
    }
    
    try:
        r = await async_http_client.post(OLLAMA_URL, json=payload)
        res_json = r.json()
        ai_answer = res_json.get("response", "Ошибка модели")
        
        return {"user_id": user_id, "ai_answer": ai_answer}
    except Exception as e:
        logger.error(f"Ollama error: {e}")
        return {"user_id": user_id, "ai_answer": "Извини, я задумался. Попробуй еще раз!"}
