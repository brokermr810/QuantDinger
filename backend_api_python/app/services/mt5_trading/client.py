"""
MetaTrader 5 Trading Client

Uses official MetaTrader5 Python library to connect to MT5 terminal for trading.
Note: Requires Windows platform and MT5 terminal installed.
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import datetime

from app.utils.logger import get_logger
from app.services.mt5_trading.symbols import normalize_symbol, parse_symbol

logger = get_logger(__name__)

# Lazy import MetaTrader5 to allow other features to work without it installed
mt5 = None


def _ensure_mt5():
    """Ensure MetaTrader5 is imported."""
    global mt5
    if mt5 is None:
        try:
            import MetaTrader5 as _mt5
            mt5 = _mt5
        except ImportError:
            raise ImportError(
                "MetaTrader5 is not installed. Run: pip install MetaTrader5\n"
                "Note: This library only works on Windows with MT5 terminal installed."
            )
    return mt5


@dataclass
class MT5Config:
    """MT5 connection configuration."""
    login: int = 0  # MT5 account number
    password: str = ""  # MT5 password
    server: str = ""  # Broker server name (e.g., "ICMarkets-Demo")
    terminal_path: str = ""  # Optional: path to terminal64.exe
    timeout: int = 60000  # Connection timeout in milliseconds
    magic_number: int = 123456  # EA magic number for identifying orders


@dataclass
class OrderResult:
    """Order execution result."""
    success: bool
    order_id: int = 0
    deal_id: int = 0
    filled: float = 0.0
    price: float = 0.0
    status: str = ""
    message: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


class MT5Client:
    """
    MetaTrader 5 Trading Client
    
    Usage:
        config = MT5Config(
            login=12345678,
            password="your_password",
            server="ICMarkets-Demo"
        )
        client = MT5Client(config)
        
        if client.connect():
            # Place order
            result = client.place_market_order("EURUSD", "buy", 0.1)
            
            # Get positions
            positions = client.get_positions()
            
            client.disconnect()
    """
    
    def __init__(self, config: Optional[MT5Config] = None):
        self.config = config or MT5Config()
        self._connected = False
        self._lock = threading.Lock()
    
    @property
    def connected(self) -> bool:
        """Check if connected to MT5 terminal."""
        if not self._connected:
            return False
        try:
            _ensure_mt5()
            info = mt5.terminal_info()
            return info is not None and info.connected
        except Exception:
            return False
    
    def connect(self) -> bool:
        """
        Connect to MT5 terminal.
        
        Returns:
            True if connected successfully
        """
        with self._lock:
            if self.connected:
                return True
            
            try:
                _ensure_mt5()
                
                # Initialize MT5 connection
                init_params = {}
                
                if self.config.terminal_path:
                    init_params["path"] = self.config.terminal_path
                
                if self.config.login and self.config.password and self.config.server:
                    init_params["login"] = self.config.login
                    init_params["password"] = self.config.password
                    init_params["server"] = self.config.server
                    init_params["timeout"] = self.config.timeout
                
                logger.info(f"Connecting to MT5: server={self.config.server}, login={self.config.login}")
                
                if init_params:
                    initialized = mt5.initialize(**init_params)
                else:
                    # Connect to already running terminal
                    initialized = mt5.initialize()
                
                if not initialized:
                    error = mt5.last_error()
                    logger.error(f"MT5 initialization failed: {error}")
                    return False
                
                self._connected = True
                
                # Log account info
                account_info = mt5.account_info()
                if account_info:
                    logger.info(f"MT5 connected: account={account_info.login}, "
                               f"server={account_info.server}, balance={account_info.balance}")
                else:
                    logger.warning("MT5 connected but account info not available")
                
                return True
                
            except Exception as e:
                logger.error(f"MT5 connection failed: {e}")
                self._connected = False
                return False
    
    def disconnect(self):
        """Disconnect from MT5 terminal."""
        with self._lock:
            if self._connected:
                try:
                    _ensure_mt5()
                    mt5.shutdown()
                except Exception as e:
                    logger.warning(f"MT5 disconnect exception: {e}")
                finally:
                    self._connected = False
                    logger.info("MT5 disconnected")
    
    def _ensure_connected(self):
        """Ensure connection is established."""
        if not self.connected:
            if not self.connect():
                raise ConnectionError("Cannot connect to MT5 terminal")
    
    # ==================== Order Methods ====================
    
    def place_market_order(
        self,
        symbol: str,
        side: str,
        volume: float,
        deviation: int = 20,
        comment: str = "QuantDinger",
    ) -> OrderResult:
        """
        Place a market order.
        
        Args:
            symbol: Trading symbol (e.g., "EURUSD")
            side: Direction ("buy" or "sell")
            volume: Lot size (e.g., 0.1 = 1 mini lot)
            deviation: Maximum price deviation in points
            comment: Order comment
            
        Returns:
            OrderResult
        """
        try:
            self._ensure_connected()
            _ensure_mt5()
            
            # Normalize symbol
            symbol = normalize_symbol(symbol)
            
            # Get symbol info
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                return OrderResult(
                    success=False,
                    message=f"Symbol not found: {symbol}"
                )
            
            # Validate volume against symbol constraints
            volume_float = float(volume)
            if volume_float < symbol_info.volume_min:
                return OrderResult(
                    success=False,
                    message=f"Volume {volume_float} is less than minimum {symbol_info.volume_min}"
                )
            if volume_float > symbol_info.volume_max:
                return OrderResult(
                    success=False,
                    message=f"Volume {volume_float} exceeds maximum {symbol_info.volume_max}"
                )
            # Round volume to lot step
            volume_step = symbol_info.volume_step
            if volume_step > 0:
                volume_float = round(volume_float / volume_step) * volume_step
            
            if not symbol_info.visible:
                # Enable symbol in Market Watch
                if not mt5.symbol_select(symbol, True):
                    return OrderResult(
                        success=False,
                        message=f"Failed to select symbol: {symbol}"
                    )
            
            # Get current price
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return OrderResult(
                    success=False,
                    message=f"Failed to get tick for: {symbol}"
                )
            
            # Determine order type and price
            if side.lower() == "buy":
                order_type = mt5.ORDER_TYPE_BUY
                price = tick.ask
            else:
                order_type = mt5.ORDER_TYPE_SELL
                price = tick.bid
            
            # Determine filling mode based on symbol properties
            # Different brokers support different filling modes
            filling_mode = mt5.ORDER_FILLING_IOC  # Default
            if symbol_info.filling_mode & mt5.ORDER_FILLING_IOC:
                filling_mode = mt5.ORDER_FILLING_IOC
            elif symbol_info.filling_mode & mt5.ORDER_FILLING_FOK:
                filling_mode = mt5.ORDER_FILLING_FOK
            elif symbol_info.filling_mode & mt5.ORDER_FILLING_RETURN:
                filling_mode = mt5.ORDER_FILLING_RETURN
            
            # Prepare order request
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume_float,  # Use validated and rounded volume
                "type": order_type,
                "price": price,
                "deviation": deviation,
                "magic": self.config.magic_number,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling_mode,
            }
            
            # Send order
            result = mt5.order_send(request)
            
            if result is None:
                error = mt5.last_error()
                return OrderResult(
                    success=False,
                    message=f"Order send failed: {error}"
                )
            
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                return OrderResult(
                    success=False,
                    order_id=result.order if hasattr(result, 'order') else 0,
                    status=str(result.retcode),
                    message=f"Order rejected: {result.comment}",
                    raw=result._asdict() if hasattr(result, '_asdict') else {}
                )
            
            return OrderResult(
                success=True,
                order_id=result.order,
                deal_id=result.deal,
                filled=result.volume,
                price=result.price,
                status="filled",
                message="Order executed",
                raw=result._asdict() if hasattr(result, '_asdict') else {}
            )
            
        except Exception as e:
            logger.error(f"Market order failed: {e}")
            return OrderResult(
                success=False,
                message=str(e)
            )
    
    def place_limit_order(
        self,
        symbol: str,
        side: str,
        volume: float,
        price: float,
        comment: str = "QuantDinger",
    ) -> OrderResult:
        """
        Place a pending limit order.
        
        Args:
            symbol: Trading symbol
            side: Direction ("buy" or "sell")
            volume: Lot size
            price: Limit price
            comment: Order comment
            
        Returns:
            OrderResult
        """
        try:
            self._ensure_connected()
            _ensure_mt5()
            
            symbol = normalize_symbol(symbol)
            
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                return OrderResult(
                    success=False,
                    message=f"Symbol not found: {symbol}"
                )
            
            if not symbol_info.visible:
                mt5.symbol_select(symbol, True)
            
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return OrderResult(
                    success=False,
                    message=f"Failed to get tick for: {symbol}"
                )
            
            # Determine order type based on side and price relative to market
            if side.lower() == "buy":
                if price < tick.ask:
                    order_type = mt5.ORDER_TYPE_BUY_LIMIT
                else:
                    order_type = mt5.ORDER_TYPE_BUY_STOP
            else:
                if price > tick.bid:
                    order_type = mt5.ORDER_TYPE_SELL_LIMIT
                else:
                    order_type = mt5.ORDER_TYPE_SELL_STOP
            
            request = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": symbol,
                "volume": float(volume),
                "type": order_type,
                "price": price,
                "magic": self.config.magic_number,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
            }
            
            result = mt5.order_send(request)
            
            if result is None:
                error = mt5.last_error()
                return OrderResult(
                    success=False,
                    message=f"Order send failed: {error}"
                )
            
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                return OrderResult(
                    success=False,
                    status=str(result.retcode),
                    message=f"Order rejected: {result.comment}",
                )
            
            return OrderResult(
                success=True,
                order_id=result.order,
                price=price,
                status="pending",
                message="Pending order placed",
                raw=result._asdict() if hasattr(result, '_asdict') else {}
            )
            
        except Exception as e:
            logger.error(f"Limit order failed: {e}")
            return OrderResult(
                success=False,
                message=str(e)
            )
    
    def close_position(
        self,
        ticket: int,
        volume: Optional[float] = None,
        deviation: int = 20,
        comment: str = "QuantDinger close",
    ) -> OrderResult:
        """
        Close an open position.
        
        Args:
            ticket: Position ticket number
            volume: Volume to close (None = close all)
            deviation: Maximum price deviation
            comment: Order comment
            
        Returns:
            OrderResult
        """
        try:
            self._ensure_connected()
            _ensure_mt5()
            
            # Get position info
            position = mt5.positions_get(ticket=ticket)
            if not position:
                return OrderResult(
                    success=False,
                    message=f"Position not found: {ticket}"
                )
            
            pos = position[0]
            symbol = pos.symbol
            
            # Get symbol info for filling mode
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                return OrderResult(
                    success=False,
                    message=f"Symbol not found: {symbol}"
                )
            
            # Get tick
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return OrderResult(
                    success=False,
                    message=f"Failed to get tick for: {symbol}"
                )
            
            # Determine close direction and price
            if pos.type == mt5.POSITION_TYPE_BUY:
                order_type = mt5.ORDER_TYPE_SELL
                price = tick.bid
            else:
                order_type = mt5.ORDER_TYPE_BUY
                price = tick.ask
            
            close_volume = volume if volume else pos.volume
            
            # Determine filling mode based on symbol properties
            filling_mode = mt5.ORDER_FILLING_IOC  # Default
            if symbol_info.filling_mode & mt5.ORDER_FILLING_IOC:
                filling_mode = mt5.ORDER_FILLING_IOC
            elif symbol_info.filling_mode & mt5.ORDER_FILLING_FOK:
                filling_mode = mt5.ORDER_FILLING_FOK
            elif symbol_info.filling_mode & mt5.ORDER_FILLING_RETURN:
                filling_mode = mt5.ORDER_FILLING_RETURN
            
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(close_volume),
                "type": order_type,
                "position": ticket,
                "price": price,
                "deviation": deviation,
                "magic": self.config.magic_number,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling_mode,
            }
            
            result = mt5.order_send(request)
            
            if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                return OrderResult(
                    success=False,
                    message=f"Close failed: {result.comment if result else 'Unknown error'}"
                )
            
            return OrderResult(
                success=True,
                order_id=result.order,
                deal_id=result.deal,
                filled=result.volume,
                price=result.price,
                status="closed",
                message="Position closed",
            )
            
        except Exception as e:
            logger.error(f"Close position failed: {e}")
            return OrderResult(
                success=False,
                message=str(e)
            )
    
    def cancel_order(self, ticket: int) -> bool:
        """
        Cancel a pending order.
        
        Args:
            ticket: Order ticket number
            
        Returns:
            True if cancelled successfully
        """
        try:
            self._ensure_connected()
            _ensure_mt5()
            
            request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": ticket,
            }
            
            result = mt5.order_send(request)
            
            if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                logger.warning(f"Cancel order failed: {result.comment if result else 'Unknown'}")
                return False
            
            logger.info(f"Order {ticket} cancelled")
            return True
            
        except Exception as e:
            logger.error(f"Cancel order failed: {e}")
            return False
    
    # ==================== Query Methods ====================
    
    def get_account_info(self) -> Dict[str, Any]:
        """
        Get account information.
        
        Returns:
            Account info dictionary
        """
        try:
            self._ensure_connected()
            _ensure_mt5()
            
            info = mt5.account_info()
            if info is None:
                return {"success": False, "error": "Failed to get account info"}
            
            return {
                "success": True,
                "login": info.login,
                "server": info.server,
                "name": info.name,
                "currency": info.currency,
                "balance": info.balance,
                "equity": info.equity,
                "margin": info.margin,
                "margin_free": info.margin_free,
                "margin_level": info.margin_level,
                "profit": info.profit,
                "leverage": info.leverage,
                "trade_allowed": info.trade_allowed,
                "trade_expert": info.trade_expert,
            }
            
        except Exception as e:
            logger.error(f"Get account info failed: {e}")
            return {"success": False, "error": str(e)}
    
    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get open positions.
        
        Args:
            symbol: Filter by symbol (optional)
            
        Returns:
            List of positions
        """
        try:
            self._ensure_connected()
            _ensure_mt5()
            
            if symbol:
                positions = mt5.positions_get(symbol=normalize_symbol(symbol))
            else:
                positions = mt5.positions_get()
            
            if positions is None:
                return []
            
            result = []
            for pos in positions:
                result.append({
                    "ticket": pos.ticket,
                    "symbol": pos.symbol,
                    "type": "buy" if pos.type == mt5.POSITION_TYPE_BUY else "sell",
                    "volume": pos.volume,
                    "price_open": pos.price_open,
                    "price_current": pos.price_current,
                    "sl": pos.sl,
                    "tp": pos.tp,
                    "profit": pos.profit,
                    "swap": pos.swap,
                    "magic": pos.magic,
                    "comment": pos.comment,
                    "time": datetime.fromtimestamp(pos.time).isoformat(),
                })
            
            return result
            
        except Exception as e:
            logger.error(f"Get positions failed: {e}")
            return []
    
    def get_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get pending orders.
        
        Args:
            symbol: Filter by symbol (optional)
            
        Returns:
            List of orders
        """
        try:
            self._ensure_connected()
            _ensure_mt5()
            
            if symbol:
                orders = mt5.orders_get(symbol=normalize_symbol(symbol))
            else:
                orders = mt5.orders_get()
            
            if orders is None:
                return []
            
            result = []
            for order in orders:
                order_type_map = {
                    mt5.ORDER_TYPE_BUY_LIMIT: "buy_limit",
                    mt5.ORDER_TYPE_SELL_LIMIT: "sell_limit",
                    mt5.ORDER_TYPE_BUY_STOP: "buy_stop",
                    mt5.ORDER_TYPE_SELL_STOP: "sell_stop",
                }
                
                result.append({
                    "ticket": order.ticket,
                    "symbol": order.symbol,
                    "type": order_type_map.get(order.type, str(order.type)),
                    "volume_initial": order.volume_initial,
                    "volume_current": order.volume_current,
                    "price_open": order.price_open,
                    "price_current": order.price_current,
                    "sl": order.sl,
                    "tp": order.tp,
                    "magic": order.magic,
                    "comment": order.comment,
                    "time_setup": datetime.fromtimestamp(order.time_setup).isoformat(),
                })
            
            return result
            
        except Exception as e:
            logger.error(f"Get orders failed: {e}")
            return []
    
    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Get real-time quote.
        
        Args:
            symbol: Symbol code
            
        Returns:
            Quote data
        """
        try:
            self._ensure_connected()
            _ensure_mt5()
            
            symbol = normalize_symbol(symbol)
            
            # Select symbol
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                return {"success": False, "error": f"Symbol not found: {symbol}"}
            
            if not symbol_info.visible:
                mt5.symbol_select(symbol, True)
            
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return {"success": False, "error": f"Failed to get tick: {symbol}"}
            
            return {
                "success": True,
                "symbol": symbol,
                "bid": tick.bid,
                "ask": tick.ask,
                "last": tick.last,
                "volume": tick.volume,
                "time": datetime.fromtimestamp(tick.time).isoformat(),
                "spread": round((tick.ask - tick.bid) / symbol_info.point, 1),
            }
            
        except Exception as e:
            logger.error(f"Get quote failed: {e}")
            return {"success": False, "error": str(e)}
    
    def get_symbols(self, group: str = "*") -> List[Dict[str, Any]]:
        """
        Get available symbols.
        
        Args:
            group: Filter by group pattern (e.g., "*USD*", "Forex*")
            
        Returns:
            List of symbol info
        """
        try:
            self._ensure_connected()
            _ensure_mt5()
            
            symbols = mt5.symbols_get(group=group)
            if symbols is None:
                return []
            
            result = []
            for s in symbols:
                result.append({
                    "name": s.name,
                    "description": s.description,
                    "path": s.path,
                    "currency_base": s.currency_base,
                    "currency_profit": s.currency_profit,
                    "digits": s.digits,
                    "point": s.point,
                    "trade_mode": s.trade_mode,
                    "volume_min": s.volume_min,
                    "volume_max": s.volume_max,
                    "volume_step": s.volume_step,
                })
            
            return result
            
        except Exception as e:
            logger.error(f"Get symbols failed: {e}")
            return []
    
    def get_connection_status(self) -> Dict[str, Any]:
        """Get connection status."""
        try:
            _ensure_mt5()
            terminal_info = mt5.terminal_info() if self._connected else None
            account_info = mt5.account_info() if self._connected else None
            
            return {
                "connected": self.connected,
                "login": self.config.login,
                "server": self.config.server,
                "account_login": account_info.login if account_info else None,
                "account_server": account_info.server if account_info else None,
                "terminal_connected": terminal_info.connected if terminal_info else False,
                "trade_allowed": terminal_info.trade_allowed if terminal_info else False,
            }
        except Exception as e:
            return {
                "connected": False,
                "error": str(e),
            }


# Global singleton (optional)
_global_client: Optional[MT5Client] = None
_global_lock = threading.Lock()


def get_mt5_client(config: Optional[MT5Config] = None) -> MT5Client:
    """
    Get global MT5 client singleton.
    
    Args:
        config: Configuration (only effective on first call)
        
    Returns:
        MT5Client instance
    """
    global _global_client
    
    with _global_lock:
        if _global_client is None:
            _global_client = MT5Client(config)
        return _global_client


def reset_mt5_client():
    """Reset global client (disconnect and clear instance)."""
    global _global_client
    
    with _global_lock:
        if _global_client is not None:
            _global_client.disconnect()
            _global_client = None
