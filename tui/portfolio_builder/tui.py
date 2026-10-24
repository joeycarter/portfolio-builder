import copy
import curses
import queue
import textwrap
import threading
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

from portfolio_builder.engine import build_plan
from portfolio_builder.models import (
    HUNDRED,
    ZERO,
    Group,
    Portfolio,
    Security,
    currency,
    nonnegative,
    number,
    positive,
)
from portfolio_builder.quotes import YahooProvider, refresh_quotes
from portfolio_builder.storage import export_orders, load_portfolio, save_portfolio


def amount(value: Decimal) -> str:
    return f"{value:,.2f}"


def quantity(value: Decimal) -> str:
    return (
        format(value, "f").rstrip("0").rstrip(".")
        if "." in format(value, "f")
        else str(value)
    )


class App:
    def __init__(self, screen, portfolio: Portfolio, path: Path, dirty: bool = False):
        self.screen = screen
        self.portfolio = portfolio
        self.path = path
        self.dirty = dirty
        self.selected = 0
        self.offset = 0
        self.status = "Start with N: add a target group, then A: add its ticker. Press ? for help."
        self.accent = curses.A_BOLD
        self.muted = curses.A_DIM
        self.highlight = curses.A_REVERSE
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)
            self.accent = curses.color_pair(1) | curses.A_BOLD
            self.highlight = curses.color_pair(2) | curses.A_BOLD
        self.screen.keypad(True)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def put(self, row: int, column: int, content: str, style: int = 0) -> None:
        height, width = self.screen.getmaxyx()
        if 0 <= row < height and 0 <= column < width - 1:
            try:
                self.screen.addnstr(row, column, content, width - column - 1, style)
            except curses.error:
                pass

    def rows(self) -> list[tuple[int, int | None]]:
        return [
            entry
            for group_index, group in enumerate(self.portfolio.groups)
            for entry in [
                (group_index, None),
                *[(group_index, index) for index in range(len(group.securities))],
            ]
        ]

    def current(self) -> tuple[int, int | None]:
        rows = self.rows()
        if not rows:
            raise ValueError("Add a group first (N).")
        return rows[min(self.selected, len(rows) - 1)]

    def money(self, cad_value: Decimal) -> str:
        return amount(self.portfolio.convert(cad_value, "CAD"))

    def draw(self) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        portfolio = self.portfolio
        if height < 22 or width < 90:
            self.put(
                0,
                0,
                "Portfolio Builder needs at least 90 columns x 22 rows.",
                self.accent,
            )
            self.put(2, 0, f"Current size: {width} x {height}. Resize, or Q to quit.")
            self.screen.refresh()
            return
        self.put(0, 2, "PORTFOLIO / BUILDER", self.accent)
        self.put(
            0,
            27,
            f"{portfolio.mode.upper()}  |  {portfolio.display_currency} display  |  "
            f"{'fractional' if portfolio.fractional else 'whole'} shares",
        )
        self.put(
            1,
            2,
            f"{'* unsaved' if self.dirty else 'saved / unchanged'}  {self.path}",
            self.muted,
        )
        holdings = sum(
            (
                security.shares * portfolio.price_cad(security)
                for group in portfolio.groups
                for security in group.securities
            ),
            ZERO,
        )
        total = holdings + portfolio.cash_in_cad()
        self.put(
            3,
            2,
            f"PORTFOLIO VALUE  {self.money(total)} {portfolio.display_currency}",
            self.accent,
        )
        self.put(
            4,
            2,
            f"Holdings {self.money(holdings)}   Cash + deposit {self.money(portfolio.cash_in_cad())}   "
            f"1 USD = {portfolio.usd_cad} CAD",
        )
        self.put(
            5,
            2,
            f"Cash: {amount(portfolio.cash_cad)} CAD + {amount(portfolio.cash_usd)} USD   "
            f"Additional: {amount(portfolio.additional_cash)} {portfolio.additional_currency}",
        )
        target_sum = sum((group.target for group in portfolio.groups), ZERO)
        self.put(
            6,
            2,
            f"Targets: {target_sum}% {'[ready]' if target_sum == HUNDRED else '[must total 100%]'}   "
            f"FX: {portfolio.fx_as_of}",
            self.muted,
        )
        self.put(
            8,
            2,
            f"{'GROUP / TICKER':<27} {'TARGET':>7} {'CURRENT':>8} {'SHARES':>12} "
            f"{'LOCAL PRICE':>13} {'VALUE (' + portfolio.display_currency + ')':>16}",
            self.accent,
        )
        rows = self.rows()
        self.selected = max(0, min(self.selected, len(rows) - 1))
        visible = height - 16
        self.offset = max(0, min(self.offset, self.selected))
        if self.selected >= self.offset + visible:
            self.offset = self.selected - visible + 1
        for screen_row, (group_index, security_index) in enumerate(
            rows[self.offset : self.offset + visible], 9
        ):
            group = portfolio.groups[group_index]
            style = (
                self.highlight if screen_row - 9 + self.offset == self.selected else 0
            )
            if security_index is None:
                value = sum(
                    (
                        security.shares * portfolio.price_cad(security)
                        for security in group.securities
                    ),
                    ZERO,
                )
                percent = value / total * HUNDRED if total else ZERO
                line = f"{group.name[:27]:<27} {group.target:>6.2f}% {percent:>7.2f}% {'':>12} {'':>13} {self.money(value):>16}"
            else:
                security = group.securities[security_index]
                preferred = "*" if group.preferred().ticker == security.ticker else " "
                label = f"  {preferred} {security.ticker}"
                line = (
                    f"{label[:27]:<27} {'':>7} {'':>8} {quantity(security.shares):>12} "
                )
                line += f"{amount(security.price):>9} {security.currency} {self.money(security.shares * portfolio.price_cad(security)):>16}"
            self.put(screen_row, 2, line.ljust(width - 4), style)
        if not rows:
            self.put(
                10, 4, "No securities yet. N creates a group; A adds a ticker to it."
            )
            self.put(
                12,
                4,
                "One ticker per group = individual target. Multiple tickers = shared target.",
                self.muted,
            )
        if rows:
            group_index, security_index = self.current()
            group = portfolio.groups[group_index]
            detail = (
                f"Buy ticker: {group.preferred().ticker if group.securities else '(add a ticker)'} | "
                "Group members share one target; existing mix is preserved."
            )
            if security_index is not None:
                detail = f"{group.securities[security_index].ticker} quote: {group.securities[security_index].quote_as_of}"
            self.put(height - 6, 2, detail, self.muted)
        self.put(height - 5, 2, self.status, self.accent)
        self.put(
            height - 4,
            2,
            "N new group   A add ticker   Enter edit   D delete   Up/Down select   ? help",
        )
        self.put(
            height - 3,
            2,
            "M mode   C currency   B cash   X FX   F fractional   R refresh   P plan",
        )
        self.put(
            height - 2,
            2,
            "S save   L load   Q quit    * = preferred buy ticker; quotes and FX need review",
            self.muted,
        )
        self.screen.refresh()

    def form(
        self, title: str, fields: list[tuple[str, str]], hint: str = ""
    ) -> list[str] | None:
        values = [value for _, value in fields]
        active = 0
        replace = True
        while True:
            self.screen.erase()
            height, width = self.screen.getmaxyx()
            self.put(1, 2, title, self.accent)
            for index, line in enumerate(
                textwrap.wrap(hint, max(20, width - 6))[:3], 3
            ):
                self.put(index, 2, line, self.muted)
            first = max(0, active - max(1, height - 12) + 1)
            for index in range(first, min(len(fields), first + max(1, height - 12))):
                row = 7 + index - first
                self.put(row, 2, fields[index][0][:27])
                visible_value = values[index][-(max(5, width - 34)) :]
                self.put(
                    row,
                    31,
                    (visible_value or " ").ljust(max(1, width - 34)),
                    self.highlight if index == active else 0,
                )
            self.put(
                height - 3,
                2,
                "Tab/Down next | Up previous | Enter next/submit | Ctrl-S submit | Esc cancel",
            )
            self.put(
                height - 2,
                2,
                "Typing replaces the selected value. Backspace edits; Ctrl-U clears.",
                self.muted,
            )
            self.screen.refresh()
            key = self.screen.get_wch()
            if key == "\x1b":
                return None
            if key == "\x13" or (
                key in ("\n", "\r", curses.KEY_ENTER) and active == len(fields) - 1
            ):
                return [value.strip() for value in values]
            if key in ("\t", curses.KEY_DOWN, "\n", "\r", curses.KEY_ENTER):
                active = (active + 1) % len(fields)
                replace = True
            elif key in (curses.KEY_UP, curses.KEY_BTAB):
                active = (active - 1) % len(fields)
                replace = True
            elif key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                values[active] = values[active][:-1]
                replace = False
            elif key == "\x15":
                values[active] = ""
                replace = False
            elif (
                isinstance(key, str) and key.isprintable() and len(values[active]) < 512
            ):
                values[active] = key if replace else values[active] + key
                replace = False

    def viewer(
        self,
        title: str,
        lines: list[str],
        footer: str = "Esc / Q / Enter to return",
        extra: str = "",
    ) -> str:
        offset = 0
        while True:
            self.screen.erase()
            height, width = self.screen.getmaxyx()
            wrapped = [
                part
                for line in lines
                for part in (
                    textwrap.wrap(line, max(20, width - 5), replace_whitespace=False)
                    or [""]
                )
            ]
            visible = max(1, height - 6)
            offset = min(offset, max(0, len(wrapped) - visible))
            self.put(1, 2, title, self.accent)
            for row, line in enumerate(wrapped[offset : offset + visible], 3):
                self.put(row, 2, line)
            self.put(height - 2, 2, f"{footer} | Up/Down/PgUp/PgDn scroll", self.muted)
            self.screen.refresh()
            key = self.screen.get_wch()
            if isinstance(key, str) and key.lower() in extra and key:
                return key.lower()
            if key in ("\x1b", "q", "Q", "\n", "\r", curses.KEY_ENTER):
                return ""
            if key in (curses.KEY_DOWN, "j"):
                offset = min(max(0, len(wrapped) - visible), offset + 1)
            elif key in (curses.KEY_UP, "k"):
                offset = max(0, offset - 1)
            elif key in (curses.KEY_NPAGE, " "):
                offset = min(max(0, len(wrapped) - visible), offset + visible)
            elif key == curses.KEY_PPAGE:
                offset = max(0, offset - visible)
            elif key == curses.KEY_HOME:
                offset = 0
            elif key == curses.KEY_END:
                offset = max(0, len(wrapped) - visible)

    def confirm(self, message: str) -> bool:
        return (
            self.viewer("Please confirm", [message], "Y confirm | Esc cancel", "y")
            == "y"
        )

    def commit(self, draft: Portfolio, status: str) -> None:
        draft.validate()
        self.portfolio = draft
        self.dirty = True
        self.status = status

    def edit_group(self, create: bool = False) -> None:
        index = len(self.portfolio.groups) if create else self.current()[0]
        group = Group("", ZERO) if create else self.portfolio.groups[index]
        result = self.form(
            "New target group" if create else "Edit target group",
            [
                ("Group name", group.name),
                ("Target percent", str(group.target)),
                ("Preferred buy ticker", group.preferred_ticker),
            ],
            "Targets across groups must total 100%. Leave buy ticker blank to use the first member. "
            "For an individual security, create a group with just that ticker.",
        )
        if result is None:
            return
        draft = copy.deepcopy(self.portfolio)
        updated = Group(
            result[0],
            number(result[1], "Target"),
            copy.deepcopy(group.securities),
            result[2].upper(),
        )
        if create:
            draft.groups.append(updated)
        else:
            draft.groups[index] = updated
        self.commit(
            draft,
            "Group saved. Add a ticker with A; edit the shared target with Enter.",
        )
        if create:
            self.selected = len(self.rows()) - 1

    def edit_security(self, create: bool = False) -> None:
        group_index, security_index = self.current()
        if not create and security_index is None:
            self.edit_group()
            return
        group = self.portfolio.groups[group_index]
        security = (
            Security("", "CAD", ZERO) if create else group.securities[security_index]
        )
        fields = [("Ticker (e.g. VUN.TO)", security.ticker)]
        if not create:
            fields.extend(
                [
                    ("Listing currency", security.currency),
                    ("Price per share", str(security.price)),
                ]
            )
        fields.extend(
            [
                ("Current shares", str(security.shares)),
                (
                    "Use for purchases? y/n",
                    "y"
                    if (
                        not group.securities
                        or group.preferred().ticker == security.ticker
                    )
                    else "n",
                ),
            ]
        )
        help_text = (
            "Listing currency and price are fetched automatically: current regular-session price, "
            "or the last close outside trading hours. "
            if create
            else "Prices are in the listing currency. Enter a positive manual price; R can refresh it later. "
        )
        result = self.form(
            f"{'Add ticker to' if create else 'Edit ticker in'} {group.name}",
            fields,
            help_text + "Rebalance uses current holdings. Create requires zero shares.",
        )
        if result is None:
            return
        preferred = result[-1].lower()
        if preferred not in ("y", "n"):
            raise ValueError("Use for purchases must be y or n.")
        updated = Security(
            result[0].upper(),
            "" if create else currency(result[1].upper()),
            ZERO if create else positive(result[2], "Price"),
            nonnegative(result[-2], "Shares"),
        )
        if create:

            def fetch_price() -> None:
                quote = YahooProvider().quote(updated.ticker)
                updated.currency = quote.currency
                updated.price = quote.price
                updated.quote_as_of = quote.as_of
                updated.validate()

            if not self.run_quote_request(
                fetch_price,
                f"Fetching price and currency for {updated.ticker}...",
                "Add cancelled; no security added.",
            ):
                return
        if (updated.ticker, updated.price, updated.currency) == (
            security.ticker,
            security.price,
            security.currency,
        ):
            updated.quote_as_of = security.quote_as_of
        draft = copy.deepcopy(self.portfolio)
        target_group = draft.groups[group_index]
        if create:
            target_group.securities.append(updated)
        else:
            target_group.securities[security_index] = updated
        if preferred == "y":
            target_group.preferred_ticker = updated.ticker
        elif target_group.preferred_ticker == security.ticker:
            target_group.preferred_ticker = next(
                (
                    item.ticker
                    for item in target_group.securities
                    if item.ticker != updated.ticker
                ),
                updated.ticker,
            )
        elif not target_group.preferred_ticker:
            target_group.preferred_ticker = next(
                (
                    item.ticker
                    for item in target_group.securities
                    if item.ticker != updated.ticker
                ),
                updated.ticker,
            )
        self.commit(
            draft, "Ticker saved. * marks the preferred security for group purchases."
        )
        self.selected = self.rows().index(
            (
                group_index,
                len(target_group.securities) - 1 if create else security_index,
            )
        )

    def delete(self) -> None:
        group_index, security_index = self.current()
        group = self.portfolio.groups[group_index]
        label = (
            f"group {group.name} and all its members"
            if security_index is None
            else group.securities[security_index].ticker
        )
        if not self.confirm(
            f"Delete {label}? This removes holdings from the model; it does NOT create a sell order. "
            "To liquidate, keep the group and set its target to 0%."
        ):
            return
        draft = copy.deepcopy(self.portfolio)
        if security_index is None:
            del draft.groups[group_index]
        else:
            target = draft.groups[group_index]
            removed = target.securities.pop(security_index)
            if target.preferred_ticker == removed.ticker:
                target.preferred_ticker = ""
        self.commit(draft, "Removed from portfolio model.")

    def edit_cash(self) -> None:
        portfolio = self.portfolio
        result = self.form(
            "Cash & additional investment",
            [
                ("Existing CAD cash", str(portfolio.cash_cad)),
                ("Existing USD cash", str(portfolio.cash_usd)),
                ("Additional cash", str(portfolio.additional_cash)),
                ("Additional currency", portfolio.additional_currency),
            ],
            "Create: enter your available cash. Rebalance: enter existing uninvested cash and an optional new deposit. "
            "Do not count the deposit twice. All cash is included in target percentages.",
        )
        if result is not None:
            draft = copy.deepcopy(portfolio)
            draft.cash_cad = nonnegative(result[0], "CAD cash")
            draft.cash_usd = nonnegative(result[1], "USD cash")
            draft.additional_cash = nonnegative(result[2], "Additional cash")
            draft.additional_currency = currency(result[3].upper())
            self.commit(draft, "Cash updated.")

    def edit_fx(self) -> None:
        result = self.form(
            "Exchange rate",
            [("CAD per 1 USD", str(self.portfolio.usd_cad))],
            "Example: 1.35 means 1 USD buys 1.35 CAD. The initial rate is a placeholder, not a market quote.",
        )
        if result is not None:
            draft = copy.deepcopy(self.portfolio)
            draft.usd_cad = positive(result[0], "FX rate")
            draft.fx_as_of = "manual / unverified"
            self.commit(
                draft, "Exchange rate updated. Percentages use converted values."
            )

    def refresh(self) -> None:
        draft = copy.deepcopy(self.portfolio)
        if self.run_quote_request(
            lambda: refresh_quotes(draft, YahooProvider()),
            "Refreshing quotes and USD/CAD...",
            "Refresh cancelled; prices unchanged.",
        ):
            self.commit(
                draft, "Quotes and FX refreshed. Review quote dates before planning."
            )

    def run_quote_request(
        self, action: Callable[[], object], title: str, cancelled_status: str
    ) -> bool:
        result_queue = queue.Queue()

        def worker() -> None:
            try:
                action()
                result_queue.put(None)
            except Exception as error:
                result_queue.put(error)

        threading.Thread(target=worker, daemon=True).start()
        self.screen.timeout(100)
        try:
            while True:
                self.screen.erase()
                self.put(2, 2, title, self.accent)
                self.put(
                    4,
                    2,
                    "Fetching regular-session prices (last close outside trading hours). Esc cancels.",
                )
                self.screen.refresh()
                try:
                    outcome = result_queue.get_nowait()
                except queue.Empty:
                    try:
                        if self.screen.get_wch() == "\x1b":
                            self.status = cancelled_status
                            return False
                    except curses.error:
                        pass
                    continue
                if outcome is not None:
                    raise ValueError(str(outcome))
                return True
        finally:
            self.screen.timeout(-1)

    def show_plan(self) -> None:
        plan = build_plan(self.portfolio)
        denomination = self.portfolio.display_currency
        lines = [
            f"Mode: {plan.mode.upper()} | Display: {denomination} | 1 USD = {self.portfolio.usd_cad} CAD",
            f"Total value: {self.money(plan.total_cad)} {denomination} | "
            f"Uninvested after trades: {self.money(plan.remaining_cash_cad)} {denomination}",
            "",
            "GROUP ALLOCATIONS (cash remains in the denominator)",
            f"{'Group':<24} {'Target':>8} {'After':>8} {'Before':>13} {'After value':>13} {'Target value':>13}",
        ]
        for allocation in plan.allocations:
            lines.append(
                f"{allocation.group[:24]:<24} {allocation.target_percent:>7.2f}% {allocation.actual_percent:>7.2f}% "
                f"{self.money(allocation.before_cad):>13} {self.money(allocation.after_cad):>13} "
                f"{self.money(allocation.target_cad):>13}"
            )
        lines.extend(["", "PROPOSED ORDERS (sells first; no orders are executed)"])
        for order in plan.orders:
            lines.append(
                f"{order.side:4} {quantity(order.shares):>12} {order.ticker:<12} @ {amount(order.price)} "
                f"{order.currency} = {amount(order.local_value)} {order.currency} "
                f"({self.money(order.value_cad)} {denomination}) [{order.group}]"
            )
        if not plan.orders:
            lines.append(
                "No orders: already at target or remaining differences are below the share increment."
            )
        lines.extend(["", "PROJECTED HOLDINGS"])
        for ticker, shares in plan.final_shares.items():
            lines.append(f"{ticker:<16} {quantity(shares)} shares")
        lines.extend(["", "CASH BY CURRENCY BEFORE FX CONVERSION"])
        for code, balance in plan.settlement_cash.items():
            lines.append(
                f"{code}: {amount(balance)} {'(shortfall: conversion required)' if balance < ZERO else ''}"
            )
        lines.extend(
            [
                "",
                "QUOTE / FX INPUTS",
                f"USD/CAD: {self.portfolio.usd_cad} | {self.portfolio.fx_as_of}",
            ]
        )
        for group in self.portfolio.groups:
            for security in group.securities:
                lines.append(
                    f"{security.ticker}: {security.price} {security.currency} | {security.quote_as_of}"
                )
        lines.extend(
            [
                "",
                "ASSUMPTIONS & WARNINGS",
                *plan.warnings,
                "",
                "This is a preview. Holdings, cash, and deposits are NOT changed by planning or exporting.",
                "After actual trades, edit current shares and cash; clear any deposit already invested.",
            ]
        )
        while (
            self.viewer("PORTFOLIO PLAN", lines, "E export CSV | Esc return", "e")
            == "e"
        ):
            result = self.form("Export proposed orders", [("CSV path", "orders.csv")])
            if result and result[0]:
                path = Path(result[0]).expanduser()
                if path.exists() and not self.confirm(f"Overwrite {path}?"):
                    continue
                export_orders(plan, self.portfolio, path)
                self.status = f"Orders exported to {path}. No holdings changed."
                self.viewer("Export complete", [self.status])

    def save(self) -> None:
        result = self.form(
            "Save portfolio",
            [("JSON path", str(self.path))],
            "Saves targets, groups, holdings, cash, prices, and settings. No trades are executed.",
        )
        if result and result[0]:
            path = Path(result[0]).expanduser()
            if path.exists() and not self.confirm(
                f"Replace the saved portfolio at {path}?"
            ):
                return
            save_portfolio(self.portfolio, path)
            self.path = path
            self.dirty = False
            self.status = f"Saved to {path}."

    def load(self) -> None:
        if self.dirty and not self.confirm(
            "Discard unsaved changes and load another portfolio?"
        ):
            return
        result = self.form("Load portfolio", [("JSON path", str(self.path))])
        if result and result[0]:
            path = Path(result[0]).expanduser()
            portfolio = load_portfolio(path)
            self.portfolio = portfolio
            self.path = path
            self.dirty = False
            self.selected = self.offset = 0
            self.status = f"Loaded {path}."

    def help(self) -> None:
        self.viewer(
            "QUICK GUIDE",
            [
                "CREATE: N adds a group with its desired percent; A adds its ticker and fetches its price online. "
                "Repeat until group targets total 100%. B sets cash, X sets USD/CAD, P previews purchases.",
                "",
                "REBALANCE: L loads your saved targets; M switches to rebalance. Edit each ticker's actual shares "
                "with Enter. B sets uninvested cash and an optional new deposit. P previews sales and purchases.",
                "",
                "GROUPS: For a 40% equity / 60% bond portfolio, create equity at 40% and bonds at 60%. "
                "Put VUN.TO (CAD) and VTI (USD) in equity, and ZAG.TO (CAD) in bonds. Equity's target applies "
                "to the combined, FX-adjusted value of VUN.TO and VTI. Choose either as the preferred buy ticker.",
                "",
                "EXISTING MIX: No trading between members just to adjust their mix. Purchases go to the preferred "
                "ticker; sales reduce an overweight group, lowest converted share price first. There are no "
                "per-member targets inside a group. Use separate groups for separate ticker percentages.",
                "",
                "WHOLE SHARES: Orders round down; small deviations and leftover cash are expected. F enables "
                "six-decimal fractional orders. A 0% group is fully liquidated, including fractional holdings. "
                "This is a deterministic heuristic, not a global minimum-drift or tax optimizer.",
                "",
                "FX: X sets CAD per USD. C only changes display units, never the orders. All available cash is "
                "treated as convertible buying power. Negative currency settlement balances mean you must "
                "convert currency before buying. Spreads, commissions, and taxes are not modeled.",
                "",
                "QUOTES: Adding a ticker fetches its price online. Existing prices can be edited manually offline. "
                "R downloads current regular-session prices and USD/CAD "
                "using yfinance; outside regular hours it uses the last session's close, not extended-hours prices. "
                "Data may be delayed. Review timestamps: prices are not executable live quotes. Listing currencies "
                "are explicit; a provider currency mismatch is rejected. A failed refresh changes nothing.",
                "",
                "KEYS: Up/Down select; Enter edit; N new group; A add ticker to selected group; D delete; "
                "M mode; C display currency; B cash; X FX; F fractional; R refresh; P plan; S save; L load; Q quit.",
                "",
                "FORMS: Typing replaces a highlighted value. Backspace edits it. Ctrl-U clears. Tab/Enter moves "
                "forward; Up moves back. Enter on the last field or Ctrl-S submits. Esc cancels.",
                "",
                "SAFETY: Plans and exports never update holdings or execute trades. After actual trades, update "
                "shares and cash manually and clear any invested additional cash before planning again. "
                "Save targets for your next rebalance. No portfolio recommendations are supplied.",
            ],
        )

    def run(self) -> None:
        actions = {
            "n": lambda: self.edit_group(True),
            "a": lambda: self.edit_security(True),
            "d": self.delete,
            "b": self.edit_cash,
            "x": self.edit_fx,
            "r": self.refresh,
            "p": self.show_plan,
            "s": self.save,
            "l": self.load,
            "?": self.help,
        }
        while True:
            self.draw()
            key = self.screen.get_wch()
            try:
                if key in ("q", "Q"):
                    if not self.dirty or self.confirm(
                        "Quit and discard unsaved changes? Esc returns; S saves from the main screen."
                    ):
                        return
                elif key in (curses.KEY_DOWN, "j"):
                    self.selected = min(max(0, len(self.rows()) - 1), self.selected + 1)
                elif key in (curses.KEY_UP, "k"):
                    self.selected = max(0, self.selected - 1)
                elif key in ("\n", "\r", curses.KEY_ENTER):
                    self.edit_security()
                elif isinstance(key, str):
                    key = key.lower()
                    if key in actions:
                        actions[key]()
                    elif key in ("m", "c", "f"):
                        draft = copy.deepcopy(self.portfolio)
                        if key == "m":
                            draft.mode = (
                                "rebalance" if draft.mode == "create" else "create"
                            )
                        elif key == "c":
                            draft.display_currency = (
                                "USD" if draft.display_currency == "CAD" else "CAD"
                            )
                        else:
                            draft.fractional = not draft.fractional
                        self.commit(draft, "Settings updated.")
            except (ValueError, OSError, ArithmeticError) as error:
                self.status = str(error)
                self.viewer("Unable to complete action", [str(error)])


def run_tui(portfolio: Portfolio, path: Path, dirty: bool = False) -> None:
    try:
        curses.wrapper(lambda screen: App(screen, portfolio, path, dirty).run())
    except curses.error as error:
        raise ValueError(
            f"Terminal error: {error}. Check TERM and terminal capabilities, or use --plan."
        ) from error
