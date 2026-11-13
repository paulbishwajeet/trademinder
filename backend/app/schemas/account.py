import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Optional
from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field

# Broker is free text; this is the list the UI offers.
KNOWN_BROKERS = ["E*TRADE", "Schwab", "Fidelity", "Robinhood", "Other"]

LastFour = Annotated[str, Field(pattern=r"^[0-9]{4}$")]

# Hex SHA-256 of broker + full account number, computed by the extension.
Fingerprint = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def _no_account_number(label: str) -> str:
    # Dropdown labels end in the last four only; a long digit run would be a full account number.
    if re.search(r"\d{6,}", label):
        raise ValueError("label must not contain an account number")
    return label.strip()


ExternalLabel = Annotated[str, Field(min_length=1, max_length=100), AfterValidator(_no_account_number)]

# Account facts (migration 019). Values mirror app.services.account_facts; the KB matches on the
# account_tax_status / account_purpose spellings.
TaxTreatment = Literal["taxable", "traditional_ira", "roth_ira", "other_tax_advantaged"]
AccountPurpose = Literal["trading", "long_term"]
MarginType = Literal["cash", "limited_margin", "margin", "portfolio_margin"]
OptionsTier = Literal["none", "covered", "cash_secured_and_long", "spreads", "uncovered"]
AccountTaxStatus = Literal["taxable", "tax_advantaged"]


def _blank_to_none(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


OptionsLevelLabel = Annotated[Optional[Annotated[str, Field(max_length=40)]], BeforeValidator(_blank_to_none)]


class AccountFactsInput(BaseModel):
    """Every fact is optional. On update, an absent field is left alone and an explicit null clears it.
    Combination rules and money checks run in the service (422 with a code)."""
    tax_treatment: Optional[TaxTreatment] = None
    account_purpose: Optional[AccountPurpose] = None
    margin_type: Optional[MarginType] = None
    options_tier: Optional[OptionsTier] = None
    options_level_label: OptionsLevelLabel = None
    net_liquidation_value: Optional[Decimal] = None
    cash_balance: Optional[Decimal] = None


class AccountSummary(BaseModel):
    """Compact account label embedded in trade / wheel / spread responses."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nickname: str
    broker: str
    last_four: Optional[str] = None


class AccountLinkInfo(BaseModel):
    """E*TRADE link details shown in Settings. The fingerprint itself is never returned."""
    label: Optional[str] = None
    last_seen_at: Optional[datetime] = None


class AccountResponse(AccountSummary):
    link: Optional[AccountLinkInfo] = None
    default_category_id: Optional[uuid.UUID] = None
    is_default: bool
    sort_order: int
    is_archived: bool
    created_at: datetime
    category_ids: list[uuid.UUID] = []
    # True when the account holds nothing and may be hard-deleted (otherwise archive it).
    can_delete: bool = False
    # Account facts. Money serializes as JSON strings.
    tax_treatment: Optional[TaxTreatment] = None
    account_purpose: Optional[AccountPurpose] = None
    margin_type: Optional[MarginType] = None
    options_tier: Optional[OptionsTier] = None
    options_level_label: Optional[str] = None
    net_liquidation_value: Optional[Decimal] = None
    cash_balance: Optional[Decimal] = None
    values_as_of: Optional[datetime] = None
    facts_updated_at: Optional[datetime] = None
    # Derived, read-only
    account_tax_status: Optional[AccountTaxStatus] = None
    facts_complete: bool = False


class AccountCreate(AccountFactsInput):
    broker: Annotated[str, Field(min_length=1, max_length=30)]
    nickname: Annotated[str, Field(min_length=1, max_length=50)]
    last_four: Optional[LastFour] = None
    sort_order: Optional[int] = None  # None → after the user's existing accounts
    is_default: bool = False
    # None → the account uses every category in the user's library
    category_ids: Optional[list[uuid.UUID]] = None
    default_category_id: Optional[uuid.UUID] = None


class AccountUpdate(AccountFactsInput):
    broker: Optional[Annotated[str, Field(min_length=1, max_length=30)]] = None
    nickname: Optional[Annotated[str, Field(min_length=1, max_length=50)]] = None
    last_four: Optional[LastFour] = None
    sort_order: Optional[int] = None
    default_category_id: Optional[uuid.UUID] = None
    # Only `true` is meaningful: it moves the default here. Unset by defaulting another account.
    is_default: Optional[bool] = None


class AccountCategoriesUpdate(BaseModel):
    category_ids: list[uuid.UUID]


class AccountOrderUpdate(BaseModel):
    account_ids: list[uuid.UUID]


class AccountLinkResolveRequest(BaseModel):
    fingerprint: Fingerprint
    label: Optional[ExternalLabel] = None


class AccountLinkResolveResponse(BaseModel):
    linked: bool
    account: Optional[AccountSummary] = None
    is_archived: bool = False


class AccountLinkRequest(BaseModel):
    fingerprint: Fingerprint
    label: ExternalLabel


class AccountCreateAndLink(BaseModel):
    fingerprint: Fingerprint
    label: ExternalLabel
    account: AccountCreate
