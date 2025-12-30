# QuantDinger Python 策略開發指南

本指南將詳細介紹如何在 QuantDinger 平台中使用 Python 開發交易策略。QuantDinger 提供了靈活的執行環境，支持數據訪問、指標計算和信號生成。

## 1. 概覽

QuantDinger 中的策略基於 **信號提供者 (Signal Provider)** 模式運行。系統執行你的 Python 腳本，該腳本負責處理市場數據（DataFrame）並輸出交易信號。

執行流程如下：
1.  **輸入**：系統將包含 OHLCV 數據的 `df` (Pandas DataFrame) 注入到你的腳本環境中。
2.  **處理**：你使用 Python (`pandas`, `numpy`) 計算指標並定義 `buy`/`sell` 邏輯。
3.  **輸出**：你構造一個特定的 `output` 字典，包含繪圖數據和信號。

---

## 2. 環境與數據

你的腳本運行在一個沙盒化的 Python 環境中。

### 2.1 預導入庫
以下庫默認可用（**無需** `import`）：
*   `pd` (pandas)
*   `np` (numpy)

### 2.2 輸入數據 (`df`)
一個名為 `df` 的 Pandas DataFrame 變量會自動存在於全局作用域中。它包含所選代碼和時間週期的歷史市場數據。

**列 (Columns):**
*   `time`: 時間戳 (datetime 或 int，視上下文而定)
*   `open`: 開盤價 (float)
*   `high`: 最高價 (float)
*   `low`: 最低價 (float)
*   `close`: 收盤價 (float)
*   `volume`: 成交量 (float)

**示例:**
```python
# 獲取收盤價序列
closes = df['close']

# 計算簡單移動平均線 (SMA)
sma_20 = df['close'].rolling(20).mean()
```

---

## 3. 開發策略

一個標準的策略腳本包含三個部分：
1.  **指標計算**：計算技術指標。
2.  **信號生成**：定義買入和賣出信號邏輯。
3.  **輸出構建**：格式化結果以供圖表展示和執行引擎使用。

### 3.1 指標計算
你可以使用標準的 Pandas 操作來計算指標。

```python
# 示例：MACD 計算
short_window = 12
long_window = 26
signal_window = 9

ema12 = df['close'].ewm(span=short_window, adjust=False).mean()
ema26 = df['close'].ewm(span=long_window, adjust=False).mean()
macd = ema12 - ema26
signal_line = macd.ewm(span=signal_window, adjust=False).mean()
```

### 3.2 信號生成 (關鍵)

你 **必須** 在 `df` 中創建（或作為獨立變量）兩個布爾類型的 Series，分別命名為 `buy` 和 `sell`。

*   `True` 表示觸發信號。
*   `False` 表示無信號。

**重要：邊緣觸發 (Edge Triggering)**
為了避免在連續的 K 線上重複發出信號（這可能導致重複下單，取決於後端配置），最佳實踐是使用 **邊緣觸發** 信號（即只在條件變真的那一刻發出信號）。

```python
# 條件：收盤價上穿 SMA 20
condition_buy = (df['close'] > sma_20) & (df['close'].shift(1) <= sma_20.shift(1))

# 條件：收盤價下穿 SMA 20
condition_sell = (df['close'] < sma_20) & (df['close'].shift(1) >= sma_20.shift(1))

# 賦值給 df (回測必需)
df['buy'] = condition_buy.fillna(False)
df['sell'] = condition_sell.fillna(False)
```

**關於信號類型的說明:**
*   QuantDinger 會根據你的策略配置（僅做多、僅做空或雙向）來標準化信號。
*   你的腳本只需輸出 "buy"（看漲意圖）或 "sell"（看跌意圖）。後端會處理開倉/平倉邏輯。

### 3.3 可視化標記
為了在圖表上展示，你通常希望將信號圖標放在 K 線的上方或下方。

```python
# 將買入標記放在最低價下方 0.5% 處
buy_marks = [
    df['low'].iloc[i] * 0.995 if df['buy'].iloc[i] else None 
    for i in range(len(df))
]

# 將賣出標記放在最高價上方 0.5% 處
sell_marks = [
    df['high'].iloc[i] * 1.005 if df['sell'].iloc[i] else None 
    for i in range(len(df))
]
```

### 3.4 `output` 變量 (必須)
最後一步是將一個字典賦值給變量 `output`。這告訴前端如何繪圖，以及告訴後端信號在哪裡。

