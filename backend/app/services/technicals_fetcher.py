# backend/app/services/technicals_fetcher.py
import pandas as pd

from app.services.price_fetcher import _compute_rsi_14
from app.services.schwab_client import get_schwab_client, SchwabAPIError


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


_NONE_CROSSOVER_FIELDS: dict = {
    "cross_date": None,
    "cross_direction": None,
    "periods_since_cross": None,
    "strength_score": None,
    "trend": None,
}


def _macd_crossover_state(close: pd.Series) -> dict:
    if len(close) < 35:
        return dict(_NONE_CROSSOVER_FIELDS)

    exp1 = close.ewm(span=12, adjust=False).mean()
    exp2 = close.ewm(span=26, adjust=False).mean()
    macd_line = exp1 - exp2
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    diff = macd_line - signal_line

    sign = diff.apply(lambda x: 1 if x > 0 else -1)
    crossovers = sign[sign != sign.shift(1)].iloc[1:]
    if crossovers.empty:
        return dict(_NONE_CROSSOVER_FIELDS)

    last_cross_date = crossovers.index[-1]
    direction = "bullish" if crossovers.iloc[-1] == 1 else "bearish"

    since = diff[diff.index >= last_cross_date]
    periods_since = len(since) - 1

    if direction == "bullish":
        peak_val = float(since.max())
        peak_date = since.idxmax()
    else:
        peak_val = float(since.min())
        peak_date = since.idxmin()

    current = float(since.iloc[-1])
    score = round((current / peak_val) * 100, 1) if peak_val != 0 else 0.0

    if peak_date == since.index[-1]:
        trend = "expanding"
    elif score >= 70:
        trend = "holding_strong"
    elif score >= 30:
        trend = "squeezing"
    else:
        trend = "fading_near_flip"

    return {
        "cross_date": str(last_cross_date.date()),
        "cross_direction": direction,
        "periods_since_cross": periods_since,
        "strength_score": score,
        "trend": trend,
    }


_NONE_RSI_CROSSOVER_FIELDS: dict = {
    "rsi_14": None,
    "rsi_ma_14": None,
    "cross_date": None,
    "cross_direction": None,
    "periods_since_cross": None,
    "strength_score": None,
    "trend": None,
}


def _rsi_crossover_state(close: pd.Series) -> dict:
    if len(close) < 15:
        return dict(_NONE_RSI_CROSSOVER_FIELDS)

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = (100 - (100 / (1 + rs))).fillna(100)

    rsi_14 = round(float(rsi.iloc[-1]), 2)
    rsi_ma = rsi.rolling(14).mean()
    rsi_ma_14 = round(float(rsi_ma.iloc[-1]), 2) if not pd.isna(rsi_ma.iloc[-1]) else None

    diff = (rsi - rsi_ma).dropna()
    if len(diff) < 35:
        return {**_NONE_RSI_CROSSOVER_FIELDS, "rsi_14": rsi_14, "rsi_ma_14": rsi_ma_14}

    sign = diff.apply(lambda x: 1 if x > 0 else -1)
    crossovers = sign[sign != sign.shift(1)].iloc[1:]
    if crossovers.empty:
        return {**_NONE_RSI_CROSSOVER_FIELDS, "rsi_14": rsi_14, "rsi_ma_14": rsi_ma_14}

    last_cross_date = crossovers.index[-1]
    direction = "bullish" if crossovers.iloc[-1] == 1 else "bearish"

    since = diff[diff.index >= last_cross_date]
    periods_since = len(since) - 1

    if direction == "bullish":
        peak_val = float(since.max())
        peak_date = since.idxmax()
    else:
        peak_val = float(since.min())
        peak_date = since.idxmin()

    current = float(since.iloc[-1])
    score = round((current / peak_val) * 100, 1) if peak_val != 0 else 0.0

    if peak_date == since.index[-1]:
        trend = "expanding"
    elif score >= 70:
        trend = "holding_strong"
    elif score >= 30:
        trend = "squeezing"
    else:
        trend = "fading_near_flip"

    return {
        "rsi_14": rsi_14,
        "rsi_ma_14": rsi_ma_14,
        "cross_date": str(last_cross_date.date()),
        "cross_direction": direction,
        "periods_since_cross": periods_since,
        "strength_score": score,
        "trend": trend,
    }


