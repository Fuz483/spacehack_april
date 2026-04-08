import os
import json
import httpx
import uvicorn
from fastapi import FastAPI, Request, BackgroundTasks
from openai import AsyncOpenAI
import redis.asyncio as redis

app = FastAPI(title="AI Orchestrator")

LLM_API_KEY = os.getenv("LLM_API_KEY")
SERVICE_1C_URL = os.getenv("SERVICE_1C_URL")
SERVICE_BITRIX_URL = os.getenv("SERVICE_BITRIX_URL")
REDIS_URL = os.getenv("REDIS_URL")

# Используем Groq API для быстрых и бесплатных ответов
client = AsyncOpenAI(api_key=LLM_API_KEY, base_url="https://api.groq.com/openai/v1")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# ID сотрудников из твоего Битрикса
ROLES = {"economist": 1, "dispatcher": 16, "technologist": 16}


async def process_message(chat_id: str, message_text: str):
    history_str = await redis_client.get(f"chat:{chat_id}")
    if history_str:
        history = json.loads(history_str)
    else:
        history = [{"role": "system", "content": """
        Ты AI-маршрутизатор типографии. Твоя задача выбрать СТРОГО ОДНО действие в формате JSON.
        ПРАВИЛА:
        1. Если клиент прямо спрашивает про НАЛИЧИЕ, ОСТАТКИ или "ЕСТЬ ЛИ НА СКЛАДЕ" (бумага, картон, пленка и т.д.) -> ОБЯЗАТЕЛЬНО верни: {"action": "check_stock", "material": "название"}
        2. Если вопрос про расчет стоимости или цены -> {"action": "transfer", "role": "economist", "summary": "суть"}
        3. Если вопрос про сроки и доставку -> {"action": "transfer", "role": "dispatcher", "summary": "суть"}
        4. Если клиент прислал макет или задает технические вопросы по файлу -> {"action": "transfer", "role": "technologist", "summary": "суть"}
        Отвечай только JSON, без лишнего текста.
        """}]

    history.append({"role": "user", "content": message_text})

    try:
        response = await client.chat.completions.create(
            model="llama3-8b-8192",
            messages=history,
            response_format={"type": "json_object"}
        )
        ai_msg = response.choices[0].message.content
        history.append({"role": "assistant", "content": ai_msg})
        await redis_client.setex(f"chat:{chat_id}", 3600, json.dumps(history))

        decision = json.loads(ai_msg)
        action = decision.get("action")

        async with httpx.AsyncClient() as http:
            if action == "check_stock":
                resp = await http.get(f"{SERVICE_1C_URL}/stock", params={"material_name": decision.get("material")})
                stock_info = resp.json()

                # Добавляем инфу в контекст и просим LLM сформировать ответ клиенту
                history.append({"role": "system", "content": f"Остатки 1С: {stock_info}"})
                history.append(
                    {"role": "system", "content": 'Верни {"action": "reply", "text": "ответ клиенту о наличии"}'})

                resp_2 = await client.chat.completions.create(
                    model="llama3-8b-8192", messages=history, response_format={"type": "json_object"}
                )
                final_decision = json.loads(resp_2.choices[0].message.content)

                # Отправляем ответ клиенту в Битрикс
                await http.post(f"{SERVICE_BITRIX_URL}/send_message", json={
                    "chat_id": chat_id, "message": final_decision.get("text"), "system": "N"
                })

            elif action == "transfer":
                role = decision.get("role")
                target_id = ROLES.get(role, 1)

                # Оставляем скрытое сообщение для сотрудника и переводим диалог
                await http.post(f"{SERVICE_BITRIX_URL}/send_message", json={
                    "chat_id": chat_id, "message": f"🤖 Собранные данные: {decision.get('summary')}", "system": "Y"
                })
                await http.post(f"{SERVICE_BITRIX_URL}/transfer", json={
                    "chat_id": chat_id, "user_id": target_id
                })

    except Exception as e:
        print("Ошибка:", e)


@app.post("/webhook")
async def b24_webhook(request: Request, background_tasks: BackgroundTasks):
    data = await request.form()

    # 1. Распечатаем ВЕСЬ сырой словарь, который прислал Битрикс
    print("=== ПРИШЕЛ ВЕБХУК ОТ БИТРИКСА ===", flush=True)
    print(dict(data), flush=True)

    author_id = data.get("data[PARAMS][AUTHOR_ID]")
    chat_id = data.get("data[PARAMS][CHAT_ID]")
    message = data.get("data[PARAMS][MESSAGE]")

    # 2. Посмотрим, смог ли код вытащить нужные поля
    print(f"РАЗОБРАЛИ: AUTHOR_ID={author_id}, CHAT_ID={chat_id}, MESSAGE={message}", flush=True)

    # Игнорируем сообщения от самого бота/сотрудников
    if author_id != "0":
        if chat_id and message:
            print("-> УСПЕХ! Отправляем в background_task думать...", flush=True)
            background_tasks.add_task(process_message, chat_id, message)
        else:
            print("-> ОШИБКА: chat_id или message пустые! Нейросеть не запустится.", flush=True)
    else:
        print("-> ИГНОР: это сообщение от самого бота/сотрудника", flush=True)

    return {"status": "ok"}


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)