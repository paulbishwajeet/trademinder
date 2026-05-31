import pytest
from httpx import AsyncClient
from datetime import date

SESSION_PAYLOAD = {
    "ticker": "NVDA",
    "strategy": "WHEEL",
    "status": "put_open",
    "opened_at": str(date.today()),
}

async def test_placeholder(client: AsyncClient):
    # Will be replaced in Task 2 — just confirms import works
    assert True