def _detect_volume_spikes(
    volume: pd.Series,
    lookback_days: int = 10,
    baseline_days: int = 20,
    threshold: float = 2.0,
) -> list[dict]:
    spikes = []
    n = len(volume)
    for i in range(max(0, n - lookback_days), n):
        baseline = volume.iloc[max(0, i - baseline_days):i]
        if len(baseline) < baseline_days:
            continue
        avg = float(baseline.mean())
        if avg <= 0:
            continue
        today = float(volume.iloc[i])
        ratio = round(today / avg, 2)
        if ratio >= threshold:
            spikes.append({
                "date": str(volume.index[i].date()),
                "volume": int(today),
                "avg_volume": int(avg),
                "ratio": ratio,
            })
    return spikes


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
    import yfinance as yf
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


def fetch_technicals(ticker: str, return_closes: bool = False) -> dict | tuple[dict, pd.Series]:
    try:
        client = get_schwab_client()

        df_d = client.get_price_history(ticker, "year", 1, "daily", 1)
        if df_d is None or df_d.empty:
            err = {"fetch_status": "error", "fetch_error": f"No daily data for {ticker}"}
            return (err, pd.Series(dtype=float)) if return_closes else err

        close_d = df_d["Close"].dropna()
        if len(close_d) < 2:
            err = {"fetch_status": "error", "fetch_error": f"Insufficient daily history for {ticker}"}
            return (err, pd.Series(dtype=float)) if return_closes else err

        volume_d = df_d["Volume"].dropna()

        df_w = client.get_price_history(ticker, "year", 2, "weekly", 1)
        close_w = pd.Series(dtype=float)
        if df_w is not None and not df_w.empty:
            close_w = df_w["Close"].dropna()

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
        ma_100d = round(float(close_d.rolling(100).mean().iloc[-1]), 2) if len(close_d) >= 100 else None
        ma_50d = round(float(close_d.rolling(50).mean().iloc[-1]), 2) if len(close_d) >= 50 else None
        ma_20d = round(float(close_d.rolling(20).mean().iloc[-1]), 2) if len(close_d) >= 20 else None

        price_vs_ma200 = ("above" if price > ma_200d else "below") if ma_200d is not None else None
        price_vs_ma100 = ("above" if price > ma_100d else "below") if ma_100d is not None else None
        price_vs_ma50 = ("above" if price > ma_50d else "below") if ma_50d is not None else None
        price_vs_ma20 = ("above" if price > ma_20d else "below") if ma_20d is not None else None

        rolling_mean = close_d.rolling(20).mean()
        rolling_std = close_d.rolling(20).std()
        b_mid = round(float(rolling_mean.iloc[-1]), 2) if len(close_d) >= 20 else None
        b_upper = round(float((rolling_mean + rolling_std * 2).iloc[-1]), 2) if len(close_d) >= 20 else None
        b_lower = round(float((rolling_mean - rolling_std * 2).iloc[-1]), 2) if len(close_d) >= 20 else None
        b_pos = (
            _bollinger_position(price, b_upper, b_mid, b_lower)
            if (b_upper is not None and b_mid is not None and b_lower is not None)
            else None
        )

        macd = _compute_macd_weekly(close_w)
        weekly_crossover = _macd_crossover_state(close_w)
        daily_crossover = _macd_crossover_state(close_d)
        rsi_crossover = _rsi_crossover_state(close_d)
        volume_spikes = _detect_volume_spikes(volume_d)
        sentiment = _infer_sentiment(macd["macd_signal"], price, ma_50d, rsi_14)
        next_earnings = _get_next_earnings(ticker)

        result = {
            "macd_signal": macd["macd_signal"],
            "macd_notes": macd["macd_notes"],
            **{f"macd_weekly_{k}": v for k, v in weekly_crossover.items()},
            **{f"macd_daily_{k}": v for k, v in daily_crossover.items()},
            "rsi_14": rsi_14,
            "rsi_result": rsi_result,
            "rsi_ma_14": rsi_crossover["rsi_ma_14"],
            "rsi_cross_date": rsi_crossover["cross_date"],
            "rsi_cross_direction": rsi_crossover["cross_direction"],
            "rsi_periods_since_cross": rsi_crossover["periods_since_cross"],
            "rsi_strength_score": rsi_crossover["strength_score"],
            "rsi_trend": rsi_crossover["trend"],
            "volume_spikes": volume_spikes,
            "ma_200d": ma_200d,
            "ma_100d": ma_100d,
            "ma_50d": ma_50d,
            "ma_20d": ma_20d,
            "price_vs_ma200": price_vs_ma200,
            "price_vs_ma100": price_vs_ma100,
            "price_vs_ma50": price_vs_ma50,
            "price_vs_ma20": price_vs_ma20,
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
        return (result, close_d) if return_closes else result

    except SchwabAPIError as exc:
        err = {"fetch_status": "error", "fetch_error": str(exc)}
        return (err, pd.Series(dtype=float)) if return_closes else err
    except Exception as exc:
        err = {"fetch_status": "error", "fetch_error": str(exc)}
        return (err, pd.Series(dtype=float)) if return_closes else err


def fetch_macd_crossover(ticker: str) -> dict:
    try:
        client = get_schwab_client()
        df_w = client.get_price_history(ticker, "year", 2, "weekly", 1)
        df_d = client.get_price_history(ticker, "year", 1, "daily", 1)
    except SchwabAPIError as exc:
        return {
            "weekly": dict(_NONE_CROSSOVER_FIELDS),
            "daily": dict(_NONE_CROSSOVER_FIELDS),
            "fetch_status": "error",
            "fetch_error": str(exc),
        }

    if df_w is None or df_w.empty or df_d is None or df_d.empty:
        raise ValueError(f"No price history for {ticker}")

    close_w = df_w["Close"].dropna()
    close_d = df_d["Close"].dropna()

    return {
        "weekly": _macd_crossover_state(close_w),
        "daily": _macd_crossover_state(close_d),
        "fetch_status": "ok",
        "fetch_error": None,
    }


def fetch_rsi_signal(ticker: str) -> dict:
    try:
        client = get_schwab_client()
        df_d = client.get_price_history(ticker, "year", 1, "daily", 1)
    except SchwabAPIError as exc:
        return {**_NONE_RSI_CROSSOVER_FIELDS, "fetch_status": "error", "fetch_error": str(exc)}

    if df_d is None or df_d.empty:
        raise ValueError(f"No daily data for {ticker}")

    close_d = df_d["Close"].dropna()
    result = _rsi_crossover_state(close_d)
    result["fetch_status"] = "ok"
    result["fetch_error"] = None
    return result


def fetch_volume_spikes(ticker: str) -> dict:
    try:
        client = get_schwab_client()
        df_d = client.get_price_history(ticker, "year", 1, "daily", 1)
    except SchwabAPIError as exc:
        return {
            "spikes": [],
            "lookback_days": 10,
            "baseline_days": 20,
            "threshold_multiple": 2.0,
            "fetch_status": "error",
            "fetch_error": str(exc),
        }

    if df_d is None or df_d.empty:
        raise ValueError(f"No daily data for {ticker}")

    volume_d = df_d["Volume"].dropna()
    return {
        "spikes": _detect_volume_spikes(volume_d),
        "lookback_days": 10,
        "baseline_days": 20,
        "threshold_multiple": 2.0,
        "fetch_status": "ok",
        "fetch_error": None,
    }
