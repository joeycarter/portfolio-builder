import copy
import csv
import io
import json
import tempfile
import unittest
import warnings
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from portfolio_builder.__main__ import demo_portfolio, main
from portfolio_builder.engine import build_plan
from portfolio_builder.quotes import Quote, YahooProvider, refresh_quotes
from portfolio_builder.storage import (
    export_orders,
    load_portfolio,
    portfolio_from_dict,
    portfolio_to_dict,
    save_portfolio,
)


class StorageTests(unittest.TestCase):
    def test_round_trip_preserves_all_settings_and_decimal_precision(self):
        portfolio = demo_portfolio()
        portfolio.groups[0].securities[0].shares = Decimal("1.123456789")
        portfolio.additional_cash = Decimal("12.34")
        portfolio.additional_currency = "USD"
        portfolio.mode = "rebalance"
        portfolio.fractional = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "saved.json"
            save_portfolio(portfolio, path)
            self.assertEqual(load_portfolio(path), portfolio)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_failed_save_preserves_original(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "saved.json"
            save_portfolio(demo_portfolio(), path)
            original = path.read_bytes()
            with patch(
                "portfolio_builder.storage.os.replace",
                side_effect=OSError("disk failure"),
            ):
                with self.assertRaises(OSError):
                    save_portfolio(demo_portfolio(), path)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_incomplete_drafts_can_be_saved(self):
        portfolio = demo_portfolio()
        portfolio.groups[0].securities.clear()
        portfolio.groups[0].target = Decimal("10")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "draft.json"
            save_portfolio(portfolio, path)
            self.assertEqual(load_portfolio(path), portfolio)

    def test_invalid_files(self):
        for data in ({}, [], None, {"version": 2}, {"version": 1, "groups": None}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                portfolio_from_dict(data)
        data = portfolio_to_dict(demo_portfolio())
        data["cash_usd"] = "NaN"
        with self.assertRaises(ValueError):
            portfolio_from_dict(data)

    def test_csv_export_contains_listing_and_display_values(self):
        portfolio = demo_portfolio()
        portfolio.display_currency = "USD"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "orders.csv"
            export_orders(build_plan(portfolio), portfolio, path)
            with path.open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["quote_currency"], "CAD")
            self.assertEqual(rows[0]["display_currency"], "USD")
            self.assertEqual(Decimal(rows[0]["quote_value"]), 4000)


class QuoteTests(unittest.TestCase):
    def provider(self):
        provider = MagicMock()
        provider.quote.side_effect = lambda ticker: Quote(
            Decimal("20"), "USD" if ticker == "VTI" else "CAD", "test close"
        )
        provider.usd_cad.return_value = Quote(Decimal("1.4"), "CAD", "test FX")
        return provider

    def test_successful_refresh(self):
        portfolio = demo_portfolio()
        self.assertEqual(
            refresh_quotes(portfolio, self.provider()), ["VUN.TO", "VTI", "ZAG.TO"]
        )
        self.assertEqual(portfolio.usd_cad, Decimal("1.4"))
        self.assertEqual(portfolio.groups[0].securities[0].price, 20)
        self.assertEqual(portfolio.groups[0].securities[0].quote_as_of, "test close")

    def test_failure_is_atomic(self):
        for failure in (
            "ticker",
            "fx",
            "currency",
            "price",
            "timestamp",
            "fx_currency",
        ):
            with self.subTest(failure=failure):
                portfolio = demo_portfolio()
                original = copy.deepcopy(portfolio)
                provider = self.provider()
                if failure == "ticker":
                    provider.quote.side_effect = RuntimeError("network unavailable")
                elif failure == "fx":
                    provider.usd_cad.side_effect = RuntimeError("network unavailable")
                elif failure == "currency":
                    provider.quote.side_effect = lambda ticker: Quote(
                        Decimal("20"), "USD", "test"
                    )
                elif failure == "price":
                    provider.usd_cad.return_value = Quote(Decimal("NaN"), "CAD", "test")
                elif failure == "timestamp":
                    provider.usd_cad.return_value = Quote(
                        Decimal("1.4"), "CAD", "\x1bBAD"
                    )
                else:
                    provider.usd_cad.return_value = Quote(Decimal("1.4"), "USD", "test")
                with self.assertRaisesRegex(ValueError, "Nothing updated"):
                    refresh_quotes(portfolio, provider)
                self.assertEqual(portfolio, original)

    def yahoo_provider(self, **overrides):
        provider = YahooProvider.__new__(YahooProvider)
        provider.client = MagicMock()
        provider.client.Ticker.return_value.get_info.return_value = {
            "currency": "CAD",
            "regularMarketPrice": 101.25,
            "regularMarketTime": int(
                datetime(2026, 10, 21, 15, 30, tzinfo=timezone.utc).timestamp()
            ),
            "marketState": "REGULAR",
            "regularMarketPreviousClose": 98.75,
            "previousClose": 98.75,
            "preMarketPrice": 99.5,
            "postMarketPrice": 103.5,
            "currentPrice": 103.5,
            **overrides,
        }
        return provider

    def test_yahoo_uses_current_regular_session_price_and_quote_timestamp(self):
        provider = self.yahoo_provider()
        quote = provider.quote("VUN.TO")
        self.assertEqual(quote.price, Decimal("101.25"))
        self.assertEqual(quote.currency, "CAD")
        self.assertEqual(quote.as_of, "Yahoo current 2026-10-21T15:30:00+00:00")
        provider.client.Ticker.assert_called_once_with("VUN.TO")
        provider.client.Ticker.return_value.get_info.assert_called_once_with()
        provider.client.Ticker.return_value.history.assert_not_called()

    def test_yahoo_uses_latest_close_outside_regular_hours(self):
        for state in ("PRE", "PREPRE", "POST", "POSTPOST", "CLOSED"):
            for close in (
                datetime(2026, 10, 20, 20, tzinfo=timezone.utc),
                datetime(2026, 10, 16, 20, tzinfo=timezone.utc),
                datetime(2026, 11, 27, 18, tzinfo=timezone.utc),
            ):
                with self.subTest(state=state, close=close):
                    provider = self.yahoo_provider(
                        marketState=state, regularMarketTime=int(close.timestamp())
                    )
                    quote = provider.quote("VUN.TO")
                    self.assertEqual(quote.price, Decimal("101.25"))
                    self.assertEqual(quote.as_of, f"Yahoo close {close.isoformat()}")

    def test_yahoo_unknown_market_state_keeps_regular_session_price(self):
        for state in (None, "UNKNOWN"):
            with self.subTest(state=state):
                quote = self.yahoo_provider(marketState=state).quote("VUN.TO")
                self.assertEqual(quote.price, Decimal("101.25"))
                self.assertEqual(
                    quote.as_of, "Yahoo regular-session 2026-10-21T15:30:00+00:00"
                )

    def test_yahoo_rejects_invalid_or_missing_quote_fields(self):
        for field, values in (
            ("regularMarketPrice", (None, 0, -1, float("nan"), float("inf"))),
            ("regularMarketTime", (None, 0, -1, "invalid", float("nan"), float("inf"))),
            ("currency", (None, "", "EUR")),
        ):
            for value in values:
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        self.yahoo_provider(**{field: value}).quote("VUN.TO")
            with self.subTest(missing=field):
                provider = self.yahoo_provider()
                del provider.client.Ticker.return_value.get_info.return_value[field]
                with self.assertRaises(ValueError):
                    provider.quote("VUN.TO")

    def test_yahoo_rejects_empty_quote(self):
        provider = self.yahoo_provider()
        provider.client.Ticker.return_value.get_info.return_value = {}
        with self.assertRaisesRegex(ValueError, "No recent quote"):
            provider.quote("MISSING")

    def test_yahoo_refresh_fetches_again(self):
        provider = self.yahoo_provider()
        self.assertEqual(provider.quote("VUN.TO").price, Decimal("101.25"))
        provider.client.Ticker.return_value.get_info.return_value[
            "regularMarketPrice"
        ] = 102.5
        self.assertEqual(provider.quote("VUN.TO").price, Decimal("102.5"))
        self.assertEqual(provider.client.Ticker.call_count, 2)
        self.assertEqual(provider.client.Ticker.return_value.get_info.call_count, 2)

    def test_yahoo_filters_timestamp_deprecation_for_prices_and_fx(self):
        provider = self.yahoo_provider()
        info = provider.client.Ticker.return_value.get_info.return_value

        def get_info():
            warnings.warn_explicit(
                "Timestamp.utcnow is deprecated and will be removed in a future version.",
                DeprecationWarning,
                "yfinance/scrapers/quote.py",
                700,
                module="yfinance.scrapers.quote",
            )
            return info

        provider.client.Ticker.return_value.get_info.side_effect = get_info
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.assertEqual(provider.quote("VUN.TO").price, Decimal("101.25"))
            self.assertEqual(provider.usd_cad().price, Decimal("101.25"))
        self.assertEqual(caught, [])

    def test_yahoo_preserves_unrelated_warnings(self):
        provider = self.yahoo_provider()
        info = provider.client.Ticker.return_value.get_info.return_value
        cases = (
            ("Another deprecation", DeprecationWarning, "yfinance.scrapers.quote"),
            (
                "Timestamp.utcnow is deprecated",
                RuntimeWarning,
                "yfinance.scrapers.quote",
            ),
            ("Timestamp.utcnow is deprecated", DeprecationWarning, "another_module"),
        )

        def get_info():
            for message, category, module in cases:
                warnings.warn_explicit(message, category, "quote.py", 1, module=module)
            return info

        provider.client.Ticker.return_value.get_info.side_effect = get_info
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            provider.quote("VUN.TO")
        self.assertEqual(
            [(str(item.message), item.category) for item in caught],
            [(message, category) for message, category, module in cases],
        )

    def test_yahoo_restores_warning_filters_after_success_and_failure(self):
        for fails in (False, True):
            with self.subTest(fails=fails):
                provider = self.yahoo_provider()
                if fails:
                    provider.client.Ticker.return_value.get_info.side_effect = (
                        ValueError("Network unavailable")
                    )
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    if fails:
                        with self.assertRaisesRegex(ValueError, "Network unavailable"):
                            provider.quote("VUN.TO")
                    else:
                        provider.quote("VUN.TO")
                    warnings.warn_explicit(
                        "Timestamp.utcnow is deprecated",
                        DeprecationWarning,
                        "yfinance/scrapers/quote.py",
                        700,
                        module="yfinance.scrapers.quote",
                    )
                self.assertEqual(len(caught), 1)

    def test_yahoo_fx_uses_latest_rate_and_currency(self):
        provider = self.yahoo_provider(regularMarketPrice=1.375)
        quote = provider.usd_cad()
        self.assertEqual(quote.price, Decimal("1.375"))
        self.assertEqual(quote.currency, "CAD")
        provider.client.Ticker.assert_called_once_with("CAD=X")

    def test_missing_optional_dependency(self):
        with patch.dict("sys.modules", {"yfinance": None}):
            with self.assertRaisesRegex(ValueError, "optional dependency"):
                YahooProvider()


class CliTests(unittest.TestCase):
    def test_demo_json_plan(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--demo", "--plan"]), 0)
        data = json.loads(output.getvalue())
        self.assertEqual(Decimal(data["total_cad"]), 10000)
        self.assertEqual(len(data["orders"]), 2)

    def test_missing_file(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            redirect_stderr(io.StringIO()) as errors,
        ):
            self.assertEqual(
                main(["--file", str(Path(directory) / "missing.json"), "--plan"]), 1
            )
            self.assertIn("not found", errors.getvalue())

    def test_export_does_not_overwrite_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "orders.csv"
            path.write_text("original")
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--demo", "--plan", "--export", str(path)]), 1)
            self.assertEqual(path.read_text(), "original")

    def test_noninteractive_tui_reports_helpful_error(self):
        with (
            patch("sys.stdin.isatty", return_value=False),
            redirect_stderr(io.StringIO()) as errors,
        ):
            self.assertEqual(main(["--demo"]), 1)
            self.assertIn("--plan", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
