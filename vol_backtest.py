"""
Volatility strategy backtester: simulates buying an at-the-money straddle
ahead of a stock's earnings announcement and closing it out the day after,
using a historical-volatility-based approximation for option pricing
(see README for why yfinance can't give us real historical option prices).
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

sys.path.append(str(Path(__file__).resolve().parent.parent))
from P1.pricer import black_scholes
from P2.historical_vol import Mode, calculate_all_volatilities


def fetch_earnings_dates(ticker: str, limit: int = 20) -> pd.DataFrame:
    """Pull historical earnings dates for `ticker`, keeping only events that
    have already happened (i.e. have a reported EPS), sorted oldest-first,
    with timestamps normalized to midnight so date-matching against price
    history is reliable regardless of what time of day the announcement was.
    """
    stock = yf.Ticker(ticker)
    earnings = stock.get_earnings_dates(limit=limit)
    earnings = earnings.dropna(subset=["Reported EPS"])
    earnings = earnings.sort_index()
    earnings.index = earnings.index.tz_localize(None).normalize()
    return earnings


def fetch_price_history(ticker: str, period: str = "6y") -> pd.DataFrame:
    """Pull daily price history for `ticker`, with timezone stripped so it can
    be matched against earnings dates (which come with their own timezone).
    """
    stock = yf.Ticker(ticker)
    history = stock.history(period=period)
    history.index = history.index.tz_localize(None)
    return history



def get_trading_day_offset(price_history: pd.DataFrame, target_date: pd.Timestamp, offset: int):
    """Find the trading day that is `offset` trading days away from
    target_date. Negative offset = before, positive = after. Returns None
    if the offset would fall outside the available price history.
    """
    idx = price_history.index.get_indexer([target_date], method="nearest")[0]
    new_idx = idx + offset
    if new_idx < 0 or new_idx >= len(price_history):
        return None
    return price_history.index[new_idx]


def estimate_historical_vol(price_history: pd.DataFrame, as_of_date: pd.Timestamp, lookback: int = 30) -> float:
    """Close-to-close historical volatility over the `lookback` days ending
    at as_of_date, reusing Project 2's estimator as a stand-in for the
    implied volatility we can't observe historically.
    """
    idx = price_history.index.get_indexer([as_of_date], method="nearest")[0]
    window = price_history.iloc[max(0, idx - lookback): idx + 1]
    results = calculate_all_volatilities(window, mode=Mode.VALS)
    return results["Close-to-Close"]


def backtest_one_event(
    earnings_date: pd.Timestamp,
    price_history: pd.DataFrame,
    offset_entry: int = -5,
    offset_exit: int = 1,
    days_to_expiry: int = 30,
    r: float = 0.05,
):
    """Simulate buying an ATM straddle `offset_entry` trading days before
    earnings_date and selling it `offset_exit` trading days after, pricing
    both legs with Black-Scholes using a historical-vol approximation.
    Returns None if there isn't enough price history to compute either date.
    """
    entry_date = get_trading_day_offset(price_history, earnings_date, offset_entry)
    exit_date = get_trading_day_offset(price_history, earnings_date, offset_exit)

    if entry_date is None or exit_date is None:
        return None

    S_entry = price_history.loc[entry_date, "Close"]
    S_exit = price_history.loc[exit_date, "Close"]
    K = round(S_entry / 5) * 5

    entry_vol = estimate_historical_vol(price_history, entry_date)

    T_entry = days_to_expiry / 365
    days_elapsed = offset_exit - offset_entry
    T_exit = (days_to_expiry - days_elapsed) / 365

    straddle_cost = (
        black_scholes(S_entry, K, T_entry, r, entry_vol, "call")
        + black_scholes(S_entry, K, T_entry, r, entry_vol, "put")
    )
    straddle_value_exit = (
        black_scholes(S_exit, K, T_exit, r, entry_vol, "call")
        + black_scholes(S_exit, K, T_exit, r, entry_vol, "put")
    )

    return {
        "earnings_date": earnings_date,
        "entry_date": entry_date,
        "exit_date": exit_date,
        "S_entry": S_entry,
        "S_exit": S_exit,
        "strike": K,
        "entry_vol": entry_vol,
        "straddle_cost": straddle_cost,
        "straddle_value_exit": straddle_value_exit,
        "pnl": straddle_value_exit - straddle_cost,
    }


def run_backtest(
    ticker: str,
    offset_entry: int = -5,
    offset_exit: int = 1,
    days_to_expiry: int = 30,
    r: float = 0.05,
    earnings_limit: int = 20,
    history_period: str = "6y",
) -> pd.DataFrame:
    """Run backtest_one_event across every available historical earnings
    date for `ticker` and return the results as a single DataFrame.
    """
    earnings_dates = fetch_earnings_dates(ticker, limit=earnings_limit)
    history = fetch_price_history(ticker, period=history_period)

    results = []
    for earnings_date in earnings_dates.index:
        event_result = backtest_one_event(
            earnings_date, history,
            offset_entry=offset_entry, offset_exit=offset_exit,
            days_to_expiry=days_to_expiry, r=r,
        )
        if event_result is not None:
            results.append(event_result)

    return pd.DataFrame(results)




def compute_stats(results_df: pd.DataFrame) -> dict:
    """Compute win rate, average/total P&L, and max drawdown from a
    backtest results DataFrame (must contain a 'pnl' column).
    """
    pnl = results_df["pnl"]
    cumulative_pnl = pnl.cumsum()
    running_max = cumulative_pnl.cummax()
    drawdown = cumulative_pnl - running_max

    return {
        "num_trades": len(pnl),
        "win_rate": (pnl > 0).mean(),
        "avg_pnl": pnl.mean(),
        "total_pnl": pnl.sum(),
        "max_drawdown": drawdown.min(),
    }


def plot_cumulative_pnl(results_df: pd.DataFrame, ticker: str, save_path: str = None):
    """Plot cumulative P&L over time for a backtest results DataFrame.
    Saves to `save_path` if given, using a ticker-specific default filename
    otherwise, and returns the filename actually used.
    """
    cumulative_pnl = results_df["pnl"].cumsum()

    if save_path is None:
        save_path = f"{ticker}_straddle_backtest_cumulative_pnl.png"

    plt.figure(figsize=(12, 6))
    plt.plot(results_df["earnings_date"], cumulative_pnl, marker="o", color="navy")
    plt.axhline(0, color="gray", linestyle="--", linewidth=1)
    plt.title(f"Cumulative P&L: {ticker} Earnings Straddle Strategy")
    plt.xlabel("Earnings Date")
    plt.ylabel("Cumulative P&L ($)")
    plt.xticks(rotation=45)
    plt.grid(True, linestyle=":", alpha=0.5)
    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.show()

    return save_path


def stats(ticker: str = "TSLA"):
    results_df = run_backtest(ticker)

    print(results_df[["earnings_date", "S_entry", "S_exit", "strike", "entry_vol", "pnl"]])

    stats = compute_stats(results_df)
    print(f"\nNumber of trades: {stats['num_trades']}")
    print(f"Win rate: {stats['win_rate']*100:.1f}%")
    print(f"Average P&L per trade: {stats['avg_pnl']:.2f}")
    print(f"Total P&L: {stats['total_pnl']:.2f}")
    print(f"Max drawdown: {stats['max_drawdown']:.2f}")

    plot_cumulative_pnl(results_df, ticker)


if __name__ == "__main__":
    stats()