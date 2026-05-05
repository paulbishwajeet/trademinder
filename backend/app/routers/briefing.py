# backend/app/routers/briefing.py
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/briefing", tags=["briefing"])

NOT_IMPLEMENTED = JSONResponse({"detail": "not implemented"}, status_code=501)


@router.get("/today")
async def get_today_briefing():
    return NOT_IMPLEMENTED


@router.post("/generate")
async def generate_briefing():
    return NOT_IMPLEMENTED


@router.get("/{briefing_date}")
async def get_briefing_by_date(briefing_date: str):
    return NOT_IMPLEMENTED
