# backend/app/main.py
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import settings
from app.deps import get_current_user
from app.routers import accounts, admin, auth, extension, me, dashboard, trades, commentary, alerts, market, market_data, briefing, categories, positions, signals, sessions, wheel, screener, chain
from app.services.account_facts import AccountFactsError
from app.services.market_data import prime_market_data
from app.services.market_data_errors import MarketDataUnavailable
from app.scheduler import scheduler, start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    await prime_market_data()
    start_scheduler()
    yield
    scheduler.shutdown(wait=False)


# Every route is behind auth, so the schema stays private in production (https).
_docs = not settings.secure_cookies
app = FastAPI(
    title="TradeMinder API", version="0.3.0", lifespan=lifespan,
    docs_url="/docs" if _docs else None, redoc_url="/redoc" if _docs else None,
    openapi_url="/openapi.json" if _docs else None,
)

# The SPA and the API share one origin (Traefik), so the browser needs no CORS. Only the allow-listed
# extensions may call cross-origin, with a bearer token (no cookies).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[f"chrome-extension://{ext_id}" for ext_id in settings.extension_id_list],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    # The extension's service worker reads the market data offline flag from this header.
    expose_headers=["X-Market-Data-Offline"],
)


@app.exception_handler(AccountFactsError)
async def account_facts_error_handler(request: Request, exc: AccountFactsError):
    """Impossible account-fact combinations: 422 with a code and the fields to highlight."""
    return JSONResponse(status_code=422, content={"detail": exc.detail, "code": exc.code, "fields": exc.fields})


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


# Auth routes and /api/me sit outside the seam (/api/me allows pending users). Every other router is
# behind it here, so a route can't be left unauthenticated by forgetting a dependency.
app.include_router(auth.router)
app.include_router(me.router)
_signed_in = [Depends(get_current_user)]
for _module in (admin, extension, accounts, dashboard, trades, commentary, alerts, market, market_data, briefing, categories, positions, signals, sessions, wheel, screener, chain):
    app.include_router(_module.router, dependencies=_signed_in)
