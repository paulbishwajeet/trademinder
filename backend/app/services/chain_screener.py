# backend/app/services/chain_screener.py
from datetime import date


def _select_friday_expiries(exp_map: dict, num_expiries: int) -> list[dict]:
    """Pick the earliest `num_expiries` Friday expirations from a Schwab
    putExpDateMap/callExpDateMap, sorted ascending by days-to-expiration."""
    entries = []
    for exp_key in exp_map:
        exp_str, dte_str = exp_key.split(":")
        exp_date = date.fromisoformat(exp_str)
        if exp_date.weekday() != 4:  # Monday=0 ... Friday=4
            continue
        entries.append({"exp_key": exp_key, "expiration_date": exp_str, "dte": int(dte_str)})
    entries.sort(key=lambda e: e["dte"])
    return entries[:num_expiries]


def _score_delta_fit(delta: float, target_delta: float, tolerance: float) -> float:
    dist = abs(abs(delta) - target_delta)
    return round(max(0.0, 25 * (1 - dist / (tolerance * 1.5))), 1)


def _score_arr(arr_pct: float, min_arr_pct: float) -> float:
    if min_arr_pct <= 0:
        return 25.0
    return round(min(25.0, 25 * arr_pct / min_arr_pct), 1)


def _score_volume(volume: int, min_volume: int) -> float:
    if min_volume <= 0:
        return 15.0
    return round(min(15.0, 15 * volume / min_volume), 1)


def _score_oi(oi: int, min_oi: int) -> float:
    if min_oi <= 0:
        return 15.0
    return round(min(15.0, 15 * oi / min_oi), 1)


def _score_spread(spread_pct: float) -> float:
    if spread_pct <= 0.05:
        return 20.0
    return round(max(0.0, 20 * (1 - (spread_pct - 0.05) / 0.25)), 1)


def _score_candidate(
    contract: dict,
    strike: float,
    dte: int,
    spot: float,
    target_delta: float,
    delta_tolerance: float,
    min_arr_pct: float,
    min_volume: int,
    min_oi: int,
) -> dict:
    delta = float(contract.get("delta") or 0.0)
    last = float(contract.get("last") or 0.0)
    bid = float(contract.get("bid") or 0.0)
    ask = float(contract.get("ask") or 0.0)
    volume = int(contract.get("totalVolume") or 0)
    oi = int(contract.get("openInterest") or 0)
    mid = (bid + ask) / 2

    arr_pct = (last / strike) * (365 / dte) * 100 if dte > 0 and strike > 0 else 0.0
    spread_pct = (ask - bid) / mid if mid > 0 else 1.0
    breakeven = strike - last
    downside_cushion_pct = ((spot - breakeven) / spot) * 100 if spot else 0.0
    capital_required = strike * 100

    factors = [
        {"name": "Delta Fit", "points": _score_delta_fit(delta, target_delta, delta_tolerance), "max": 25,
         "detail": f"delta {delta:.3f} vs target {target_delta:.2f}"},
        {"name": "ARR", "points": _score_arr(arr_pct, min_arr_pct), "max": 25,
         "detail": f"{arr_pct:.1f}% (min {min_arr_pct:.0f}%)"},
        {"name": "Volume", "points": _score_volume(volume, min_volume), "max": 15,
         "detail": f"{volume} (min {min_volume})"},
        {"name": "Open Interest", "points": _score_oi(oi, min_oi), "max": 15,
         "detail": f"{oi} (min {min_oi})"},
        {"name": "Spread Tightness", "points": _score_spread(spread_pct), "max": 20,
         "detail": f"{spread_pct * 100:.1f}% of mid"},
    ]
    score = round(sum(f["points"] for f in factors), 1)

    return {
        "strike": strike, "delta": delta, "last": last, "bid": bid, "ask": ask,
        "spread_pct": round(spread_pct, 4), "volume": volume, "open_interest": oi,
        "arr_pct": round(arr_pct, 1), "breakeven": round(breakeven, 2),
        "downside_cushion_pct": round(downside_cushion_pct, 2),
        "capital_required": round(capital_required, 2),
        "score": score, "factors": factors,
    }
