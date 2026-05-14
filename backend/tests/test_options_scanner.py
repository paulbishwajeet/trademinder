# backend/tests/test_options_scanner.py
import math

import pandas as pd
import pytest

from app.services.options_scanner import _bs_delta, _compute_iv_excess


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
