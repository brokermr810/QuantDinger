from __future__ import annotations

import pandas as pd

import pytest

from app.services.backtest_engine.engine import BacktestEngine
from app.services.backtest_engine.models import BacktestConfig
from app.services.backtest_engine.signals import SignalStrategyAdapter
from app.services.backtest_engine.strategy_api import SignalFrameBacktestRunner, SignalFrameStrategy


def _df() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=8, freq="D")
    return pd.DataFrame(
        {
            "open": [100, 101, 105, 104, 107, 103, 99, 101],
            "high": [102, 106, 108, 109, 108, 104, 102, 103],
            "low": [99, 100, 103, 102, 101, 98, 97, 100],
            "close": [101, 105, 104, 107, 103, 99, 101, 102],
            "volume": [1000] * 8,
        },
        index=idx,
    )


def _blank_signals(df: pd.DataFrame) -> dict:
    return {
        "open_long": pd.Series(False, index=df.index),
        "close_long": pd.Series(False, index=df.index),
        "open_short": pd.Series(False, index=df.index),
        "close_short": pd.Series(False, index=df.index),
        "add_long": pd.Series(False, index=df.index),
        "add_short": pd.Series(False, index=df.index),
    }


def _run(df: pd.DataFrame, signals: dict, cfg: BacktestConfig):
    return BacktestEngine(cfg).run(
        df=df,
        strategy=SignalStrategyAdapter(df, signals, cfg),
        start_date=df.index[0].to_pydatetime(),
        end_date=df.index[-1].to_pydatetime(),
    )


def test_engine_market_order_next_open_lifecycle():
    df = _df()
    signals = _blank_signals(df)
    signals["open_long"].loc[df.index[0]] = True
    signals["close_long"].loc[df.index[3]] = True
    cfg = BacktestConfig(initial_capital=10000, commission=0.0, signal_timing="next_bar_open", trade_direction="long")

    result = _run(df, signals, cfg)

    assert result["engine"]["version"] == "quantdinger-backtest-engine-v2"
    assert result["totalTrades"] == 1
    assert len(result["orders"]) == 2
    assert result["orders"][0]["status"] == "filled"
    assert result["trades"][0]["type"] == "open_long"
    assert result["trades"][1]["type"] == "close_long"
    assert result["trades"][1]["holding_bars"] == 3
    assert result["bestTrade"] != 0
    assert "worstTrade" in result
    assert result["avgTrade"] != 0


def test_engine_rejects_signal_frame_entry_exit_aliases():
    df = _df()
    signals = {
        "enter_long": pd.Series(False, index=df.index),
        "exit_long": pd.Series(False, index=df.index),
        "enter_short": pd.Series(False, index=df.index),
        "exit_short": pd.Series(False, index=df.index),
    }
    signals["enter_long"].loc[df.index[0]] = True
    signals["exit_long"].loc[df.index[2]] = True
    cfg = BacktestConfig(initial_capital=10000, commission=0.0, signal_timing="next_bar_open", trade_direction="long")

    try:
        _run(df, signals, cfg)
    except ValueError as exc:
        assert "canonical signal keys" in str(exc)
    else:
        raise AssertionError("alias-based signal frames must be rejected")


def test_signal_frame_strategy_runner_uses_canonical_columns():
    class CrossStrategy(SignalFrameStrategy):
        def populate_indicators(self, df, metadata):
            df["fast"] = df["close"].rolling(2).mean()
            df["slow"] = df["close"].rolling(3).mean()
            return df

        def populate_signals(self, df, metadata):
            df["open_long"] = df.index == df.index[0]
            df["close_long"] = df.index == df.index[3]
            return df

    df = _df()
    cfg = BacktestConfig(initial_capital=10000, commission=0.0, signal_timing="next_bar_open", trade_direction="long")

    result = SignalFrameBacktestRunner(cfg).run(strategy=CrossStrategy(), df=df, metadata={"symbol": "BTC/USDT"})

    assert result["engine"]["version"] == "quantdinger-backtest-engine-v2"
    assert result["totalTrades"] == 1


