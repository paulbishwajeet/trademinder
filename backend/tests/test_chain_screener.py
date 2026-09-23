import pytest
from datetime import date, timedelta


def test_select_friday_expiries_picks_only_fridays_in_order():
    from app.services.chain_screener import _select_friday_expiries
    exp_map = {
        "2026-09-25:2": {},   # Friday
        "2026-09-28:5": {},   # Monday
        "2026-10-02:9": {},   # Friday
        "2026-10-05:12": {},  # Monday
        "2026-10-09:16": {},  # Friday
        "2026-10-16:23": {},  # Friday
    }
    result = _select_friday_expiries(exp_map, num_expiries=3)
    assert [e["expiration_date"] for e in result] == ["2026-09-25", "2026-10-02", "2026-10-09"]
    assert [e["dte"] for e in result] == [2, 9, 16]
    assert result[0]["exp_key"] == "2026-09-25:2"


def test_select_friday_expiries_respects_limit():
    from app.services.chain_screener import _select_friday_expiries
    exp_map = {"2026-09-25:2": {}, "2026-10-02:9": {}, "2026-10-09:16": {}, "2026-10-16:23": {}}
    result = _select_friday_expiries(exp_map, num_expiries=2)
    assert len(result) == 2
    assert [e["expiration_date"] for e in result] == ["2026-09-25", "2026-10-02"]


def test_select_friday_expiries_empty_when_no_fridays():
    from app.services.chain_screener import _select_friday_expiries
    exp_map = {"2026-09-28:5": {}, "2026-10-05:12": {}}
    result = _select_friday_expiries(exp_map, num_expiries=3)
    assert result == []


def test_score_delta_fit_full_points_at_target():
    from app.services.chain_screener import _score_delta_fit
    assert _score_delta_fit(delta=-0.2, target_delta=0.2, tolerance=0.1) == 25.0


def test_score_delta_fit_zero_at_edge():
    from app.services.chain_screener import _score_delta_fit
    # dist = 0.15 == tolerance * 1.5 -> exactly 0
    assert _score_delta_fit(delta=-0.35, target_delta=0.2, tolerance=0.1) == 0.0


def test_score_delta_fit_partial_credit_matches_live_nvda_data():
    from app.services.chain_screener import _score_delta_fit
    # NVDA 10-02 $220 strike, delta -0.319, target 0.2, tolerance 0.1 (from live spike)
    points = _score_delta_fit(delta=-0.319, target_delta=0.2, tolerance=0.1)
    assert 5.0 <= points <= 5.5


def test_score_arr_no_cliff_below_minimum():
    from app.services.chain_screener import _score_arr
    # NVDA's real 10-02 $215 strike: ARR 22.6%, min 30% -> meaningful partial credit, not 0
    points = _score_arr(arr_pct=22.6, min_arr_pct=30.0)
    assert points == pytest.approx(18.83, abs=0.1)


def test_score_arr_full_points_at_minimum():
    from app.services.chain_screener import _score_arr
    assert _score_arr(arr_pct=30.0, min_arr_pct=30.0) == 25.0


def test_score_arr_capped_above_minimum():
    from app.services.chain_screener import _score_arr
    assert _score_arr(arr_pct=100.0, min_arr_pct=30.0) == 25.0


def test_score_volume_and_oi_scale_to_threshold():
    from app.services.chain_screener import _score_volume, _score_oi
    assert _score_volume(volume=100, min_volume=200) == 7.5
    assert _score_volume(volume=400, min_volume=200) == 15.0  # capped
    assert _score_oi(oi=250, min_oi=500) == 7.5
    assert _score_oi(oi=1000, min_oi=500) == 15.0  # capped


def test_score_spread_full_points_when_tight():
    from app.services.chain_screener import _score_spread
    # NVDA 10-02 $220 strike real spread: (2.32-2.30)/2.31 ~= 0.0087
    assert _score_spread(spread_pct=0.009) == 20.0


def test_score_spread_zero_when_very_wide():
    from app.services.chain_screener import _score_spread
    assert _score_spread(spread_pct=0.30) == 0.0


def test_score_candidate_combines_all_factors_matches_live_nvda_data():
    from app.services.chain_screener import _score_candidate
    contract = {"delta": -0.319, "last": 2.32, "bid": 2.30, "ask": 2.32, "totalVolume": 3751, "openInterest": 11689}
    candidate = _score_candidate(
        contract, strike=220.0, dte=9, spot=224.85,
        target_delta=0.2, delta_tolerance=0.1,
        min_arr_pct=30.0, min_volume=200, min_oi=500,
    )
    assert candidate["strike"] == 220.0
    assert candidate["arr_pct"] == pytest.approx(42.8, abs=0.2)  # matches live NVDA spike output exactly
    assert candidate["breakeven"] == pytest.approx(217.68, abs=0.01)
    assert len(candidate["factors"]) == 5
    assert candidate["score"] == pytest.approx(sum(f["points"] for f in candidate["factors"]))
