"""Options scanner service: fetch LEAPS chain, fit IV surface, rank by IV excess."""

import logging
import math
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

_RISK_FREE_RATE = 0.045


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        f = float(val)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        f = float(val)
        return int(f) if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _norm_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2))


def _bs_delta(
    S: float, K: float, T: float, r: float, sigma: float, opt_type: str
) -> float:
    """Black-Scholes delta for a European call or put."""
    if T <= 0 or sigma < 0.001:
        if opt_type == "call":
            return 1.0 if S > K else 0.0
        return -1.0 if S < K else 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    return _norm_cdf(d1) if opt_type == "call" else _norm_cdf(d1) - 1.0


def _compute_iv_excess(df: pd.DataFrame) -> pd.DataFrame:
    """Add iv_fitted and iv_excess via least-squares 2-D surface fit.

    Surface: IV ≈ a + b·m + c·m² + d·√T + e·m·√T
    where m = log(K/S) and T = DTE/365.
    """
    df = df.copy()
    valid = df[(df["iv"] > 0.02) & (df["dte"] > 0)]
    if len(valid) < 5:
        df["iv_fitted"] = df["iv"]
        df["iv_excess"] = 0.0
        return df

    m = valid["log_moneyness"].values
    sqrt_T = np.sqrt(valid["dte"].values / 365.0)
    iv = valid["iv"].values
    X = np.column_stack([np.ones_like(m), m, m**2, sqrt_T, m * sqrt_T])

    try:
        coeffs, _, _, _ = np.linalg.lstsq(X, iv, rcond=None)
    except np.linalg.LinAlgError:
        df["iv_fitted"] = df["iv"]
        df["iv_excess"] = 0.0
        return df

    m_all = df["log_moneyness"].values
    sqrt_T_all = np.sqrt(df["dte"].values / 365.0)
    X_all = np.column_stack(
        [np.ones_like(m_all), m_all, m_all**2, sqrt_T_all, m_all * sqrt_T_all]
    )
    df["iv_fitted"] = X_all @ coeffs
    df["iv_excess"] = df["iv"] - df["iv_fitted"]
    return df


def _fetch_earnings_dates(ticker: str) -> list[date]:
    """Return sorted upcoming earnings dates from yfinance (up to 8 quarters)."""
    import yfinance as yf

    t = yf.Ticker(ticker)
    today = date.today()

    try:
        ed = t.get_earnings_dates(limit=8)
        if ed is not None and not ed.empty:
            future = [
                idx.date() for idx in ed.index
                if hasattr(idx, "date") and idx.date() >= today
            ]
            if future:
                return sorted(future)
    except Exception:
        pass

    try:
        cal = t.calendar
        if cal is not None:
            raw = None
            if isinstance(cal, dict):
                raw = cal.get("Earnings Date")
            elif hasattr(cal, "index") and "Earnings Date" in cal.index:
                raw = cal.loc["Earnings Date"]
            if raw is not None:
                dates = (
                    list(raw)
                    if hasattr(raw, "__iter__") and not isinstance(raw, str)
                    else [raw]
                )
                result = []
                for d in dates:
                    try:
                        d2 = d.date() if hasattr(d, "date") else d
                        if d2 >= today:
                            result.append(d2)
                    except Exception:
                        pass
                if result:
                    return sorted(result)
    except Exception:
        pass

    try:
        ed = t.earnings_dates
        if ed is not None and not ed.empty:
            future = [
                idx.date() for idx in ed.index
                if hasattr(idx, "date") and idx.date() >= today
            ]
            if future:
                return sorted(future)[:8]
    except Exception:
        pass

    return []


def _annotate_earnings(
    df: pd.DataFrame, earnings_dates: list[date]
) -> pd.DataFrame:
    """Add earnings_count: number of earnings events before each expiration."""
    if df.empty:
        return df
    today = date.today()

    def _count(exp_str: str) -> int:
        try:
            exp = date.fromisoformat(exp_str)
        except (ValueError, TypeError):
            return 0
        return sum(1 for d in earnings_dates if today < d <= exp)

    df = df.copy()
    df["earnings_count"] = df["expiration"].apply(_count)
    return df