def test_signal_frame_strategy_rejects_alias_columns():
    class AliasStrategy(SignalFrameStrategy):
        def populate_signals(self, df, metadata):
            df["enter_long"] = True
            return df

    with pytest.raises(ValueError, match="unsupported alias"):
        AliasStrategy().build_signal_frame(_df(), {})


def test_engine_limit_order_uses_price_trigger():
    df = _df()
    signals = _blank_signals(df)
    signals["open_long"].loc[df.index[0]] = True
    signals["open_long_price"] = pd.Series([100.5, 0, 0, 0, 0, 0, 0, 0], index=df.index)
    cfg = BacktestConfig(initial_capital=10000, signal_timing="same_bar_close", trade_direction="long")

    result = _run(df, signals, cfg)

    assert result["orders"][0]["type"] == "limit"
    assert result["orders"][0]["status"] == "filled"
    assert result["trades"][0]["price"] == 100.5


def test_engine_short_signal_generates_short_leg():
    df = _df()
    signals = _blank_signals(df)
    signals["open_short"].loc[df.index[0]] = True
    signals["close_short"].loc[df.index[4]] = True
    cfg = BacktestConfig(initial_capital=10000, signal_timing="next_bar_open", trade_direction="short")

    result = _run(df, signals, cfg)

    assert result["totalTrades"] == 1
    assert result["trades"][0]["type"] == "open_short"
    assert result["trades"][1]["type"] == "close_short"


def test_engine_reduce_long_scales_out_before_full_close():
    df = _df()
    signals = _blank_signals(df)
    signals["reduce_long"] = pd.Series(False, index=df.index)
    signals["open_long"].loc[df.index[0]] = True
    signals["reduce_long"].loc[df.index[2]] = True
    signals["reduce_long_pct"] = pd.Series([0, 0, 0.5, 0, 0, 0, 0, 0], index=df.index)
    signals["close_long"].loc[df.index[5]] = True
    cfg = BacktestConfig(initial_capital=10000, signal_timing="same_bar_close", trade_direction="long")

    result = _run(df, signals, cfg)

    close_trades = [t for t in result["trades"] if t["type"] == "close_long"]
    assert len(close_trades) == 2
    assert close_trades[0]["reason"] == "reduce_position"
    assert 0 < close_trades[0]["amount"] < result["trades"][0]["amount"]
    assert close_trades[1]["reason"] == "signal_close"


def test_engine_counts_breakeven_close_as_completed_trade():
    idx = pd.date_range("2024-01-01", periods=4, freq="D")
    df = pd.DataFrame(
        {
            "open": [100, 100, 100, 100],
            "high": [100, 100, 100, 100],
            "low": [100, 100, 100, 100],
            "close": [100, 100, 100, 100],
            "volume": [1000] * 4,
        },
        index=idx,
    )
    signals = _blank_signals(df)
    signals["open_long"].loc[idx[0]] = True
    signals["close_long"].loc[idx[2]] = True
    cfg = BacktestConfig(initial_capital=10000, commission=0.0, signal_timing="next_bar_open", trade_direction="long")

    result = _run(df, signals, cfg)

    assert result["totalTrades"] == 1
    assert result["closedTrades"][0]["profit"] == 0


def test_spot_oversized_notional_is_rejected_when_cash_is_insufficient():
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    df = pd.DataFrame(
        {
            "open": [100, 100, 100],
            "high": [100, 100, 100],
            "low": [100, 100, 100],
            "close": [100, 100, 100],
            "volume": [1000] * 3,
        },
        index=idx,
    )
    signals = _blank_signals(df)
    signals["open_long"].loc[idx[0]] = True
    signals["open_long_quote_amount"] = pd.Series([1_000_000, 0, 0], index=df.index)
    cfg = BacktestConfig(
        initial_capital=10_000,
        commission=0.001,
        signal_timing="same_bar_close",
        trade_direction="long",
        market_type="spot",
    )

    result = _run(df, signals, cfg)

    assert result["orders"][0]["status"] == "rejected"
    assert result["orders"][0]["rejectReason"] == "insufficient_cash"
    assert result["orders"][0]["filledQuantity"] == 0.0
    assert result["trades"] == []
    assert result["finalEquity"] == 10000.0
    assert result["engine"]["rejectedOrderCount"] == 1


