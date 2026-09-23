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
