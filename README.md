# strategies_backup

Snapshot of assorted trading strategy prototypes used for backtesting and comparison.
Each file is a self-contained strategy that plugs into the [`hl-backtest-engine`](https://github.com/takinanton/hl-backtest-engine) harness.

## Style

- Strategies are pure functions of price / indicator inputs → signals. No IO, no state.
- Backtests must run with the honesty overlay (fees + slippage + walk-forward + mirror-matched hold benchmark) or they are worthless.
- Anything that only works in-sample gets deleted, not tuned.

## Layout

- `uk_*.py` — discretionary methodology variants.
- `breakout_*.py`, `flag_*.py`, `123_*.py` — pattern-based.
- `funding_*.py`, `carry_*.py` — funding / basis capture prototypes.

## Non-goal

Not a curated production set. This directory is a graveyard + workbench.