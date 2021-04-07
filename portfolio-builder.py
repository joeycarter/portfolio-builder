#!/usr/bin/env python3

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#     ____             __  ____      ___          ____        _ __    __           #
#    / __ \____  _____/ /_/ __/___  / (_)___     / __ )__  __(_) /___/ /__  _____  #
#   / /_/ / __ \/ ___/ __/ /_/ __ \/ / / __ \   / __  / / / / / / __  / _ \/ ___/  #
#  / ____/ /_/ / /  / /_/ __/ /_/ / / / /_/ /  / /_/ / /_/ / / / /_/ /  __/ /      #
# /_/    \____/_/   \__/_/  \____/_/_/\____/  /_____/\__,_/_/_/\__,_/\___/_/       #
#                                                                                  #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

"""
Portfolio Builder
=================

A simple tool to build an ETF-based portfolio with a mix of bonds and equities
depending on your preferred risk level and available cash.

The ETF selection used here is based on the "Model ETF Portfolios" article from
the Canadian Portfolio Manager website:

    https://www.canadianportfoliomanagerblog.com/model-etf-portfolios/
"""


import datetime
import enum
import glob
import sys

import click
import tabulate

import pandas as pd
import numpy as np
import yfinance as yf


# Custom exceptions
class PortfolioException(Exception):
    """Exceptions related to the portfolio builder."""

    pass


# Error messages
def echo_warning(msg):
    click.echo(f"{click.style('warning:', fg='yellow', bold=True)} {msg}", err=True)


def echo_error(msg):
    click.echo(f"{click.style('error:', fg='red', bold=True)} {msg}", err=True)


def echo_fatal(msg):
    click.echo(f"{click.style('fatal:', fg='red', bold=True)} {msg}", err=True)


class Mode(enum.Enum):
    build = 1  # Build a portfolio from scratch
    rebalance = 2  # Rebalance an existing portfolio


class Portfolio:
    """An object to represent a portfolio.

    Parameters
    ----------
    risk_level : int
        Risk level (0 to 10).

    etf_provider : str
        ETF provider. Currently on 'vanguard' and 'ishares' are supported.

    cash : float
        Cash to invest (CAD).

    fractions : bool
        Allow fractions when computing number of shares to buy/sell. Normally
        these numbers are required to be whole numbers.

    mode : :class:`.Mode`
        Portfolio mode. Choose from `build` (build a portfolio from scratch) and
        `rebalance` (rebalance an existing portfolio).

    verbose : bool, int
        Be verbose.
    """

    def __init__(self, risk_level, etf_provider, cash, fractions, mode, verbose):
        self.risk_level = risk_level
        self.etf_provider = etf_provider
        self.cash = cash
        self.fractions = fractions
        self.mode = mode
        self.verbose = verbose

        if etf_provider == "vanguard":
            self.allocations = pd.read_csv("data/allocations_vanguard.csv", index_col=0)

        elif etf_provider == "ishares":
            self.allocations = pd.read_csv("data/allocations_ishares.csv", index_col=0)

        else:
            raise PortfolioException(f"unknown ETF provider '{etf_provider}'")

        self.current_prices = None
        self.shares = None

        if self.mode == Mode.build:
            self.account = None
        elif self.mode == Mode.rebalance:
            self.account = self._read_account_data()
        else:
            raise PortfolioException(f"unknown portfolio mode '{self.mode}'")

    def _read_account_data(self):
        """Read current account data.

        Searches the 'accounts' directory for .csv files. If more than one file
        is found, the user is prompted to select which one to use.

        Returns
        -------
        account : pandas.DataFrame
            Current account data as a pandas DataFrame.
        """
        click.echo("Reading current account data...")

        account_files = glob.glob("accounts/*.csv")

        if len(account_files) == 1:
            account_file = account_files[0]

        elif len(account_files) > 1:
            click.echo("Found multiple account data files:")
            for i, account_file in enumerate(account_files):
                click.echo(f"  ({i}) {account_file}")

            while True:
                index = click.prompt(
                    "Please enter which account file you would like to use", type=int
                )

                if index >= 0 and index < len(account_files):
                    break
                else:
                    click.echo(f"Error: invalid account file {index}")

            account_file = account_files[index]

        else:
            raise PortfolioException("no account data file")

        if self.verbose:
            click.echo(f" -> Reading account data from file '{account_file}'")

        account = pd.read_csv(account_file)

        return account.iloc[0]  # For now only return first row

    def build(self):
        """Build the current portfolio based on current prices and available cash."""
        click.echo("Retrieving current ETF prices...")

        self.current_prices = yf.download(
            " ".join(self.allocations.columns), start=datetime.datetime.now()
        )["Close"].iloc[-1]

        click.echo("Done")

        # Use same ticker order
        self.current_prices = self.current_prices.reindex(self.allocations.columns)

        if self.mode == Mode.build:
            # Build from scratch
            self.shares = (
                self.cash * (self.allocations.loc[self.risk_level] / 100) / self.current_prices
            )

        elif self.mode == Mode.rebalance:
            # Rebalance current portfolio
            self.shares = (
                (self.allocations.loc[self.risk_level] / 100)
                * (self.cash + np.sum(self.account * self.current_prices))
                - self.account * self.current_prices
            ) / self.current_prices

        if not self.fractions:
            self.shares = np.floor(self.shares).astype("int")

        if np.all(self.shares == 0):
            echo_warning("Insufficient funds to build portfolio to targets")

        click.echo()

    def print_portfolio(self):
        if self.shares is None:
            echo_error("portfolio has not been built yet")

        if self.mode == Mode.build:
            data = {
                "ETF": self.shares.index.to_list(),
                "Price\n(CAD)": self.current_prices.to_list(),
                "To\nBuy/Sell": self.shares.to_list(),
                "Value\n(CAD)": (self.shares * self.current_prices).to_list(),
                "% of\nPortfolio": (
                    100
                    * (self.shares * self.current_prices)
                    / np.sum(self.shares * self.current_prices)
                ).to_list(),
                "Target % of\nPortfolio": self.allocations.loc[self.risk_level].to_list(),
            }

            if self.fractions:
                fmt = ("", ".3f", ".2f", ".2f", ".2f", ".2f")
            else:
                fmt = ("", ".3f", "", ".2f", ".2f", ".2f")

        elif self.mode == Mode.rebalance:
            total_shares = self.shares + self.account

            data = {
                "ETF": self.shares.index.to_list(),
                "Price\n(CAD)": self.current_prices.to_list(),
                "Current\nQuantity": self.account.to_list(),
                "To\nBuy/Sell": self.shares.to_list(),
                "Total\nQuantity": total_shares.to_list(),
                "Value\n(CAD)": (total_shares * self.current_prices).to_list(),
                "% of\nPortfolio": (
                    100
                    * (total_shares * self.current_prices)
                    / np.sum(total_shares * self.current_prices)
                ).to_list(),
                "Target % of\nPortfolio": self.allocations.loc[self.risk_level].to_list(),
            }

            if self.fractions:
                fmt = ("", ".3f", "", ".2f", ".2f", ".2f", ".2f", ".2f")
            else:
                fmt = ("", ".3f", "", "", ".2f", ".2f", ".2f", ".2f")

        click.echo("Your portfolio:")
        click.echo("~~~~~~~~~~~~~~~\n")

        click.echo(tabulate.tabulate(data, headers="keys", floatfmt=fmt))

        total_cost = np.sum(self.shares * self.current_prices)
        leftover_cash = self.cash - total_cost

        click.echo()
        click.echo(f"Total cost:    ${total_cost:.2f} CAD")
        click.echo(f"Leftover cash: ${leftover_cash:.2f} CAD")


