"""House defaults for an account's risk limits, in percent (10 means 10%).

An account limit left unset means "use the house default", never "no limit". These are read when the
API resolves an account's effective limits and are never written into an account row, so changing a
value here reaches every account that didn't override it.

TODO(KB import): a later feature replaces these constants with the values stated by the imported
trading knowledge base. Today they mirror its house rules.
"""
from decimal import Decimal

# At most 10% of the account in one stock.
MAX_POSITION_PCT = Decimal("10")
# At most 1–3% in a speculative stock; the top of the range.
MAX_SPECULATIVE_POSITION_PCT = Decimal("3")
# Keep margin use under 30%.
MAX_MARGIN_USED_PCT = Decimal("30")
