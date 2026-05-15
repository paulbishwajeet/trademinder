# backend/tests/test_options_scanner.py
import math
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.services.options_scanner import _bs_delta, _compute_iv_excess, run_scan


def test_bs_delta_call_deep_itm():
    delta = _bs_delta(S=200.0, K=100.0, T=1.0, r=0.045, sigma=0.30, opt_type="call")
    assert delta > 0.95


def test_bs_delta_put_deep_otm():
    delta = _bs_delta(S=200.0, K=100.0, T=1.0, r=0.045, sigma=0.30, opt_type="put")
    assert -0.05 < delta <= 0.0


def test_bs_delta_atm_call_near_half():
    delta = _bs_delta(S=100.0, K=100.0, T=1.0, r=0.045, sigma=0.30, opt_type="call")
    assert 0.45 < delta < 0.65


def test_bs_delta_expired_itm_call_returns_one():
    delta = _bs_delta(S=150.0, K=100.0, T=0.0, r=0.045, sigma=0.30, opt_type="call")
    assert delta == 1.0


def test_bs_delta_expired_otm_call_returns_zero():
    delta = _bs_delta(S=100.0, K=150.0, T=0.0, r=0.045, sigma=0.30, opt_type="call")
    assert delta == 0.0


def test_compute_iv_excess_adds_columns():
    rows = [
        {"log_moneyness": math.log(k / 100), "dte": 400, "iv": 0.30 + 0.01 * i}
        for i, k in enumerate([80, 90, 95, 100, 105, 110, 120, 130])
    ]
    df = pd.DataFrame(rows)
    result = _compute_iv_excess(df)
    assert "iv_fitted" in result.columns
    assert "iv_excess" in result.columns
    assert len(result) == len(df)


def test_compute_iv_excess_small_chain_returns_zero_excess():
    df = pd.DataFrame([
        {"log_moneyness": 0.0, "dte": 400, "iv": 0.30},
        {"log_moneyness": 0.1, "dte": 400, "iv": 0.32},
    ])
    result = _compute_iv_excess(df)
    assert (result["iv_excess"] == 0.0).all()


def test_compute_iv_excess_mean_near_zero():
    """Mean IV excess should be close to 0 — the surface goes through the data."""
    rows = [
        {
            "log_moneyness": math.log(k / 100),
            "dte": d,
            "iv": 0.25 + 0.005 * abs(k - 100) / 10 + 0.02 * math.sqrt(d / 365),
        }
        for k in [80, 90, 95, 100, 105, 110, 120]
        for d in [365, 450, 550]
    ]
    df = pd.DataFrame(rows)
    result = _compute_iv_excess(df)
    assert abs(result["iv_excess"].mean()) < 0.02


def _call_row(strike: float, oi: int = 100) -> dict:
    return {
        "strike": strike,
        "bid": 10.0, "ask": 11.0, "lastPrice": 10.5,
        "impliedVolatility": 0.45,
        "openInterest": oi, "volume": 50,
    }


def _mock_ticker(spot: float, expirations: list, chains: dict) -> MagicMock:
    m = MagicMock()
    m.fast_info.last_price = spot
    m.options = expirations

    def option_chain(exp: str):
        calls_df, puts_df = chains.get(exp, (pd.DataFrame(), pd.DataFrame()))
        r = MagicMock()
        r.calls, r.puts = calls_df, puts_df
        return r

    m.option_chain.side_effect = option_chain
    m.get_earnings_dates.return_value = None
    m.calendar = None
    m.earnings_dates = None
    return m


def test_run_scan_returns_expected_keys():
    today = date.today()
    exp = (today + timedelta(days=400)).strftime("%Y-%m-%d")
    df = pd.DataFrame([_call_row(160.0)])
    with patch("yfinance.Ticker", return_value=_mock_ticker(150.0, [exp], {exp: (df, pd.DataFrame())})):
        result = run_scan("AMD", "calls", 365, 10, 0.90)

    assert result["ticker"] == "AMD"
    assert result["spot"] == 150.0
    assert "lt_close_date" in result
    assert "earnings_dates" in result
    assert isinstance(result["options"], list)
    assert len(result["options"]) == 1
    row = result["options"][0]
    for key in ("type", "strike", "expiration", "dte", "bid", "ask", "mid",
                "iv", "iv_fitted", "iv_excess", "delta", "ann_yield_pct",
                "open_interest", "earnings_count"):
        assert key in row, f"missing key: {key}"


def test_run_scan_filters_low_oi():
    today = date.today()
    exp = (today + timedelta(days=400)).strftime("%Y-%m-%d")
    df = pd.DataFrame([_call_row(160.0, oi=5)])  # OI below min_oi=25
    with patch("yfinance.Ticker", return_value=_mock_ticker(150.0, [exp], {exp: (df, pd.DataFrame())})):
        result = run_scan("AMD", "calls", 365, 25, 0.90)
    assert result["options"] == []


def test_run_scan_sorted_by_iv_excess_descending():
    today = date.today()
    exps = [(today + timedelta(days=d)).strftime("%Y-%m-%d") for d in [380, 410, 440, 470, 500, 530]]
    multi_df = pd.DataFrame([
        {"strike": 150.0, "bid": 8.0, "ask": 9.0, "lastPrice": 8.5,
         "impliedVolatility": 0.60, "openInterest": 200, "volume": 100},
        {"strike": 160.0, "bid": 6.0, "ask": 7.0, "lastPrice": 6.5,
         "impliedVolatility": 0.40, "openInterest": 150, "volume": 80},
    ])
    chains = {e: (multi_df.copy(), pd.DataFrame()) for e in exps}
    with patch("yfinance.Ticker", return_value=_mock_ticker(140.0, exps, chains)):
        result = run_scan("AMD", "calls", 365, 10, 0.90)

    opts = result["options"]
    for i in range(len(opts) - 1):
        assert opts[i]["iv_excess"] >= opts[i + 1]["iv_excess"]


def test_run_scan_raises_for_missing_price():
    with patch("yfinance.Ticker") as mock_cls:
        m = MagicMock()
        m.fast_info.last_price = None
        mock_cls.return_value = m
        with pytest.raises(ValueError, match="live price"):
            run_scan("INVALID", "calls", 365, 25, 0.70)


def test_run_scan_returns_both_types():
    today = date.today()
    exp = (today + timedelta(days=400)).strftime("%Y-%m-%d")
    calls_df = pd.DataFrame([_call_row(160.0)])
    puts_df = pd.DataFrame([_call_row(140.0)])
    with patch("yfinance.Ticker", return_value=_mock_ticker(150.0, [exp], {exp: (calls_df, puts_df)})):
        result = run_scan("AMD", "both", 365, 10, 0.90)

    types = {r["type"] for r in result["options"]}
    assert "call" in types
    assert "put" in types
