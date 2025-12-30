# QuantDinger Python 戦略開発ガイド

このガイドでは、QuantDingerプラットフォームでPythonを使用して取引戦略を開発する方法について詳しく説明します。QuantDingerは、データアクセス、インジケーター計算、シグナル生成をサポートする柔軟な実行環境を提供します。

## 1. 概要

QuantDingerの戦略は、**シグナルプロバイダー（Signal Provider）** モードに基づいて動作します。システムはPythonスクリプトを実行し、スクリプトは市場データ（DataFrame）を処理して取引シグナルを出力します。

実行フローは以下の通りです：
1.  **入力**: システムは、OHLCVデータを含む `df`（Pandas DataFrame）をスクリプト環境に注入します。
2.  **処理**: Python（`pandas`、`numpy`）を使用してインジケーターを計算し、`buy`/`sell` ロジックを定義します。
3.  **出力**: プロットデータとシグナルを含む特定の `output` 辞書を構築します。

---

## 2. 環境とデータ

スクリプトはサンドボックス化されたPython環境で実行されます。

### 2.1 プリインポートされたライブラリ
以下のライブラリはデフォルトで利用可能です（`import` する**必要はありません**）：
*   `pd` (pandas)
*   `np` (numpy)

### 2.2 入力データ (`df`)
`df` という名前のPandas DataFrame変数が自動的にグローバルスコープに存在します。これには、選択された銘柄と時間枠の過去の市場データが含まれています。

**列 (Columns):**
*   `time`: タイムスタンプ (datetime または int、コンテキストによる)
*   `open`: 始値 (float)
*   `high`: 高値 (float)
*   `low`: 安値 (float)
*   `close`: 終値 (float)
*   `volume`: 出来高 (float)

**例:**
```python
# 終値シリーズを取得
closes = df['close']

# 単純移動平均線 (SMA) を計算
sma_20 = df['close'].rolling(20).mean()
```

---

## 3. 戦略の開発

標準的な戦略スクリプトは、3つの部分で構成されます：
1.  **インジケーター計算**: テクニカル指標を計算します。
2.  **シグナル生成**: 買いと売りのシグナルロジックを定義します。
3.  **出力の構築**: チャート表示と実行エンジンのための結果をフォーマットします。

### 3.1 インジケーター計算
標準的なPandas操作を使用してインジケーターを計算できます。

```python
# 例: MACD 計算
short_window = 12
long_window = 26
signal_window = 9

ema12 = df['close'].ewm(span=short_window, adjust=False).mean()
ema26 = df['close'].ewm(span=long_window, adjust=False).mean()
macd = ema12 - ema26
signal_line = macd.ewm(span=signal_window, adjust=False).mean()
```

### 3.2 シグナル生成 (重要)

`df` 内に（または独立した変数として）`buy` と `sell` という名前の2つのブール型Seriesを **作成する必要があります**。

*   `True` はシグナルトリガーを示します。
*   `False` はシグナルなしを示します。

**重要: エッジトリガー (Edge Triggering)**
連続したローソク足でシグナルが繰り返し発生するのを防ぐため（バックエンドの設定によっては重複注文につながる可能性があります）、**エッジトリガー** シグナル（条件が真になった瞬間にのみシグナルを出す）を使用するのがベストプラクティスです。

```python
# 条件: 終値が SMA 20 を上抜け
condition_buy = (df['close'] > sma_20) & (df['close'].shift(1) <= sma_20.shift(1))

# 条件: 終値が SMA 20 を下抜け
condition_sell = (df['close'] < sma_20) & (df['close'].shift(1) >= sma_20.shift(1))

# df に代入 (バックテストに必須)
df['buy'] = condition_buy.fillna(False)
df['sell'] = condition_sell.fillna(False)
```

**シグナルタイプに関する注意:**
*   QuantDingerは、戦略設定（ロングのみ、ショートのみ、または両方向）に基づいてシグナルを正規化します。
*   スクリプトは単に "buy"（強気）または "sell"（弱気）を出力するだけです。バックエンドがエントリー/エグジットロジックを処理します。

### 3.3 視覚的マーカー
チャートに表示するために、通常はシグナルアイコンをローソク足の上または下に配置します。

```python
# 買いマーカーを安値の 0.5% 下に配置
buy_marks = [
    df['low'].iloc[i] * 0.995 if df['buy'].iloc[i] else None 
    for i in range(len(df))
]

# 売りマーカーを高値の 0.5% 上に配置
sell_marks = [
    df['high'].iloc[i] * 1.005 if df['sell'].iloc[i] else None 
    for i in range(len(df))
]
```

