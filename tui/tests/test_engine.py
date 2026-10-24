import copy
import random
import unittest
from decimal import Decimal

from portfolio_builder.engine import build_plan
from portfolio_builder.models import Group, Portfolio, Security, number


def security(ticker="VUN.TO", currency="CAD", price="100", shares="0"):
    return Security(ticker, currency, Decimal(price), Decimal(shares))


def group(name, target, *members, preferred=""):
    return Group(name, Decimal(target), list(members), preferred)


class EngineTests(unittest.TestCase):
    def test_create_40_60(self):
        portfolio = Portfolio(
            groups=[
                group("Equity", "40", security()),
                group("Bonds", "60", security("ZAG.TO", price="15")),
            ],
            cash_cad=Decimal("10000"),
        )
        plan = build_plan(portfolio)
        self.assertEqual(
            plan.final_shares, {"VUN.TO": Decimal("40"), "ZAG.TO": Decimal("400")}
        )
        self.assertEqual(plan.remaining_cash_cad, 0)
        self.assertEqual([entry.actual_percent for entry in plan.allocations], [40, 60])

    def test_mixed_currency_percentages_include_fx(self):
        portfolio = Portfolio(
            groups=[
                group("Canada", "40", security()),
                group("US", "60", security("VTI", "USD", "100")),
            ],
            usd_cad=Decimal("1.5"),
            cash_cad=Decimal("1000"),
        )
        plan = build_plan(portfolio)
        self.assertEqual(plan.final_shares, {"VUN.TO": 4, "VTI": 4})
        self.assertEqual(plan.settlement_cash, {"CAD": 600, "USD": -400})
        self.assertTrue(any("400.00 USD" in warning for warning in plan.warnings))

    def test_display_currency_never_changes_orders_or_rounding(self):
        portfolio = Portfolio(
            groups=[
                group("CAD", "33.33", security(price="18.97")),
                group("USD", "66.67", security("VTI", "USD", "278.91")),
            ],
            usd_cad=Decimal("1.37819"),
            cash_cad=Decimal("7777.77"),
            cash_usd=Decimal("333.33"),
            fractional=True,
        )
        cad = build_plan(portfolio)
        portfolio.display_currency = "USD"
        self.assertEqual(cad, build_plan(portfolio))

    def test_rebalance_sells_then_buys(self):
        portfolio = Portfolio(
            groups=[
                group("Equity", "40", security(shares="80")),
                group("Bonds", "60", security("ZAG.TO", price="100", shares="20")),
            ],
            mode="rebalance",
        )
        plan = build_plan(portfolio)
        self.assertEqual(
            [(order.side, order.shares) for order in plan.orders],
            [("SELL", 40), ("BUY", 40)],
        )
        self.assertEqual(plan.final_shares, {"VUN.TO": 40, "ZAG.TO": 60})

    def test_new_cash_can_rebalance_without_sales(self):
        portfolio = Portfolio(
            groups=[
                group("A", "50", security(shares="10")),
                group("B", "50", security("ZAG.TO", shares="5")),
            ],
            mode="rebalance",
            additional_cash=Decimal("500"),
        )
        plan = build_plan(portfolio)
        self.assertEqual(len(plan.orders), 1)
        self.assertEqual(plan.orders[0].ticker, "ZAG.TO")
        self.assertEqual(plan.orders[0].side, "BUY")
        self.assertEqual(plan.orders[0].shares, 5)

    def test_cash_and_additional_usd(self):
        portfolio = Portfolio(
            groups=[group("A", "100", security())],
            usd_cad=Decimal("1.5"),
            cash_cad=Decimal("100"),
            cash_usd=Decimal("200"),
            additional_cash=Decimal("400"),
            additional_currency="USD",
        )
        plan = build_plan(portfolio)
        self.assertEqual(plan.total_cad, 1000)
        self.assertEqual(plan.final_shares["VUN.TO"], 10)

    def test_group_retains_existing_member_mix(self):
        portfolio = Portfolio(
            groups=[
                group(
                    "Equity",
                    "50",
                    security(shares="5"),
                    security("VTI", "USD", "100", "2"),
                ),
                group("Bonds", "50", security("ZAG.TO", price="100", shares="8")),
            ],
            usd_cad=Decimal("1.5"),
            mode="rebalance",
        )
        plan = build_plan(portfolio)
        self.assertEqual(plan.orders, ())
        self.assertEqual(plan.final_shares, {"VUN.TO": 5, "VTI": 2, "ZAG.TO": 8})

    def test_group_buys_only_preferred_member(self):
        portfolio = Portfolio(
            groups=[
                group(
                    "Equity",
                    "100",
                    security(),
                    security("VTI", "USD", "100"),
                    preferred="VTI",
                )
            ],
            cash_cad=Decimal("1500"),
            usd_cad=Decimal("1.5"),
        )
        plan = build_plan(portfolio)
        self.assertEqual(plan.final_shares, {"VUN.TO": 0, "VTI": 10})

    def test_group_overweight_sells_across_members(self):
        portfolio = Portfolio(
            groups=[
                group(
                    "Equity",
                    "20",
                    security(shares="5"),
                    security("VTI", "USD", "100", "10"),
                ),
                group("Bonds", "80", security("ZAG.TO", price="100")),
            ],
            mode="rebalance",
            usd_cad=Decimal("1.5"),
        )
        plan = build_plan(portfolio)
        self.assertEqual(
            [(order.ticker, order.side, order.shares) for order in plan.orders],
            [("VUN.TO", "SELL", 5), ("VTI", "SELL", 7), ("ZAG.TO", "BUY", 15)],
        )
        self.assertEqual(plan.remaining_cash_cad, 50)
        self.assertEqual(plan.final_shares["VTI"], 3)

    def test_whole_shares_leave_cash_without_overspending(self):
        portfolio = Portfolio(
            groups=[group("A", "100", security(price="333"))], cash_cad=Decimal("1000")
        )
        plan = build_plan(portfolio)
        self.assertEqual(plan.final_shares["VUN.TO"], 3)
        self.assertEqual(plan.remaining_cash_cad, 1)
        self.assertEqual(plan.allocations[0].actual_percent, Decimal("99.9"))

    def test_fractional_shares_use_six_decimals(self):
        portfolio = Portfolio(
            groups=[group("A", "100", security(price="300"))],
            cash_cad=Decimal("1000"),
            fractional=True,
        )
        plan = build_plan(portfolio)
        self.assertEqual(plan.final_shares["VUN.TO"], Decimal("3.333333"))
        self.assertEqual(plan.remaining_cash_cad, Decimal("0.0001"))

    def test_whole_orders_retain_fractional_holdings(self):
        portfolio = Portfolio(
            groups=[
                group("A", "50", security(shares="10.5")),
                group("B", "50", security("ZAG.TO")),
            ],
            mode="rebalance",
        )
        plan = build_plan(portfolio)
        self.assertEqual(plan.final_shares["VUN.TO"], Decimal("5.5"))
        self.assertTrue(
            all(
                order.shares == order.shares.to_integral_value()
                for order in plan.orders
            )
        )

    def test_zero_percent_group_fully_liquidates(self):
        portfolio = Portfolio(
            groups=[
                group("A", "0", security(shares="10.5")),
                group("B", "100", security("ZAG.TO")),
            ],
            mode="rebalance",
        )
        plan = build_plan(portfolio)
        self.assertEqual(plan.final_shares["VUN.TO"], 0)
        self.assertEqual(plan.orders[0].shares, Decimal("10.5"))
        self.assertTrue(any("Liquidating" in warning for warning in plan.warnings))

    def test_plan_does_not_mutate_inputs(self):
        portfolio = Portfolio(
            groups=[group("A", "100", security())], additional_cash=Decimal("1000")
        )
        original = copy.deepcopy(portfolio)
        self.assertEqual(build_plan(portfolio), build_plan(portfolio))
        self.assertEqual(portfolio, original)

    def test_validation(self):
        valid = Portfolio(
            groups=[group("A", "100", security())], cash_cad=Decimal("1000")
        )
        mutations = [
            lambda item: setattr(item, "usd_cad", Decimal("0")),
            lambda item: setattr(item, "cash_cad", Decimal("-1")),
            lambda item: setattr(item, "display_currency", "EUR"),
            lambda item: setattr(item, "additional_currency", "EUR"),
            lambda item: setattr(item, "mode", "other"),
            lambda item: setattr(item, "fractional", "false"),
            lambda item: setattr(item.groups[0], "target", Decimal("99.999")),
            lambda item: setattr(item.groups[0], "preferred_ticker", "BAD"),
            lambda item: setattr(item.groups[0].securities[0], "shares", Decimal("1")),
            lambda item: setattr(item.groups[0].securities[0], "price", Decimal("0")),
            lambda item: setattr(item.groups[0].securities[0], "price", Decimal("NaN")),
            lambda item: setattr(item.groups[0].securities[0], "shares", Decimal("-1")),
            lambda item: setattr(item.groups[0].securities[0], "currency", "EUR"),
            lambda item: setattr(item.groups[0].securities[0], "ticker", "BAD TICKER"),
            lambda item: item.groups[0].securities.clear(),
            lambda item: item.groups.clear(),
            lambda item: item.groups.append(group("B", "0", security())),
            lambda item: item.groups.append(group("a", "0", security("ZAG.TO"))),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                portfolio = copy.deepcopy(valid)
                mutate(portfolio)
                with self.assertRaises(ValueError):
                    build_plan(portfolio)

    def test_zero_value_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "positive value"):
            build_plan(Portfolio(groups=[group("A", "100", security())]))

    def test_invalid_numeric_values(self):
        for value in (
            "NaN",
            "Infinity",
            "-Infinity",
            "abc",
            "1e100",
            "1e-100",
            True,
            None,
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                number(value)

    def test_randomized_conservation_and_nonnegative_quantities(self):
        generator = random.Random(8128)
        for iteration in range(250):
            targets = sorted(
                [0, 100, generator.randint(0, 100), generator.randint(0, 100)]
            )
            groups = []
            for index in range(3):
                groups.append(
                    group(
                        str(index),
                        str(targets[index + 1] - targets[index]),
                        security(
                            f"CAD{index}",
                            "CAD",
                            str(generator.randint(1, 400)),
                            str(Decimal(generator.randint(0, 10000)) / 100),
                        ),
                        security(
                            f"USD{index}",
                            "USD",
                            str(generator.randint(1, 400)),
                            str(Decimal(generator.randint(0, 10000)) / 100),
                        ),
                    )
                )
            portfolio = Portfolio(
                groups=groups,
                mode="rebalance",
                fractional=bool(iteration % 2),
                usd_cad=Decimal(generator.randint(11000, 17000)) / 10000,
                cash_cad=Decimal(generator.randint(0, 10000)),
            )
            plan = build_plan(portfolio)
            with self.subTest(iteration=iteration):
                self.assertGreaterEqual(plan.remaining_cash_cad, 0)
                self.assertTrue(
                    all(shares >= 0 for shares in plan.final_shares.values())
                )
                self.assertEqual(
                    sum(entry.after_cad for entry in plan.allocations)
                    + plan.remaining_cash_cad,
                    plan.total_cad,
                )
                self.assertEqual(
                    plan.settlement_cash["CAD"]
                    + plan.settlement_cash["USD"] * portfolio.usd_cad,
                    plan.remaining_cash_cad,
                )
                for entry in plan.allocations:
                    if entry.before_cad > entry.target_cad:
                        self.assertGreaterEqual(entry.after_cad, entry.target_cad)
                    else:
                        self.assertLessEqual(entry.after_cad, entry.target_cad)


if __name__ == "__main__":
    unittest.main()