**結構:**
```python
output = {
    "name": "我的策略名稱",
    "plots": [ ... ],   # 要繪製的線條/指標列表
    "signals": [ ... ]  # 信號標記列表
}
```

**Plots Schema (繪圖配置):**
*   `name`: 圖例名稱 (例如 "SMA 20")
*   `data`: 數值列表 (必須與 `df` 長度一致)。使用 `.tolist()` 轉換。
*   `color`: 十六進制顏色字符串 (例如 "#ff0000")。
*   `overlay`: `True` 表示繪製在主圖（價格圖）上，`False` 表示繪製在副圖（如 RSI/MACD）。

**Signals Schema (信號配置):**
*   `type`: 必須是 "buy" 或 "sell"。
*   `text`: 圖標上顯示的文本 (例如 "B", "S")。
*   `data`: 數值列表 (價格位置)。無信號處為 `None`。
*   `color`: 圖標顏色。

---

## 4. 完整示例：雙均線交叉 (Dual SMA)

以下是一個完整的、可複製的雙均線策略示例：當 SMA(10) 上穿 SMA(30) 時買入，下穿時賣出。

```python
# 1. 指標計算
# -----------------------
# 計算短期和長期 SMA
sma_short = df['close'].rolling(10).mean()
sma_long = df['close'].rolling(30).mean()

# 2. 信號邏輯
# -----------------------
# 買入：短期 SMA 上穿 長期 SMA
raw_buy = (sma_short > sma_long) & (sma_short.shift(1) <= sma_long.shift(1))

# 賣出：短期 SMA 下穿 長期 SMA
raw_sell = (sma_short < sma_long) & (sma_short.shift(1) >= sma_long.shift(1))

# 清理 NaN 並確保布爾類型
buy = raw_buy.fillna(False)
sell = raw_sell.fillna(False)

# 賦值給 df 列 (後端執行的關鍵)
df['buy'] = buy
df['sell'] = sell

# 3. 可視化格式化
# -----------------------
# 計算標記位置
buy_marks = [
    df['low'].iloc[i] * 0.995 if buy.iloc[i] else None 
    for i in range(len(df))
]

sell_marks = [
    df['high'].iloc[i] * 1.005 if sell.iloc[i] else None 
    for i in range(len(df))
]

# 4. 最終輸出
# -----------------------
output = {
  'name': '雙均線策略',
  'plots': [
    {
        'name': 'SMA 10',
        'data': sma_short.fillna(0).tolist(),
        'color': '#1890ff',
        'overlay': True
    },
    {
        'name': 'SMA 30',
        'data': sma_long.fillna(0).tolist(),
        'color': '#faad14',
        'overlay': True
    }
  ],
  'signals': [
    {
        'type': 'buy',
        'text': '買',
        'data': buy_marks,
        'color': '#00E676'
    },
    {
        'type': 'sell',
        'text': '賣',
        'data': sell_marks,
        'color': '#FF5252'
    }
  ]
}
```

## 5. 最佳實踐與故障排除

### 5.1 處理 NaN
滾動計算（如 `rolling(14)`）會在數據開頭產生 `NaN` 值。
*   **規則**：生成信號前必須處理 `NaN`。
*   **修復**：使用 `.fillna(0)` 或 `.fillna(False)`。

### 5.2 未來函數 (Look-ahead Bias)
系統基於 K 線 **收盤** 時產生的信號執行交易。
*   回測引擎通常在 **下一根 K 線的開盤價** 執行訂單。
*   你的信號邏輯應依賴 `close` (當前已完成的 K 線) 或 `shift(1)` (前一根 K 線)。切勿使用 `shift(-1)`。

### 5.3 性能
避免在計算邏輯中遍歷 DataFrame 行 (`for i in range(len(df)): ...`)。這非常慢。
*   **錯誤**：使用循環計算 SMA。
*   **正確**：使用 `df['close'].rolling(...)`。
*   **例外**：構建 `buy_marks`/`sell_marks` 列表通常需要列表推導式，這是可接受的（僅用於可視化輸出）。

### 5.4 調試
由於在某些執行模式下無法輕易看到 `print()` 輸出，如果策略加載失敗，請檢查後端日誌 (`backend_api_python/logs/app.log`)。
*   常見錯誤：`KeyError` (列名錯誤)。
*   常見錯誤：`ValueError` (數組長度不一致)。確保 `plots` 中的數據長度與 `df` 一致。

