# backend/app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import trades, commentary, alerts, market, briefing

app = FastAPI(title="TradeMinder API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


app.include_router(trades.router)
app.include_router(commentary.router)
app.include_router(alerts.router)
app.include_router(market.router)
app.include_router(briefing.router)