@click.command(context_settings=dict(help_option_names=["-h", "--help"]))
@click.option(
    "-r",
    "--risk-level",
    type=click.IntRange(0, 10),
    prompt="Enter your risk level (0 to 10)",
    help="Risk level on a scale from 0 (all bonds) to 10 (all equities).",
)
@click.option(
    "-e",
    "--etf-provider",
    type=click.Choice(["vanguard", "ishares"], case_sensitive=False),
    prompt="Enter your preferred ETF provider",
    help="ETF provider. Choose from 'vanguard' and 'ishares'.",
)
@click.option(
    "-c",
    "--cash",
    type=float,
    prompt="Enter your cash available to invest (CAD)",
    help="Cash available to invest (CAD).",
)
@click.option(
    "-f",
    "--fractions",
    is_flag=True,
    default=False,
    help="Allow fractions when computing number of shares to buy/sell. "
    "Normally these numbers are required to be whole numbers.",
)
@click.option(
    "--rebalance",
    is_flag=True,
    default=False,
    help="Rebalance an existing portfolio. Place accounts in your portfolio in "
    "the 'accounts/' directory.",
)
@click.option(
    "-v", "--verbose", count=True, help="Be verbose. Multiple -v options increase the verbosity."
)
def main(risk_level, etf_provider, cash, fractions, rebalance, verbose):
    """A simple tool to build an ETF-based portfolio with a mix of bonds and
    equities depending on your preferred risk level and available cash.
    """
    try:
        mode = Mode.rebalance if rebalance else Mode.build

        portfolio = Portfolio(risk_level, etf_provider, cash, fractions, mode, verbose)
        portfolio.build()
        portfolio.print_portfolio()

    except KeyboardInterrupt:
        return 1

    except PortfolioException as err:
        echo_error(err)

    except Exception as err:
        echo_fatal(f"an unknown exception occurred: {err}")
        raise


if __name__ == "__main__":
    sys.exit(main())
