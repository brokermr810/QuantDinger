# QuantDinger chart-only indicator example.
# Paste into Indicator IDE. This file does not backtest or trade.

# @param fast_len int 12 Fast EMA period
# @param slow_len int 26 Slow EMA period
# @param confirm_next_bar bool false Show markers one bar after confirmation

my_indicator_name = "Dual EMA Viewer"
my_indicator_description = "Chart-only EMA crossover indicator with visual event markers."

df = df.copy()

fast_len = int(params.get("fast_len", 12))
slow_len = int(params.get("slow_len", 26))
confirm_next_bar = bool(params.get("confirm_next_bar", False))

close = df["close"]
high = df["high"]
low = df["low"]

def edge(condition):
    s = condition.fillna(False).astype(bool)
    return s & ~s.shift(1).fillna(False)

def to_plot_list(series):
    return [None if pd.isna(v) else float(v) for v in series]

ema_fast = close.ewm(span=fast_len, adjust=False).mean()
ema_slow = close.ewm(span=slow_len, adjust=False).mean()

golden = edge(ema_fast > ema_slow)
death = edge(ema_fast < ema_slow)

if confirm_next_bar:
    golden = golden.shift(1).fillna(False).astype(bool)
    death = death.shift(1).fillna(False).astype(bool)

buy_marks = [
    float(low.iloc[i] * 0.995) if bool(golden.iloc[i]) else None
    for i in range(len(df))
]
sell_marks = [
    float(high.iloc[i] * 1.005) if bool(death.iloc[i]) else None
    for i in range(len(df))
]

output = {
    "name": my_indicator_name,
    "plots": [
        {
            "name": "EMA Fast",
            "data": to_plot_list(ema_fast),
            "color": "#22c55e",
            "type": "line",
            "overlay": True,
        },
        {
            "name": "EMA Slow",
            "data": to_plot_list(ema_slow),
            "color": "#3b82f6",
            "type": "line",
            "overlay": True,
        },
    ],
    "signals": [
        {"type": "buy", "text": "Golden", "color": "#22c55e", "data": buy_marks},
        {"type": "sell", "text": "Death", "color": "#ef4444", "data": sell_marks},
    ],
    "layers": [],
}
