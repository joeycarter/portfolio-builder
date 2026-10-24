import curses
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from portfolio_builder.__main__ import demo_portfolio
from portfolio_builder.engine import build_plan
from portfolio_builder.models import Portfolio
from portfolio_builder.quotes import Quote
from portfolio_builder.storage import load_portfolio
from portfolio_builder.tui import App


class Screen:
    def __init__(self, keys=(), height=30, width=115):
        self.keys = iter(keys)
        self.height = height
        self.width = width
        self.output = []
        self.timeouts = []

    def timeout(self, value):
        self.timeouts.append(value)

    def getmaxyx(self):
        return self.height, self.width

    def addnstr(self, row, column, content, length, style):
        assert 0 <= row < self.height
        assert 0 <= column < self.width
        self.output.append(content[:length])

    def get_wch(self):
        return next(self.keys)

    def keypad(self, value):
        pass

    def erase(self):
        pass

    def refresh(self):
        pass


class TuiTests(unittest.TestCase):
    def setUp(self):
        colors = patch("curses.has_colors", return_value=False)
        cursor = patch("curses.curs_set")
        colors.start()
        cursor.start()
        self.addCleanup(colors.stop)
        self.addCleanup(cursor.stop)
        threads = patch(
            "portfolio_builder.tui.threading.Thread",
            side_effect=lambda target, daemon: SimpleNamespace(start=target),
        )
        threads.start()
        self.addCleanup(threads.stop)

    def app(self, portfolio=None, keys=()):
        return App(Screen(keys), portfolio or demo_portfolio(), Path("portfolio.json"))

    def test_keyboard_create_plan_save_load_workflow(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "my-portfolio.json"
            keys = (
                "nEquity\n40\n\n"
                "aVUN.TO\n0\ny\n"
                "nBonds\n60\n\n"
                "aZAG.TO\n0\ny\n"
                "b10000\n0\n0\nCAD\n"
                "pq"
                f"s{path}\n"
                "q"
            )
            app = self.app(Portfolio(), keys)
            with patch("portfolio_builder.tui.YahooProvider") as provider:
                provider.return_value.quote.side_effect = [
                    Quote(Decimal("100"), "CAD", "Yahoo current test"),
                    Quote(Decimal("15"), "CAD", "Yahoo close test"),
                ]
                app.run()
            saved = load_portfolio(path)
            plan = build_plan(saved)
            self.assertEqual(plan.final_shares, {"VUN.TO": 40, "ZAG.TO": 400})
            self.assertEqual(saved, app.portfolio)
            self.assertFalse(app.dirty)
            self.assertIn("PORTFOLIO PLAN", app.screen.output)

    def test_add_fetches_price_and_currency_without_prompting_for_them(self):
        for ticker, denomination, label in (
            ("spy", "USD", "current"),
            ("spy", "USD", "close"),
            ("zsp.to", "CAD", "current"),
            ("zsp.to", "CAD", "close"),
        ):
            with self.subTest(ticker=ticker, label=label):
                app = self.app()
                quote = Quote(Decimal("123.45"), denomination, f"Yahoo {label} test")
                with (
                    patch.object(
                        app, "form", return_value=[ticker, "2.5", "y"]
                    ) as form,
                    patch("portfolio_builder.tui.YahooProvider") as provider,
                ):
                    provider.return_value.quote.return_value = quote
                    app.edit_security(True)
                fields = form.call_args.args[1]
                self.assertNotIn("Price per share", [label for label, value in fields])
                self.assertNotIn("Listing currency", [label for label, value in fields])
                provider.return_value.quote.assert_called_once_with(ticker.upper())
                provider.return_value.usd_cad.assert_not_called()
                added = app.portfolio.groups[0].securities[-1]
                self.assertEqual(
                    (added.price, added.currency, added.quote_as_of),
                    (quote.price, quote.currency, quote.as_of),
                )
                self.assertEqual(added.shares, Decimal("2.5"))
                self.assertEqual(
                    app.portfolio.groups[0].preferred_ticker, ticker.upper()
                )
                self.assertEqual(app.current(), (0, 2))
                self.assertTrue(app.dirty)
                self.assertEqual(app.screen.timeouts, [100, -1])

    def test_failed_add_leaves_portfolio_unchanged(self):
        for outcome in (
            ValueError("Network unavailable"),
            Quote(Decimal("100"), "EUR", "Yahoo close test"),
            Quote(Decimal("100"), "", "Yahoo close test"),
            Quote(Decimal("0"), "CAD", "Yahoo close test"),
            Quote(Decimal("100"), "CAD", ""),
        ):
            with self.subTest(outcome=outcome):
                app = self.app()
                original = app.portfolio
                with (
                    patch.object(app, "form", return_value=["NEW.TO", "0", "y"]),
                    patch("portfolio_builder.tui.YahooProvider") as provider,
                ):
                    provider.return_value.quote.side_effect = [outcome]
                    with self.assertRaises(ValueError):
                        app.edit_security(True)
                self.assertIs(app.portfolio, original)
                self.assertFalse(app.dirty)
                self.assertEqual(app.selected, 0)
                self.assertEqual(app.screen.timeouts, [100, -1])

    def test_cancel_add_discards_late_quote(self):
        app = self.app(keys="\x1b")
        original = app.portfolio
        with (
            patch.object(app, "form", return_value=["NEW.TO", "0", "y"]),
            patch("portfolio_builder.tui.threading.Thread") as thread,
            patch("portfolio_builder.tui.YahooProvider") as provider,
        ):
            provider.return_value.quote.return_value = Quote(
                Decimal("100"), "CAD", "Yahoo close test"
            )
            app.edit_security(True)
            thread.call_args.kwargs["target"]()
        self.assertIs(app.portfolio, original)
        self.assertFalse(app.dirty)
        self.assertEqual(app.status, "Add cancelled; no security added.")
        self.assertEqual(app.screen.timeouts, [100, -1])

    def test_cancel_add_form_does_not_fetch(self):
        app = self.app()
        with (
            patch.object(app, "form", return_value=None),
            patch("portfolio_builder.tui.YahooProvider") as provider,
        ):
            app.edit_security(True)
        provider.assert_not_called()
        self.assertFalse(app.dirty)

    def test_refresh_still_updates_prices_and_fx(self):
        app = self.app()
        with patch("portfolio_builder.tui.YahooProvider") as provider:
            provider.return_value.quote.side_effect = [
                Quote(Decimal("120"), "CAD", "Yahoo current test"),
                Quote(Decimal("110"), "USD", "Yahoo current test"),
                Quote(Decimal("16"), "CAD", "Yahoo close test"),
            ]
            provider.return_value.usd_cad.return_value = Quote(
                Decimal("1.4"), "CAD", "Yahoo current test"
            )
            app.refresh()
        self.assertEqual(app.portfolio.groups[0].securities[0].price, 120)
        self.assertEqual(app.portfolio.usd_cad, Decimal("1.4"))
        self.assertTrue(app.dirty)
        self.assertEqual(app.screen.timeouts, [100, -1])

    def test_rebalance_edit_preserves_target_and_price_timestamp(self):
        app = self.app()
        app.portfolio.mode = "rebalance"
        app.selected = 1
        with patch.object(
            app, "form", return_value=["VUN.TO", "CAD", "100", "80", "y"]
        ):
            app.edit_security()
        self.assertEqual(app.portfolio.groups[0].target, 40)
        self.assertEqual(app.portfolio.groups[0].securities[0].shares, 80)
        self.assertEqual(
            app.portfolio.groups[0].securities[0].quote_as_of, "illustrative only"
        )

    def test_bad_edit_does_not_mutate_portfolio(self):
        app = self.app()
        original = app.portfolio
        app.selected = 1
        with patch.object(app, "form", return_value=["ZAG.TO", "CAD", "100", "0", "y"]):
            with self.assertRaisesRegex(ValueError, "Duplicate ticker"):
                app.edit_security()
        self.assertIs(app.portfolio, original)
        self.assertFalse(app.dirty)

    def test_preferred_ticker_rename(self):
        app = self.app()
        app.selected = 1
        with patch.object(app, "form", return_value=["NEW.TO", "CAD", "100", "0", "y"]):
            app.edit_security()
        self.assertEqual(app.portfolio.groups[0].preferred_ticker, "NEW.TO")
        self.assertEqual(
            app.portfolio.groups[0].securities[0].quote_as_of, "manual / unverified"
        )

    def test_deleting_preferred_member_uses_remaining_member(self):
        app = self.app()
        app.selected = 1
        with patch.object(app, "confirm", return_value=True):
            app.delete()
        self.assertEqual(app.portfolio.groups[0].preferred().ticker, "VTI")
        app.draw()

    def test_plan_preview_does_not_consume_additional_cash(self):
        app = self.app()
        app.portfolio.additional_cash = Decimal("500")
        with patch.object(app, "viewer", return_value=""):
            app.show_plan()
        self.assertEqual(app.portfolio.additional_cash, 500)
        self.assertEqual(app.portfolio.groups[0].securities[0].shares, 0)

    def test_currency_mode_fractional_keys(self):
        app = self.app(keys="cmfqy")
        app.run()
        self.assertEqual(app.portfolio.display_currency, "USD")
        self.assertEqual(app.portfolio.mode, "rebalance")
        self.assertTrue(app.portfolio.fractional)

    def test_small_terminal_and_resize(self):
        app = self.app()
        app.screen.height, app.screen.width = 10, 40
        app.draw()
        self.assertTrue(any("needs at least" in line for line in app.screen.output))
        app.screen.height, app.screen.width = 30, 115
        app.draw()
        self.assertIn("PORTFOLIO / BUILDER", app.screen.output)

    def test_cancel_form(self):
        app = self.app(keys="\x1b")
        self.assertIsNone(app.form("Test", [("Value", "original")]))

    def test_form_replace_and_backspace(self):
        app = self.app(keys=["1", "2", curses.KEY_BACKSPACE, "3", "\n"])
        self.assertEqual(app.form("Test", [("Value", "original")]), ["13"])


if __name__ == "__main__":
    unittest.main()
