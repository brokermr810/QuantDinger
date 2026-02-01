# ============================================================
# 多指标组合策略 (均线+RSI+MACD)
# Multi-Indicator Composite Strategy
# ============================================================
# 
# 使用方法:
# 1. 可配置均线周期、RSI阈值等参数
# 2. 买入条件: RSI超卖 + MACD金叉 + 成交量放大
# 3. 卖出条件: RSI超买 或 MACD死叉
# 
# ============================================================

# === 参数声明 ===
# @param sma_short int 10 短期均线周期
# @param sma_long int 30 长期均线周期
# @param rsi_period int 14 RSI周期
# @param rsi_oversold int 30 RSI超卖阈值
# @param rsi_overbought int 70 RSI超买阈值
# @param use_macd bool True 是否使用MACD过滤
# @param use_volume bool False 是否使用成交量过滤
# @param volume_mult float 1.5 成交量放大倍数

# === 获取参数 ===
sma_short_period = params.get('sma_short', 10)
sma_long_period = params.get('sma_long', 30)
rsi_period = params.get('rsi_period', 14)
rsi_oversold = params.get('rsi_oversold', 30)
rsi_overbought = params.get('rsi_overbought', 70)
use_macd = params.get('use_macd', True)
use_volume = params.get('use_volume', False)
volume_mult = params.get('volume_mult', 1.5)

# === 指标信息 ===
my_indicator_name = "多指标组合策略"
my_indicator_description = f"SMA{sma_short_period}/{sma_long_period} + RSI{rsi_period}"

df = df.copy()

# === 计算均线 ===
sma_short = df["close"].rolling(sma_short_period).mean()
sma_long = df["close"].rolling(sma_long_period).mean()

# === 计算RSI ===
delta = df["close"].diff()
gain = delta.where(delta > 0, 0).rolling(window=rsi_period).mean()
loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
rs = gain / loss
rsi = 100 - (100 / (1 + rs))

# === 计算MACD ===
exp1 = df["close"].ewm(span=12, adjust=False).mean()
exp2 = df["close"].ewm(span=26, adjust=False).mean()
macd = exp1 - exp2
macd_signal = macd.ewm(span=9, adjust=False).mean()
macd_hist = macd - macd_signal

# === 计算成交量均线 ===
volume_ma = df["volume"].rolling(20).mean()

# === 生成信号条件 ===
# 均线金叉
ma_golden = (sma_short > sma_long) & (sma_short.shift(1) <= sma_long.shift(1))
# 均线死叉
ma_death = (sma_short < sma_long) & (sma_short.shift(1) >= sma_long.shift(1))
# RSI超卖
rsi_buy = rsi < rsi_oversold
# RSI超买
rsi_sell = rsi > rsi_overbought
# MACD金叉
macd_golden = (macd > macd_signal) & (macd.shift(1) <= macd_signal.shift(1))
# MACD死叉
macd_death = (macd < macd_signal) & (macd.shift(1) >= macd_signal.shift(1))
# 成交量放大
volume_up = df["volume"] > volume_ma * volume_mult

# === 综合买卖信号 ===
buy = ma_golden | rsi_buy  # 均线金叉 或 RSI超卖

if use_macd:
    buy = buy & (macd > macd_signal)  # 需要MACD向上
    
if use_volume:
    buy = buy & volume_up  # 需要成交量放大

sell = ma_death | rsi_sell  # 均线死叉 或 RSI超买

if use_macd:
    sell = sell | macd_death  # MACD死叉也卖出

df["buy"] = buy.fillna(False).astype(bool)
df["sell"] = sell.fillna(False).astype(bool)

# === 买卖标记点 ===
buy_marks = [df["low"].iloc[i] * 0.995 if df["buy"].iloc[i] else None for i in range(len(df))]
sell_marks = [df["high"].iloc[i] * 1.005 if df["sell"].iloc[i] else None for i in range(len(df))]

# === 图表输出配置 ===
output = {
    "name": my_indicator_name,
    "plots": [
        {"name": f"SMA{sma_short_period}", "data": sma_short.tolist(), "color": "#FF9800", "overlay": True},
        {"name": f"SMA{sma_long_period}", "data": sma_long.tolist(), "color": "#3F51B5", "overlay": True}
    ],
    "signals": [
        {"type": "buy", "text": "B", "data": buy_marks, "color": "#00E676"},
        {"type": "sell", "text": "S", "data": sell_marks, "color": "#FF5252"}
    ]
}