def _fetch_chain(
    ticker: str, opt_type: str, min_dte: int
) -> tuple[float, pd.DataFrame]:
    """Fetch LEAPS option chain from yfinance.

    Returns (spot, df). Raises ValueError if spot cannot be fetched.
    """
    import yfinance as yf

    t = yf.Ticker(ticker)
    spot = t.fast_info.last_price
    if not spot or float(spot) <= 0:
        raise ValueError(f"Could not fetch live price for {ticker}")
    spot = float(spot)

    today = date.today()
    expirations = [
        e for e in t.options
        if (datetime.strptime(e, "%Y-%m-%d").date() - today).days >= min_dte
    ]

    rows = []
    for exp_str in expirations:
        exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
        dte = (exp_date - today).days
        if dte <= 0:
            continue
        T = dte / 365.0
        try:
            chain = t.option_chain(exp_str)
        except Exception as exc:
            log.warning("Skipping %s: %s", exp_str, exc)
            continue

        sides: list[tuple[str, pd.DataFrame | None]] = []
        if opt_type in ("both", "calls"):
            sides.append(("call", chain.calls))
        if opt_type in ("both", "puts"):
            sides.append(("put", chain.puts))

        for side, side_df in sides:
            if side_df is None or side_df.empty:
                continue
            for _, row in side_df.iterrows():
                K = _safe_float(row.get("strike"))
                bid = _safe_float(row.get("bid"))
                ask = _safe_float(row.get("ask"))
                last = _safe_float(row.get("lastPrice"))
                iv = _safe_float(row.get("impliedVolatility"))
                oi = _safe_int(row.get("openInterest"))
                volume = _safe_int(row.get("volume"))
                # yfinance 1.3+ returns OI=0 for LEAPS; fall back to volume
                if oi == 0 and volume > 0:
                    oi = volume

                if bid <= 0 and ask <= 0 and last <= 0:
                    continue
                mid = (bid + ask) / 2 if bid > 0 and ask > 0 else last
                if mid <= 0 or iv < 0.005 or K <= 0:
                    continue

                capital = spot if side == "call" else K
                ann_yield = (mid / capital) * (365.0 / dte) * 100.0

                rows.append({
                    "type": side,
                    "strike": K,
                    "expiration": exp_str,
                    "dte": dte,
                    "log_moneyness": math.log(K / spot),
                    "bid": bid,
                    "ask": ask,
                    "mid": mid,
                    "iv": iv,
                    "iv_fitted": iv,
                    "iv_excess": 0.0,
                    "delta": _bs_delta(spot, K, T, _RISK_FREE_RATE, iv, side),
                    "ann_yield_pct": ann_yield,
                    "open_interest": oi,
                    "earnings_count": 0,
                })

    return spot, pd.DataFrame(rows) if rows else pd.DataFrame()


def run_scan(
    ticker: str,
    opt_type: str = "both",
    min_dte: int = 365,
    min_oi: int = 25,
    max_delta: float = 0.70,
) -> dict:
    """Fetch LEAPS chain → IV surface → earnings → filter → sort.

    Intended to be called via asyncio.run_in_executor.
    Raises ValueError if the ticker price cannot be fetched.
    """
    spot, df = _fetch_chain(ticker, opt_type, min_dte)
    earnings_dates = _fetch_earnings_dates(ticker)

    if not df.empty:
        df = _compute_iv_excess(df)
        df = _annotate_earnings(df, earnings_dates)
        df = df[
            (df["open_interest"] >= min_oi) & (df["delta"].abs() <= max_delta)
        ].copy()
        df = df.sort_values("iv_excess", ascending=False)

    options = []
    for _, row in df.iterrows():
        options.append({
            "type": row["type"],
            "strike": round(float(row["strike"]), 2),
            "expiration": row["expiration"],
            "dte": int(row["dte"]),
            "bid": round(float(row["bid"]), 2),
            "ask": round(float(row["ask"]), 2),
            "mid": round(float(row["mid"]), 2),
            "iv": round(float(row["iv"]), 4),
            "iv_fitted": round(float(row["iv_fitted"]), 4),
            "iv_excess": round(float(row["iv_excess"]), 4),
            "delta": round(float(row["delta"]), 4),
            "ann_yield_pct": round(float(row["ann_yield_pct"]), 2),
            "open_interest": int(row["open_interest"]),
            "earnings_count": int(row["earnings_count"]),
        })

    return {
        "ticker": ticker,
        "spot": round(spot, 2),
        "scan_ts": datetime.utcnow().isoformat() + "Z",
        "lt_close_date": (date.today() + timedelta(days=366)).isoformat(),
        "earnings_dates": [d.isoformat() for d in earnings_dates],
        "options": options,
    }
