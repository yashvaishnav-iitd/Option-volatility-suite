# Volatility Strategy Backtester

A Python backtester that simulates buying an at-the-money straddle ahead of a stock's earnings announcement and closing it out the day after, to test whether the stock's actual reaction exceeded what was already priced in — and compares results across a low-volatility mega-cap (AAPL) and a high-volatility growth stock (TSLA).

## Core question being tested

Buying a straddle (one call + one put, same strike/expiry) is a pure bet on the *size* of a move, not its direction. The strategy only profits if the stock's **realized** move around earnings exceeds what was already **priced in** via the assumed volatility at entry. This project directly tests that, using real historical stock prices and a self-built Black-Scholes pricer.

## The real-data limitation, and how it's handled

`yfinance` only provides *current* options chains — there's no way to pull "what was this option actually priced at back in 2021." Two honest approaches were considered:

- **Used here:** approximate entry/exit option prices with our own Black-Scholes pricer (from the companion pricing project), fed with a **historical (realized) volatility estimate** as a stand-in for what implied volatility probably was at the time.
- **Not pursued:** sourcing real historical options data — more authentic, but not available for free and out of scope for this project.

This is a stated, transparent simulation, not a claim of real historical option prices — worth saying explicitly in any writeup or interview discussion, the way a real quant researcher would caveat an approximated backtest.

## Design decisions

| Decision | Choice | Reasoning |
|---|---|---|
| Strategy | Long straddle (buy call + put, same strike/expiry) | Pure bet on move size, not direction |
| Event type | Earnings announcements | Known, recurring, historically volatile events |
| Entry timing | 5 trading days before earnings | Balances avoiding excess time decay (Theta) against staying close enough that the strike remains near-the-money |
| Exit timing | 1 trading day after earnings | Captures the immediate reaction only; avoids mixing in unrelated later drift |
| Strike selection | Rounded to nearest $5 from entry price | Approximates a realistic, tradeable at-the-money strike |
| Assumed expiry | 30 days from entry | Long enough to survive to the event, short enough to be realistic |
| Entry volatility | 30-day close-to-close historical vol (reused from the historical-volatility project) | No real historical option quotes available; an honest, stated approximation |
| Exit volatility | Same as entry vol | Isolates the effect of the stock price move alone; does not model "IV crush" — a stated simplification |

**Why not buy earlier than 5 days for a cheaper premium?** More days before the event means more Theta decay paid for no additional event-specific exposure, more chance the stock drifts away from the strike before the event even happens, and it starts capturing the IV run-up itself (a different strategy) rather than isolating the announcement's own effect.

## Files

| File | Purpose |
|---|---|
| `vol_backtest.py` | Fetches earnings dates and price history, runs the backtest across all historical events, computes stats, and plots cumulative P&L |

## How it works

- **`fetch_earnings_dates(ticker)`** — pulls historical earnings dates, drops any not-yet-reported (future) event, and **normalizes timestamps to midnight**. This step matters more than it looks: earnings announcements carry a specific time (e.g. `16:00:00`), and matching that time-of-day timestamp against midnight-stamped price data can silently shift the matched trading day forward by one — `.normalize()` prevents this.
- **`fetch_price_history(ticker)`** — pulls daily OHLC data, with timezone stripped so it can be matched against the (also timezone-stripped) earnings dates.
- **`get_trading_day_offset(price_history, date, offset)`** — finds the trading day a given number of *trading* days (not calendar days) before/after a target date, so weekends/holidays are automatically skipped.
- **`estimate_historical_vol(price_history, date)`** — reuses the Close-to-Close estimator from the historical-volatility project over a 30-day lookback window ending at the given date.
- **`backtest_one_event(earnings_date, price_history)`** — prices the straddle at entry and exit using Black-Scholes, and returns the resulting P&L along with the intermediate values (strike, entry/exit prices, assumed vol).
- **`run_backtest(ticker)`** — loops `backtest_one_event` across every available historical earnings date, returning one results table.
- **`compute_stats(results_df)`** — win rate, average P&L, total P&L, and max drawdown (largest peak-to-trough decline in cumulative P&L).
- **`plot_cumulative_pnl(results_df, ticker)`** — plots and saves the equity curve, with a ticker-specific title and filename.

