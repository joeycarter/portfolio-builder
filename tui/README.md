# Portfolio Builder

A keyboard-driven terminal app for creating and rebalancing portfolios of CAD- and
USD-listed securities. Define target percentages, enter holdings and cash, and
preview FX-aware buy/sell orders. Save the targets for your next rebalance.

## Run

Requires Python 3.11+ and an interactive terminal at least **90 columns × 22 rows**
(115 × 30 recommended). Linux/macOS use Python's standard-library `curses`; no
third-party packages are needed for offline operation.

```sh
python3 -m portfolio_builder
```

Start with the illustrative 40% equity / 60% bonds example:

```sh
python3 -m portfolio_builder --demo
```

The example has VUN.TO and VTI in the equity group, ZAG.TO in bonds, and CAD 10,000
to invest. **All example prices and FX rates are made-up inputs, not market data
or investment recommendations.** A new empty portfolio also starts with an
unverified placeholder USD/CAD rate; replace it before using the plan.

Optional installation provides the `portfolio-builder` command:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
portfolio-builder --demo
```

On Windows, activate with `.venv\Scripts\activate`; installation includes
`windows-curses`. The core planner and JSON output do not require curses.

## Create a portfolio

1. Press **N** to add a group and its target percentage. For a single security,
   give it its own group (for example, `VUN`, target `40`).
2. Press **A** to add the ticker to the selected group. Enter `0` current shares.
   Its listing currency and price are fetched online automatically:
   the current regular-session price, or the last available close outside trading
   hours. Install the quote dependency below first; no manual currency or price is requested.
3. Add the other group(s), for example `Bonds`, target `60`, ticker `ZAG.TO`.
   Targets must total exactly 100% before a plan can be generated.
4. Press **B** to enter available CAD and/or USD cash. You can also enter a
   separate additional deposit; do not include that deposit in both fields.
5. Press **X** to set the exchange rate as **CAD per 1 USD**. **C** changes the
   display currency without changing the resulting orders.
6. Press **P** to preview allocations, proposed orders, projected holdings,
   residual cash, currency shortfalls, and the input quote timestamps.
7. In the plan, **E** exports orders to CSV. On the main screen, **S** saves the
   portfolio as JSON.

Forms use Tab/Enter to advance and Up to go back. Typing replaces a highlighted
value; Backspace edits it, and Ctrl-U clears it. Enter on the last field or Ctrl-S
submits. Esc cancels. The full guide is available with **?**.

## Rebalance

Load your saved portfolio with **L** or `--file`, then press **M** for rebalance
mode. Use Up/Down and Enter to edit each ticker's **actual current share count**.
Enter existing uninvested cash and an optional new deposit with **B**, update
prices/FX, and press **P**. Saved target percentages are reused.

```sh
python3 -m portfolio_builder --file examples/rebalance.json
```

Rebalancing accounts for the total value of existing holdings plus both cash
balances and the additional deposit. New cash can eliminate the need for sales.
Otherwise, the plan sells overweight groups before buying underweight groups.

**Planning, exporting, and saving do not execute trades or update holdings.**
After making any real trades, update share counts and cash balances, clear the
additional deposit already invested, and save. This prevents counting the same
deposit twice on the next rebalance. Create mode rejects nonzero holdings rather
than silently ignoring them.

## Shared targets / interchangeable securities

A group has one target percentage and one preferred ticker for new purchases.
For example:

| Group | Target | Members | Preferred purchase |
| --- | ---: | --- | --- |
| Equity | 40% | VUN.TO (CAD), VTI (USD) | VUN.TO |
| Bonds | 60% | ZAG.TO (CAD) | ZAG.TO |

The equity target applies to the **combined, currency-converted market value**
of VUN.TO and VTI. If the group is at target, its members are left alone: the app
does not sell one merely to buy the other. If it needs more investment, purchases
go to the preferred ticker (marked `*`). Change it in the group or ticker editor.

An overweight group is sold down in ascending CAD-equivalent share-price order,
then ticker order, to make rounding deterministic. This is not tax-lot selection
or a tax optimizer. Members have no individual sub-targets; use separate groups
if each ticker needs its own percentage. A ticker may appear in only one group.
The app does not verify that grouped funds have equivalent underlying exposure.

Set a group's target to **0%** to propose liquidating it. Deleting it instead
removes it from the model and does **not** generate a sale.

## Currency and rounding rules

- Calculations use `Decimal` and a canonical CAD valuation. USD prices, holdings,
  and cash are multiplied by USD/CAD before computing percentages. USD display
  divides CAD valuations by the same rate; it never influences trade quantities.
- Total value includes all holdings, existing cash, and the optional deposit.
  Each group's target value is `total × target_percent / 100`.
- Whole shares are the default. Sales round down without taking a group below
  its target, and buys round down within its deficit and the available cash.
  Underweight groups are processed in their saved order. This deterministic
  heuristic does not claim globally optimal allocation or minimum turnover.
- **F** enables fractional orders in increments of `0.000001` shares. Existing
  fractional holdings can be entered in either mode. Full liquidation of a 0%
  group includes its entire fractional balance, even in whole-share mode.
- Rounding can leave uninvested cash and allocation drift. Reported percentages
  include residual cash in their denominator rather than hiding it by
  renormalizing invested positions to 100%.
- All cash is treated as convertible at the entered FX rate. The plan reports
  CAD and USD settlement balances **before FX conversion**; a negative balance
  identifies a currency shortfall to cover before buying. The app does not
  execute conversions, model settlement timing, or assume a margin account.
- No commissions, FX spreads, capital-gains taxes, tax lots, account restrictions,
  short selling, or leverage are modeled. Review all inputs and orders yourself.

## Automatic prices and quote refresh

Adding a ticker requires online prices. Existing prices and FX can still be
edited manually offline. To enable automatic prices and **R**:

```sh
pip install -e '.[quotes]'
```

The optional `yfinance` adapter requests the **latest regular-session price**,
and quote currency when adding a ticker. Pressing **R** refreshes all securities
and the `CAD=X` USD/CAD rate. During regular
market hours it uses the current reported price; outside regular hours it uses
the most recent session's closing price, including before opening, after closing,
weekends, and holidays. Pre-market and after-hours prices are not used.

The adapter reads Yahoo's `regularMarketPrice` and `regularMarketTime`, rather
than daily history or `regularMarketPreviousClose` (which can refer to an older
session). Yahoo's market state labels the quote as current or close; an unavailable
or unrecognized state is labeled regular-session instead. No local-clock market
schedule is assumed. Missing or invalid regular-session prices/timestamps cause
refresh to fail rather than silently substituting other prices.

Quotes may be delayed and are not executable live quotes. The provider's actual
quote timestamp (UTC) is shown for each security and in the plan; check it for
staleness. Prices are fetched when adding a ticker or refreshing, not streamed automatically.
Tickers must match the provider's symbols (for example `VUN.TO` on
Toronto vs `VTI` in the US). Listing currency is determined from the provider's
quote when adding a ticker, never guessed from the symbol. Only CAD and USD are
supported. Existing securities can still be edited manually; provider currency
mismatches during refresh are rejected.

Adding a ticker and refreshing run off the UI thread and can be cancelled with
Esc. If fetching a new ticker's price fails or is cancelled, it is not added.
A missing ticker,
network failure, unsupported currency, or invalid rate leaves **all** existing
quotes unchanged. Provider availability, market-data permissions, and rate limits
remain external dependencies. Existing securities can use manual values if refresh is unavailable.

## Saved files and noninteractive use

By default the app loads `portfolio.json` if it exists, or starts empty. **S**
allows saving elsewhere; **L** opens another file. Targets, group membership,
preferred tickers, quote dates, holdings, cash, and settings are persisted.
Incomplete draft targets can be saved. Saving uses a temporary file and atomic
replacement, and the TUI asks before overwriting an existing file.

```sh
python3 -m portfolio_builder --file examples/rebalance.json --plan
python3 -m portfolio_builder --demo --plan --export orders.csv
```

JSON plans include canonical fields suffixed `_cad`, display currency and display
totals, local-currency order prices, allocations, projected share counts, warnings,
and settlement cash by currency. Decimal amounts are serialized as strings.
CSV contains local and display values plus the FX rate. Headless exports refuse
to overwrite existing files. No broker credentials or API keys are required.

## Development

```sh
python3 -m unittest discover -v
```

Tests cover creation/rebalancing, mixed-currency cash, shared targets, unchanged
group mixes, additional deposits, display-currency invariance, fractional/whole
rounding, validation, atomic persistence, quote-provider failures, CLI output, and
keyboard-driven TUI workflows. Randomized scenarios check value conservation and
nonnegative cash/holdings. Quote-provider tests use mocks, not external services.

The project is split into `models.py` (inputs/validation), `engine.py` (pure
allocation logic), `storage.py` (JSON/CSV), `quotes.py` (optional adapter), and
`tui.py` (curses interface).
