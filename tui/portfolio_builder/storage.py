import csv
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from portfolio_builder.engine import Plan
from portfolio_builder.models import Group, Portfolio, Security, number


def portfolio_to_dict(portfolio: Portfolio) -> dict:
    return {"version": 1, **asdict(portfolio)}


def portfolio_from_dict(data: dict) -> Portfolio:
    try:
        if data["version"] != 1:
            raise ValueError("Unsupported portfolio file version.")
        groups = [
            Group(
                name=entry["name"],
                target=number(entry["target"], "Target"),
                preferred_ticker=entry.get("preferred_ticker", ""),
                securities=[
                    Security(
                        ticker=item["ticker"],
                        currency=item["currency"],
                        price=number(item["price"], "Price"),
                        shares=number(item.get("shares", "0"), "Shares"),
                        quote_as_of=item.get("quote_as_of", "manual / unverified"),
                    )
                    for item in entry["securities"]
                ],
            )
            for entry in data["groups"]
        ]
        portfolio = Portfolio(
            groups=groups,
            display_currency=data["display_currency"],
            usd_cad=number(data["usd_cad"], "FX"),
            fx_as_of=data.get("fx_as_of", "manual / unverified"),
            cash_cad=number(data.get("cash_cad", "0")),
            cash_usd=number(data.get("cash_usd", "0")),
            additional_cash=number(data.get("additional_cash", "0")),
            additional_currency=data.get("additional_currency", "CAD"),
            mode=data.get("mode", "create"),
            fractional=data.get("fractional", False),
        )
        portfolio.validate()
        return portfolio
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError(f"Invalid portfolio file: {error}") from error


def atomic_write(path: Path, content: str) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_portfolio(portfolio: Portfolio, path: Path) -> None:
    portfolio.validate()
    atomic_write(
        path, json.dumps(portfolio_to_dict(portfolio), default=str, indent=2) + "\n"
    )


def load_portfolio(path: Path) -> Portfolio:
    return portfolio_from_dict(
        json.loads(path.expanduser().read_text(encoding="utf-8"))
    )


def export_orders(plan: Plan, portfolio: Portfolio, path: Path) -> None:
    import io

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "group",
            "ticker",
            "side",
            "shares",
            "price",
            "quote_currency",
            "quote_value",
            "display_value",
            "display_currency",
            "usd_cad",
        ]
    )
    for order in plan.orders:
        writer.writerow(
            [
                order.group,
                order.ticker,
                order.side,
                str(order.shares),
                str(order.price),
                order.currency,
                str(order.local_value),
                str(portfolio.convert(order.value_cad, "CAD")),
                portfolio.display_currency,
                str(portfolio.usd_cad),
            ]
        )
    atomic_write(path, output.getvalue())


def plan_to_dict(plan: Plan, portfolio: Portfolio) -> dict:
    return {
        "display_currency": portfolio.display_currency,
        "usd_cad": str(portfolio.usd_cad),
        "fx_as_of": portfolio.fx_as_of,
        "quotes": {
            security.ticker: {
                "price": str(security.price),
                "currency": security.currency,
                "as_of": security.quote_as_of,
            }
            for group in portfolio.groups
            for security in group.securities
        },
        "total_display": str(portfolio.convert(plan.total_cad, "CAD")),
        "remaining_cash_display": str(
            portfolio.convert(plan.remaining_cash_cad, "CAD")
        ),
        **asdict(plan),
    }