def test_swap_oversized_notional_is_rejected_when_margin_is_insufficient():
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    df = pd.DataFrame(
        {
            "open": [100, 100, 100],
            "high": [100, 100, 100],
            "low": [100, 100, 100],
            "close": [100, 100, 100],
            "volume": [1000] * 3,
        },
        index=idx,
    )
    signals = _blank_signals(df)
    signals["open_long"].loc[idx[0]] = True
    signals["open_long_quote_amount"] = pd.Series([1_000_000, 0, 0], index=df.index)
    cfg = BacktestConfig(
        initial_capital=10_000,
        commission=0.0,
        leverage=1.0,
        signal_timing="same_bar_close",
        trade_direction="long",
        market_type="swap",
    )

    result = _run(df, signals, cfg)

    assert result["orders"][0]["status"] == "rejected"
    assert result["orders"][0]["rejectReason"] == "insufficient_margin"
    assert result["orders"][0]["filledQuantity"] == 0.0
    assert result["trades"] == []
    assert result["finalEquity"] == 10000.0
    assert result["engine"]["rejectedOrderCount"] == 1


def test_swap_margin_is_reserved_for_existing_positions():
    idx = pd.date_range("2024-01-01", periods=4, freq="D")
    df = pd.DataFrame(
        {
            "open": [100, 100, 100, 100],
            "high": [100, 100, 100, 100],
            "low": [100, 100, 100, 100],
            "close": [100, 100, 100, 100],
            "volume": [1000] * 4,
        },
        index=idx,
    )
    signals = _blank_signals(df)
    signals["open_long"].loc[idx[0]] = True
    signals["add_long"].loc[idx[1]] = True
    signals["open_long_quote_amount"] = pd.Series([9_000, 0, 0, 0], index=df.index)
    signals["add_long_quote_amount"] = pd.Series([0, 2_000, 0, 0], index=df.index)
    cfg = BacktestConfig(
        initial_capital=10_000,
        commission=0.0,
        leverage=1.0,
        signal_timing="same_bar_close",
        trade_direction="long",
        market_type="swap",
    )

    result = _run(df, signals, cfg)

    assert result["orders"][0]["status"] == "filled"
    assert result["orders"][1]["status"] == "rejected"
    assert result["orders"][1]["rejectReason"] == "insufficient_margin"
    assert len(result["trades"]) == 2
    assert result["trades"][0]["type"] == "open_long"
    assert result["trades"][1]["type"] == "close_long"


def test_swap_quote_amount_means_margin_before_leverage():
    idx = pd.date_range("2024-01-01", periods=4, freq="D")
    df = pd.DataFrame(
        {
            "open": [100, 100, 100, 100],
            "high": [100, 100, 100, 100],
            "low": [100, 100, 100, 100],
            "close": [100, 100, 100, 100],
            "volume": [1000] * 4,
        },
        index=idx,
    )
    signals = _blank_signals(df)
    signals["open_long"].loc[idx[0]] = True
    signals["add_long"].loc[idx[1]] = True
    signals["open_long_quote_amount"] = pd.Series([10_000, 0, 0, 0], index=df.index)
    signals["add_long_quote_amount"] = pd.Series([0, 1, 0, 0], index=df.index)
    cfg = BacktestConfig(
        initial_capital=10_000,
        commission=0.0,
        leverage=10.0,
        signal_timing="same_bar_close",
        trade_direction="long",
        market_type="swap",
    )

    result = _run(df, signals, cfg)

    assert result["orders"][0]["status"] == "filled"
    assert result["orders"][0]["notional"] == 10000
    assert result["trades"][0]["amount"] == 1000
    assert result["orders"][1]["status"] == "rejected"
    assert result["orders"][1]["rejectReason"] == "insufficient_margin"


