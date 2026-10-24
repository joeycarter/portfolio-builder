from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR, localcontext

from portfolio_builder.models import (
    CURRENCIES,
    HUNDRED,
    ZERO,
    Group,
    Portfolio,
    Security,
)


@dataclass(frozen=True)
class Order:
    group: str
    ticker: str
    side: str
    shares: Decimal
    price: Decimal
    currency: str
    value_cad: Decimal

    @property
    def local_value(self) -> Decimal:
        return self.shares * self.price


@dataclass(frozen=True)
class Allocation:
    group: str
    target_percent: Decimal
    before_cad: Decimal
    after_cad: Decimal
    target_cad: Decimal
    actual_percent: Decimal


@dataclass(frozen=True)
class Plan:
    mode: str
    total_cad: Decimal
    starting_cash_cad: Decimal
    remaining_cash_cad: Decimal
    orders: tuple[Order, ...]
    allocations: tuple[Allocation, ...]
    final_shares: dict[str, Decimal]
    settlement_cash: dict[str, Decimal]
    warnings: tuple[str, ...]


def build_plan(portfolio: Portfolio) -> Plan:
    portfolio.validate(for_plan=True)
    with localcontext() as context:
        context.prec = 60
        return _build_plan(portfolio)


def _build_plan(portfolio: Portfolio) -> Plan:
    quantities = {
        security.ticker: security.shares
        for group in portfolio.groups
        for security in group.securities
    }
    before = {
        group.name: sum(
            (
                security.shares * portfolio.price_cad(security)
                for security in group.securities
            ),
            ZERO,
        )
        for group in portfolio.groups
    }
    starting_cash = portfolio.cash_in_cad()
    total = starting_cash + sum(before.values(), ZERO)
    if total <= ZERO:
        raise ValueError(
            "Enter cash to invest or existing holdings with positive value."
        )
    targets = {group.name: total * group.target / HUNDRED for group in portfolio.groups}
    cash = starting_cash
    orders: list[Order] = []
    quantum = Decimal("0.000001") if portfolio.fractional else Decimal("1")

    def rounded_shares(value: Decimal, price: Decimal) -> Decimal:
        return (value / price / quantum).to_integral_value(
            rounding=ROUND_FLOOR
        ) * quantum

    def trade(group_name: str, security: Security, side: str, shares: Decimal) -> None:
        nonlocal cash
        if shares <= ZERO:
            return
        value = shares * portfolio.price_cad(security)
        direction = Decimal("1") if side == "BUY" else Decimal("-1")
        quantities[security.ticker] += direction * shares
        cash -= direction * value
        orders.append(
            Order(
                group_name,
                security.ticker,
                side,
                shares,
                security.price,
                security.currency,
                value,
            )
        )

    def group_value(group: Group) -> Decimal:
        return sum(
            (
                quantities[security.ticker] * portfolio.price_cad(security)
                for security in group.securities
            ),
            ZERO,
        )

    for group in portfolio.groups:
        excess = before[group.name] - targets[group.name]
        if excess <= ZERO:
            continue
        for security in sorted(
            group.securities, key=lambda item: (portfolio.price_cad(item), item.ticker)
        ):
            held = quantities[security.ticker]
            if group.target == ZERO:
                quantity = held
            else:
                quantity = min(
                    (held / quantum).to_integral_value(rounding=ROUND_FLOOR) * quantum,
                    rounded_shares(max(ZERO, excess), portfolio.price_cad(security)),
                )
            trade(group.name, security, "SELL", quantity)
            excess -= quantity * portfolio.price_cad(security)

    for group in portfolio.groups:
        deficit = targets[group.name] - group_value(group)
        if deficit <= ZERO or cash <= ZERO:
            continue
        security = group.preferred()
        quantity = rounded_shares(min(deficit, cash), portfolio.price_cad(security))
        trade(group.name, security, "BUY", quantity)

    allocations = tuple(
        Allocation(
            group.name,
            group.target,
            before[group.name],
            group_value(group),
            targets[group.name],
            group_value(group) / total * HUNDRED,
        )
        for group in portfolio.groups
    )
    settlement = {"CAD": portfolio.cash_cad, "USD": portfolio.cash_usd}
    settlement[portfolio.additional_currency] += portfolio.additional_cash
    for order in orders:
        settlement[order.currency] += order.local_value * (
            1 if order.side == "SELL" else -1
        )
    warnings = [
        "Estimates only: review prices, FX, taxes, commissions, spreads, and trading restrictions.",
        "No trades are sent to a broker. FX conversion is assumed at the entered rate with no fees.",
        "Group members are treated as interchangeable; the app does not verify fund equivalence.",
    ]
    if cash > ZERO:
        warnings.append(
            "Share rounding leaves cash uninvested; targets include this residual cash."
        )
    if not portfolio.fractional and any(
        order.shares != order.shares.to_integral_value() for order in orders
    ):
        warnings.append(
            "Liquidating a 0% group includes existing fractional shares; verify broker support."
        )
    for denomination in CURRENCIES:
        if settlement[denomination] < ZERO:
            warnings.append(
                f"Convert currency to cover {-settlement[denomination]:,.2f} {denomination} before buys."
            )
    return Plan(
        portfolio.mode,
        total,
        starting_cash,
        cash,
        tuple(orders),
        allocations,
        quantities,
        settlement,
        tuple(warnings),
    )
