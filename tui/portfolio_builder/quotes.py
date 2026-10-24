from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol
import warnings

from portfolio_builder.models import Portfolio, Security, currency, positive, text


@dataclass(frozen=True)
class Quote:
    price: Decimal
    currency: str
    as_of: str


class QuoteProvider(Protocol):
    def quote(self, ticker: str) -> Quote: ...

    def usd_cad(self) -> Quote: ...


class YahooProvider:
    def __init__(self) -> None:
        try:
            import yfinance
        except ImportError:
            raise ValueError(
                'Online prices need the optional dependency: pip install -e ".[quotes]"'
            ) from None
        self.client = yfinance

    def quote(self, ticker: str) -> Quote:
        instrument = self.client.Ticker(ticker)
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"Timestamp\.utcnow is deprecated\b",
                category=DeprecationWarning,
                module=r"yfinance\.scrapers\.quote$",
            )
            info = instrument.get_info()
        if not info:
            raise ValueError(
                f"No recent quote for {ticker}; check the ticker and try again."
            )
        denomination = currency(info.get("currency", ""))
        price = positive(
            info.get("regularMarketPrice"), f"{ticker} regular-session price"
        )
        timestamp = positive(info.get("regularMarketTime"), f"{ticker} quote timestamp")
        as_of = datetime.fromtimestamp(float(timestamp), timezone.utc).isoformat()
        market_state = info.get("marketState")
        if market_state == "REGULAR":
            label = "current"
        elif market_state in ("PRE", "PREPRE", "POST", "POSTPOST", "CLOSED"):
            label = "close"
        else:
            label = "regular-session"
        return Quote(
            price,
            denomination,
            f"Yahoo {label} {as_of}",
        )

    def usd_cad(self) -> Quote:
        return self.quote("CAD=X")


def refresh_quotes(portfolio: Portfolio, provider: QuoteProvider) -> list[str]:
    updated: list[tuple[Security, Quote]] = []
    errors: list[str] = []
    for group in portfolio.groups:
        for security in group.securities:
            try:
                quote = provider.quote(security.ticker)
                positive(quote.price, f"{security.ticker} price")
                text(quote.as_of, "Quote timestamp")
                if quote.currency != security.currency:
                    raise ValueError(
                        f"provider returned {quote.currency}, configured as {security.currency}; fix the currency first"
                    )
                updated.append((security, quote))
            except Exception as error:
                errors.append(f"{security.ticker}: {error}")
    fx_quote = None
    try:
        fx_quote = provider.usd_cad()
        positive(fx_quote.price, "FX rate")
        text(fx_quote.as_of, "FX timestamp")
        if fx_quote.currency != "CAD":
            raise ValueError("USD/CAD quote must be denominated in CAD.")
    except Exception as error:
        errors.append(f"USD/CAD: {error}")
    if errors:
        raise ValueError("Nothing updated. " + " | ".join(errors))
    for security, quote in updated:
        security.price = quote.price
        security.quote_as_of = quote.as_of
    portfolio.usd_cad = fx_quote.price
    portfolio.fx_as_of = fx_quote.as_of
    return [security.ticker for security, _ in updated]
