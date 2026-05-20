# backend/app/services/technicals_fetcher.py
import yfinance as yf
import pandas as pd

from app.services.price_fetcher import _compute_rsi_14


def _compute_macd_weekly(close_w: pd.Series) -> dict[str, str]:
    if len(close_w) < 26:
        return {"macd_signal": "neutral", "macd_notes": "below 0 line"}
    exp1 = close_w.ewm(span=12, adjust=False).mean()
    exp2 = close_w.ewm(span=26, adjust=False).mean()
    macd_line = exp1 - exp2
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    last_macd = float(macd_line.iloc[-1])
    last_signal = float(signal_line.iloc[-1])
    if last_macd > last_signal:
        macd_signal = "bullish"
    elif last_macd < last_signal:
        macd_signal = "bearish"
    else:
        macd_signal = "neutral"
    macd_notes = "above 0 line" if last_macd > 0 else "below 0 line"
    return {"macd_signal": macd_signal, "macd_notes": macd_notes}


def _bollinger_position(price: float, upper: float, mid: float, lower: float) -> str:
    band_width = upper - lower
    if band_width == 0:
        return "mid"
    upper_zone = mid + (band_width * 0.25)
    lower_zone = mid - (band_width * 0.25)
    if price > upper:
        return "above_upper"
    if price > upper_zone:
        return "near_upper"
    if price < lower:
        return "below_lower"
    if price < lower_zone:
        return "near_lower"
    return "mid"


def _infer_sentiment(macd_signal: str, price: float, ma_50d: float | None, rsi_14: float | None) -> str:
    if ma_50d is None:
        return "neutral"
    if macd_signal == "bullish" and price > ma_50d and (rsi_14 is None or rsi_14 <= 70):
        return "bullish"
    if macd_signal == "bearish" and price < ma_50d:
        return "bearish"
    return "neutral"


def _get_next_earnings(ticker: str) -> str | None:
    try:
        cal = yf.Ticker(ticker).calendar
        if not cal:
            return None
        dates = cal.get("Earnings Date")
        if not dates:
            return None
        if isinstance(dates, list) and dates:
            return str(dates[0])[:10]
        return str(dates)[:10]
    except Exception:
        return None


def fetch_technicals(ticker: str) -> dict:
    try:
        df_d = yf.download(ticker, period="200d", interval="1d", progress=False, auto_adjust=True)
        if df_d is None or df_d.empty:
            return {"fetch_status": "error", "fetch_error": f"No daily data for {ticker}"}

        close_d = df_d["Close"]
        if isinstance(close_d, pd.DataFrame):
            close_d = close_d.iloc[:, 0]
        close_d = close_d.dropna()

        if len(close_d) < 2:
            return {"fetch_status": "error", "fetch_error": f"Insufficient daily history for {ticker}"}

        df_w = yf.download(ticker, period="2y", interval="1wk", progress=False, auto_adjust=True)
        close_w = pd.Series(dtype=float)
        if df_w is not None and not df_w.empty:
            close_w = df_w["Close"]
            if isinstance(close_w, pd.DataFrame):
                close_w = close_w.iloc[:, 0]
            close_w = close_w.dropna()

        price = round(float(close_d.iloc[-1]), 2)
        prev_price = round(float(close_d.iloc[-2]), 2)
        day_color = "green" if price >= prev_price else "red"

        rsi_14 = _compute_rsi_14(close_d)
        rsi_result = None
        if rsi_14 is not None:
            if rsi_14 < 30:
                rsi_result = "rsi_oversold"
            elif rsi_14 > 70:
                rsi_result = "rsi_overbought"

        ma_200d = round(float(close_d.rolling(200).mean().iloc[-1]), 2) if len(close_d) >= 200 else None
        ma_50d = round(float(close_d.rolling(50).mean().iloc[-1]), 2) if len(close_d) >= 50 else None

        price_vs_ma200 = ("above" if price > ma_200d else "below") if ma_200d is not None else None
        price_vs_ma50 = ("above" if price > ma_50d else "below") if ma_50d is not None else None

        rolling_mean = close_d.rolling(20).mean()
        rolling_std = close_d.rolling(20).std()
        b_mid = round(float(rolling_mean.iloc[-1]), 2) if len(close_d) >= 20 else None
        b_upper = round(float((rolling_mean + rolling_std * 2).iloc[-1]), 2) if len(close_d) >= 20 else None
        b_lower = round(float((rolling_mean - rolling_std * 2).iloc[-1]), 2) if len(close_d) >= 20 else None
        b_pos = _bollinger_position(price, b_upper, b_mid, b_lower) if (b_upper is not None and b_mid is not None and b_lower is not None) else None

        macd = _compute_macd_weekly(close_w)
        sentiment = _infer_sentiment(macd["macd_signal"], price, ma_50d, rsi_14)
        next_earnings = _get_next_earnings(ticker)

        return {
            "macd_signal": macd["macd_signal"],
            "macd_notes": macd["macd_notes"],
            "rsi_14": rsi_14,
            "rsi_result": rsi_result,
            "ma_200d": ma_200d,
            "ma_50d": ma_50d,
            "price_vs_ma200": price_vs_ma200,
            "price_vs_ma50": price_vs_ma50,
            "bollinger_upper": b_upper,
            "bollinger_mid": b_mid,
            "bollinger_lower": b_lower,
            "bollinger_position": b_pos,
            "day_color": day_color,
            "price_action": str(price),
            "sentiment": sentiment,
            "next_earnings_date": next_earnings,
            "notes": None,
            "fetch_status": "ok",
            "fetch_error": None,
        }
    except Exception as exc:
        return {"fetch_status": "error", "fetch_error": str(exc)}