## A real bug found and fixed along the way

Initial versions omitted the `.normalize()` step. Since earnings timestamps carry a specific time-of-day and price history is stamped at midnight, `nearest`-match date lookups could silently snap the "anchor" day forward by one trading day — before the `-5`/`+1` offsets were even applied. This meant the exit was sometimes actually **2 trading days after** earnings instead of 1, diluting the announcement-specific effect with an extra day of unrelated drift. Verified concretely: the un-normalized version showed higher total P&L, which is not an improvement — it's evidence of capturing more random price variance from the extra holding day, not a real edge (confirmed by checking that the average absolute stock move was larger in the buggy version purely due to the extra day, not any actual insight). **Always validate against exact, deliberately-chosen entry/exit dates before trusting a backtest's headline number.**

## Results

### AAPL (24 historical earnings events, 2020–2026)

| Metric | Value |
|---|---|
| Win rate | 62.5% |
| Average P&L per trade | $1.21 |
| Total P&L | $28.97 |
| Max drawdown | −$3.58 |
| Average absolute earnings-day move | 4.12% |

### TSLA (24 historical earnings events, 2020–2026)

| Metric | Value |
|---|---|
| Win rate | 41.7% |
| Average P&L per trade | $3.48 |
| Total P&L | $83.61 |
| Max drawdown | −$28.55 |
| Average absolute earnings-day move | 8.53% |

### Interpretation

TSLA wins less often but pays off far more when it does, and drops much further along the way — a classic high-volatility straddle profile: lower win rate, higher payoff asymmetry, larger drawdowns. AAPL behaves more like a "grind it out" strategy: wins more consistently, but each win/loss is modest, consistent with AAPL's more muted, well-priced-in earnings reactions (as a heavily-analyst-covered mega-cap) versus TSLA's higher-expectation, more surprise-prone profile. The two largest EPS *surprises* in the AAPL dataset (42% and 28% beats) both produced near-zero stock moves and small losses — a reminder that a large earnings *surprise* doesn't necessarily translate into a large *price* move.

**Caution on max drawdown:** TSLA's −$28.55 drawdown occurred immediately before a single +$25.77 winning trade pulled the curve back up — a reminder that backtest results, especially drawdown figures, can be sensitive to exactly when you stop measuring.

## Usage

```bash
pip install yfinance pandas numpy matplotlib scipy
python vol_backtest.py   # defaults to TSLA
```

To run a different ticker or use the pieces independently:

```python
from vol_backtest import main, run_backtest, compute_stats

main("AAPL")  # full run: prints table, stats, and shows/saves the plot

# or, piece by piece:
results_df = run_backtest("AAPL")
stats = compute_stats(results_df)
```

## Known gaps / possible extensions

- Entry/exit prices are Black-Scholes approximations using historical volatility, not real historical option quotes — a stated, necessary simplification given data availability.
- Exit pricing reuses the entry volatility rather than modeling "IV crush" (the typical drop in implied vol right after an event resolves) — a real effect this version doesn't capture.
- Only the Close-to-Close volatility estimator is used for the entry-vol proxy; the historical-volatility project also built Parkinson, Garman-Klass, and Yang-Zhang estimators, any of which could be substituted or compared.
- No transaction costs or bid-ask spread are modeled — real straddle execution would be slightly more expensive on both entry and exit.
- Tested on two tickers (AAPL, TSLA); extending to a broader universe of stocks (e.g. by volatility regime, sector, or market cap) would give a more robust picture of when this strategy tends to work.

## Background

This project connects directly to the realized-vs-implied volatility theme running through the pricing and volatility-estimation work: a straddle only profits when what actually happens (realized volatility) exceeds what the market — or in this simulation, recent historical behavior — priced in ahead of time (implied/assumed volatility). This is the same mechanic a real volatility trading desk evaluates constantly, just applied here as a discrete, dated, repeatable historical test rather than a continuous live position.
