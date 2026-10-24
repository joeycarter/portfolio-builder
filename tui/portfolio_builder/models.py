from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation


ZERO = Decimal("0")
HUNDRED = Decimal("100")
CURRENCIES = ("CAD", "USD")


def number(value: object, label: str = "Value") -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{label} must be a number.") from None
    if not result.is_finite():
        raise ValueError(f"{label} must be finite.")
    if abs(result) > Decimal("1e15"):
        raise ValueError(f"{label} is too large (maximum 1e15).")
    if result and abs(result) < Decimal("1e-12"):
        raise ValueError(f"{label} is too small (minimum nonzero value 1e-12).")
    return result


def nonnegative(value: object, label: str) -> Decimal:
    result = number(value, label)
    if result < ZERO:
        raise ValueError(f"{label} cannot be negative.")
    return result


def positive(value: object, label: str) -> Decimal:
    result = number(value, label)
    if result <= ZERO:
        raise ValueError(f"{label} must be greater than zero.")
    return result


def currency(value: str) -> str:
    if value not in CURRENCIES:
        raise ValueError("Currency must be CAD or USD.")
    return value


def text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or not value.isprintable():
        raise ValueError(f"{label} must be nonempty, printable text.")
    if len(value) > 80:
        raise ValueError(f"{label} must be at most 80 characters.")
    return value.strip()


@dataclass
class Security:
    ticker: str
    currency: str
    price: Decimal
    shares: Decimal = ZERO
    quote_as_of: str = "manual / unverified"

    def validate(self) -> None:
        if text(self.ticker, "Ticker") != self.ticker or any(
            char.isspace() for char in self.ticker
        ):
            raise ValueError("Ticker cannot contain whitespace.")
        currency(self.currency)
        positive(self.price, f"{self.ticker} price")
        nonnegative(self.shares, f"{self.ticker} shares")
        text(self.quote_as_of, "Quote timestamp")


@dataclass
class Group:
    name: str
    target: Decimal
    securities: list[Security] = field(default_factory=list)
    preferred_ticker: str = ""

    def preferred(self) -> Security:
        if not self.securities:
            raise ValueError(f"{self.name}: add at least one security.")
        if not self.preferred_ticker:
            return self.securities[0]
        for security in self.securities:
            if security.ticker == self.preferred_ticker:
                return security
        raise ValueError(f"{self.name}: preferred ticker must belong to this group.")


@dataclass
class Portfolio:
    groups: list[Group] = field(default_factory=list)
    display_currency: str = "CAD"
    usd_cad: Decimal = Decimal("1.35")
    fx_as_of: str = "manual / unverified"
    cash_cad: Decimal = ZERO
    cash_usd: Decimal = ZERO
    additional_cash: Decimal = ZERO
    additional_currency: str = "CAD"
    mode: str = "create"
    fractional: bool = False

    def convert(
        self, amount: Decimal, source: str, destination: str | None = None
    ) -> Decimal:
        destination = destination or self.display_currency
        currency(source)
        currency(destination)
        if source == destination:
            return amount
        if source == "USD":
            return amount * self.usd_cad
        return amount / self.usd_cad

    def price_cad(self, security: Security) -> Decimal:
        return self.convert(security.price, security.currency, "CAD")

    def cash_in_cad(self) -> Decimal:
        return (
            self.cash_cad
            + self.cash_usd * self.usd_cad
            + self.convert(self.additional_cash, self.additional_currency, "CAD")
        )

    def validate(self, for_plan: bool = False) -> None:
        currency(self.display_currency)
        currency(self.additional_currency)
        positive(self.usd_cad, "USD/CAD exchange rate")
        text(self.fx_as_of, "FX timestamp")
        for label in ("cash_cad", "cash_usd", "additional_cash"):
            nonnegative(getattr(self, label), label)
        if self.mode not in ("create", "rebalance"):
            raise ValueError("Mode must be create or rebalance.")
        if not isinstance(self.fractional, bool):
            raise ValueError("Fractional shares must be true or false.")
        names: set[str] = set()
        tickers: set[str] = set()
        for group in self.groups:
            text(group.name, "Group name")
            if not isinstance(group.preferred_ticker, str):
                raise ValueError("Preferred ticker must be text.")
            if group.name.casefold() in names:
                raise ValueError(f"Duplicate group: {group.name}.")
            names.add(group.name.casefold())
            if not ZERO <= number(group.target, "Target") <= HUNDRED:
                raise ValueError(f"{group.name}: target must be between 0 and 100.")
            for security in group.securities:
                security.validate()
                if security.ticker.upper() in tickers:
                    raise ValueError(f"Duplicate ticker: {security.ticker}.")
                tickers.add(security.ticker.upper())
                if for_plan and self.mode == "create" and security.shares:
                    raise ValueError(
                        "Create mode requires zero holdings. Switch to rebalance to use existing shares."
                    )
            if group.securities or for_plan:
                group.preferred()
        if for_plan:
            if not self.groups:
                raise ValueError("Add at least one group and security.")
            total = sum((group.target for group in self.groups), ZERO)
            if total != HUNDRED:
                raise ValueError(f"Group targets must total 100%; currently {total}%.")
