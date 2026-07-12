"""
QuantDinger chart-only indicator example: multi-indicator composite.

This file demonstrates the current indicator contract:
- read OHLCV data from df
- read visual parameters from params
- compute plots and chart markers
- return output
- do not create orders, positions, stop loss, take profit, or backtest columns

To trade this idea, convert it into a Script Strategy first.
"""

my_indicator_name = "Multi Indicator Composite"
my_indicator_description = (
    "Chart-only composite of SMA trend, RSI regime, MACD momentum, and volume filter."
)

# @param sma_short int 10 Short SMA period
# @param sma_long int 30 Long SMA period
# @param rsi_period int 14 RSI period
# @param rsi_oversold int 30 RSI oversold level
# @param rsi_overbought int 70 RSI overbought level
# @param use_macd bool true Require MACD direction confirmation
# @param use_volume bool false Require volume expansion for buy markers
# @param volume_mult float 1.5 Volume expansion multiplier

df = df.copy()

sma_short_period = int(params.get("sma_short", 10))
sma_long_period = int(params.get("sma_long", 30))
rsi_period = int(params.get("rsi_period", 14))
rsi_oversold = float(params.get("rsi_oversold", 30))
rsi_overbought = float(params.get("rsi_overbought", 70))
use_macd = bool(params.get("use_macd", True))
use_volume = bool(params.get("use_volume", False))
volume_mult = float(params.get("volume_mult", 1.5))

close = df["close"]
high = df["high"]
low = df["low"]
volume = df["volume"]

sma_short = close.rolling(sma_short_period).mean()
sma_long = close.rolling(sma_long_period).mean()

delta = close.diff()
gain = delta.clip(lower=0).rolling(rsi_period).mean()
loss = (-delta.clip(upper=0)).rolling(rsi_period).mean()
rs = gain / loss.replace(0, np.nan)
rsi = 100 - (100 / (1 + rs))

ema_fast = close.ewm(span=12, adjust=False).mean()
ema_slow = close.ewm(span=26, adjust=False).mean()
macd = ema_fast - ema_slow
macd_signal = macd.ewm(span=9, adjust=False).mean()
macd_hist = macd - macd_signal

volume_ma = volume.rolling(20).mean()

trend_up = sma_short > sma_long
trend_down = sma_short < sma_long
rsi_buy_zone = rsi <= rsi_oversold
rsi_sell_zone = rsi >= rsi_overbought
macd_up = macd_hist > 0
macd_down = macd_hist < 0
volume_ok = volume > (volume_ma * volume_mult)

buy_condition = (trend_up & rsi_buy_zone).fillna(False)
sell_condition = (trend_down & rsi_sell_zone).fillna(False)

if use_macd:
    buy_condition = buy_condition & macd_up.fillna(False)
    sell_condition = sell_condition & macd_down.fillna(False)

if use_volume:
    buy_condition = buy_condition & volume_ok.fillna(False)

buy_edge = buy_condition & ~buy_condition.shift(1).fillna(False)
sell_edge = sell_condition & ~sell_condition.shift(1).fillna(False)

buy_marks = [
    float(low.iloc[i] * 0.995) if bool(buy_edge.iloc[i]) else None
    for i in range(len(df))
]
sell_marks = [
    float(high.iloc[i] * 1.005) if bool(sell_edge.iloc[i]) else None
    for i in range(len(df))
]

trend_lamp = [
    "up" if bool(trend_up.fillna(False).iloc[i]) else "down" if bool(trend_down.fillna(False).iloc[i]) else "flat"
    for i in range(len(df))
]

output = {
    "name": my_indicator_name,
    "description": my_indicator_description,
    "plots": [
        {
            "name": f"SMA {sma_short_period}",
            "data": sma_short.fillna(0).tolist(),
            "color": "#f59e0b",
            "type": "line",
            "overlay": True,
        },
        {
            "name": f"SMA {sma_long_period}",
            "data": sma_long.fillna(0).tolist(),
            "color": "#2563eb",
            "type": "line",
            "overlay": True,
        },
        {
            "name": "RSI",
            "data": rsi.fillna(50).tolist(),
            "color": "#8b5cf6",
            "type": "line",
            "overlay": False,
        },
        {
            "name": "MACD Histogram",
            "data": macd_hist.fillna(0).tolist(),
            "color": "#14b8a6",
            "type": "histogram",
            "overlay": False,
        },
    ],
    "signals": [
        {"type": "buy", "text": "Composite Buy", "data": buy_marks, "color": "#22c55e"},
        {"type": "sell", "text": "Composite Sell", "data": sell_marks, "color": "#ef4444"},
    ],
    "layers": [
        {
            "name": "Trend Lamp",
            "type": "lamp",
            "data": trend_lamp,
            "colors": {"up": "#16a34a", "down": "#dc2626", "flat": "#6b7280"},
        }
    ],
}
