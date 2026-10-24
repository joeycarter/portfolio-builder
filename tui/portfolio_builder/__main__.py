import argparse
import json
import sys
from pathlib import Path

from portfolio_builder.engine import build_plan
from portfolio_builder.models import Portfolio
from portfolio_builder.storage import (
    export_orders,
    load_portfolio,
    plan_to_dict,
    portfolio_from_dict,
)


def demo_portfolio() -> Portfolio:
    return portfolio_from_dict(
        {
            "version": 1,
            "display_currency": "CAD",
            "usd_cad": "1.35",
            "cash_cad": "10000",
            "fx_as_of": "illustrative only - not market data",
            "mode": "create",
            "groups": [
                {
                    "name": "Equity",
                    "target": "40",
                    "preferred_ticker": "VUN.TO",
                    "securities": [
                        {
                            "ticker": "VUN.TO",
                            "currency": "CAD",
                            "price": "100",
                            "quote_as_of": "illustrative only",
                        },
                        {
                            "ticker": "VTI",
                            "currency": "USD",
                            "price": "250",
                            "quote_as_of": "illustrative only",
                        },
                    ],
                },
                {
                    "name": "Bonds",
                    "target": "60",
                    "securities": [
                        {
                            "ticker": "ZAG.TO",
                            "currency": "CAD",
                            "price": "15",
                            "quote_as_of": "illustrative only",
                        },
                    ],
                },
            ],
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build and rebalance CAD/USD portfolios in your terminal."
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=Path("portfolio.json"),
        help="Saved portfolio JSON (default: portfolio.json)",
    )
    parser.add_argument(
        "--demo", action="store_true", help="Start with illustrative 40/60 example data"
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Print a JSON plan without launching the TUI",
    )
    parser.add_argument(
        "--export",
        type=Path,
        metavar="CSV",
        help="Export orders (requires --plan; refuses overwrite)",
    )
    args = parser.parse_args(argv)
    if args.export and not args.plan:
        parser.error("--export requires --plan")
    try:
        if args.demo:
            portfolio = demo_portfolio()
        elif args.file.expanduser().exists():
            portfolio = load_portfolio(args.file)
        elif args.plan or args.file != Path("portfolio.json"):
            raise ValueError(f"Portfolio not found: {args.file}")
        else:
            portfolio = Portfolio()
        if args.plan:
            plan = build_plan(portfolio)
            if args.export:
                if args.export.expanduser().exists():
                    raise ValueError(f"Export already exists: {args.export}")
                export_orders(plan, portfolio, args.export)
            print(json.dumps(plan_to_dict(plan, portfolio), default=str, indent=2))
        else:
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                raise ValueError(
                    "The TUI needs an interactive terminal. Use --plan for JSON output."
                )
            from portfolio_builder.tui import run_tui

            run_tui(portfolio, args.file, dirty=args.demo)
    except (ValueError, OSError, ArithmeticError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except ImportError as error:
        print(
            f"Missing dependency: {error}. On Windows install windows-curses.",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
