import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Мок 1С Сервиса")

class StockResponse(BaseModel):
    available: bool
    current_balance: int
    unit: str

FAKE_DB = {
    "бумага": {"balance": 5000, "unit": "листов"},
    "картон": {"balance": 0, "unit": "листов"},
    "пленка": {"balance": 200, "unit": "рулонов"}
}

@app.get("/stock", response_model=StockResponse)
async def stock(material_name: str):
    material = material_name.lower()
    for key, data in FAKE_DB.items():
        if key in material:
            return StockResponse(
                available=data["balance"] > 0,
                current_balance=data["balance"],
                unit=data["unit"]
            )
    return StockResponse(available=False, current_balance=0, unit="шт")

@app.post("/calculate")
async def calculate(req: dict):
    return {"status": "success", "total_price": 4500.0, "currency": "RUB"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)