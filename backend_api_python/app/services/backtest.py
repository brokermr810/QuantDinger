"""
Backtest Service
"""
import math
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

import pandas as pd
import numpy as np

from app.data_sources import DataSourceFactory
from app.utils.logger import get_logger
from app.services.indicator_params import IndicatorParamsParser, IndicatorCaller

logger = get_logger(__name__)


class BacktestService:
    """Backtest Service"""
    
    # Timeframe in seconds
    TIMEFRAME_SECONDS = {
        '1m': 60, '5m': 300, '15m': 900, '30m': 1800,
        '1H': 3600, '4H': 14400, '1D': 86400, '1W': 604800
    }
    
    # Multi-timeframe backtest threshold configuration
    # 1m backtest: max 1 month (~43,200 candles)
    # 5m backtest: max 1 year (~105,120 candles)
    MTF_CONFIG = {
        'max_1m_days': 30,        # Max days for 1-minute backtest
        'max_5m_days': 365,       # Max days for 5-minute backtest
        'default_exec_tf': '1m',  # Default execution timeframe
        'fallback_exec_tf': '5m', # Fallback execution timeframe
    }
    
    @staticmethod
    def _infer_candle_path(open_: float, high: float, low: float, close: float) -> List[float]:
        """
        Infer the price path within a candle.
        
        Determines the order of price movement based on open/close relationship:
        - Bullish candle (close >= open): Open -> Low -> High -> Close (dip then rally)
        - Bearish candle (close < open): Open -> High -> Low -> Close (rally then dip)
        
        Returns:
            Price path list [price1, price2, price3, price4]
        """
        if close >= open_:
            # Bullish: dip first then rally
            return [open_, low, high, close]
        else:
            # Bearish: rally first then dip
            return [open_, high, low, close]
    
    def get_execution_timeframe(self, start_date: datetime, end_date: datetime, market: str = 'crypto') -> tuple:
        """
        Automatically select execution timeframe based on backtest date range.
        
        Args:
            start_date: Start date
            end_date: End date
            market: Market type
            
        Returns:
            (execution_timeframe, precision_info)
            - execution_timeframe: '1m' or '5m'
            - precision_info: Precision info dict for frontend display
        """
        days_diff = (end_date - start_date).days
        
        # Only crypto market supports high-precision backtest
        if market.lower() not in ['crypto', 'cryptocurrency']:
            return None, {
                'enabled': False,
                'reason': 'only_crypto',
                'message': 'High-precision backtest only supports cryptocurrency market'
            }
        
        if days_diff <= self.MTF_CONFIG['max_1m_days']:
            # Within 1 month: use 1-minute precision
            estimated_candles = days_diff * 24 * 60
            return '1m', {
                'enabled': True,
                'timeframe': '1m',
                'days': days_diff,
                'estimated_candles': estimated_candles,
                'precision': 'high',
                'message': f'Using 1-minute precision backtest (~{estimated_candles:,} candles)'
            }
        elif days_diff <= self.MTF_CONFIG['max_5m_days']:
            # 1 month to 1 year: use 5-minute precision
            estimated_candles = days_diff * 24 * 12
            return '5m', {
                'enabled': True,
                'timeframe': '5m',
                'days': days_diff,
                'estimated_candles': estimated_candles,
                'precision': 'medium',
                'message': f'Range exceeds 30 days, using 5-minute precision (~{estimated_candles:,} candles)'
            }
        else:
            # Over 1 year: high-precision backtest not supported
            return None, {
                'enabled': False,
                'reason': 'too_long',
                'days': days_diff,
                'max_days': self.MTF_CONFIG['max_5m_days'],
                'message': f'Backtest range {days_diff} days exceeds max limit {self.MTF_CONFIG["max_5m_days"]} days'
            }
    
    def run_multi_timeframe(
        self,
        indicator_code: str,
        market: str,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        initial_capital: float = 10000.0,
        commission: float = 0.001,
        slippage: float = 0.0,
        leverage: int = 1,
        trade_direction: str = 'long',
        strategy_config: Optional[Dict[str, Any]] = None,
        enable_mtf: bool = True
    ) -> Dict[str, Any]:
        """
        Multi-timeframe backtest.
        
        Uses strategy timeframe for signal generation and execution timeframe (1m/5m) 
        for precise trade simulation.
        
        Args:
            indicator_code: Indicator code
            market: Market type
            symbol: Trading symbol
            timeframe: Strategy timeframe (for signal generation)
            start_date: Start date
            end_date: End date
            initial_capital: Initial capital
            commission: Commission rate
            slippage: Slippage
            leverage: Leverage
            trade_direction: Trade direction
            strategy_config: Strategy configuration
            enable_mtf: Whether to enable multi-timeframe backtest
            
        Returns:
            Backtest result with precision info
        """
        # Get execution timeframe
        exec_tf, precision_info = self.get_execution_timeframe(start_date, end_date, market)
        
        if not enable_mtf or not precision_info.get('enabled'):
            # Fallback to standard candle backtest
            result = self.run(
                indicator_code=indicator_code,
                market=market,
                symbol=symbol,
                timeframe=timeframe,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                commission=commission,
                slippage=slippage,
                leverage=leverage,
                trade_direction=trade_direction,
                strategy_config=strategy_config
            )
            result['precision_info'] = precision_info or {
                'enabled': False,
                'timeframe': timeframe,
                'precision': 'standard',
                'message': 'Using standard candle backtest'
            }
            return result
        
        logger.info(f"Multi-timeframe backtest: strategy_tf={timeframe}, exec_tf={exec_tf}, range={start_date} ~ {end_date}")
        
        # 1. Fetch strategy timeframe candles (for signal generation)
        df_signal = self._fetch_kline_data(market, symbol, timeframe, start_date, end_date)
        if df_signal.empty:
            raise ValueError("No candle data available in the backtest date range")
        
        # 2. Execute indicator code to get signals
        backtest_params = {
            'leverage': leverage,
            'initial_capital': initial_capital,
            'commission': commission,
            'trade_direction': trade_direction
        }
        signals = self._execute_indicator(indicator_code, df_signal, backtest_params)
        
        # 3. Fetch execution timeframe candles (for precise trade simulation)
        df_exec = self._fetch_kline_data(market, symbol, exec_tf, start_date, end_date)
        if df_exec.empty:
            logger.warning(f"Cannot fetch {exec_tf} candles, falling back to standard backtest")
            result = self.run(
                indicator_code=indicator_code,
                market=market,
                symbol=symbol,
                timeframe=timeframe,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                commission=commission,
                slippage=slippage,
                leverage=leverage,
                trade_direction=trade_direction,
                strategy_config=strategy_config
            )
            result['precision_info'] = {
                'enabled': False,
                'reason': 'data_unavailable',
                'message': f'Cannot fetch {exec_tf} data, using standard backtest'
            }
            return result
        
        logger.info(f"Data fetched: signal_candles={len(df_signal)}, exec_candles={len(df_exec)}")
        
        # 4. Use execution timeframe for precise trade simulation
        equity_curve, trades, total_commission = self._simulate_trading_mtf(
            df_signal=df_signal,
            df_exec=df_exec,
            signals=signals,
            initial_capital=initial_capital,
            commission=commission,
            slippage=slippage,
            leverage=leverage,
            trade_direction=trade_direction,
            strategy_config=strategy_config,
            signal_timeframe=timeframe,
            exec_timeframe=exec_tf
        )
        
        # 5. Calculate metrics
        metrics = self._calculate_metrics(equity_curve, trades, initial_capital, timeframe, start_date, end_date, total_commission)
        
        # 6. Format result
        result = self._format_result(metrics, equity_curve, trades)
        result['precision_info'] = precision_info
        result['execution_timeframe'] = exec_tf
        result['signal_candles'] = len(df_signal)
        result['execution_candles'] = len(df_exec)
        
        return result
    
    def _simulate_trading_mtf(
        self,
        df_signal: pd.DataFrame,
        df_exec: pd.DataFrame,
        signals: dict,
        initial_capital: float,
        commission: float,
        slippage: float,
        leverage: int,
        trade_direction: str,
        strategy_config: Optional[Dict[str, Any]],
        signal_timeframe: str,
        exec_timeframe: str
    ) -> tuple:
        """
        Multi-timeframe trading simulation.
        
        Simulates trades candle by candle on execution timeframe, 
        using inferred candle price path to determine trigger order.
        """
        equity_curve = []
        trades = []
        total_commission_paid = 0.0
        is_liquidated = False
        min_capital_to_trade = 1.0
        
        capital = initial_capital
        position = 0
        entry_price = 0.0
        position_type = None  # 'long' or 'short'
        
        # Parse strategy config
        cfg = strategy_config or {}
        risk_cfg = cfg.get('risk') or {}
        stop_loss_pct = float(risk_cfg.get('stopLossPct') or 0.0)
        take_profit_pct = float(risk_cfg.get('takeProfitPct') or 0.0)
        trailing_cfg = risk_cfg.get('trailing') or {}
        trailing_enabled = bool(trailing_cfg.get('enabled'))
        trailing_pct = float(trailing_cfg.get('pct') or 0.0)
        trailing_activation_pct = float(trailing_cfg.get('activationPct') or 0.0)
        
        lev = max(int(leverage or 1), 1)
        stop_loss_pct_eff = stop_loss_pct / lev if stop_loss_pct > 0 else 0
        take_profit_pct_eff = take_profit_pct / lev if take_profit_pct > 0 else 0
        trailing_pct_eff = trailing_pct / lev if trailing_pct > 0 else 0
        trailing_activation_pct_eff = trailing_activation_pct / lev if trailing_activation_pct > 0 else 0
        
        # If trailing stop enabled but no activation threshold set, use take profit threshold
        if trailing_enabled and trailing_pct_eff > 0:
            if trailing_activation_pct_eff <= 0 and take_profit_pct_eff > 0:
                trailing_activation_pct_eff = take_profit_pct_eff
        
        # Entry percentage
        pos_cfg = cfg.get('position') or {}
        raw_entry_pct = pos_cfg.get('entryPct')
        # If entryPct is None, 0, or not provided, default to 1.0 (100%)
        if raw_entry_pct is None or raw_entry_pct == 0:
            entry_pct_cfg = 1.0
        else:
            entry_pct_cfg = float(raw_entry_pct)
            if entry_pct_cfg > 1:
                entry_pct_cfg = entry_pct_cfg / 100.0
        entry_pct_cfg = max(0.01, min(entry_pct_cfg, 1.0))  # Minimum 1% to avoid 0 position
        
        logger.info(f"Trading params: capital={capital}, leverage={lev}, entry_pct={entry_pct_cfg}, strategy_config={cfg}")
        
        highest_since_entry = None
        lowest_since_entry = None
        
        # Normalize signal format
        if not isinstance(signals, dict):
            raise ValueError("signals must be a dict")
        
        # Debug: check signal index compatibility
        signal_keys = list(signals.keys())
        logger.info(f"Signal keys: {signal_keys}")
        if signal_keys:
            first_key = signal_keys[0]
            if hasattr(signals[first_key], 'index'):
                sig_index = signals[first_key].index
                df_index = df_signal.index
                logger.info(f"Signal index len={len(sig_index)}, df_signal index len={len(df_index)}")
                if len(sig_index) > 0 and len(df_index) > 0:
                    logger.info(f"Signal index first={sig_index[0]}, df_signal index first={df_index[0]}")
                    # Check if indices match
                    if not sig_index.equals(df_index):
                        logger.warning("Signal index does NOT match df_signal index! This may cause signal lookup failures.")
        
        # Check if trade_direction is 'both' mode
        is_both_mode = str(trade_direction or 'both').lower() == 'both'
        
        if all(k in signals for k in ['open_long', 'close_long', 'open_short', 'close_short']):
            norm_signals = signals
            norm_signals['_both_mode'] = False  # Explicit 4-signal mode, not both mode
        elif all(k in signals for k in ['buy', 'sell']):
            buy = signals['buy'].fillna(False).astype(bool)
            sell = signals['sell'].fillna(False).astype(bool)
            td = str(trade_direction or 'both').lower()
            if td == 'long':
                norm_signals = {
                    'open_long': buy, 'close_long': sell,
                    'open_short': pd.Series([False] * len(df_signal), index=df_signal.index),
                    'close_short': pd.Series([False] * len(df_signal), index=df_signal.index),
                }
            elif td == 'short':
                norm_signals = {
                    'open_long': pd.Series([False] * len(df_signal), index=df_signal.index),
                    'close_long': pd.Series([False] * len(df_signal), index=df_signal.index),
                    'open_short': sell, 'close_short': buy,
                }
            else:
                # Both mode: buy signal triggers long entry (close short if any, then open long)
                # sell signal triggers short entry (close long if any, then open short)
                # We use special signal types 'enter_long' and 'enter_short' to indicate
                # that the signal should auto-close opposing position before opening
                norm_signals = {
                    'open_long': buy, 'close_long': pd.Series([False] * len(df_signal), index=df_signal.index),
                    'open_short': sell, 'close_short': pd.Series([False] * len(df_signal), index=df_signal.index),
                    '_both_mode': True  # Flag to indicate both mode for special handling
                }
        else:
            raise ValueError("Invalid signal format")
        
        # Map signals to execution timeframe
        # Strategy timeframe seconds (e.g. 1H=3600, 1D=86400)
        signal_tf_seconds = self.TIMEFRAME_SECONDS.get(signal_timeframe, 3600)
        exec_tf_seconds = self.TIMEFRAME_SECONDS.get(exec_timeframe, 60)
        
        logger.info(f"Signal timeframe: {signal_timeframe} ({signal_tf_seconds}s), Exec timeframe: {exec_timeframe} ({exec_tf_seconds}s)")
        
        # Preprocessing: create signal queue sorted by effective time
        # Each signal executes at the open of the next execution candle after its candle closes
        signal_queue = []  # [(effective_time, signal_type, signal_bar_time), ...]
        
        # Debug: check signal values
        debug_signal_counts = {'open_long': 0, 'close_long': 0, 'open_short': 0, 'close_short': 0}
        
        for sig_time in df_signal.index:
            # Signal candle end time = start time + period
            sig_end = sig_time + timedelta(seconds=signal_tf_seconds)
            
            # Check if this signal candle has signals
            # Use .loc[] instead of .get() to be more explicit
            try:
                ol = bool(norm_signals['open_long'].loc[sig_time]) if sig_time in norm_signals['open_long'].index else False
                cl = bool(norm_signals['close_long'].loc[sig_time]) if sig_time in norm_signals['close_long'].index else False
                os = bool(norm_signals['open_short'].loc[sig_time]) if sig_time in norm_signals['open_short'].index else False
                cs = bool(norm_signals['close_short'].loc[sig_time]) if sig_time in norm_signals['close_short'].index else False
            except Exception as e:
                logger.warning(f"Error accessing signal at {sig_time}: {e}")
                continue
            
            if ol:
                signal_queue.append((sig_end, 'open_long', sig_time))
                debug_signal_counts['open_long'] += 1
            if cl:
                signal_queue.append((sig_end, 'close_long', sig_time))
                debug_signal_counts['close_long'] += 1
            if os:
                signal_queue.append((sig_end, 'open_short', sig_time))
                debug_signal_counts['open_short'] += 1
            if cs:
                signal_queue.append((sig_end, 'close_short', sig_time))
                debug_signal_counts['close_short'] += 1
        
        logger.info(f"Debug signal counts from queue building: {debug_signal_counts}")
        
        # Sort by effective time
        signal_queue.sort(key=lambda x: x[0])
        signal_queue_idx = 0  # Current signal queue pointer
        
        logger.info(f"Signal queue built: total {len(signal_queue)} signals")
        if signal_queue:
            logger.info(f"First signal: {signal_queue[0][1]} @ {signal_queue[0][0]} (from {signal_queue[0][2]})")
            logger.info(f"Last signal: {signal_queue[-1][1]} @ {signal_queue[-1][0]} (from {signal_queue[-1][2]})")
        
        # Count signals by type
        signal_counts = {}
        for _, sig_type, _ in signal_queue:
            signal_counts[sig_type] = signal_counts.get(sig_type, 0) + 1
        logger.info(f"Signal counts: {signal_counts}")
        
        # Log execution data range
        if len(df_exec) > 0:
            exec_start = df_exec.index[0]
            exec_end = df_exec.index[-1]
            logger.info(f"Exec data range: {exec_start} ~ {exec_end}")
            # Check first few candles for data validity
            first_row = df_exec.iloc[0]
            logger.info(f"First exec candle: open={first_row['open']}, high={first_row['high']}, low={first_row['low']}, close={first_row['close']}")
        
        # Current pending signal to execute
        pending_signal = None  # ('open_long', 'close_long', 'open_short', 'close_short')
        pending_signal_time = None  # Signal effective time
        executed_trades_count = 0  # Debug counter
        
        for i, (timestamp, row) in enumerate(df_exec.iterrows()):
            # 爆仓后直接停止回测，输出结果
            if is_liquidated:
                break
            
            if position == 0 and capital < min_capital_to_trade:
                is_liquidated = True
                capital = 0
                equity_curve.append({'time': timestamp.strftime('%Y-%m-%d %H:%M'), 'value': 0})
                continue
            
            open_ = row['open']
            high = row['high']
            low = row['low']
            close = row['close']
            
            # Use inferred candle price path to determine trigger order
            price_path = self._infer_candle_path(open_, high, low, close)
            
            # Check if new signal becomes effective
            # Signal executes at the first execution candle open after its candle closes
            while signal_queue_idx < len(signal_queue):
                sig_effective_time, sig_type, sig_bar_time = signal_queue[signal_queue_idx]
                
                # Debug: log first few signal checks
                if i < 10 and signal_queue_idx < len(signal_queue):
                    logger.debug(f"[i={i}] Checking signal #{signal_queue_idx}: {sig_type} @ {sig_effective_time}, exec_time={timestamp}, position={position}")
                
                # If current exec candle time >= signal effective time, signal can execute
                if timestamp >= sig_effective_time:
                    # Check if signal can execute (based on current position)
                    # In both mode, open_long can execute even with short position (will auto-close first)
                    # Similarly, open_short can execute even with long position
                    can_execute = False
                    both_mode_active = norm_signals.get('_both_mode', False)
                    
                    if sig_type == 'open_long':
                        if position == 0:
                            can_execute = True
                        elif both_mode_active and position < 0:
                            # Both mode: have short position, will close short then open long
                            can_execute = True
                    elif sig_type == 'close_long' and position > 0:
                        can_execute = True
                    elif sig_type == 'open_short':
                        if position == 0:
                            can_execute = True
                        elif both_mode_active and position > 0:
                            # Both mode: have long position, will close long then open short
                            can_execute = True
                    elif sig_type == 'close_short' and position < 0:
                        can_execute = True
                    
                    if can_execute:
                        pending_signal = sig_type
                        pending_signal_time = sig_effective_time
                        signal_queue_idx += 1
                        if executed_trades_count < 5:
                            logger.info(f"Signal ready: {sig_type} @ {timestamp}, will execute at open price (both_mode={both_mode_active})")
                        break
                    else:
                        # Signal doesn't meet execution conditions, skip
                        if signal_queue_idx < 5:
                            logger.info(f"Skipping signal #{signal_queue_idx}: {sig_type} (position={position}, can_execute=False)")
                        signal_queue_idx += 1
                        continue
                else:
                    # Not yet at signal effective time
                    break
            
            # Check trigger conditions along price path
            for path_price in price_path:
                if is_liquidated:
                    break
                
                # 1. Check stop-loss/take-profit/trailing stop (highest priority)
                if position != 0 and position_type in ['long', 'short']:
                    triggered = False
                    
                    if position_type == 'long' and position > 0:
                        if highest_since_entry is None:
                            highest_since_entry = entry_price
                        highest_since_entry = max(highest_since_entry, path_price)
                        
                        # Stop loss
                        if stop_loss_pct_eff > 0:
                            sl_price = entry_price * (1 - stop_loss_pct_eff)
                            if path_price <= sl_price:
                                exec_price = sl_price * (1 - slippage)
                                commission_fee = position * exec_price * commission
                                profit = (exec_price - entry_price) * position - commission_fee
                                capital += profit
                                if capital < 0:
                                    capital = 0
                                    is_liquidated = True
                                total_commission_paid += commission_fee
                                trades.append({
                                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                    'type': 'close_long_stop',
                                    'price': round(exec_price, 4),
                                    'amount': round(position, 4),
                                    'profit': round(profit, 2),
                                    'balance': round(max(0, capital), 2)
                                })
                                position = 0
                                position_type = None
                                highest_since_entry = None
                                lowest_since_entry = None
                                triggered = True
                        
                        # Trailing stop
                        if not triggered and trailing_enabled and trailing_pct_eff > 0:
                            trail_active = True
                            if trailing_activation_pct_eff > 0:
                                trail_active = highest_since_entry >= entry_price * (1 + trailing_activation_pct_eff)
                            if trail_active:
                                tr_price = highest_since_entry * (1 - trailing_pct_eff)
                                if path_price <= tr_price:
                                    exec_price = tr_price * (1 - slippage)
                                    commission_fee = position * exec_price * commission
                                    profit = (exec_price - entry_price) * position - commission_fee
                                    capital += profit
                                    total_commission_paid += commission_fee
                                    trades.append({
                                        'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                        'type': 'close_long_trailing',
                                        'price': round(exec_price, 4),
                                        'amount': round(position, 4),
                                        'profit': round(profit, 2),
                                        'balance': round(max(0, capital), 2)
                                    })
                                    position = 0
                                    position_type = None
                                    highest_since_entry = None
                                    lowest_since_entry = None
                                    triggered = True
                        
                        # Fixed take profit (disabled when trailing stop is enabled)
                        if not triggered and not trailing_enabled and take_profit_pct_eff > 0:
                            tp_price = entry_price * (1 + take_profit_pct_eff)
                            if path_price >= tp_price:
                                exec_price = tp_price * (1 - slippage)
                                commission_fee = position * exec_price * commission
                                profit = (exec_price - entry_price) * position - commission_fee
                                capital += profit
                                total_commission_paid += commission_fee
                                trades.append({
                                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                    'type': 'close_long_profit',
                                    'price': round(exec_price, 4),
                                    'amount': round(position, 4),
                                    'profit': round(profit, 2),
                                    'balance': round(max(0, capital), 2)
                                })
                                position = 0
                                position_type = None
                                highest_since_entry = None
                                lowest_since_entry = None
                                triggered = True
                    
                    elif position_type == 'short' and position < 0:
                        shares = abs(position)
                        if lowest_since_entry is None:
                            lowest_since_entry = entry_price
                        lowest_since_entry = min(lowest_since_entry, path_price)
                        
                        # Stop loss
                        if stop_loss_pct_eff > 0:
                            sl_price = entry_price * (1 + stop_loss_pct_eff)
                            if path_price >= sl_price:
                                exec_price = sl_price * (1 + slippage)
                                commission_fee = shares * exec_price * commission
                                profit = (entry_price - exec_price) * shares - commission_fee
                                if capital + profit <= 0:
                                    capital = 0
                                    is_liquidated = True
                                    trades.append({
                                        'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                        'type': 'liquidation',
                                        'price': round(exec_price, 4),
                                        'amount': round(shares, 4),
                                        'profit': round(-initial_capital, 2),
                                        'balance': 0
                                    })
                                else:
                                    capital += profit
                                    total_commission_paid += commission_fee
                                    trades.append({
                                        'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                        'type': 'close_short_stop',
                                        'price': round(exec_price, 4),
                                        'amount': round(shares, 4),
                                        'profit': round(profit, 2),
                                        'balance': round(max(0, capital), 2)
                                    })
                                position = 0
                                position_type = None
                                highest_since_entry = None
                                lowest_since_entry = None
                                triggered = True
                        
                        # Trailing stop
                        if not triggered and trailing_enabled and trailing_pct_eff > 0:
                            trail_active = True
                            if trailing_activation_pct_eff > 0:
                                trail_active = lowest_since_entry <= entry_price * (1 - trailing_activation_pct_eff)
                            if trail_active:
                                tr_price = lowest_since_entry * (1 + trailing_pct_eff)
                                if path_price >= tr_price:
                                    exec_price = tr_price * (1 + slippage)
                                    commission_fee = shares * exec_price * commission
                                    profit = (entry_price - exec_price) * shares - commission_fee
                                    if capital + profit <= 0:
                                        capital = 0
                                        is_liquidated = True
                                        trades.append({
                                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                            'type': 'liquidation',
                                            'price': round(exec_price, 4),
                                            'amount': round(shares, 4),
                                            'profit': round(-initial_capital, 2),
                                            'balance': 0
                                        })
                                    else:
                                        capital += profit
                                        total_commission_paid += commission_fee
                                        trades.append({
                                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                            'type': 'close_short_trailing',
                                            'price': round(exec_price, 4),
                                            'amount': round(shares, 4),
                                            'profit': round(profit, 2),
                                            'balance': round(max(0, capital), 2)
                                        })
                                    position = 0
                                    position_type = None
                                    highest_since_entry = None
                                    lowest_since_entry = None
                                    triggered = True
                        
                        # Fixed take profit
                        if not triggered and not trailing_enabled and take_profit_pct_eff > 0:
                            tp_price = entry_price * (1 - take_profit_pct_eff)
                            if path_price <= tp_price:
                                exec_price = tp_price * (1 + slippage)
                                commission_fee = shares * exec_price * commission
                                profit = (entry_price - exec_price) * shares - commission_fee
                                capital += profit
                                total_commission_paid += commission_fee
                                trades.append({
                                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                    'type': 'close_short_profit',
                                    'price': round(exec_price, 4),
                                    'amount': round(shares, 4),
                                    'profit': round(profit, 2),
                                    'balance': round(max(0, capital), 2)
                                })
                                position = 0
                                position_type = None
                                highest_since_entry = None
                                lowest_since_entry = None
                                triggered = True
                    
                    if triggered:
                        pending_signal = None
                        continue
                
                # 2. Execute pending signal (at open price)
                if pending_signal and path_price == open_:
                    both_mode_active = norm_signals.get('_both_mode', False)
                    
                    # open_long: In both mode, first close short if any, then open long
                    if pending_signal == 'open_long' and (position == 0 or (both_mode_active and position < 0)):
                        exec_price = open_ * (1 + slippage)
                        
                        # If in both mode and have short position, close it first
                        if both_mode_active and position < 0:
                            shares_to_close = abs(position)
                            close_price = open_ * (1 + slippage)
                            close_commission = shares_to_close * close_price * commission
                            close_profit = (entry_price - close_price) * shares_to_close - close_commission
                            capital += close_profit
                            if capital < 0:
                                capital = 0
                            total_commission_paid += close_commission
                            trades.append({
                                'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                'type': 'close_short',
                                'price': round(close_price, 4),
                                'amount': round(shares_to_close, 4),
                                'profit': round(close_profit, 2),
                                'balance': round(max(0, capital), 2)
                            })
                            position = 0
                            position_type = None
                            executed_trades_count += 1
                            if executed_trades_count <= 10:
                                logger.info(f"Trade #{executed_trades_count}: close_short (before open_long) @ {timestamp}, price={close_price:.4f}, profit={close_profit:.2f}")
                            # 检查是否爆仓
                            if capital < min_capital_to_trade:
                                is_liquidated = True
                                capital = 0
                                pending_signal = None
                                continue
                        
                        # Now open long
                        use_capital = capital * entry_pct_cfg
                        if exec_price > 0:
                            shares = (use_capital * lev) / exec_price
                        else:
                            logger.warning(f"Invalid exec_price={exec_price} at {timestamp}, skipping open_long")
                            pending_signal = None
                            continue
                        commission_fee = shares * exec_price * commission
                        capital -= commission_fee
                        total_commission_paid += commission_fee
                        position = shares
                        entry_price = exec_price
                        position_type = 'long'
                        highest_since_entry = exec_price
                        lowest_since_entry = exec_price
                        trades.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'type': 'open_long',
                            'price': round(exec_price, 4),
                            'amount': round(shares, 4),
                            'profit': 0,
                            'balance': round(max(0, capital), 2)
                        })
                        executed_trades_count += 1
                        if executed_trades_count <= 10:
                            logger.info(f"Trade #{executed_trades_count}: open_long @ {timestamp}, price={exec_price:.4f}, shares={shares:.4f}")
                        pending_signal = None
                    
                    elif pending_signal == 'close_long' and position > 0:
                        exec_price = open_ * (1 - slippage)
                        commission_fee = position * exec_price * commission
                        profit = (exec_price - entry_price) * position - commission_fee
                        capital += profit
                        if capital < 0:
                            capital = 0
                        total_commission_paid += commission_fee
                        trades.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'type': 'close_long',
                            'price': round(exec_price, 4),
                            'amount': round(position, 4),
                            'profit': round(profit, 2),
                            'balance': round(max(0, capital), 2)
                        })
                        position = 0
                        position_type = None
                        highest_since_entry = None
                        lowest_since_entry = None
                        pending_signal = None
                        # 检查是否爆仓
                        if capital < min_capital_to_trade:
                            is_liquidated = True
                            capital = 0
                    
                    # open_short: In both mode, first close long if any, then open short
                    elif pending_signal == 'open_short' and (position == 0 or (both_mode_active and position > 0)):
                        exec_price = open_ * (1 - slippage)
                        
                        # If in both mode and have long position, close it first
                        if both_mode_active and position > 0:
                            close_price = open_ * (1 - slippage)
                            close_commission = position * close_price * commission
                            close_profit = (close_price - entry_price) * position - close_commission
                            capital += close_profit
                            if capital < 0:
                                capital = 0
                            total_commission_paid += close_commission
                            trades.append({
                                'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                'type': 'close_long',
                                'price': round(close_price, 4),
                                'amount': round(position, 4),
                                'profit': round(close_profit, 2),
                                'balance': round(max(0, capital), 2)
                            })
                            position = 0
                            position_type = None
                            executed_trades_count += 1
                            if executed_trades_count <= 10:
                                logger.info(f"Trade #{executed_trades_count}: close_long (before open_short) @ {timestamp}, price={close_price:.4f}, profit={close_profit:.2f}")
                            # 检查是否爆仓
                            if capital < min_capital_to_trade:
                                is_liquidated = True
                                capital = 0
                                pending_signal = None
                                continue
                        
                        # Now open short
                        use_capital = capital * entry_pct_cfg
                        if exec_price > 0:
                            shares = (use_capital * lev) / exec_price
                        else:
                            logger.warning(f"Invalid exec_price={exec_price} at {timestamp}, skipping open_short")
                            pending_signal = None
                            continue
                        commission_fee = shares * exec_price * commission
                        capital -= commission_fee
                        total_commission_paid += commission_fee
                        position = -shares
                        entry_price = exec_price
                        position_type = 'short'
                        highest_since_entry = exec_price
                        lowest_since_entry = exec_price
                        trades.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'type': 'open_short',
                            'price': round(exec_price, 4),
                            'amount': round(shares, 4),
                            'profit': 0,
                            'balance': round(max(0, capital), 2)
                        })
                        executed_trades_count += 1
                        if executed_trades_count <= 10:
                            logger.info(f"Trade #{executed_trades_count}: open_short @ {timestamp}, price={exec_price:.4f}, shares={shares:.4f}")
                        pending_signal = None
                    
                    elif pending_signal == 'close_short' and position < 0:
                        shares = abs(position)
                        exec_price = open_ * (1 + slippage)
                        commission_fee = shares * exec_price * commission
                        profit = (entry_price - exec_price) * shares - commission_fee
                        capital += profit
                        if capital < 0:
                            capital = 0
                        total_commission_paid += commission_fee
                        trades.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'type': 'close_short',
                            'price': round(exec_price, 4),
                            'amount': round(shares, 4),
                            'profit': round(profit, 2),
                            'balance': round(max(0, capital), 2)
                        })
                        position = 0
                        position_type = None
                        highest_since_entry = None
                        lowest_since_entry = None
                        pending_signal = None
                        # 检查是否爆仓
                        if capital < min_capital_to_trade:
                            is_liquidated = True
                            capital = 0
            
            # Calculate current equity
            if position > 0:
                unrealized = (close - entry_price) * position
                current_equity = capital + unrealized
            elif position < 0:
                shares = abs(position)
                unrealized = (entry_price - close) * shares
                current_equity = capital + unrealized
            else:
                current_equity = capital
            
            equity_curve.append({
                'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                'value': round(max(0, current_equity), 2)
            })
        
        # Summary log
        logger.info(f"MTF simulation complete: executed_trades={executed_trades_count}, total_trades_recorded={len(trades)}, final_capital={capital:.2f}")
        if len(trades) == 0:
            logger.warning(f"No trades executed! signal_queue_idx={signal_queue_idx}, total_signals={len(signal_queue)}")
        
        return equity_curve, trades, total_commission_paid
    
    def run_code_strategy(
        self,
        code: str,
        symbol: str,
        timeframe: str,
        limit: int = 1000
    ) -> Dict[str, Any]:
        """
        Run strategy code and return the 'output' variable defined in code.
        Used for signal bot preview functionality.
        """
        # 1. Calculate time range
        end_date = datetime.now()
        tf_seconds = self.TIMEFRAME_SECONDS.get(timeframe, 3600)
        start_date = end_date - timedelta(seconds=tf_seconds * limit)
        
        # 2. Fetch data (assuming market='crypto', can be optimized later)
        df = self._fetch_kline_data('crypto', symbol, timeframe, start_date, end_date)
        
        if df.empty:
            return {"error": "No data found"}

        # 3. Prepare execution environment
        local_vars = {
            'df': df.copy(),
            'np': np,
            'pd': pd,
            'output': {}  # Default empty output
        }
        
        # 4. Execute code
        try:
            import builtins
            def safe_import(name, *args, **kwargs):
                allowed = ['numpy', 'pandas', 'math', 'json', 'datetime', 'time']
                if name in allowed or name.split('.')[0] in allowed:
                    return builtins.__import__(name, *args, **kwargs)
                raise ImportError(f"Import not allowed: {name}")
            
            safe_builtins = {k: getattr(builtins, k) for k in dir(builtins) 
                           if not k.startswith('_') and k not in ['eval', 'exec', 'compile', 'open', 'input', 'exit']}
            safe_builtins['__import__'] = safe_import
            
            exec_env = local_vars.copy()
            exec_env['__builtins__'] = safe_builtins
            
            exec(code, exec_env)
            
            return exec_env.get('output', {})
            
        except Exception as e:
            logger.error(f"Strategy execution failed: {e}")
            logger.error(traceback.format_exc())
            return {"error": str(e)}

    def run(
        self,
        indicator_code: str,
        market: str,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        initial_capital: float = 10000.0,
        commission: float = 0.001,
        slippage: float = 0.0,  # Ideal backtest environment, no slippage
        leverage: int = 1,
        trade_direction: str = 'long',
        strategy_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Run backtest.
        
        Args:
            indicator_code: Indicator code
            market: Market type
            symbol: Trading symbol
            timeframe: Timeframe
            start_date: Start date
            end_date: End date
            initial_capital: Initial capital
            commission: Commission rate
            slippage: Slippage
            
        Returns:
            Backtest result
        """
        
        # 1. Fetch candle data
        df = self._fetch_kline_data(market, symbol, timeframe, start_date, end_date)
        if df.empty:
            raise ValueError("No candle data available in the backtest date range")
        
        
        # 2. Execute indicator code to get signals (pass backtest params)
        backtest_params = {
            'leverage': leverage,
            'initial_capital': initial_capital,
            'commission': commission,
            'trade_direction': trade_direction
        }
        signals = self._execute_indicator(indicator_code, df, backtest_params)
        
        # 3. Simulate trading
        equity_curve, trades, total_commission = self._simulate_trading(
            df, signals, initial_capital, commission, slippage, leverage, trade_direction, strategy_config
        )
        
        # 4. Calculate metrics
        metrics = self._calculate_metrics(equity_curve, trades, initial_capital, timeframe, start_date, end_date, total_commission)
        
        # 5. Format result
        return self._format_result(metrics, equity_curve, trades)
    
    def _fetch_kline_data(
        self,
        market: str,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """Fetch candle data and convert to DataFrame"""
        # Calculate required candle count
        total_seconds = (end_date - start_date).total_seconds()
        tf_seconds = self.TIMEFRAME_SECONDS.get(timeframe, 86400)
        limit = math.ceil(total_seconds / tf_seconds) + 200
        
        # Calculate before_time (end date + 1 day)
        before_time = int((end_date + timedelta(days=1)).timestamp())
        
        
        # Fetch data
        kline_data = DataSourceFactory.get_kline(
            market=market,
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
            before_time=before_time
        )
        
        if not kline_data:
            logger.warning("No candle data retrieved")
            return pd.DataFrame()
        
        if kline_data:
            first_time = datetime.fromtimestamp(kline_data[0]['time'])
            last_time = datetime.fromtimestamp(kline_data[-1]['time'])
        
        # Convert to DataFrame
        df = pd.DataFrame(kline_data)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df = df.set_index('time')
        
        if len(df) > 0:
            pass
        
        # Filter date range
        df = df[(df.index >= start_date) & (df.index <= end_date)].copy()
        
        if len(df) > 0:
            pass
        
        return df
    
    def _execute_indicator(self, code: str, df: pd.DataFrame, backtest_params: dict = None):
        """Execute indicator code to get signals.
        
        Args:
            code: Indicator code
            df: Candle data
            backtest_params: Backtest parameters dict (leverage, initial_capital, commission, trade_direction)
        """
        # Supported indicator signal formats:
        # - Preferred (simple): df['buy'], df['sell'] as boolean
        # - Backtest/internal (4-way): df['open_long'], df['close_long'], df['open_short'], df['close_short'] as boolean
        signals = pd.Series(0, index=df.index)
        
        try:
            # Prepare execution environment
            local_vars = {
                'df': df.copy(),
                'open': df['open'],
                'high': df['high'],
                'low': df['low'],
                'close': df['close'],
                'volume': df['volume'],
                'signals': signals,
                'np': np,
                'pd': pd,
            }
            
            # Add backtest params to execution environment (if provided)
            if backtest_params:
                local_vars['backtest_params'] = backtest_params
                local_vars['leverage'] = backtest_params.get('leverage', 1)
                local_vars['initial_capital'] = backtest_params.get('initial_capital', 10000)
                local_vars['commission'] = backtest_params.get('commission', 0.0002)
                local_vars['trade_direction'] = backtest_params.get('trade_direction', 'both')
            
            # === 指标参数支持 ===
            # 从 backtest_params 获取用户设置的指标参数
            user_indicator_params = (backtest_params or {}).get('indicator_params', {})
            # 解析指标代码中声明的参数
            declared_params = IndicatorParamsParser.parse_params(code)
            # 合并参数（用户值优先，否则使用默认值）
            merged_params = IndicatorParamsParser.merge_params(declared_params, user_indicator_params)
            local_vars['params'] = merged_params
            
            # === 指标调用器支持 ===
            user_id = (backtest_params or {}).get('user_id', 1)
            indicator_id = (backtest_params or {}).get('indicator_id')
            indicator_caller = IndicatorCaller(user_id, indicator_id)
            local_vars['call_indicator'] = indicator_caller.call_indicator
            
            # Add technical indicator functions
            local_vars.update(self._get_indicator_functions())
            
            # Add safe builtins (keep full builtins to support lambda etc.)
            # but remove dangerous functions like eval, exec, open etc.
            import builtins
            
            # Create restricted __import__ that only allows safe modules
            def safe_import(name, *args, **kwargs):
                """Only allow importing numpy, pandas, math, json etc."""
                allowed_modules = ['numpy', 'pandas', 'math', 'json', 'datetime', 'time']
                if name in allowed_modules or name.split('.')[0] in allowed_modules:
                    return builtins.__import__(name, *args, **kwargs)
                raise ImportError(f"Import not allowed: {name}")
            
            safe_builtins = {k: getattr(builtins, k) for k in dir(builtins) 
                           if not k.startswith('_') and k not in [
                               'eval', 'exec', 'compile', 'open', 'input',
                               'help', 'exit', 'quit',
                               'copyright', 'credits', 'license'
                           ]}
            
            # Add restricted __import__
            safe_builtins['__import__'] = safe_import
            
            # Create unified execution environment (globals and locals use same dict)
            # This allows functions to access np, pd etc.
            exec_env = local_vars.copy()
            exec_env['__builtins__'] = safe_builtins
            
            # Pre-execute import statements to ensure np and pd are available
            pre_import_code = """
import numpy as np
import pandas as pd
"""
            exec(pre_import_code, exec_env)
            
            # Security check: validate code doesn't contain dangerous operations
            from app.utils.safe_exec import validate_code_safety
            is_safe, error_msg = validate_code_safety(code)
            if not is_safe:
                logger.error(f"Backtest code security check failed: {error_msg}")
                raise ValueError(f"Code contains unsafe operations: {error_msg}")
            
            # Execute user code safely (with timeout)
            from app.utils.safe_exec import safe_exec_code
            exec_result = safe_exec_code(
                code=code,
                exec_globals=exec_env,
                exec_locals=exec_env,
                timeout=60  # Backtest allows longer time (60 seconds)
            )
            
            if not exec_result['success']:
                raise RuntimeError(f"Code execution failed: {exec_result['error']}")
            
            # Get the executed df
            executed_df = exec_env.get('df', df)

            # Validation: if chart signals are provided, df['buy']/df['sell'] must exist for backtest normalization.
            # This keeps indicator scripts simple and consistent (chart=buy/sell, execution=normalized in backend).
            output_obj = exec_env.get('output')
            has_output_signals = isinstance(output_obj, dict) and isinstance(output_obj.get('signals'), list) and len(output_obj.get('signals')) > 0
            if has_output_signals and not all(col in executed_df.columns for col in ['buy', 'sell']):
                raise ValueError(
                    "Invalid indicator script: output['signals'] is provided, but df['buy'] and df['sell'] are missing. "
                    "Please set df['buy'] and df['sell'] as boolean columns (len == len(df))."
                )
            
            # Extract signals from executed df
            if all(col in executed_df.columns for col in ['open_long', 'close_long', 'open_short', 'close_short']):
                
                signals = {
                    'open_long': executed_df['open_long'].fillna(False).astype(bool),
                    'close_long': executed_df['close_long'].fillna(False).astype(bool),
                    'open_short': executed_df['open_short'].fillna(False).astype(bool),
                    'close_short': executed_df['close_short'].fillna(False).astype(bool)
                }
                
                # Convention: backtest uses 4-way signals only.
                # Position sizing, TP/SL, trailing, etc must be handled by strategy_config / strategy logic.
            elif all(col in executed_df.columns for col in ['buy', 'sell']):
                # Simple buy/sell signals (recommended for indicator authors)
                signals = {
                    'buy': executed_df['buy'].fillna(False).astype(bool),
                    'sell': executed_df['sell'].fillna(False).astype(bool)
                }
            
            else:
                raise ValueError(
                    "Indicator must define either 4-way columns "
                    "(df['open_long'], df['close_long'], df['open_short'], df['close_short']) "
                    "or simple columns (df['buy'], df['sell'])."
                )
            
        except Exception as e:
            logger.error(f"Indicator code execution error: {e}")
            logger.error(traceback.format_exc())
        
        return signals
    
    def _get_indicator_functions(self) -> Dict:
        """Get technical indicator functions"""
        def SMA(series, period):
            return series.rolling(window=period).mean()
        
        def EMA(series, period):
            return series.ewm(span=period, adjust=False).mean()
        
        def RSI(series, period=14):
            delta = series.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss
            return 100 - (100 / (1 + rs))
        
        def MACD(series, fast=12, slow=26, signal=9):
            exp1 = series.ewm(span=fast, adjust=False).mean()
            exp2 = series.ewm(span=slow, adjust=False).mean()
            macd = exp1 - exp2
            macd_signal = macd.ewm(span=signal, adjust=False).mean()
            macd_hist = macd - macd_signal
            return macd, macd_signal, macd_hist
        
        def BOLL(series, period=20, std_dev=2):
            middle = series.rolling(window=period).mean()
            std = series.rolling(window=period).std()
            upper = middle + std_dev * std
            lower = middle - std_dev * std
            return upper, middle, lower
        
        def ATR(high, low, close, period=14):
            tr1 = high - low
            tr2 = abs(high - close.shift())
            tr3 = abs(low - close.shift())
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            return tr.rolling(window=period).mean()
        
        def CROSSOVER(series1, series2):
            return (series1 > series2) & (series1.shift(1) <= series2.shift(1))
        
        def CROSSUNDER(series1, series2):
            return (series1 < series2) & (series1.shift(1) >= series2.shift(1))
        
        return {
            'SMA': SMA,
            'EMA': EMA,
            'RSI': RSI,
            'MACD': MACD,
            'BOLL': BOLL,
            'ATR': ATR,
            'CROSSOVER': CROSSOVER,
            'CROSSUNDER': CROSSUNDER,
        }
    
    def _simulate_trading(
        self,
        df: pd.DataFrame,
        signals,
        initial_capital: float,
        commission: float,
        slippage: float,
        leverage: int = 1,
        trade_direction: str = 'long',
        strategy_config: Optional[Dict[str, Any]] = None
    ) -> tuple:
        """
        Simulate trading.
        
        Args:
            signals: Signals, can be pd.Series (old format) or dict (new 4-way format)
            trade_direction: Trade direction
                - 'long': Long only (buy->sell)
                - 'short': Short only (sell->buy, reversed PnL)
                - 'both': Both directions (buy->sell long + sell->buy short)
        """
        # Normalize supported signal formats into 4-way signals.
        if not isinstance(signals, dict):
            raise ValueError("signals must be a dict (either 4-way or buy/sell).")

        if all(k in signals for k in ['open_long', 'close_long', 'open_short', 'close_short']):
            norm = signals
        elif all(k in signals for k in ['buy', 'sell']):
            buy = signals['buy'].fillna(False).astype(bool)
            sell = signals['sell'].fillna(False).astype(bool)

            td = (trade_direction or 'both')
            td = str(td).lower()
            if td not in ['long', 'short', 'both']:
                td = 'both'

            # Mapping rules:
            # - long: buy=open_long, sell=close_long
            # - short: sell=open_short, buy=close_short
            # - both: buy=open_long+close_short, sell=open_short+close_long
            if td == 'long':
                norm = {
                    'open_long': buy,
                    'close_long': sell,
                    'open_short': pd.Series([False] * len(df), index=df.index),
                    'close_short': pd.Series([False] * len(df), index=df.index),
                }
            elif td == 'short':
                norm = {
                    'open_long': pd.Series([False] * len(df), index=df.index),
                    'close_long': pd.Series([False] * len(df), index=df.index),
                    'open_short': sell,
                    'close_short': buy,
                    '_both_mode': False,
                }
            else:
                # Both mode: buy signal opens long (auto-close short first)
                # sell signal opens short (auto-close long first)
                norm = {
                    'open_long': buy,
                    'close_long': pd.Series([False] * len(df), index=df.index),  # Disabled, handled by open_short
                    'open_short': sell,
                    'close_short': pd.Series([False] * len(df), index=df.index),  # Disabled, handled by open_long
                    '_both_mode': True,  # Flag to indicate auto-close opposing position
                }
        else:
            raise ValueError("signals dict must contain either 4-way keys or buy/sell keys.")

        return self._simulate_trading_new_format(df, norm, initial_capital, commission, slippage, leverage, trade_direction, strategy_config)
    
    def _simulate_trading_new_format(
        self,
        df: pd.DataFrame,
        signals: dict,
        initial_capital: float,
        commission: float,
        slippage: float,
        leverage: int = 1,
        trade_direction: str = 'both',
        strategy_config: Optional[Dict[str, Any]] = None
    ) -> tuple:
        """
        Simulate trading with 4-way signal format (supports position management and scaling).
        
        Args:
            trade_direction: Trade direction ('long', 'short', 'both')
        """
        equity_curve = []
        trades = []
        total_commission_paid = 0
        is_liquidated = False
        liquidation_price = 0
        min_capital_to_trade = 1.0  # Below this balance, consider wiped out, no new orders
        
        capital = initial_capital
        position = 0  # Positive=long, Negative=short
        entry_price = 0  # Average entry price
        position_type = None  # 'long' or 'short'
        
        # Position management related
        has_position_management = 'add_long' in signals and 'add_short' in signals
        position_batches = []  # Store each position batch: [{'price': xxx, 'amount': xxx}, ...]

        # --- Strategy config: signals + parameters = strategy (sent from BacktestModal as strategyConfig) ---
        cfg = strategy_config or {}
        exec_cfg = cfg.get('execution') or {}
        # Signal confirmation / execution timing:
        # - bar_close: execute on the same bar close (more aggressive)
        # - next_bar_open: execute on next bar open after signal is confirmed on bar close (recommended, closer to live)
        signal_timing = str(exec_cfg.get('signalTiming') or 'next_bar_open').strip().lower()
        risk_cfg = cfg.get('risk') or {}
        stop_loss_pct = float(risk_cfg.get('stopLossPct') or 0.0)
        take_profit_pct = float(risk_cfg.get('takeProfitPct') or 0.0)
        trailing_cfg = risk_cfg.get('trailing') or {}
        trailing_enabled = bool(trailing_cfg.get('enabled'))
        trailing_pct = float(trailing_cfg.get('pct') or 0.0)
        trailing_activation_pct = float(trailing_cfg.get('activationPct') or 0.0)

        # Risk percentages are defined on margin PnL; convert to price move thresholds by leverage.
        lev = max(int(leverage or 1), 1)
        stop_loss_pct_eff = stop_loss_pct / lev
        take_profit_pct_eff = take_profit_pct / lev
        trailing_pct_eff = trailing_pct / lev
        trailing_activation_pct_eff = trailing_activation_pct / lev

        # Conflict rule (TP vs trailing):
        # - If trailing is enabled, it takes precedence.
        # - If activationPct is not provided, reuse takeProfitPct as the trailing activation threshold.
        # - When trailing is enabled, fixed take-profit exits are disabled to avoid ambiguity.
        if trailing_enabled and trailing_pct_eff > 0:
            if trailing_activation_pct_eff <= 0 and take_profit_pct_eff > 0:
                trailing_activation_pct_eff = take_profit_pct_eff

        # IMPORTANT: risk percentages are defined on margin PnL (user expectation):
        # e.g. 10x leverage + 5% SL means ~0.5% adverse price move.
        lev = max(int(leverage or 1), 1)
        stop_loss_pct_eff = stop_loss_pct / lev
        take_profit_pct_eff = take_profit_pct / lev
        trailing_pct_eff = trailing_pct / lev
        trailing_activation_pct_eff = trailing_activation_pct / lev

        pos_cfg = cfg.get('position') or {}
        entry_pct_cfg = float(pos_cfg.get('entryPct') or 1.0)  # expected 0~1
        # Accept both 0~1 and 0~100 inputs (some clients may send percent units).
        if entry_pct_cfg > 1:
            entry_pct_cfg = entry_pct_cfg / 100.0
        entry_pct_cfg = max(0.0, min(entry_pct_cfg, 1.0))

        scale_cfg = cfg.get('scale') or {}
        trend_add_cfg = scale_cfg.get('trendAdd') or {}
        dca_add_cfg = scale_cfg.get('dcaAdd') or {}
        trend_reduce_cfg = scale_cfg.get('trendReduce') or {}
        adverse_reduce_cfg = scale_cfg.get('adverseReduce') or {}

        trend_add_enabled = bool(trend_add_cfg.get('enabled'))
        trend_add_step_pct = float(trend_add_cfg.get('stepPct') or 0.0)
        trend_add_size_pct = float(trend_add_cfg.get('sizePct') or 0.0)
        trend_add_max_times = int(trend_add_cfg.get('maxTimes') or 0)

        dca_add_enabled = bool(dca_add_cfg.get('enabled'))
        dca_add_step_pct = float(dca_add_cfg.get('stepPct') or 0.0)
        dca_add_size_pct = float(dca_add_cfg.get('sizePct') or 0.0)
        dca_add_max_times = int(dca_add_cfg.get('maxTimes') or 0)

        # Prevent logical conflict: trend scale-in and mean-reversion scale-in should not run together.
        # Otherwise both may trigger in the same candle (high/low both hit), causing double scaling unexpectedly.
        if trend_add_enabled and dca_add_enabled:
            dca_add_enabled = False

        trend_reduce_enabled = bool(trend_reduce_cfg.get('enabled'))
        trend_reduce_step_pct = float(trend_reduce_cfg.get('stepPct') or 0.0)
        trend_reduce_size_pct = float(trend_reduce_cfg.get('sizePct') or 0.0)
        trend_reduce_max_times = int(trend_reduce_cfg.get('maxTimes') or 0)

        adverse_reduce_enabled = bool(adverse_reduce_cfg.get('enabled'))
        adverse_reduce_step_pct = float(adverse_reduce_cfg.get('stepPct') or 0.0)
        adverse_reduce_size_pct = float(adverse_reduce_cfg.get('sizePct') or 0.0)
        adverse_reduce_max_times = int(adverse_reduce_cfg.get('maxTimes') or 0)

        # Trigger pct as post-leverage margin threshold: divide by leverage for price trigger
        # e.g. 10x + 5% trigger means ~0.5% price movement
        trend_add_step_pct_eff = trend_add_step_pct / lev
        dca_add_step_pct_eff = dca_add_step_pct / lev
        trend_reduce_step_pct_eff = trend_reduce_step_pct / lev
        adverse_reduce_step_pct_eff = adverse_reduce_step_pct / lev

        # State: used for trailing exits and scale-in/scale-out anchor levels
        highest_since_entry = None
        lowest_since_entry = None
        trend_add_times = 0
        dca_add_times = 0
        trend_reduce_times = 0
        adverse_reduce_times = 0
        last_trend_add_anchor = None
        last_dca_add_anchor = None
        last_trend_reduce_anchor = None
        last_adverse_reduce_anchor = None
        
        # Convert signals to arrays
        open_long_arr = signals['open_long'].values
        close_long_arr = signals['close_long'].values
        open_short_arr = signals['open_short'].values
        close_short_arr = signals['close_short'].values

        # Apply execution timing to avoid look-ahead bias:
        # If signals are computed using bar close, realistic execution is next bar open.
        if signal_timing in ['next_bar_open', 'next_open', 'nextopen', 'next']:
            open_long_arr = np.insert(open_long_arr[:-1], 0, False)
            close_long_arr = np.insert(close_long_arr[:-1], 0, False)
            open_short_arr = np.insert(open_short_arr[:-1], 0, False)
            close_short_arr = np.insert(close_short_arr[:-1], 0, False)
        
        # Filter signals by trade direction
        if trade_direction == 'long':
            # Long only: disable all short signals
            open_short_arr = np.zeros(len(df), dtype=bool)
            close_short_arr = np.zeros(len(df), dtype=bool)
        elif trade_direction == 'short':
            # Short only: disable all long signals
            open_long_arr = np.zeros(len(df), dtype=bool)
            close_long_arr = np.zeros(len(df), dtype=bool)
        else:
            pass
        
        # Add position signals
        if has_position_management:
            add_long_arr = signals['add_long'].values
            add_short_arr = signals['add_short'].values
            position_size_arr = signals.get('position_size', pd.Series([0.0] * len(df))).values
            
            # Filter add signals by trade direction
            if trade_direction == 'long':
                add_short_arr = np.zeros(len(df), dtype=bool)
            elif trade_direction == 'short':
                add_long_arr = np.zeros(len(df), dtype=bool)
        
        # Entry trigger price (if indicator provides)
        open_long_price_arr = signals.get('open_long_price', pd.Series([0.0] * len(df))).values
        open_short_price_arr = signals.get('open_short_price', pd.Series([0.0] * len(df))).values
        
        # Exit target price (if indicator provides)
        close_long_price_arr = signals.get('close_long_price', pd.Series([0.0] * len(df))).values
        close_short_price_arr = signals.get('close_short_price', pd.Series([0.0] * len(df))).values
        
        # Add position price (if indicator provides)
        add_long_price_arr = signals.get('add_long_price', pd.Series([0.0] * len(df))).values
        add_short_price_arr = signals.get('add_short_price', pd.Series([0.0] * len(df))).values
        
        for i, (timestamp, row) in enumerate(df.iterrows()):
            # 爆仓后直接停止回测，输出结果
            if is_liquidated:
                break

            # If no position and balance low, stop trading
            if position == 0 and capital < min_capital_to_trade:
                is_liquidated = True
                capital = 0
                trades.append({
                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                    'type': 'liquidation',
                    'price': round(float(row.get('close', 0) or 0), 4),
                    'amount': 0,
                    'profit': round(-initial_capital, 2),
                    'balance': 0
                })
                equity_curve.append({'time': timestamp.strftime('%Y-%m-%d %H:%M'), 'value': 0})
                break  # 直接停止
            
            # Use OHLC to evaluate triggers.
            high = row['high']
            low = row['low']
            close = row['close']
            open_ = row.get('open', close)
            
            # Default execution price depends on timing mode
            # - bar_close: close
            # - next_bar_open: open (this bar is the next bar for a prior signal)
            exec_price = open_ if signal_timing in ['next_bar_open', 'next_open', 'nextopen', 'next'] else close

            # --- Risk controls: SL / TP / trailing exit (highest priority) ---
            if position != 0 and position_type in ['long', 'short']:
                # Update extreme prices for trailing stop
                if position_type == 'long':
                    if highest_since_entry is None:
                        highest_since_entry = entry_price
                    if lowest_since_entry is None:
                        lowest_since_entry = entry_price
                    highest_since_entry = max(highest_since_entry, high)
                    lowest_since_entry = min(lowest_since_entry, low)
                else:  # short
                    if lowest_since_entry is None:
                        lowest_since_entry = entry_price
                    if highest_since_entry is None:
                        highest_since_entry = entry_price
                    lowest_since_entry = min(lowest_since_entry, low)
                    highest_since_entry = max(highest_since_entry, high)

                # Collect forced exit points in same candle
                # Backtest is candle-level, cannot determine exact trigger order; using priority:
                # StopLoss > TrailingStop > TakeProfit
                candidates = []  # [(trade_type, trigger_price)]
                if position_type == 'long' and position > 0:
                    if stop_loss_pct_eff > 0:
                        sl_price = entry_price * (1 - stop_loss_pct_eff)
                        if low <= sl_price:
                            candidates.append(('close_long_stop', sl_price))
                    # Fixed take-profit exit is disabled when trailing is enabled (see conflict rule above).
                    if (not trailing_enabled) and take_profit_pct_eff > 0:
                        tp_price = entry_price * (1 + take_profit_pct_eff)
                        if high >= tp_price:
                            candidates.append(('close_long_profit', tp_price))
                    if trailing_enabled and trailing_pct_eff > 0 and highest_since_entry is not None:
                        trail_active = True
                        if trailing_activation_pct_eff > 0:
                            trail_active = highest_since_entry >= entry_price * (1 + trailing_activation_pct_eff)
                        if trail_active:
                            tr_price = highest_since_entry * (1 - trailing_pct_eff)
                            if low <= tr_price:
                                candidates.append(('close_long_trailing', tr_price))

                    if candidates:
                        # Select by priority: SL > Trailing > TP
                        pri = {'close_long_stop': 0, 'close_long_trailing': 1, 'close_long_profit': 2}
                        trade_type, trigger_price = sorted(candidates, key=lambda x: (pri.get(x[0], 99), x[1]))[0]
                        exec_price_close = trigger_price * (1 - slippage)
                        commission_fee_close = position * exec_price_close * commission
                        # Entry commission deducted, only deduct exit commission
                        profit = (exec_price_close - entry_price) * position - commission_fee_close
                        capital += profit
                        total_commission_paid += commission_fee_close

                        trades.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'type': trade_type,
                            'price': round(exec_price_close, 4),
                            'amount': round(position, 4),
                            'profit': round(profit, 2),
                            'balance': round(max(0, capital), 2)
                        })

                        position = 0
                        position_type = None
                        liquidation_price = 0
                        highest_since_entry = None
                        lowest_since_entry = None
                        trend_add_times = dca_add_times = trend_reduce_times = adverse_reduce_times = 0
                        last_trend_add_anchor = last_dca_add_anchor = last_trend_reduce_anchor = last_adverse_reduce_anchor = None

                        equity_curve.append({'time': timestamp.strftime('%Y-%m-%d %H:%M'), 'value': round(capital, 2)})
                        continue

                if position_type == 'short' and position < 0:
                    shares = abs(position)
                    if stop_loss_pct_eff > 0:
                        sl_price = entry_price * (1 + stop_loss_pct_eff)
                        if high >= sl_price:
                            candidates.append(('close_short_stop', sl_price))
                    # Fixed take-profit exit is disabled when trailing is enabled (see conflict rule above).
                    if (not trailing_enabled) and take_profit_pct_eff > 0:
                        tp_price = entry_price * (1 - take_profit_pct_eff)
                        if low <= tp_price:
                            candidates.append(('close_short_profit', tp_price))
                    if trailing_enabled and trailing_pct_eff > 0 and lowest_since_entry is not None:
                        trail_active = True
                        if trailing_activation_pct_eff > 0:
                            trail_active = lowest_since_entry <= entry_price * (1 - trailing_activation_pct_eff)
                        if trail_active:
                            tr_price = lowest_since_entry * (1 + trailing_pct_eff)
                            if high >= tr_price:
                                candidates.append(('close_short_trailing', tr_price))

                    if candidates:
                        # Select by priority: SL > Trailing > TP
                        pri = {'close_short_stop': 0, 'close_short_trailing': 1, 'close_short_profit': 2}
                        trade_type, trigger_price = sorted(candidates, key=lambda x: (pri.get(x[0], 99), -x[1]))[0]
                        exec_price_close = trigger_price * (1 + slippage)
                        commission_fee_close = shares * exec_price_close * commission
                        # Entry commission deducted, only deduct exit commission
                        profit = (entry_price - exec_price_close) * shares - commission_fee_close

                        if capital + profit <= 0:
                            capital = 0
                            is_liquidated = True
                            trades.append({
                                'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                'type': 'liquidation',
                                'price': round(exec_price_close, 4),
                                'amount': round(shares, 4),
                                'profit': round(-initial_capital, 2),
                                'balance': 0
                            })
                            position = 0
                            position_type = None
                            liquidation_price = 0
                            equity_curve.append({'time': timestamp.strftime('%Y-%m-%d %H:%M'), 'value': 0})
                            continue

                        capital += profit
                        total_commission_paid += commission_fee_close

                        trades.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'type': trade_type,
                            'price': round(exec_price_close, 4),
                            'amount': round(shares, 4),
                            'profit': round(profit, 2),
                            'balance': round(max(0, capital), 2)
                        })

                        position = 0
                        position_type = None
                        liquidation_price = 0
                        highest_since_entry = None
                        lowest_since_entry = None
                        trend_add_times = dca_add_times = trend_reduce_times = adverse_reduce_times = 0
                        last_trend_add_anchor = last_dca_add_anchor = last_trend_reduce_anchor = last_adverse_reduce_anchor = None

                        equity_curve.append({'time': timestamp.strftime('%Y-%m-%d %H:%M'), 'value': round(capital, 2)})
                        continue
            
            # Handle exit signals (priority, SL/TP)
            if position > 0 and close_long_arr[i]:
                # Close long: use indicator price or close
                if signal_timing in ['next_bar_open', 'next_open', 'nextopen', 'next']:
                    target_price = open_
                else:
                    target_price = close_long_price_arr[i] if close_long_price_arr[i] > 0 else close
                exec_price = target_price * (1 - slippage)
                commission_fee = position * exec_price * commission
                profit = (exec_price - entry_price) * position - commission_fee
                capital += profit
                total_commission_paid += commission_fee

                # NOTE:
                # This is a "signal close" (not a forced stop-loss/take-profit/trailing exit).
                # Do NOT label it as *_stop/*_profit based on PnL sign, otherwise it looks like a stop-loss happened
                # even when risk controls are disabled (stopLossPct/takeProfitPct == 0).
                trade_type = 'close_long'

                trades.append({
                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                    'type': trade_type,
                    'price': round(exec_price, 4),
                    'amount': round(position, 4),
                    'profit': round(profit, 2),
                    'balance': round(max(0, capital), 2)
                })
                
                position = 0
                position_type = None
                liquidation_price = 0
                highest_since_entry = None
                lowest_since_entry = None
                trend_add_times = dca_add_times = trend_reduce_times = adverse_reduce_times = 0
                last_trend_add_anchor = last_dca_add_anchor = last_trend_reduce_anchor = last_adverse_reduce_anchor = None

                # Stop if balance too low after exit
                if capital < min_capital_to_trade:
                    is_liquidated = True
                    capital = 0
                    trades.append({
                        'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                        'type': 'liquidation',
                        'price': round(exec_price, 4),
                        'amount': 0,
                        'profit': round(-initial_capital, 2),
                        'balance': 0
                    })
            
            elif position < 0 and close_short_arr[i]:
                # Close short: use indicator price or close
                if signal_timing in ['next_bar_open', 'next_open', 'nextopen', 'next']:
                    target_price = open_
                else:
                    target_price = close_short_price_arr[i] if close_short_price_arr[i] > 0 else close
                exec_price = target_price * (1 + slippage)
                shares = abs(position)
                commission_fee = shares * exec_price * commission
                profit = (entry_price - exec_price) * shares - commission_fee
                
                if capital + profit <= 0:
                    logger.warning(f"Insufficient funds when closing short - liquidation")
                    capital = 0
                    is_liquidated = True
                    trades.append({
                        'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                        'type': 'liquidation',
                        'price': round(exec_price, 4),
                        'amount': round(shares, 4),
                        'profit': round(-capital, 2),
                        'balance': 0
                    })
                    position = 0
                    position_type = None
                    equity_curve.append({'time': timestamp.strftime('%Y-%m-%d %H:%M'), 'value': 0})
                    continue
                
                capital += profit
                total_commission_paid += commission_fee

                # Signal close (not forced TP/SL/trailing).
                trade_type = 'close_short'

                trades.append({
                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                    'type': trade_type,
                    'price': round(exec_price, 4),
                    'amount': round(shares, 4),
                    'profit': round(profit, 2),
                    'balance': round(max(0, capital), 2)
                })
                
                position = 0
                position_type = None
                liquidation_price = 0
                highest_since_entry = None
                lowest_since_entry = None
                trend_add_times = dca_add_times = trend_reduce_times = adverse_reduce_times = 0
                last_trend_add_anchor = last_dca_add_anchor = last_trend_reduce_anchor = last_adverse_reduce_anchor = None

                if capital < min_capital_to_trade:
                    is_liquidated = True
                    capital = 0
                    trades.append({
                        'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                        'type': 'liquidation',
                        'price': round(exec_price, 4),
                        'amount': 0,
                        'profit': round(-initial_capital, 2),
                        'balance': 0
                    })
            
            # If this candle has a main strategy signal (open/close long/short),
            # we must NOT apply any scale-in/scale-out actions on the same candle.
            main_signal_on_bar = bool(open_long_arr[i] or open_short_arr[i] or close_long_arr[i] or close_short_arr[i])

            # --- Parameterized scaling rules (no strategy code needed) ---
            # Rules:
            # - Trend scale-in: long triggers when price rises stepPct from anchor; short triggers when price falls stepPct from anchor
            # - Mean-reversion DCA: long triggers when price falls stepPct from anchor; short triggers when price rises stepPct from anchor
            # - Trend reduce: long reduces on rise; short reduces on fall
            # - Adverse reduce: long reduces on fall; short reduces on rise
            if (not main_signal_on_bar) and position != 0 and position_type in ['long', 'short'] and capital >= min_capital_to_trade:
                # Long
                if position_type == 'long' and position > 0:
                    # Trend scale-in (trigger on higher price)
                    if trend_add_enabled and trend_add_step_pct_eff > 0 and trend_add_size_pct > 0 and (trend_add_max_times == 0 or trend_add_times < trend_add_max_times):
                        anchor = last_trend_add_anchor if last_trend_add_anchor is not None else entry_price
                        trigger = anchor * (1 + trend_add_step_pct_eff)
                        if high >= trigger:
                            order_pct = trend_add_size_pct
                            if order_pct > 0:
                                exec_price_add = trigger * (1 + slippage)
                                use_capital = capital * order_pct
                                # Commission from notional value
                                shares_add = (use_capital * leverage) / exec_price_add
                                commission_fee = shares_add * exec_price_add * commission

                                total_cost_before = position * entry_price
                                total_cost_after = total_cost_before + shares_add * exec_price_add
                                position += shares_add
                                entry_price = total_cost_after / position

                                capital -= commission_fee
                                total_commission_paid += commission_fee
                                liquidation_price = entry_price * (1 - 1.0 / leverage)

                                trend_add_times += 1
                                last_trend_add_anchor = trigger

                                trades.append({
                                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                    'type': 'add_long',
                                    'price': round(exec_price_add, 4),
                                    'amount': round(shares_add, 4),
                                    'profit': 0,
                                    'balance': round(max(0, capital), 2)
                                })

                    # Mean-reversion DCA (trigger on lower price)
                    if dca_add_enabled and dca_add_step_pct_eff > 0 and dca_add_size_pct > 0 and (dca_add_max_times == 0 or dca_add_times < dca_add_max_times):
                        anchor = last_dca_add_anchor if last_dca_add_anchor is not None else entry_price
                        trigger = anchor * (1 - dca_add_step_pct_eff)
                        if low <= trigger:
                            order_pct = dca_add_size_pct
                            if order_pct > 0:
                                exec_price_add = trigger * (1 + slippage)
                                use_capital = capital * order_pct
                                shares_add = (use_capital * leverage) / exec_price_add
                                commission_fee = shares_add * exec_price_add * commission

                                total_cost_before = position * entry_price
                                total_cost_after = total_cost_before + shares_add * exec_price_add
                                position += shares_add
                                entry_price = total_cost_after / position

                                capital -= commission_fee
                                total_commission_paid += commission_fee
                                liquidation_price = entry_price * (1 - 1.0 / leverage)

                                dca_add_times += 1
                                last_dca_add_anchor = trigger

                                trades.append({
                                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                    'type': 'add_long',
                                    'price': round(exec_price_add, 4),
                                    'amount': round(shares_add, 4),
                                    'profit': 0,
                                    'balance': round(max(0, capital), 2)
                                })

                    # Trend reduce (trigger on higher price)
                    if trend_reduce_enabled and trend_reduce_step_pct_eff > 0 and trend_reduce_size_pct > 0 and (trend_reduce_max_times == 0 or trend_reduce_times < trend_reduce_max_times):
                        anchor = last_trend_reduce_anchor if last_trend_reduce_anchor is not None else entry_price
                        trigger = anchor * (1 + trend_reduce_step_pct_eff)
                        if high >= trigger:
                            reduce_pct = max(trend_reduce_size_pct, 0.0)
                            reduce_shares = position * reduce_pct
                            if reduce_shares > 0:
                                exec_price_reduce = trigger * (1 - slippage)
                                commission_fee = reduce_shares * exec_price_reduce * commission
                                profit = (exec_price_reduce - entry_price) * reduce_shares - commission_fee
                                capital += profit
                                total_commission_paid += commission_fee
                                position -= reduce_shares
                                if position <= 1e-12:
                                    position = 0
                                    position_type = None
                                    liquidation_price = 0
                                else:
                                    liquidation_price = entry_price * (1 - 1.0 / leverage)

                                trend_reduce_times += 1
                                last_trend_reduce_anchor = trigger

                                trades.append({
                                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                    'type': 'reduce_long',
                                    'price': round(exec_price_reduce, 4),
                                    'amount': round(reduce_shares, 4),
                                    'profit': round(profit, 2),
                                    'balance': round(max(0, capital), 2)
                                })

                    # Adverse reduce (trigger on lower price)
                    if position_type == 'long' and position > 0 and adverse_reduce_enabled and adverse_reduce_step_pct_eff > 0 and adverse_reduce_size_pct > 0 and (adverse_reduce_max_times == 0 or adverse_reduce_times < adverse_reduce_max_times):
                        anchor = last_adverse_reduce_anchor if last_adverse_reduce_anchor is not None else entry_price
                        trigger = anchor * (1 - adverse_reduce_step_pct_eff)
                        if low <= trigger:
                            reduce_pct = max(adverse_reduce_size_pct, 0.0)
                            reduce_shares = position * reduce_pct
                            if reduce_shares > 0:
                                exec_price_reduce = trigger * (1 - slippage)
                                commission_fee = reduce_shares * exec_price_reduce * commission
                                profit = (exec_price_reduce - entry_price) * reduce_shares - commission_fee
                                capital += profit
                                total_commission_paid += commission_fee
                                position -= reduce_shares
                                if position <= 1e-12:
                                    position = 0
                                    position_type = None
                                    liquidation_price = 0
                                else:
                                    liquidation_price = entry_price * (1 - 1.0 / leverage)

                                adverse_reduce_times += 1
                                last_adverse_reduce_anchor = trigger

                                trades.append({
                                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                    'type': 'reduce_long',
                                    'price': round(exec_price_reduce, 4),
                                    'amount': round(reduce_shares, 4),
                                    'profit': round(profit, 2),
                                    'balance': round(max(0, capital), 2)
                                })

                # Short
                if position_type == 'short' and position < 0:
                    shares_total = abs(position)

                    # Trend scale-in (trigger on lower price)
                    if trend_add_enabled and trend_add_step_pct_eff > 0 and trend_add_size_pct > 0 and (trend_add_max_times == 0 or trend_add_times < trend_add_max_times):
                        anchor = last_trend_add_anchor if last_trend_add_anchor is not None else entry_price
                        trigger = anchor * (1 - trend_add_step_pct_eff)
                        if low <= trigger:
                            order_pct = trend_add_size_pct
                            if order_pct > 0:
                                exec_price_add = trigger * (1 - slippage)  # Sell to add short, slippage unfavorable
                                use_capital = capital * order_pct
                                shares_add = (use_capital * leverage) / exec_price_add
                                commission_fee = shares_add * exec_price_add * commission

                                total_cost_before = shares_total * entry_price
                                total_cost_after = total_cost_before + shares_add * exec_price_add
                                position -= shares_add
                                shares_total = abs(position)
                                entry_price = total_cost_after / shares_total

                                capital -= commission_fee
                                total_commission_paid += commission_fee
                                liquidation_price = entry_price * (1 + 1.0 / leverage)

                                trend_add_times += 1
                                last_trend_add_anchor = trigger

                                trades.append({
                                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                    'type': 'add_short',
                                    'price': round(exec_price_add, 4),
                                    'amount': round(shares_add, 4),
                                    'profit': 0,
                                    'balance': round(max(0, capital), 2)
                                })

                    # Mean-reversion DCA (trigger on higher price)
                    if dca_add_enabled and dca_add_step_pct_eff > 0 and dca_add_size_pct > 0 and (dca_add_max_times == 0 or dca_add_times < dca_add_max_times):
                        anchor = last_dca_add_anchor if last_dca_add_anchor is not None else entry_price
                        trigger = anchor * (1 + dca_add_step_pct_eff)
                        if high >= trigger:
                            order_pct = dca_add_size_pct
                            if order_pct > 0:
                                exec_price_add = trigger * (1 - slippage)
                                use_capital = capital * order_pct
                                shares_add = (use_capital * leverage) / exec_price_add
                                commission_fee = shares_add * exec_price_add * commission

                                total_cost_before = shares_total * entry_price
                                total_cost_after = total_cost_before + shares_add * exec_price_add
                                position -= shares_add
                                shares_total = abs(position)
                                entry_price = total_cost_after / shares_total

                                capital -= commission_fee
                                total_commission_paid += commission_fee
                                liquidation_price = entry_price * (1 + 1.0 / leverage)

                                dca_add_times += 1
                                last_dca_add_anchor = trigger

                                trades.append({
                                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                    'type': 'add_short',
                                    'price': round(exec_price_add, 4),
                                    'amount': round(shares_add, 4),
                                    'profit': 0,
                                    'balance': round(max(0, capital), 2)
                                })

                    # Trend reduce (trigger on lower price)
                    if trend_reduce_enabled and trend_reduce_step_pct_eff > 0 and trend_reduce_size_pct > 0 and (trend_reduce_max_times == 0 or trend_reduce_times < trend_reduce_max_times):
                        anchor = last_trend_reduce_anchor if last_trend_reduce_anchor is not None else entry_price
                        trigger = anchor * (1 - trend_reduce_step_pct_eff)
                        if low <= trigger:
                            reduce_pct = max(trend_reduce_size_pct, 0.0)
                            reduce_shares = shares_total * reduce_pct
                            if reduce_shares > 0:
                                exec_price_reduce = trigger * (1 + slippage)  # Cover more expensive
                                commission_fee = reduce_shares * exec_price_reduce * commission
                                profit = (entry_price - exec_price_reduce) * reduce_shares - commission_fee
                                capital += profit
                                total_commission_paid += commission_fee
                                position += reduce_shares
                                shares_total = abs(position)
                                if shares_total <= 1e-12:
                                    position = 0
                                    position_type = None
                                    liquidation_price = 0
                                else:
                                    liquidation_price = entry_price * (1 + 1.0 / leverage)

                                trend_reduce_times += 1
                                last_trend_reduce_anchor = trigger

                                trades.append({
                                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                    'type': 'reduce_short',
                                    'price': round(exec_price_reduce, 4),
                                    'amount': round(reduce_shares, 4),
                                    'profit': round(profit, 2),
                                    'balance': round(max(0, capital), 2)
                                })

                    # Adverse reduce (trigger on higher price)
                    if position_type == 'short' and position < 0 and adverse_reduce_enabled and adverse_reduce_step_pct_eff > 0 and adverse_reduce_size_pct > 0 and (adverse_reduce_max_times == 0 or adverse_reduce_times < adverse_reduce_max_times):
                        anchor = last_adverse_reduce_anchor if last_adverse_reduce_anchor is not None else entry_price
                        trigger = anchor * (1 + adverse_reduce_step_pct_eff)
                        if high >= trigger:
                            reduce_pct = max(adverse_reduce_size_pct, 0.0)
                            reduce_shares = shares_total * reduce_pct
                            if reduce_shares > 0:
                                exec_price_reduce = trigger * (1 + slippage)
                                commission_fee = reduce_shares * exec_price_reduce * commission
                                profit = (entry_price - exec_price_reduce) * reduce_shares - commission_fee
                                capital += profit
                                total_commission_paid += commission_fee
                                position += reduce_shares
                                shares_total = abs(position)
                                if shares_total <= 1e-12:
                                    position = 0
                                    position_type = None
                                    liquidation_price = 0
                                else:
                                    liquidation_price = entry_price * (1 + 1.0 / leverage)

                                adverse_reduce_times += 1
                                last_adverse_reduce_anchor = trigger

                                trades.append({
                                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                    'type': 'reduce_short',
                                    'price': round(exec_price_reduce, 4),
                                    'amount': round(reduce_shares, 4),
                                    'profit': round(profit, 2),
                                    'balance': round(max(0, capital), 2)
                                })

            # Handle add position signals
            if has_position_management and (not main_signal_on_bar):
                if position > 0 and add_long_arr[i] and capital >= min_capital_to_trade:
                    # Add long: use indicator price or close
                    target_price = add_long_price_arr[i] if add_long_price_arr[i] > 0 else close
                    exec_price = target_price * (1 + slippage)
                    
                    # Use specified pct to add
                    position_pct = position_size_arr[i] if position_size_arr[i] > 0 else 0.1
                    use_capital = capital * position_pct
                    shares = (use_capital * leverage) / exec_price
                    commission_fee = shares * exec_price * commission
                    
                    # Update average cost
                    total_cost_before = position * entry_price
                    total_cost_after = total_cost_before + shares * exec_price
                    position += shares
                    entry_price = total_cost_after / position
                    
                    capital -= commission_fee
                    total_commission_paid += commission_fee
                    
                    # Recalculate liquidation price
                    liquidation_price = entry_price * (1 - 1.0 / leverage)
                    
                    trades.append({
                        'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                        'type': 'add_long',
                        'price': round(exec_price, 4),
                        'amount': round(shares, 4),
                        'profit': 0,
                        'balance': round(max(0, capital), 2)
                    })
                
                elif position < 0 and add_short_arr[i] and capital >= min_capital_to_trade:
                    # Add short: use indicator price or close
                    target_price = add_short_price_arr[i] if add_short_price_arr[i] > 0 else close
                    exec_price = target_price * (1 - slippage)
                    
                    # Use specified pct to add
                    position_pct = position_size_arr[i] if position_size_arr[i] > 0 else 0.1
                    use_capital = capital * position_pct
                    shares = (use_capital * leverage) / exec_price
                    commission_fee = shares * exec_price * commission
                    
                    # Update average cost
                    current_shares = abs(position)
                    total_cost_before = current_shares * entry_price
                    total_cost_after = total_cost_before + shares * exec_price
                    position -= shares  # Short is negative
                    current_shares = abs(position)
                    entry_price = total_cost_after / current_shares
                    
                    capital -= commission_fee
                    total_commission_paid += commission_fee
                    
                    # Recalculate liquidation price
                    liquidation_price = entry_price * (1 + 1.0 / leverage)
                    
                    trades.append({
                        'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                        'type': 'add_short',
                        'price': round(exec_price, 4),
                        'amount': round(shares, 4),
                        'profit': 0,
                        'balance': round(max(0, capital), 2)
                    })
            
            # Handle entry signals
            # In both mode, open_long/open_short can auto-close opposing position first
            both_mode_active = signals.get('_both_mode', False)
            
            # open_long: can execute when position==0, OR when both_mode and position<0 (auto-close short first)
            if open_long_arr[i] and (position == 0 or (both_mode_active and position < 0)) and capital >= min_capital_to_trade:
                    # In both mode with short position, close it first
                    if both_mode_active and position < 0:
                        shares_to_close = abs(position)
                        close_price = open_ * (1 + slippage)
                        close_commission = shares_to_close * close_price * commission
                        close_profit = (entry_price - close_price) * shares_to_close - close_commission
                        capital += close_profit
                        if capital < 0:
                            capital = 0
                        total_commission_paid += close_commission
                        trades.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'type': 'close_short',
                            'price': round(close_price, 4),
                            'amount': round(shares_to_close, 4),
                            'profit': round(close_profit, 2),
                            'balance': round(max(0, capital), 2)
                        })
                        position = 0
                        position_type = None
                        liquidation_price = 0
                        highest_since_entry = None
                        lowest_since_entry = None
                        trend_add_times = dca_add_times = trend_reduce_times = adverse_reduce_times = 0
                        last_trend_add_anchor = last_dca_add_anchor = last_trend_reduce_anchor = last_adverse_reduce_anchor = None
                        # 检查是否爆仓
                        if capital < min_capital_to_trade:
                            is_liquidated = True
                            capital = 0
                            equity_curve.append({'time': timestamp.strftime('%Y-%m-%d %H:%M'), 'value': 0})
                            continue
                    
                    # Now open long (position is guaranteed to be 0 here)
                    # Use indicator entry price or close
                    if signal_timing in ['next_bar_open', 'next_open', 'nextopen', 'next']:
                        base_price = open_
                    else:
                        base_price = open_long_price_arr[i] if open_long_price_arr[i] > 0 else close
                    exec_price = base_price * (1 + slippage)
                    
                    # Use specified pct (entryPct > position_size > full)
                    position_pct = None
                    if entry_pct_cfg and entry_pct_cfg > 0:
                        position_pct = entry_pct_cfg
                    elif has_position_management and position_size_arr[i] > 0:
                        position_pct = position_size_arr[i]
                    if position_pct is not None and position_pct > 0 and position_pct < 1:
                        use_capital = capital * position_pct
                        shares = (use_capital * leverage) / exec_price
                    else:
                        shares = (capital * leverage) / exec_price
                    
                    commission_fee = shares * exec_price * commission
                    
                    position = shares
                    entry_price = exec_price
                    position_type = 'long'
                    capital -= commission_fee
                    total_commission_paid += commission_fee
                    liquidation_price = entry_price * (1 - 1.0 / leverage)
                    highest_since_entry = entry_price
                    lowest_since_entry = entry_price
                    last_trend_add_anchor = entry_price
                    last_dca_add_anchor = entry_price
                    last_trend_reduce_anchor = entry_price
                    last_adverse_reduce_anchor = entry_price
                    
                    trades.append({
                        'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                        'type': 'open_long',
                        'price': round(exec_price, 4),
                        'amount': round(shares, 4),
                        'profit': 0,
                        'balance': round(max(0, capital), 2)
                    })
                    
                    # Strict intrabar stop-loss / liquidation check right after entry (closer to live trading).
                    # If this bar touches stop-loss price, close immediately at stop price (with slippage).
                    # If this bar also touches liquidation price, assume stop-loss triggers first only if it is above liquidation.
                    if position_type == 'long' and position > 0:
                        sl_price = entry_price * (1 - stop_loss_pct_eff) if stop_loss_pct_eff > 0 else None
                        hit_sl = (sl_price is not None) and (low <= sl_price)
                        hit_liq = liquidation_price > 0 and (low <= liquidation_price)
                        if hit_sl or hit_liq:
                            if hit_liq and (not hit_sl or (sl_price is not None and sl_price <= liquidation_price)):
                                # Liquidation happens before stop-loss (or stop-loss not configured).
                                is_liquidated = True
                                capital = 0
                                trades.append({
                                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                    'type': 'liquidation',
                                    'price': round(liquidation_price, 4),
                                    'amount': round(position, 4),
                                    'profit': round(-initial_capital, 2),
                                    'balance': 0
                                })
                            else:
                                # Stop-loss triggers first.
                                exec_price_close = sl_price * (1 - slippage)
                                commission_fee_close = position * exec_price_close * commission
                                profit = (exec_price_close - entry_price) * position - commission_fee_close
                                capital += profit
                                total_commission_paid += commission_fee_close
                                if capital <= 0:
                                    is_liquidated = True
                                    capital = 0
                                trades.append({
                                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                    'type': 'close_long_stop',
                                    'price': round(exec_price_close, 4),
                                    'amount': round(position, 4),
                                    'profit': round(profit, 2),
                                    'balance': round(max(0, capital), 2)
                                })

                            position = 0
                            position_type = None
                            liquidation_price = 0
                            highest_since_entry = None
                            lowest_since_entry = None
                            equity_curve.append({'time': timestamp.strftime('%Y-%m-%d %H:%M'), 'value': round(capital, 2)})
                            continue
            
            # open_short: can execute when position==0, OR when both_mode and position>0 (auto-close long first)
            elif open_short_arr[i] and (position == 0 or (both_mode_active and position > 0)) and capital >= min_capital_to_trade:
                    # In both mode with long position, close it first
                    if both_mode_active and position > 0:
                        close_price = open_ * (1 - slippage)
                        close_commission = position * close_price * commission
                        close_profit = (close_price - entry_price) * position - close_commission
                        capital += close_profit
                        if capital < 0:
                            capital = 0
                        total_commission_paid += close_commission
                        trades.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'type': 'close_long',
                            'price': round(close_price, 4),
                            'amount': round(position, 4),
                            'profit': round(close_profit, 2),
                            'balance': round(max(0, capital), 2)
                        })
                        position = 0
                        position_type = None
                        liquidation_price = 0
                        highest_since_entry = None
                        lowest_since_entry = None
                        trend_add_times = dca_add_times = trend_reduce_times = adverse_reduce_times = 0
                        last_trend_add_anchor = last_dca_add_anchor = last_trend_reduce_anchor = last_adverse_reduce_anchor = None
                        # 检查是否爆仓
                        if capital < min_capital_to_trade:
                            is_liquidated = True
                            capital = 0
                            equity_curve.append({'time': timestamp.strftime('%Y-%m-%d %H:%M'), 'value': 0})
                            continue
                    
                    # Now open short (position is guaranteed to be 0 here)
                    # Use indicator entry price or close
                    if signal_timing in ['next_bar_open', 'next_open', 'nextopen', 'next']:
                        base_price = open_
                    else:
                        base_price = open_short_price_arr[i] if open_short_price_arr[i] > 0 else close
                    exec_price = base_price * (1 - slippage)
                    
                    # Use specified pct (entryPct > position_size > full)
                    position_pct = None
                    if entry_pct_cfg and entry_pct_cfg > 0:
                        position_pct = entry_pct_cfg
                    elif has_position_management and position_size_arr[i] > 0:
                        position_pct = position_size_arr[i]
                    if position_pct is not None and position_pct > 0 and position_pct < 1:
                        use_capital = capital * position_pct
                        shares = (use_capital * leverage) / exec_price
                    else:
                        shares = (capital * leverage) / exec_price
                    
                    commission_fee = shares * exec_price * commission
                    
                    position = -shares
                    entry_price = exec_price
                    position_type = 'short'
                    capital -= commission_fee
                    total_commission_paid += commission_fee
                    liquidation_price = entry_price * (1 + 1.0 / leverage)
                    highest_since_entry = entry_price
                    lowest_since_entry = entry_price
                    last_trend_add_anchor = entry_price
                    last_dca_add_anchor = entry_price
                    last_trend_reduce_anchor = entry_price
                    last_adverse_reduce_anchor = entry_price
                    
                    trades.append({
                        'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                        'type': 'open_short',
                        'price': round(exec_price, 4),
                        'amount': round(shares, 4),
                        'profit': 0,
                        'balance': round(max(0, capital), 2)
                    })
                    
                    # Strict intrabar stop-loss / liquidation check right after entry (closer to live trading).
                    if position_type == 'short' and position < 0:
                        sl_price = entry_price * (1 + stop_loss_pct_eff) if stop_loss_pct_eff > 0 else None
                        hit_sl = (sl_price is not None) and (high >= sl_price)
                        hit_liq = liquidation_price > 0 and (high >= liquidation_price)
                        if hit_sl or hit_liq:
                            if hit_liq and (not hit_sl or (sl_price is not None and sl_price >= liquidation_price)):
                                # Liquidation happens before stop-loss (or stop-loss not configured).
                                is_liquidated = True
                                capital = 0
                                trades.append({
                                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                    'type': 'liquidation',
                                    'price': round(liquidation_price, 4),
                                    'amount': round(abs(position), 4),
                                    'profit': round(-initial_capital, 2),
                                    'balance': 0
                                })
                            else:
                                # Stop-loss triggers first.
                                exec_price_close = sl_price * (1 + slippage)
                                shares_close = abs(position)
                                commission_fee_close = shares_close * exec_price_close * commission
                                profit = (entry_price - exec_price_close) * shares_close - commission_fee_close
                                capital += profit
                                total_commission_paid += commission_fee_close
                                if capital <= 0:
                                    is_liquidated = True
                                    capital = 0
                                trades.append({
                                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                    'type': 'close_short_stop',
                                    'price': round(exec_price_close, 4),
                                    'amount': round(shares_close, 4),
                                    'profit': round(profit, 2),
                                    'balance': round(max(0, capital), 2)
                                })

                            position = 0
                            position_type = None
                            liquidation_price = 0
                            highest_since_entry = None
                            lowest_since_entry = None
                            equity_curve.append({'time': timestamp.strftime('%Y-%m-%d %H:%M'), 'value': round(capital, 2)})
                            continue
            
            # Check if liquidation hit (safety net)
            # Note: check after all active exit signals
            # If liquidation hit, check SL signal first
            if position != 0 and not is_liquidated:
                if position_type == 'long' and low <= liquidation_price:
                    # Long触及爆仓线：检查是否有止损信号
                    has_stop_loss = close_long_arr[i] and close_long_price_arr[i] > 0
                    stop_loss_price = close_long_price_arr[i] if has_stop_loss else 0
                    
                    # Determine SL or liquidation first
                    if has_stop_loss and stop_loss_price > liquidation_price:
                        # SL triggers before liquidation
                        exec_price_close = stop_loss_price * (1 - slippage)
                        commission_fee_close = position * exec_price_close * commission
                        profit = (exec_price_close - entry_price) * position - commission_fee_close
                        capital += profit
                        total_commission_paid += commission_fee_close
                        
                        trades.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'type': 'close_long_stop',
                            'price': round(exec_price_close, 4),
                            'amount': round(position, 4),
                            'profit': round(profit, 2),
                            'balance': round(max(0, capital), 2)
                        })
                    else:
                        # SL not strict enough, liquidation triggered
                        logger.warning(f"Long liquidation! entry={entry_price:.2f}, low={low:.2f}, "
                                     f"爆仓线={liquidation_price:.2f}, 止损价={stop_loss_price:.2f}")
                        is_liquidated = True
                        capital = 0
                        trades.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'type': 'liquidation',
                            'price': round(liquidation_price, 4),
                            'amount': round(abs(position), 4),
                            'profit': round(-initial_capital, 2),
                            'balance': 0
                        })
                    
                    position = 0
                    position_type = None
                    equity_curve.append({'time': timestamp.strftime('%Y-%m-%d %H:%M'), 'value': capital})
                    continue
                    
                elif position_type == 'short' and high >= liquidation_price:
                    # Short触及爆仓线：检查是否有止损信号
                    has_stop_loss = close_short_arr[i] and close_short_price_arr[i] > 0
                    stop_loss_price = close_short_price_arr[i] if has_stop_loss else 0
                    
                    logger.warning(f"[candle {i}] Short hit liquidation! entry={entry_price:.2f}, high={high:.2f}, liq_price={liquidation_price:.2f}, "
                              f"止损信号={close_short_arr[i]}, 止损价={stop_loss_price:.4f}, 时间={timestamp}")
                    
                    # Determine SL or liquidation first
                    if has_stop_loss and stop_loss_price < liquidation_price:
                        # SL triggers before liquidation
                        exec_price_close = stop_loss_price * (1 + slippage)
                        shares_close = abs(position)
                        commission_fee_close = shares_close * exec_price_close * commission
                        profit = (entry_price - exec_price_close) * shares_close - commission_fee_close
                        capital += profit
                        total_commission_paid += commission_fee_close
                        
                        trades.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'type': 'close_short_stop',
                            'price': round(exec_price_close, 4),
                            'amount': round(shares_close, 4),
                            'profit': round(profit, 2),
                            'balance': round(max(0, capital), 2)
                        })
                    else:
                        # SL not strict enough, liquidation triggered
                        logger.warning(f"Short liquidation! entry={entry_price:.2f}, high={high:.2f}, "
                                     f"爆仓线={liquidation_price:.2f}, 止损价={stop_loss_price:.2f}")
                        is_liquidated = True
                        capital = 0
                        trades.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'type': 'liquidation',
                            'price': round(liquidation_price, 4),
                            'amount': round(abs(position), 4),
                            'profit': round(-initial_capital, 2),
                            'balance': 0
                        })
                    
                    position = 0
                    position_type = None
                    equity_curve.append({'time': timestamp.strftime('%Y-%m-%d %H:%M'), 'value': capital})
                    continue
            
            # Record equity (unrealized PnL from close)
            if position_type == 'long':
                unrealized_pnl = (close - entry_price) * position
                total_value = capital + unrealized_pnl
            elif position_type == 'short':
                shares = abs(position)
                unrealized_pnl = (entry_price - close) * shares
                total_value = capital + unrealized_pnl
            else:
                total_value = capital
            
            if total_value < 0:
                total_value = 0
            
            equity_curve.append({
                'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                'value': round(total_value, 2)
            })
        
        # Force exit at backtest end
        if position != 0:
            timestamp = df.index[-1]
            final_close = df.iloc[-1]['close']
            
            if position > 0:  # Close long
                exec_price = final_close * (1 - slippage)
                commission_fee = position * exec_price * commission
                profit = (exec_price - entry_price) * position - commission_fee
                capital += profit
                total_commission_paid += commission_fee
                
                trades.append({
                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                    'type': 'close_long',
                    'price': round(exec_price, 4),
                    'amount': round(position, 4),
                    'profit': round(profit, 2),
                    'balance': round(max(0, capital), 2)
                })
            else:  # Close short
                exec_price = final_close * (1 + slippage)
                shares = abs(position)
                commission_fee = shares * exec_price * commission
                profit = (entry_price - exec_price) * shares - commission_fee
                
                if capital + profit <= 0:
                    logger.warning(f"Liquidation at backtest end!")
                    capital = 0
                    is_liquidated = True
                    trades.append({
                        'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                        'type': 'liquidation',
                        'price': round(exec_price, 4),
                        'amount': round(shares, 4),
                        'profit': round(-capital, 2),
                        'balance': 0
                    })
                else:
                    capital += profit
                    total_commission_paid += commission_fee
                    trades.append({
                        'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                        'type': 'close_short',
                        'price': round(exec_price, 4),
                        'amount': round(shares, 4),
                        'profit': round(profit, 2),
                        'balance': round(max(0, capital), 2)
                    })
            
            if equity_curve:
                equity_curve[-1]['value'] = round(capital, 2)
        
        return equity_curve, trades, total_commission_paid
    
    def _simulate_trading_old_format(
        self,
        df: pd.DataFrame,
        signals: pd.Series,
        initial_capital: float,
        commission: float,
        slippage: float,
        leverage: int = 1,
        trade_direction: str = 'long',
        strategy_config: Optional[Dict[str, Any]] = None
    ) -> tuple:
        """
        使用旧格式信号进行交易模拟（保持兼容性）
        """
        equity_curve = []
        trades = []
        total_commission_paid = 0  # Accumulated commission
        is_liquidated = False  # Liquidation flag
        liquidation_price = 0  # Liquidation price
        min_capital_to_trade = 1.0  # Below this balance, consider wiped out
        
        capital = initial_capital
        position = 0  # Positive=long, Negative=short
        entry_price = 0
        position_type = None  # 'long' or 'short'

        # Risk controls (also supported for legacy signals): SL / TP / trailing exit
        cfg = strategy_config or {}
        exec_cfg = cfg.get('execution') or {}
        # Signal confirmation / execution timing (legacy mode):
        # - bar_close: execute on the same bar close
        # - next_bar_open: execute on next bar open after signal is confirmed on bar close (recommended)
        signal_timing = str(exec_cfg.get('signalTiming') or 'next_bar_open').strip().lower()
        risk_cfg = cfg.get('risk') or {}
        stop_loss_pct = float(risk_cfg.get('stopLossPct') or 0.0)
        take_profit_pct = float(risk_cfg.get('takeProfitPct') or 0.0)
        trailing_cfg = risk_cfg.get('trailing') or {}
        trailing_enabled = bool(trailing_cfg.get('enabled'))
        trailing_pct = float(trailing_cfg.get('pct') or 0.0)
        trailing_activation_pct = float(trailing_cfg.get('activationPct') or 0.0)
        
        # Risk percentages are defined on margin PnL; convert to price move thresholds by leverage.
        lev = max(int(leverage or 1), 1)
        stop_loss_pct_eff = stop_loss_pct / lev
        take_profit_pct_eff = take_profit_pct / lev
        trailing_pct_eff = trailing_pct / lev
        trailing_activation_pct_eff = trailing_activation_pct / lev
        highest_since_entry = None
        lowest_since_entry = None

        # --- Position / scaling config (make old-format strategies support the same backtest modal features) ---
        pos_cfg = cfg.get('position') or {}
        entry_pct_cfg = float(pos_cfg.get('entryPct') if pos_cfg.get('entryPct') is not None else 1.0)  # expected 0~1
        # Accept both 0~1 and 0~100 inputs (some clients may send percent units).
        if entry_pct_cfg > 1:
            entry_pct_cfg = entry_pct_cfg / 100.0
        entry_pct_cfg = max(0.0, min(entry_pct_cfg, 1.0))

        scale_cfg = cfg.get('scale') or {}
        trend_add_cfg = scale_cfg.get('trendAdd') or {}
        dca_add_cfg = scale_cfg.get('dcaAdd') or {}
        trend_reduce_cfg = scale_cfg.get('trendReduce') or {}
        adverse_reduce_cfg = scale_cfg.get('adverseReduce') or {}

        trend_add_enabled = bool(trend_add_cfg.get('enabled'))
        trend_add_step_pct = float(trend_add_cfg.get('stepPct') or 0.0)
        trend_add_size_pct = float(trend_add_cfg.get('sizePct') or 0.0)
        trend_add_max_times = int(trend_add_cfg.get('maxTimes') or 0)

        dca_add_enabled = bool(dca_add_cfg.get('enabled'))
        dca_add_step_pct = float(dca_add_cfg.get('stepPct') or 0.0)
        dca_add_size_pct = float(dca_add_cfg.get('sizePct') or 0.0)
        dca_add_max_times = int(dca_add_cfg.get('maxTimes') or 0)

        trend_reduce_enabled = bool(trend_reduce_cfg.get('enabled'))
        trend_reduce_step_pct = float(trend_reduce_cfg.get('stepPct') or 0.0)
        trend_reduce_size_pct = float(trend_reduce_cfg.get('sizePct') or 0.0)
        trend_reduce_max_times = int(trend_reduce_cfg.get('maxTimes') or 0)

        adverse_reduce_enabled = bool(adverse_reduce_cfg.get('enabled'))
        adverse_reduce_step_pct = float(adverse_reduce_cfg.get('stepPct') or 0.0)
        adverse_reduce_size_pct = float(adverse_reduce_cfg.get('sizePct') or 0.0)
        adverse_reduce_max_times = int(adverse_reduce_cfg.get('maxTimes') or 0)

        # Trigger pct to price threshold with leverage
        trend_add_step_pct_eff = trend_add_step_pct / lev
        dca_add_step_pct_eff = dca_add_step_pct / lev
        trend_reduce_step_pct_eff = trend_reduce_step_pct / lev
        adverse_reduce_step_pct_eff = adverse_reduce_step_pct / lev

        # State for scaling
        trend_add_times = 0
        dca_add_times = 0
        trend_reduce_times = 0
        adverse_reduce_times = 0
        last_trend_add_anchor = None
        last_dca_add_anchor = None
        last_trend_reduce_anchor = None
        last_adverse_reduce_anchor = None
        
        # Apply execution timing to avoid look-ahead bias in legacy signals (buy/sell series):
        # If signal is computed on bar close, realistic execution is next bar open.
        signals_exec = signals
        if signal_timing in ['next_bar_open', 'next_open', 'nextopen', 'next']:
            try:
                signals_exec = signals.shift(1).fillna(0)
            except Exception:
                signals_exec = signals

        for i, (timestamp, row) in enumerate(df.iterrows()):
            # 爆仓后直接停止回测，输出结果
            if is_liquidated:
                break

            # If no position and balance low, stop trading
            if position == 0 and capital < min_capital_to_trade:
                is_liquidated = True
                capital = 0
                trades.append({
                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                    'type': 'liquidation',
                    'price': round(float(row.get('close', 0) or 0), 4),
                    'amount': 0,
                    'profit': round(-initial_capital, 2),
                    'balance': 0
                })
                equity_curve.append({'time': timestamp.strftime('%Y-%m-%d %H:%M'), 'value': 0})
                continue
            
            signal = signals_exec.iloc[i] if i < len(signals_exec) else 0
            high = row['high']
            low = row['low']
            price = row['close']
            open_ = row.get('open', price)

            # Forced exit (TP/SL/trailing) over signals
            if position != 0 and position_type in ['long', 'short']:
                if position_type == 'long' and position > 0:
                    if highest_since_entry is None:
                        highest_since_entry = entry_price
                    highest_since_entry = max(highest_since_entry, high)
                    candidates = []
                    if stop_loss_pct_eff > 0:
                        sl_price = entry_price * (1 - stop_loss_pct_eff)
                        if low <= sl_price:
                            candidates.append(('stop', sl_price))
                    if take_profit_pct_eff > 0:
                        tp_price = entry_price * (1 + take_profit_pct_eff)
                        if high >= tp_price:
                            candidates.append(('profit', tp_price))
                    if trailing_enabled and trailing_pct_eff > 0:
                        trail_active = True
                        if trailing_activation_pct_eff > 0:
                            trail_active = highest_since_entry >= entry_price * (1 + trailing_activation_pct_eff)
                        if trail_active:
                            tr_price = highest_since_entry * (1 - trailing_pct_eff)
                            if low <= tr_price:
                                candidates.append(('trailing', tr_price))
                    if candidates:
                        # SL > TrailingStop > TP
                        pri = {'stop': 0, 'trailing': 1, 'profit': 2}
                        reason, trigger_price = sorted(candidates, key=lambda x: (pri.get(x[0], 99), x[1]))[0]
                        exec_price = trigger_price * (1 - slippage)
                        commission_fee = position * exec_price * commission
                        # Entry commission deducted, only deduct exit commission
                        profit = (exec_price - entry_price) * position - commission_fee
                        capital += profit
                        total_commission_paid += commission_fee
                        trades.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'type': {'stop': 'close_long_stop', 'profit': 'close_long_profit', 'trailing': 'close_long_trailing'}.get(reason, 'close_long'),
                            'price': round(exec_price, 4),
                            'amount': round(position, 4),
                            'profit': round(profit, 2),
                            'balance': round(max(0, capital), 2)
                        })
                        position = 0
                        position_type = None
                        liquidation_price = 0
                        highest_since_entry = None
                        lowest_since_entry = None
                        equity_curve.append({'time': timestamp.strftime('%Y-%m-%d %H:%M'), 'value': round(capital, 2)})
                        continue

                if position_type == 'short' and position < 0:
                    shares = abs(position)
                    if lowest_since_entry is None:
                        lowest_since_entry = entry_price
                    lowest_since_entry = min(lowest_since_entry, low)
                    candidates = []
                    if stop_loss_pct_eff > 0:
                        sl_price = entry_price * (1 + stop_loss_pct_eff)
                        if high >= sl_price:
                            candidates.append(('stop', sl_price))
                    if take_profit_pct_eff > 0:
                        tp_price = entry_price * (1 - take_profit_pct_eff)
                        if low <= tp_price:
                            candidates.append(('profit', tp_price))
                    if trailing_enabled and trailing_pct_eff > 0:
                        trail_active = True
                        if trailing_activation_pct_eff > 0:
                            trail_active = lowest_since_entry <= entry_price * (1 - trailing_activation_pct_eff)
                        if trail_active:
                            tr_price = lowest_since_entry * (1 + trailing_pct_eff)
                            if high >= tr_price:
                                candidates.append(('trailing', tr_price))
                    if candidates:
                        # SL > TrailingStop > TP
                        pri = {'stop': 0, 'trailing': 1, 'profit': 2}
                        reason, trigger_price = sorted(candidates, key=lambda x: (pri.get(x[0], 99), -x[1]))[0]
                        exec_price = trigger_price * (1 + slippage)
                        commission_fee = shares * exec_price * commission
                        # Entry commission deducted, only deduct exit commission
                        profit = (entry_price - exec_price) * shares - commission_fee
                        if capital + profit <= 0:
                            capital = 0
                            is_liquidated = True
                            trades.append({
                                'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                'type': 'liquidation',
                                'price': round(exec_price, 4),
                                'amount': round(shares, 4),
                                'profit': round(-initial_capital, 2),
                                'balance': 0
                            })
                            position = 0
                            position_type = None
                            liquidation_price = 0
                            equity_curve.append({'time': timestamp.strftime('%Y-%m-%d %H:%M'), 'value': 0})
                            continue
                        capital += profit
                        total_commission_paid += commission_fee
                        trades.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'type': {'stop': 'close_short_stop', 'profit': 'close_short_profit', 'trailing': 'close_short_trailing'}.get(reason, 'close_short'),
                            'price': round(exec_price, 4),
                            'amount': round(shares, 4),
                            'profit': round(profit, 2),
                            'balance': round(max(0, capital), 2)
                        })
                        position = 0
                        position_type = None
                        liquidation_price = 0
                        highest_since_entry = None
                        lowest_since_entry = None
                        equity_curve.append({'time': timestamp.strftime('%Y-%m-%d %H:%M'), 'value': round(capital, 2)})
                        continue
            
            # --- Parameterized scaling rules (also for old-format strategies) ---
            # Note: old format only has buy/sell, but scaling params should work.
            # Trigger pct as post-leverage threshold.
            # IMPORTANT: if this candle has a main buy/sell signal, do NOT apply any scale-in/scale-out.
            if signal == 0 and position != 0 and position_type in ['long', 'short'] and capital >= min_capital_to_trade:
                # Long
                if position_type == 'long' and position > 0:
                    # Trend add（顺势加仓：上涨触发）
                    if trend_add_enabled and trend_add_step_pct_eff > 0 and trend_add_size_pct > 0 and (trend_add_max_times == 0 or trend_add_times < trend_add_max_times):
                        anchor = last_trend_add_anchor if last_trend_add_anchor is not None else entry_price
                        trigger = anchor * (1 + trend_add_step_pct_eff)
                        if high >= trigger:
                            order_pct = trend_add_size_pct
                            if order_pct > 0:
                                exec_price_add = trigger * (1 + slippage)
                                use_capital = capital * order_pct
                                shares_add = (use_capital * leverage) / exec_price_add
                                commission_fee = shares_add * exec_price_add * commission

                                total_cost_before = position * entry_price
                                total_cost_after = total_cost_before + shares_add * exec_price_add
                                position += shares_add
                                entry_price = total_cost_after / position

                                capital -= commission_fee
                                total_commission_paid += commission_fee
                                liquidation_price = entry_price * (1 - 1.0 / leverage)

                                trend_add_times += 1
                                last_trend_add_anchor = trigger

                                trades.append({
                                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                    'type': 'add_long',
                                    'price': round(exec_price_add, 4),
                                    'amount': round(shares_add, 4),
                                    'profit': 0,
                                    'balance': round(max(0, capital), 2)
                                })

                    # DCA add（逆势加仓：下跌触发）
                    if dca_add_enabled and dca_add_step_pct_eff > 0 and dca_add_size_pct > 0 and (dca_add_max_times == 0 or dca_add_times < dca_add_max_times):
                        anchor = last_dca_add_anchor if last_dca_add_anchor is not None else entry_price
                        trigger = anchor * (1 - dca_add_step_pct_eff)
                        if low <= trigger:
                            order_pct = dca_add_size_pct
                            if order_pct > 0:
                                exec_price_add = trigger * (1 + slippage)
                                use_capital = capital * order_pct
                                shares_add = (use_capital * leverage) / exec_price_add
                                commission_fee = shares_add * exec_price_add * commission

                                total_cost_before = position * entry_price
                                total_cost_after = total_cost_before + shares_add * exec_price_add
                                position += shares_add
                                entry_price = total_cost_after / position

                                capital -= commission_fee
                                total_commission_paid += commission_fee
                                liquidation_price = entry_price * (1 - 1.0 / leverage)

                                dca_add_times += 1
                                last_dca_add_anchor = trigger

                                trades.append({
                                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                    'type': 'add_long',
                                    'price': round(exec_price_add, 4),
                                    'amount': round(shares_add, 4),
                                    'profit': 0,
                                    'balance': round(max(0, capital), 2)
                                })

                    # Trend reduce（顺势减仓：上涨触发）
                    if trend_reduce_enabled and trend_reduce_step_pct_eff > 0 and trend_reduce_size_pct > 0 and (trend_reduce_max_times == 0 or trend_reduce_times < trend_reduce_max_times):
                        anchor = last_trend_reduce_anchor if last_trend_reduce_anchor is not None else entry_price
                        trigger = anchor * (1 + trend_reduce_step_pct_eff)
                        if high >= trigger:
                            reduce_pct = max(trend_reduce_size_pct, 0.0)
                            reduce_shares = position * reduce_pct
                            if reduce_shares > 0:
                                exec_price_reduce = trigger * (1 - slippage)
                                commission_fee = reduce_shares * exec_price_reduce * commission
                                profit = (exec_price_reduce - entry_price) * reduce_shares - commission_fee
                                capital += profit
                                total_commission_paid += commission_fee
                                position -= reduce_shares
                                if position <= 1e-12:
                                    position = 0
                                    position_type = None
                                    liquidation_price = 0
                                    last_trend_add_anchor = last_dca_add_anchor = last_trend_reduce_anchor = last_adverse_reduce_anchor = None
                                    trend_add_times = dca_add_times = trend_reduce_times = adverse_reduce_times = 0
                                else:
                                    liquidation_price = entry_price * (1 - 1.0 / leverage)

                                trend_reduce_times += 1
                                last_trend_reduce_anchor = trigger

                                trades.append({
                                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                    'type': 'reduce_long',
                                    'price': round(exec_price_reduce, 4),
                                    'amount': round(reduce_shares, 4),
                                    'profit': round(profit, 2),
                                    'balance': round(max(0, capital), 2)
                                })

                    # Adverse reduce（逆势减仓：下跌触发）
                    if position_type == 'long' and position > 0 and adverse_reduce_enabled and adverse_reduce_step_pct_eff > 0 and adverse_reduce_size_pct > 0 and (adverse_reduce_max_times == 0 or adverse_reduce_times < adverse_reduce_max_times):
                        anchor = last_adverse_reduce_anchor if last_adverse_reduce_anchor is not None else entry_price
                        trigger = anchor * (1 - adverse_reduce_step_pct_eff)
                        if low <= trigger:
                            reduce_pct = max(adverse_reduce_size_pct, 0.0)
                            reduce_shares = position * reduce_pct
                            if reduce_shares > 0:
                                exec_price_reduce = trigger * (1 - slippage)
                                commission_fee = reduce_shares * exec_price_reduce * commission
                                profit = (exec_price_reduce - entry_price) * reduce_shares - commission_fee
                                capital += profit
                                total_commission_paid += commission_fee
                                position -= reduce_shares
                                if position <= 1e-12:
                                    position = 0
                                    position_type = None
                                    liquidation_price = 0
                                    last_trend_add_anchor = last_dca_add_anchor = last_trend_reduce_anchor = last_adverse_reduce_anchor = None
                                    trend_add_times = dca_add_times = trend_reduce_times = adverse_reduce_times = 0
                                else:
                                    liquidation_price = entry_price * (1 - 1.0 / leverage)

                                adverse_reduce_times += 1
                                last_adverse_reduce_anchor = trigger

                                trades.append({
                                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                    'type': 'reduce_long',
                                    'price': round(exec_price_reduce, 4),
                                    'amount': round(reduce_shares, 4),
                                    'profit': round(profit, 2),
                                    'balance': round(max(0, capital), 2)
                                })

                # Short
                if position_type == 'short' and position < 0:
                    shares_total = abs(position)

                    # Trend add（顺势加空：下跌触发）
                    if trend_add_enabled and trend_add_step_pct_eff > 0 and trend_add_size_pct > 0 and (trend_add_max_times == 0 or trend_add_times < trend_add_max_times):
                        anchor = last_trend_add_anchor if last_trend_add_anchor is not None else entry_price
                        trigger = anchor * (1 - trend_add_step_pct_eff)
                        if low <= trigger:
                            order_pct = trend_add_size_pct
                            if order_pct > 0:
                                exec_price_add = trigger * (1 - slippage)
                                use_capital = capital * order_pct
                                shares_add = (use_capital * leverage) / exec_price_add
                                commission_fee = shares_add * exec_price_add * commission

                                total_cost_before = shares_total * entry_price
                                total_cost_after = total_cost_before + shares_add * exec_price_add
                                position -= shares_add
                                shares_total = abs(position)
                                entry_price = total_cost_after / shares_total

                                capital -= commission_fee
                                total_commission_paid += commission_fee
                                liquidation_price = entry_price * (1 + 1.0 / leverage)

                                trend_add_times += 1
                                last_trend_add_anchor = trigger

                                trades.append({
                                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                    'type': 'add_short',
                                    'price': round(exec_price_add, 4),
                                    'amount': round(shares_add, 4),
                                    'profit': 0,
                                    'balance': round(max(0, capital), 2)
                                })

                    # DCA add（逆势加空：上涨触发）
                    if dca_add_enabled and dca_add_step_pct_eff > 0 and dca_add_size_pct > 0 and (dca_add_max_times == 0 or dca_add_times < dca_add_max_times):
                        anchor = last_dca_add_anchor if last_dca_add_anchor is not None else entry_price
                        trigger = anchor * (1 + dca_add_step_pct_eff)
                        if high >= trigger:
                            order_pct = dca_add_size_pct
                            if order_pct > 0:
                                exec_price_add = trigger * (1 - slippage)
                                use_capital = capital * order_pct
                                shares_add = (use_capital * leverage) / exec_price_add
                                commission_fee = shares_add * exec_price_add * commission

                                total_cost_before = shares_total * entry_price
                                total_cost_after = total_cost_before + shares_add * exec_price_add
                                position -= shares_add
                                shares_total = abs(position)
                                entry_price = total_cost_after / shares_total

                                capital -= commission_fee
                                total_commission_paid += commission_fee
                                liquidation_price = entry_price * (1 + 1.0 / leverage)

                                dca_add_times += 1
                                last_dca_add_anchor = trigger

                                trades.append({
                                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                    'type': 'add_short',
                                    'price': round(exec_price_add, 4),
                                    'amount': round(shares_add, 4),
                                    'profit': 0,
                                    'balance': round(max(0, capital), 2)
                                })

                    # Trend reduce（顺势减空：下跌触发，回补一部分）
                    if trend_reduce_enabled and trend_reduce_step_pct_eff > 0 and trend_reduce_size_pct > 0 and (trend_reduce_max_times == 0 or trend_reduce_times < trend_reduce_max_times):
                        anchor = last_trend_reduce_anchor if last_trend_reduce_anchor is not None else entry_price
                        trigger = anchor * (1 - trend_reduce_step_pct_eff)
                        if low <= trigger:
                            reduce_pct = max(trend_reduce_size_pct, 0.0)
                            reduce_shares = shares_total * reduce_pct
                            if reduce_shares > 0:
                                exec_price_reduce = trigger * (1 + slippage)
                                commission_fee = reduce_shares * exec_price_reduce * commission
                                profit = (entry_price - exec_price_reduce) * reduce_shares - commission_fee
                                capital += profit
                                total_commission_paid += commission_fee
                                position += reduce_shares
                                shares_total = abs(position)
                                if shares_total <= 1e-12:
                                    position = 0
                                    position_type = None
                                    liquidation_price = 0
                                    last_trend_add_anchor = last_dca_add_anchor = last_trend_reduce_anchor = last_adverse_reduce_anchor = None
                                    trend_add_times = dca_add_times = trend_reduce_times = adverse_reduce_times = 0
                                else:
                                    liquidation_price = entry_price * (1 + 1.0 / leverage)

                                trend_reduce_times += 1
                                last_trend_reduce_anchor = trigger

                                trades.append({
                                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                    'type': 'reduce_short',
                                    'price': round(exec_price_reduce, 4),
                                    'amount': round(reduce_shares, 4),
                                    'profit': round(profit, 2),
                                    'balance': round(max(0, capital), 2)
                                })

                    # Adverse reduce（逆势减空：上涨触发）
                    if position_type == 'short' and position < 0 and adverse_reduce_enabled and adverse_reduce_step_pct_eff > 0 and adverse_reduce_size_pct > 0 and (adverse_reduce_max_times == 0 or adverse_reduce_times < adverse_reduce_max_times):
                        anchor = last_adverse_reduce_anchor if last_adverse_reduce_anchor is not None else entry_price
                        trigger = anchor * (1 + adverse_reduce_step_pct_eff)
                        if high >= trigger:
                            reduce_pct = max(adverse_reduce_size_pct, 0.0)
                            reduce_shares = shares_total * reduce_pct
                            if reduce_shares > 0:
                                exec_price_reduce = trigger * (1 + slippage)
                                commission_fee = reduce_shares * exec_price_reduce * commission
                                profit = (entry_price - exec_price_reduce) * reduce_shares - commission_fee
                                capital += profit
                                total_commission_paid += commission_fee
                                position += reduce_shares
                                shares_total = abs(position)
                                if shares_total <= 1e-12:
                                    position = 0
                                    position_type = None
                                    liquidation_price = 0
                                    last_trend_add_anchor = last_dca_add_anchor = last_trend_reduce_anchor = last_adverse_reduce_anchor = None
                                    trend_add_times = dca_add_times = trend_reduce_times = adverse_reduce_times = 0
                                else:
                                    liquidation_price = entry_price * (1 + 1.0 / leverage)

                                adverse_reduce_times += 1
                                last_adverse_reduce_anchor = trigger

                                trades.append({
                                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                                    'type': 'reduce_short',
                                    'price': round(exec_price_reduce, 4),
                                    'amount': round(reduce_shares, 4),
                                    'profit': round(profit, 2),
                                    'balance': round(max(0, capital), 2)
                                })

            # Handle different trade directions
            if trade_direction == 'long':
                # Long only mode
                if signal == 1 and position == 0 and capital >= min_capital_to_trade:  # Buy to open long
                    logger.debug(f"[Long mode] Buy to open long: time={timestamp}, price={price}, leverage={leverage}x")
                    base_price = open_ if signal_timing in ['next_bar_open', 'next_open', 'nextopen', 'next'] else price
                    exec_price = base_price * (1 + slippage)
                    # With leverage: position = capital * leverage / price
                    # Use specified pct (entryPct preferred; else full)
                    position_pct = None
                    if entry_pct_cfg is not None and entry_pct_cfg > 0:
                        position_pct = entry_pct_cfg
                    if position_pct is not None and 0 < position_pct < 1:
                        use_capital = capital * position_pct
                        shares = (use_capital * leverage) / exec_price
                    else:
                        shares = (capital * leverage) / exec_price
                    # Margin (commission from capital)
                    margin = capital
                    commission_fee = shares * exec_price * commission
                    
                    position = shares
                    entry_price = exec_price
                    position_type = 'long'
                    capital -= commission_fee  # Only deduct commission
                    total_commission_paid += commission_fee
                    
                    # Long liquidation when price drops to entry * (1 - 1/leverage)
                    liquidation_price = entry_price * (1 - 1.0 / leverage)
                    logger.debug(f"Long liquidation price: {liquidation_price:.2f}")

                    # init scaling anchors
                    last_trend_add_anchor = entry_price
                    last_dca_add_anchor = entry_price
                    last_trend_reduce_anchor = entry_price
                    last_adverse_reduce_anchor = entry_price
                    
                    trades.append({
                        'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                        'type': 'open_long',
                        'price': round(exec_price, 4),
                        'amount': round(shares, 4),
                        'profit': 0,
                        'balance': round(max(0, capital), 2)
                    })
                
                elif signal == -1 and position > 0:  # Sell to close long
                    logger.debug(f"[Long mode] Sell to close long: time={timestamp}, price={price}")
                    base_price = open_ if signal_timing in ['next_bar_open', 'next_open', 'nextopen', 'next'] else price
                    exec_price = base_price * (1 - slippage)
                    # PnL = (exit - entry) * shares - commission
                    commission_fee = position * exec_price * commission
                    profit = (exec_price - entry_price) * position - commission_fee
                    capital += profit
                    total_commission_paid += commission_fee
                    liquidation_price = 0  # Clear liquidation price
                    
                    trades.append({
                        'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                        'type': 'close_long',
                        'price': round(exec_price, 4),
                        'amount': round(position, 4),
                        'profit': round(profit, 2),
                        'balance': round(max(0, capital), 2)
                    })
                    
                    position = 0
                    position_type = None
                    last_trend_add_anchor = last_dca_add_anchor = last_trend_reduce_anchor = last_adverse_reduce_anchor = None
                    trend_add_times = dca_add_times = trend_reduce_times = adverse_reduce_times = 0
                    if capital < min_capital_to_trade:
                        is_liquidated = True
                        capital = 0
                        trades.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'type': 'liquidation',
                            'price': round(exec_price, 4),
                            'amount': 0,
                            'profit': round(-initial_capital, 2),
                            'balance': 0
                        })
            
            elif trade_direction == 'short':
                # Short only mode
                if signal == -1 and position == 0 and capital >= min_capital_to_trade:  # Sell to open short
                    logger.debug(f"[Short mode] Sell to open short: time={timestamp}, price={price}, leverage={leverage}x")
                    base_price = open_ if signal_timing in ['next_bar_open', 'next_open', 'nextopen', 'next'] else price
                    exec_price = base_price * (1 - slippage)
                    # With leverage: position = capital * leverage / price
                    position_pct = None
                    if entry_pct_cfg is not None and entry_pct_cfg > 0:
                        position_pct = entry_pct_cfg
                    if position_pct is not None and 0 < position_pct < 1:
                        use_capital = capital * position_pct
                        shares = (use_capital * leverage) / exec_price
                    else:
                        shares = (capital * leverage) / exec_price
                    commission_fee = shares * exec_price * commission
                    
                    position = -shares  # Negative = short (owe shares)
                    entry_price = exec_price
                    position_type = 'short'
                    capital -= commission_fee  # Only deduct commission
                    total_commission_paid += commission_fee
                    
                    # Short liquidation when price rises to entry * (1 + 1/leverage)
                    liquidation_price = entry_price * (1 + 1.0 / leverage)
                    logger.debug(f"Short liquidation price: {liquidation_price:.2f}")

                    last_trend_add_anchor = entry_price
                    last_dca_add_anchor = entry_price
                    last_trend_reduce_anchor = entry_price
                    last_adverse_reduce_anchor = entry_price
                    
                    trades.append({
                        'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                        'type': 'open_short',
                        'price': round(exec_price, 4),
                        'amount': round(shares, 4),
                        'profit': 0,
                        'balance': round(max(0, capital), 2)
                    })
                
                elif signal == 1 and position < 0:  # Buy to close short
                    logger.debug(f"[Short mode] Buy to close short: time={timestamp}, price={price}")
                    base_price = open_ if signal_timing in ['next_bar_open', 'next_open', 'nextopen', 'next'] else price
                    exec_price = base_price * (1 + slippage)
                    shares = abs(position)  # Shares to buy back
                    # PnL = (entry - exit) * shares - commission
                    commission_fee = shares * exec_price * commission
                    profit = (entry_price - exec_price) * shares - commission_fee
                    
                    # Check for liquidation
                    if capital + profit <= 0:
                        logger.warning(f"Insufficient funds when closing short - liquidation: capital={capital:.2f}, loss={-profit:.2f}")
                        capital = 0
                        is_liquidated = True
                        trades.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'type': 'liquidation',
                            'price': round(exec_price, 4),
                            'amount': round(shares, 4),
                            'profit': round(-capital, 2),
                            'balance': 0
                        })
                    else:
                        capital += profit
                        total_commission_paid += commission_fee
                        
                        trades.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'type': 'close_short',
                            'price': round(exec_price, 4),
                            'amount': round(shares, 4),
                            'profit': round(profit, 2),
                            'balance': round(max(0, capital), 2)
                        })
                    
                    position = 0
                    position_type = None
                    liquidation_price = 0  # Clear liquidation price
                    last_trend_add_anchor = last_dca_add_anchor = last_trend_reduce_anchor = last_adverse_reduce_anchor = None
                    trend_add_times = dca_add_times = trend_reduce_times = adverse_reduce_times = 0
                    if capital < min_capital_to_trade and not is_liquidated:
                        is_liquidated = True
                        capital = 0
                        trades.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'type': 'liquidation',
                            'price': round(exec_price, 4),
                            'amount': 0,
                            'profit': round(-initial_capital, 2),
                            'balance': 0
                        })
            
            elif trade_direction == 'both':
                # Both directions mode
                if signal == 1 and position == 0 and capital >= min_capital_to_trade:  # Buy to open long
                    logger.debug(f"[Both mode] Buy to open long: time={timestamp}, price={price}, leverage={leverage}x")
                    base_price = open_ if signal_timing in ['next_bar_open', 'next_open', 'nextopen', 'next'] else price
                    exec_price = base_price * (1 + slippage)
                    # With leverage: position = capital * leverage / price
                    position_pct = None
                    if entry_pct_cfg is not None and entry_pct_cfg > 0:
                        position_pct = entry_pct_cfg
                    if position_pct is not None and 0 < position_pct < 1:
                        use_capital = capital * position_pct
                        shares = (use_capital * leverage) / exec_price
                    else:
                        shares = (capital * leverage) / exec_price
                    commission_fee = shares * exec_price * commission
                    
                    position = shares
                    entry_price = exec_price
                    position_type = 'long'
                    capital -= commission_fee  # Only deduct commission
                    total_commission_paid += commission_fee
                    
                    # Calculate liquidation price
                    liquidation_price = entry_price * (1 - 1.0 / leverage)
                    logger.debug(f"Long liquidation price: {liquidation_price:.2f}")

                    last_trend_add_anchor = entry_price
                    last_dca_add_anchor = entry_price
                    last_trend_reduce_anchor = entry_price
                    last_adverse_reduce_anchor = entry_price
                    
                    trades.append({
                        'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                        'type': 'open_long',
                        'price': round(exec_price, 4),
                        'amount': round(shares, 4),
                        'profit': 0,
                        'balance': round(max(0, capital), 2)
                    })
                
                elif signal == -1 and position == 0 and capital >= min_capital_to_trade:  # Sell to open short
                    logger.debug(f"[Both mode] Sell to open short: time={timestamp}, price={price}, leverage={leverage}x")
                    base_price = open_ if signal_timing in ['next_bar_open', 'next_open', 'nextopen', 'next'] else price
                    exec_price = base_price * (1 - slippage)
                    # With leverage: position = capital * leverage / price
                    position_pct = None
                    if entry_pct_cfg is not None and entry_pct_cfg > 0:
                        position_pct = entry_pct_cfg
                    if position_pct is not None and 0 < position_pct < 1:
                        use_capital = capital * position_pct
                        shares = (use_capital * leverage) / exec_price
                    else:
                        shares = (capital * leverage) / exec_price
                    commission_fee = shares * exec_price * commission
                    
                    position = -shares
                    entry_price = exec_price
                    position_type = 'short'
                    capital -= commission_fee
                    total_commission_paid += commission_fee
                    
                    # Calculate liquidation price
                    liquidation_price = entry_price * (1 + 1.0 / leverage)
                    logger.debug(f"Short liquidation price: {liquidation_price:.2f}")

                    last_trend_add_anchor = entry_price
                    last_dca_add_anchor = entry_price
                    last_trend_reduce_anchor = entry_price
                    last_adverse_reduce_anchor = entry_price

                    trades.append({
                        'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                        'type': 'open_short',
                        'price': round(exec_price, 4),
                        'amount': round(shares, 4),
                        'profit': 0,
                        'balance': round(max(0, capital), 2)
                    })
                
                elif signal == -1 and position > 0:  # Close long open short
                    logger.debug(f"[Both mode] Close long open short: time={timestamp}, price={price}")
                    # First close long
                    base_price = open_ if signal_timing in ['next_bar_open', 'next_open', 'nextopen', 'next'] else price
                    exec_price = base_price * (1 - slippage)
                    commission_fee_close = position * exec_price * commission
                    profit = (exec_price - entry_price) * position - commission_fee_close
                    capital += profit
                    total_commission_paid += commission_fee_close
                    
                    trades.append({
                        'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                        'type': 'close_long',
                        'price': round(exec_price, 4),
                        'amount': round(position, 4),
                        'profit': round(profit, 2),
                        'balance': round(max(0, capital), 2)
                    })
                    
                    # Stop if balance too low after exit
                    if capital < min_capital_to_trade or is_liquidated:
                        is_liquidated = True
                        capital = 0
                        trades.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'type': 'liquidation',
                            'price': round(exec_price, 4),
                            'amount': 0,
                            'profit': round(-initial_capital, 2),
                            'balance': 0
                        })
                        continue

                    # Re-open short (respects entryPct; default entryPct=100%)
                    position_pct = None
                    if entry_pct_cfg is not None and entry_pct_cfg > 0:
                        position_pct = entry_pct_cfg
                    if position_pct is not None and 0 < position_pct < 1:
                        use_capital = capital * position_pct
                        shares = (use_capital * leverage) / exec_price
                    else:
                        shares = (capital * leverage) / exec_price
                    commission_fee_open = shares * exec_price * commission
                    
                    position = -shares
                    entry_price = exec_price
                    position_type = 'short'
                    capital -= commission_fee_open
                    total_commission_paid += commission_fee_open
                    
                    # Calculate liquidation price
                    liquidation_price = entry_price * (1 + 1.0 / leverage)
                    logger.debug(f"Short liquidation price: {liquidation_price:.2f}")
                    
                    trades.append({
                        'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                        'type': 'open_short',
                        'price': round(exec_price, 4),
                        'amount': round(shares, 4),
                        'profit': 0,
                        'balance': round(max(0, capital), 2)
                    })
                
                elif signal == 1 and position < 0:  # Close short open long
                    logger.debug(f"[Both mode] Close short open long: time={timestamp}, price={price}")
                    # First close short
                    base_price = open_ if signal_timing in ['next_bar_open', 'next_open', 'nextopen', 'next'] else price
                    exec_price = base_price * (1 + slippage)
                    shares = abs(position)
                    commission_fee_close = shares * exec_price * commission
                    profit = (entry_price - exec_price) * shares - commission_fee_close
                    
                    # Check for liquidation
                    if capital + profit <= 0:
                        logger.warning(f"Insufficient funds when closing short - liquidation: capital={capital:.2f}, loss={-profit:.2f}")
                        capital = 0
                        is_liquidated = True
                        trades.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'type': 'liquidation',
                            'price': round(exec_price, 4),
                            'amount': round(shares, 4),
                            'profit': round(-capital, 2),
                            'balance': 0
                        })
                        position = 0
                        position_type = None
                        continue  # No new positions after liquidation
                    
                    capital += profit
                    total_commission_paid += commission_fee_close
                    
                    trades.append({
                        'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                        'type': 'close_short',
                        'price': round(exec_price, 4),
                        'amount': round(shares, 4),
                        'profit': round(profit, 2),
                        'balance': round(max(0, capital), 2)
                    })
                    
                    if capital < min_capital_to_trade or is_liquidated:
                        is_liquidated = True
                        capital = 0
                        trades.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'type': 'liquidation',
                            'price': round(exec_price, 4),
                            'amount': 0,
                            'profit': round(-initial_capital, 2),
                            'balance': 0
                        })
                        continue

                    # Re-open long (respects entryPct; default entryPct=100%)
                    position_pct = None
                    if entry_pct_cfg is not None and entry_pct_cfg > 0:
                        position_pct = entry_pct_cfg
                    if position_pct is not None and 0 < position_pct < 1:
                        use_capital = capital * position_pct
                        shares = (use_capital * leverage) / exec_price
                    else:
                        shares = (capital * leverage) / exec_price
                    commission_fee_open = shares * exec_price * commission
                    
                    position = shares
                    entry_price = exec_price
                    position_type = 'long'
                    capital -= commission_fee_open
                    total_commission_paid += commission_fee_open
                    
                    # Calculate liquidation price
                    liquidation_price = entry_price * (1 - 1.0 / leverage)
                    logger.debug(f"Long liquidation price: {liquidation_price:.2f}")
                    
                    trades.append({
                        'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                        'type': 'open_long',
                        'price': round(exec_price, 4),
                        'amount': round(shares, 4),
                        'profit': 0,
                        'balance': round(max(0, capital), 2)
                    })
            
            # Check if liquidation hit (safety net, only when no active exit)
            # Note: check after all signals, SL/TP takes priority
            if position != 0 and not is_liquidated:
                if position_type == 'long':
                    # Long爆仓：价格跌破爆仓线
                    if price <= liquidation_price:
                        logger.warning(f"Long liquidation! entry={entry_price:.2f}, current={price:.2f}, liq_price={liquidation_price:.2f}")
                        is_liquidated = True
                        capital = 0
                        trades.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'type': 'liquidation',
                            'price': round(liquidation_price, 4),
                            'amount': round(abs(position), 4),
                            'profit': round(-initial_capital, 2),
                            'balance': 0
                        })
                        position = 0
                        position_type = None
                        equity_curve.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'value': 0
                        })
                        continue
                elif position_type == 'short':
                    # Short爆仓：价格涨破爆仓线
                    if price >= liquidation_price:
                        logger.warning(f"Short liquidation! entry={entry_price:.2f}, current={price:.2f}, liq_price={liquidation_price:.2f}")
                        is_liquidated = True
                        capital = 0
                        trades.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'type': 'liquidation',
                            'price': round(liquidation_price, 4),
                            'amount': round(abs(position), 4),
                            'profit': round(-initial_capital, 2),
                            'balance': 0
                        })
                        position = 0
                        position_type = None
                        equity_curve.append({
                            'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                            'value': 0
                        })
                        continue
            
            # Record equity
            if position_type == 'long':
                # Long equity = cash + unrealized PnL
                # Unrealized PnL = (current - entry) * shares
                unrealized_pnl = (price - entry_price) * position
                total_value = capital + unrealized_pnl
            elif position_type == 'short':
                # Short equity = cash + unrealized PnL
                # Unrealized PnL = (entry - current) * shares
                shares = abs(position)
                unrealized_pnl = (entry_price - price) * shares
                total_value = capital + unrealized_pnl
            else:
                total_value = capital
            
            # Ensure equity is not negative (liquidation already handled)
            if total_value < 0:
                total_value = 0
            
            equity_curve.append({
                'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                'value': round(total_value, 2)
            })
        
        # Force exit at backtest end
        if position != 0:
            timestamp = df.index[-1]
            price = df.iloc[-1]['close']
            
            if position > 0:  # Close long
                exec_price = price * (1 - slippage)
                commission_fee = position * exec_price * commission
                profit = (exec_price - entry_price) * position - commission_fee
                capital += profit
                total_commission_paid += commission_fee
                
                # Record close long trade
                trades.append({
                    'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                    'type': 'close_long',
                    'price': round(exec_price, 4),
                    'amount': round(position, 4),
                    'profit': round(profit, 2),
                    'balance': round(max(0, capital), 2)
                })
            else:  # Close short
                exec_price = price * (1 + slippage)
                shares = abs(position)
                commission_fee = shares * exec_price * commission
                profit = (entry_price - exec_price) * shares - commission_fee
                
                # Check for liquidation
                if capital + profit <= 0:
                    logger.warning(f"Liquidation at backtest end! Close short loss too large: capital={capital:.2f}, loss={-profit:.2f}")
                    is_liquidated = True
                    trades.append({
                        'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                        'type': 'liquidation',
                        'price': round(exec_price, 4),
                        'amount': round(shares, 4),
                        'profit': round(-capital, 2),
                        'balance': 0
                    })
                    capital = 0
                else:
                    capital += profit
                    total_commission_paid += commission_fee
                    
                    # Record close short trade
                    trades.append({
                        'time': timestamp.strftime('%Y-%m-%d %H:%M'),
                        'type': 'close_short',
                        'price': round(exec_price, 4),
                        'amount': round(shares, 4),
                        'profit': round(profit, 2),
                        'balance': round(max(0, capital), 2)
                    })
            
            # Update last equity curve value with capital after forced exit
            if equity_curve:
                equity_curve[-1]['value'] = round(capital, 2)
        
        return equity_curve, trades, total_commission_paid
    
    def _calculate_metrics(
        self,
        equity_curve: List,
        trades: List,
        initial_capital: float,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        total_commission: float = 0
    ) -> Dict:
        """计算回测指标"""
        if not equity_curve:
            return {}
        
        final_value = equity_curve[-1]['value']
        total_return = (final_value - initial_capital) / initial_capital * 100
        
        # Calculate annualized return: simple, not compound
        # For high-return strategies, compound annualization produces unrealistic numbers
        actual_days = (end_date - start_date).total_seconds() / 86400
        years = actual_days / 365.0
        
        # Simple annualization: annualized return = total return / years
        if years > 0:
            annual_return = total_return / years
        else:
            annual_return = 0
        
        # Calculate max drawdown
        values = [e['value'] for e in equity_curve]
        max_drawdown = self._calculate_max_drawdown(values)
        
        # Calculate Sharpe ratio
        sharpe = self._calculate_sharpe(values, timeframe)
        
        # Calculate total PnL: final equity - initial capital (most accurate)
        total_profit = final_value - initial_capital
        
        # Calculate win rate (all exit trades)
        # Exit trades: trades with profit != 0
        closing_trades = [t for t in trades if t.get('profit', 0) != 0]
        win_trades = [t for t in closing_trades if t['profit'] > 0]
        loss_trades = [t for t in closing_trades if t['profit'] < 0]
        total_trades = len(closing_trades)
        win_rate = len(win_trades) / total_trades * 100 if total_trades > 0 else 0
        
        # Calculate profit factor (= total profit / total loss)
        total_wins = sum(t['profit'] for t in win_trades)
        total_losses = abs(sum(t['profit'] for t in loss_trades))
        profit_factor = total_wins / total_losses if total_losses > 0 else (total_wins if total_wins > 0 else 0)
        
        return {
            'totalReturn': round(total_return, 2),
            'annualReturn': round(annual_return, 2),
            'maxDrawdown': round(max_drawdown, 2),
            'sharpeRatio': round(sharpe, 2),
            'winRate': round(win_rate, 2),
            'profitFactor': round(profit_factor, 2),
            'totalTrades': total_trades,
            'totalProfit': round(total_profit, 2),
            'totalCommission': round(total_commission, 2)
        }
    
    def _calculate_max_drawdown(self, values: List[float]) -> float:
        """计算最大回撤"""
        if not values:
            return 0
        
        peak = values[0]
        max_dd = 0
        
        for value in values:
            if value > peak:
                peak = value
            dd = (peak - value) / peak * 100
            if dd > max_dd:
                max_dd = dd
        
        return -max_dd
    
    def _calculate_sharpe(self, values: List[float], timeframe: str = '1D', risk_free_rate: float = 0.02) -> float:
        """
        计算夏普比率
        
        Args:
            values: 权益曲线数值列表
            timeframe: 时间周期
            risk_free_rate: 无风险收益率（年化）
        """
        if len(values) < 2:
            return 0
        
        # Filter out zero values (post-liquidation data), avoid division by 0
        valid_values = [v for v in values if v > 0]
        if len(valid_values) < 2:
            return 0
        
        # Determine annualization factor by timeframe
        annualization_factor = {
            '1m': 252 * 24 * 60,      # 1m candle: ~362,880
            '5m': 252 * 24 * 12,      # 5分钟K：约72,576
            '15m': 252 * 24 * 4,      # 15分钟K：约24,192
            '30m': 252 * 24 * 2,      # 30分钟K：约12,096
            '1H': 252 * 24,           # 1H candle: 6,048
            '4H': 252 * 6,            # 4小时K：1,512
            '1D': 252,                # 1D candle: 252
            '1W': 52                  # 1W candle: 52
        }.get(timeframe, 252)
        
        try:
            # Calculate period returns
            returns = np.diff(valid_values) / valid_values[:-1]
            
            # Filter invalid values
            returns = returns[np.isfinite(returns)]
            if len(returns) == 0:
                return 0
            
            # Annualized mean return
            avg_return = np.mean(returns) * annualization_factor
            
            # Annualized std (volatility)
            std_return = np.std(returns) * np.sqrt(annualization_factor)
            
            if std_return == 0 or not np.isfinite(std_return):
                return 0
            
            # Sharpe ratio = (annualized return - risk-free rate) / annualized volatility
            sharpe = (avg_return - risk_free_rate) / std_return
            return sharpe if np.isfinite(sharpe) else 0
        except Exception as e:
            logger.warning(f"Sharpe ratio calculation failed: {e}")
            return 0
    
    def _format_result(
        self,
        metrics: Dict,
        equity_curve: List,
        trades: List
    ) -> Dict[str, Any]:
        """格式化回测结果"""
        # Simplify equity curve
        max_points = 500
        if len(equity_curve) > max_points:
            step = len(equity_curve) // max_points
            equity_curve = equity_curve[::step]
        
        # Clean NaN/Inf values for JSON serialization
        def clean_value(value):
            """清理数值，将NaN/Inf转换为0"""
            if isinstance(value, float):
                if np.isnan(value) or np.isinf(value):
                    return 0
            return value
        
        # Clean metrics
        cleaned_metrics = {}
        for key, value in metrics.items():
            cleaned_metrics[key] = clean_value(value)
        
        # Clean equity_curve
        cleaned_curve = []
        for item in equity_curve:
            cleaned_curve.append({
                'time': item['time'],
                'value': clean_value(item['value'])
            })
        
        # Clean trades
        cleaned_trades = []
        # Don't truncate trades: return all (frontend can paginate)
        for trade in trades:
            cleaned_trade = {}
            for key, value in trade.items():
                cleaned_trade[key] = clean_value(value)
            cleaned_trades.append(cleaned_trade)
        
        return {
            **cleaned_metrics,
            'equityCurve': cleaned_curve,
            'trades': cleaned_trades
        }