def test_market_slippage_is_bounded_by_bar_high_low():
    idx = pd.date_range("2024-01-01", periods=2, freq="D")
    df = pd.DataFrame(
        {
            "open": [100, 100],
            "high": [101, 101],
            "low": [99, 99],
            "close": [100, 100],
            "volume": [1000, 1000],
        },
        index=idx,
    )
    signals = _blank_signals(df)
    signals["open_long"].loc[idx[0]] = True
    cfg = BacktestConfig(initial_capital=10_000, signal_timing="same_bar_close", trade_direction="long", slippage=0.1)

    result = _run(df, signals, cfg)

    assert result["trades"][0]["price"] == 101


def test_risk_exit_slippage_is_bounded_by_bar_high_low():
    df = _intrabar_conflict_df()
    signals = _blank_signals(df)
    signals["open_long"].loc[df.index[0]] = True
    cfg = BacktestConfig(
        initial_capital=10_000,
        signal_timing="next_bar_open",
        trade_direction="long",
        stop_loss_pct=0.03,
        slippage=0.1,
        intrabar_mode="conservative",
    )

    result = _run(df, signals, cfg)

    close_trade = [t for t in result["trades"] if t["type"] == "close_long"][0]
    assert close_trade["reason"] == "stop_loss"
    assert close_trade["price"] == 96


def test_engine_risk_take_profit_closes_before_signal():
    df = _df()
    signals = _blank_signals(df)
    signals["open_long"].loc[df.index[0]] = True
    cfg = BacktestConfig(
        initial_capital=10000,
        signal_timing="next_bar_open",
        trade_direction="long",
        take_profit_pct=0.03,
    )

    result = _run(df, signals, cfg)

    close_trades = [t for t in result["trades"] if t["type"] == "close_long"]
    assert close_trades
    assert close_trades[0]["reason"] == "take_profit"


def test_engine_max_holding_bars_closes_position_at_next_open():
    df = _df()
    signals = _blank_signals(df)
    signals["open_long"].loc[df.index[0]] = True
    cfg = BacktestConfig(
        initial_capital=10000,
        signal_timing="next_bar_open",
        trade_direction="long",
        max_holding_bars=2,
    )

    result = _run(df, signals, cfg)

    close_trades = [t for t in result["trades"] if t["type"] == "close_long"]
    assert close_trades
    assert close_trades[0]["reason"] == "max_holding_bars"
    assert close_trades[0]["time"] == "2024-01-04 00:00"
    assert close_trades[0]["price"] == df.iloc[3]["open"]


def _intrabar_conflict_df() -> pd.DataFrame:
    idx = pd.date_range("2024-02-01", periods=4, freq="D")
    return pd.DataFrame(
        {
            "open": [100, 100, 101, 100],
            "high": [101, 101, 104, 101],
            "low": [99, 99, 96, 99],
            "close": [100, 100, 100, 100],
            "volume": [1000] * 4,
        },
        index=idx,
    )


