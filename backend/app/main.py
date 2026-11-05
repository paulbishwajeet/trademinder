# backend/app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.routers import accounts, me, dashboard, trades, commentary, alerts, market, market_data, briefing, categories, positions, signals, sessions, wheel, screener, chain
from app.services.market_data import prime_market_data
from app.services.market_data_errors import MarketDataUnavailable
from app.scheduler import scheduler, start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    await prime_market_data()
    start_scheduler()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="TradeMinder API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # The extension's service worker is cross-origin; it reads the offline flag from this header.
    expose_headers=["X-Market-Data-Offline"],
)


@app.exception_handler(MarketDataUnavailable)
async def market_data_unavailable_handler(request: Request, exc: MarketDataUnavailable):
    """Pure market endpoints: 503 with a structured code the SPA and extension recognise."""
    return JSONResponse(
        status_code=503,
        content={"detail": "Market data offline", "code": MarketDataUnavailable.code},
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


app.include_router(accounts.router)
app.include_router(me.router)
app.include_router(dashboard.router)
app.include_router(trades.router)
app.include_router(commentary.router)
app.include_router(alerts.router)
app.include_router(market.router)
app.include_router(market_data.router)
app.include_router(briefing.router)
app.include_router(categories.router)
app.include_router(positions.router)
app.include_router(signals.router)
app.include_router(sessions.router)
app.include_router(wheel.router)
app.include_router(screener.router)
app.include_router(chain.router)
