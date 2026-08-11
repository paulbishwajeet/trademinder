# backend/app/services/screener_fetcher.py
import logging

from app.services.schwab_client import get_schwab_client, SchwabAPIError
from app.services.technicals_fetcher import fetch_technicals, compute_iv_percentile_from_chain

log = logging.getLogger(__name__)


def fetch_screener_row(ticker: str, existing_sector: str | None = None) -> dict:
    """Fetch a full screener snapshot for one ticker: quote, technicals, IV
    percentile, and best-effort sector. Never raises — on any failure returns
    {"fetch_status": "error", "fetch_error": <str>} (a partial dict; other
    keys are absent, not None, so callers must use .get())."""
    try:
        technicals, close_d = fetch_technicals(ticker, return_closes=True)
        if technicals.get("fetch_status") != "ok":
            return {"fetch_status": "error", "fetch_error": technicals.get("fetch_error")}

        client = get_schwab_client()

        quotes = client.get_quotes([ticker])
        quote = quotes.get(ticker, {})
        price = quote.get("lastPrice") or quote.get("mark")
        prev_close = quote.get("closePrice")
        if price is None:
            return {"fetch_status": "error", "fetch_error": f"No quote for {ticker}"}
        price = float(price)
        change_pct = (
            round((price - float(prev_close)) / float(prev_close) * 100, 2)
            if prev_close else None
        )

        chain = client.get_option_chain(ticker, contract_type="CALL", strike_count=30)
        iv_percentile, _atm_iv = compute_iv_percentile_from_chain(close_d, chain, ticker)

        sector = existing_sector
        try:
            fundamental = client.get_instrument_fundamentals(ticker)
            fetched_sector = fundamental.get("sector")
            if fetched_sector:
                sector = fetched_sector
        except Exception:
            log.warning("Sector lookup failed for %s", ticker, exc_info=True)

        return {
            "sector": sector,
            "price": round(price, 2),
            "prev_close": round(float(prev_close), 2) if prev_close else None,
            "change_pct": change_pct,
            "iv_rank": None,
            "iv_percentile": iv_percentile,
            "rsi_14": technicals.get("rsi_14"),
            "macd_weekly_signal": technicals.get("macd_signal"),
            "macd_daily_signal": technicals.get("macd_daily_cross_direction") or "neutral",
            "ma_20d": technicals.get("ma_20d"),
            "ma_50d": technicals.get("ma_50d"),
            "ma_100d": technicals.get("ma_100d"),
            "ma_200d": technicals.get("ma_200d"),
            "bollinger_upper": technicals.get("bollinger_upper"),
            "bollinger_mid": technicals.get("bollinger_mid"),
            "bollinger_lower": technicals.get("bollinger_lower"),
            "bollinger_position": technicals.get("bollinger_position"),
            "next_earnings_date": technicals.get("next_earnings_date"),
            "volume_spikes": technicals.get("volume_spikes"),
            "fetch_status": "ok",
            "fetch_error": None,
        }
    except SchwabAPIError as exc:
        return {"fetch_status": "error", "fetch_error": str(exc)}
    except Exception as exc:
        log.exception("fetch_screener_row failed for %s", ticker)
        return {"fetch_status": "error", "fetch_error": str(exc)}
