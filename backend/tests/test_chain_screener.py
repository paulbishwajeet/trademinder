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
