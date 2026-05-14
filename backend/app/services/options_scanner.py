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