### 3.4 `output` 変数 (必須)
最後のステップは、辞書を変数 `output` に代入することです。これにより、フロントエンドに描画内容を伝え、バックエンドにシグナルの場所を伝えます。

**構造:**
```python
output = {
    "name": "私の戦略名",
    "plots": [ ... ],   # 描画するライン/インジケーターのリスト
    "signals": [ ... ]  # シグナルマーカーのリスト
}
```

**Plots Schema (描画設定):**
*   `name`: 凡例名 (例: "SMA 20")
*   `data`: 値のリスト (`df` と同じ長さである必要があります)。`.tolist()` を使用して変換します。
*   `color`: 16進数カラー文字列 (例: "#ff0000")。
*   `overlay`: `True` はメインチャート（価格）上に描画、`False` はサブチャート（RSI/MACDなど）に描画します。

**Signals Schema (シグナル設定):**
*   `type`: "buy" または "sell" である必要があります。
*   `text`: アイコンに表示するテキスト (例: "B", "S")。
*   `data`: 値のリスト（価格位置）。シグナルがない場所は `None`。
*   `color`: アイコンの色。

---

## 4. 完全な例: ダブル移動平均線クロスオーバー (Dual SMA)

以下は、SMA(10) が SMA(30) を上抜けたときに買い、下抜けたときに売る、完全でコピー可能な戦略の例です。

```python
# 1. インジケーター計算
# -----------------------
# 短期と長期の SMA を計算
sma_short = df['close'].rolling(10).mean()
sma_long = df['close'].rolling(30).mean()

# 2. シグナルロジック
# -----------------------
# 買い: 短期 SMA が 長期 SMA を上抜け
raw_buy = (sma_short > sma_long) & (sma_short.shift(1) <= sma_long.shift(1))

# 売り: 短期 SMA が 長期 SMA を下抜け
raw_sell = (sma_short < sma_long) & (sma_short.shift(1) >= sma_long.shift(1))

# NaN をクリーンアップし、ブール型を確保
buy = raw_buy.fillna(False)
sell = raw_sell.fillna(False)

# df 列に代入 (バックエンド実行の鍵)
df['buy'] = buy
df['sell'] = sell

# 3. 視覚フォーマット
# -----------------------
# マーカー位置を計算
buy_marks = [
    df['low'].iloc[i] * 0.995 if buy.iloc[i] else None 
    for i in range(len(df))
]

sell_marks = [
    df['high'].iloc[i] * 1.005 if sell.iloc[i] else None 
    for i in range(len(df))
]

# 4. 最終出力
# -----------------------
output = {
  'name': 'Dual SMA Strategy',
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
        'text': 'B',
        'data': buy_marks,
        'color': '#00E676'
    },
    {
        'type': 'sell',
        'text': 'S',
        'data': sell_marks,
        'color': '#FF5252'
    }
  ]
}
```

## 5. ベストプラクティスとトラブルシューティング

### 5.1 NaN の処理
ローリング計算（`rolling(14)` など）は、データの先頭に `NaN` 値を生成します。
*   **ルール**: シグナルを生成する前に必ず `NaN` を処理してください。
*   **修正**: コンテキストに応じて `.fillna(0)` または `.fillna(False)` を使用します。

### 5.2 先読みバイアス (Look-ahead Bias)
システムは、ローソク足の **終値** で発生したシグナルに基づいて取引を実行します。
*   バックテストエンジンは通常、**次のローソク足の始値** で注文を実行します。
*   シグナルロジックは `close`（現在の完了したローソク足）または `shift(1)`（前のローソク足）に依存する必要があります。`shift(-1)` は絶対に使用しないでください。

### 5.3 パフォーマンス
計算ロジックで DataFrame の行を反復処理すること（`for i in range(len(df)): ...`）は避けてください。非常に遅くなります。
*   **悪い例**: ループを使用して SMA を計算する。
*   **良い例**: `df['close'].rolling(...)` を使用する。
*   **例外**: `buy_marks`/`sell_marks` リストの構築には通常リスト内包表記が必要ですが、これは視覚的出力のみに使用されるため許容されます。

### 5.4 デバッグ
一部の実行モードでは `print()` 出力を簡単に確認できないため、戦略のロードに失敗した場合はバックエンドのログ（`backend_api_python/logs/app.log`）を確認してください。
*   一般的なエラー: `KeyError`（列名の間違い）。
*   一般的なエラー: `ValueError`（配列の長さが不一致）。`plots` のデータ長が `df` と一致していることを確認してください。

