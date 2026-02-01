# ============================================================
# 双均线策略 (支持外部参数配置)
# Dual Moving Average Strategy with External Parameters
# ============================================================
# 
# 使用方法:
# 1. 在交易助手中选择此指标
# 2. 根据不同币种配置不同参数
#    - BTC/USDT: sma_short=5, sma_long=10
#    - ETH/USDT: sma_short=5, sma_long=20
# 
# ============================================================

# === 参数声明 (会在前端表单中显示) ===
# @param sma_short int 14 短期均线周期
# @param sma_long int 28 长期均线周期

# === 获取参数 (带默认值作为后备) ===
sma_short_period = params.get('sma_short', 14)
sma_long_period = params.get('sma_long', 28)

# === 指标信息 ===
my_indicator_name = "双均线策略"
my_indicator_description = f"短期{sma_short_period}/长期{sma_long_period}均线交叉策略"

# === 计算均线 ===
df = df.copy()
sma_short = df["close"].rolling(sma_short_period).mean()
sma_long = df["close"].rolling(sma_long_period).mean()

# === 生成买卖信号 ===
# 金叉：短期均线上穿长期均线
buy = (sma_short > sma_long) & (sma_short.shift(1) <= sma_long.shift(1))
# 死叉：短期均线下穿长期均线
sell = (sma_short < sma_long) & (sma_short.shift(1) >= sma_long.shift(1))

df["buy"] = buy.fillna(False).astype(bool)
df["sell"] = sell.fillna(False).astype(bool)

# === 买卖标记点 (用于K线图显示) ===
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
