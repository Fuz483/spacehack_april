from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI(title="Mock 1C API для типографии")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- IN-MEMORY БАЗА ДАННЫХ (Прайс-лист и Склад) ---
PRICE_LIST = {
    "items": {
        "визитки": 5,
        "листовки": 15,
        "блокноты": 50
    },
    "options": {
        "ламинация": 1000,
        "скругление углов": 500
    }
}

STOCK = {
    "мелованная 300г": {"balance": 15000, "unit": "листов", "alternatives": ["матовая 250г", "лен"]},
    "матовая 250г": {"balance": 5000, "unit": "листов", "alternatives": ["мелованная 300г"]},
    "лен": {"balance": 0, "unit": "листов", "alternatives": ["мелованная 300г", "матовая 250г"]}
}


# --- PYDANTIC СХЕМЫ ---
class CalculationRequest(BaseModel):
    item: str
    quantity: int
    material: str
    options: List[str] = []


class StockResponse(BaseModel):
    available: bool
    current_balance: int
    unit: str
    alternatives: List[str]


# --- ЭНДПОИНТЫ ---
@app.post("/calculate")
async def calculate(req: CalculationRequest):
    print(f"Считаю заказ на {req.quantity} {req.item}")
    mat_stock = STOCK.get(req.material)
    if not mat_stock or mat_stock["balance"] < req.quantity:
        alts = mat_stock["alternatives"] if mat_stock else ["стандартная бумага"]
        return {
            "status": "warning",
            "message": f"Этого материала сейчас нет в нужном объеме, но есть вот это: {', '.join(alts)}",
            "alternatives": alts
        }


    base_price = PRICE_LIST["items"].get(req.item.lower(), 10)
    total = base_price * req.quantity
    for opt in req.options:
        total += PRICE_LIST["options"].get(opt.lower(), 0)

    return {
        "price": total,
        "currency": "BYN",
        "days": 2,
        "status": "success"
    }


@app.get("/stock", response_model=StockResponse)
async def stock(material_name: str):
    mat = STOCK.get(material_name.lower())

    if not mat:
        return StockResponse(available=False, current_balance=0, unit="шт", alternatives=[])

    return StockResponse(
        available=mat["balance"] > 0,
        current_balance=mat["balance"],
        unit=mat["unit"],
        alternatives=mat["alternatives"]
    )