def test_intrabar_mode_changes_same_bar_exit_priority():
    df = _intrabar_conflict_df()
    signals = _blank_signals(df)
    signals["open_long"].loc[df.index[0]] = True

    conservative = _run(
        df,
        signals,
        BacktestConfig(
            initial_capital=10000,
            signal_timing="next_bar_open",
            trade_direction="long",
            stop_loss_pct=0.03,
            take_profit_pct=0.03,
            intrabar_mode="conservative",
        ),
    )
    balanced = _run(
        df,
        signals,
        BacktestConfig(
            initial_capital=10000,
            signal_timing="next_bar_open",
            trade_direction="long",
            stop_loss_pct=0.03,
            take_profit_pct=0.03,
            intrabar_mode="balanced",
        ),
    )
    aggressive = _run(
        df,
        signals,
        BacktestConfig(
            initial_capital=10000,
            signal_timing="next_bar_open",
            trade_direction="long",
            stop_loss_pct=0.03,
            take_profit_pct=0.03,
            intrabar_mode="aggressive",
        ),
    )

    assert conservative["engine"]["intrabarMode"] == "conservative"
    assert balanced["engine"]["intrabarMode"] == "balanced"
    assert aggressive["engine"]["intrabarMode"] == "aggressive"
    assert [t for t in conservative["trades"] if t["type"] == "close_long"][0]["reason"] == "stop_loss"
    assert [t for t in balanced["trades"] if t["type"] == "close_long"][0]["reason"] == "take_profit"
    assert [t for t in aggressive["trades"] if t["type"] == "close_long"][0]["reason"] == "take_profit"


def test_limit_gap_fill_is_conservative_or_price_improved_by_mode():
    idx = pd.date_range("2024-03-01", periods=2, freq="D")
    df = pd.DataFrame(
        {
            "open": [95, 96],
            "high": [101, 98],
            "low": [94, 95],
            "close": [96, 97],
            "volume": [1000, 1000],
        },
        index=idx,
    )
    signals = _blank_signals(df)
    signals["open_long"].loc[idx[0]] = True
    signals["open_long_price"] = pd.Series([100, 0], index=df.index)

    conservative = _run(
        df,
        signals,
        BacktestConfig(initial_capital=10000, signal_timing="same_bar_close", trade_direction="long", intrabar_mode="conservative"),
    )
    aggressive = _run(
        df,
        signals,
        BacktestConfig(initial_capital=10000, signal_timing="same_bar_close", trade_direction="long", intrabar_mode="aggressive"),
    )

    assert conservative["trades"][0]["price"] == 100
    assert aggressive["trades"][0]["price"] == 95


def test_sample_supertrend_like_strategy_backtests_successfully():
    df = _df()
    signals = _blank_signals(df)
    signals["open_long"].loc[df.index[1]] = True
    signals["close_long"].loc[df.index[5]] = True
    cfg = BacktestConfig(initial_capital=20000, signal_timing="next_bar_open", trade_direction="long", intrabar_mode="conservative")

    result = _run(df, signals, cfg)

    assert result["engine"]["fillCount"] >= 2
    assert result["totalTrades"] >= 1


def test_sample_limit_mean_reversion_strategy_backtests_successfully():
    df = _df()
    signals = _blank_signals(df)
    signals["open_long"].loc[df.index[0]] = True
    signals["open_long_price"] = pd.Series([100.5, 0, 0, 0, 0, 0, 0, 0], index=df.index)
    signals["close_long"].loc[df.index[4]] = True
    cfg = BacktestConfig(initial_capital=15000, signal_timing="same_bar_close", trade_direction="long", intrabar_mode="balanced")

    result = _run(df, signals, cfg)

    assert result["orders"][0]["type"] == "limit"
    assert result["engine"]["intrabarMode"] == "balanced"
    assert result["totalTrades"] >= 1


def test_sample_layered_dca_strategy_backtests_successfully():
    df = _df()
    signals = _blank_signals(df)
    signals["open_long"].loc[df.index[0]] = True
    signals["add_long"].loc[df.index[5]] = True
    signals["open_long_quote_amount"] = pd.Series([1000, 0, 0, 0, 0, 0, 0, 0], index=df.index)
    signals["add_long_quote_amount"] = pd.Series([0, 0, 0, 0, 0, 1800, 0, 0], index=df.index)
    cfg = BacktestConfig(
        initial_capital=10000,
        signal_timing="next_bar_open",
        trade_direction="long",
        take_profit_pct=0.02,
        intrabar_mode="conservative",
    )

    result = _run(df, signals, cfg)

    assert result["engine"]["fillCount"] >= 2
    assert any(trade["type"] == "open_long" for trade in result["trades"])
