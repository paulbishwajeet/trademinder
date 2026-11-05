"""Errors shared by the market data boundary (app.services.market_data) and its providers.
Kept separate so a provider module can raise them without importing the factory."""


class MarketDataUnavailable(Exception):
    """The market data provider is offline as a whole (refresh token expired, refresh grant
    rejected, no tokens, or not configured) — not a per-ticker failure."""

    code = "market_data_offline"
