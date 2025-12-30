# QuantDinger Python 전략 개발 가이드

이 가이드는 QuantDinger 플랫폼에서 Python을 사용하여 거래 전략을 개발하는 방법을 자세히 설명합니다. QuantDinger는 데이터 액세스, 지표 계산 및 신호 생성을 지원하는 유연한 실행 환경을 제공합니다.

## 1. 개요

QuantDinger의 전략은 **신호 제공자(Signal Provider)** 모드를 기반으로 작동합니다. 시스템은 귀하의 Python 스크립트를 실행하며, 이 스크립트는 시장 데이터(DataFrame)를 처리하고 거래 신호를 출력합니다.

실행 흐름은 다음과 같습니다:
1.  **입력**: 시스템은 OHLCV 데이터를 포함하는 `df`(Pandas DataFrame)를 스크립트 환경에 주입합니다.
2.  **처리**: Python(`pandas`, `numpy`)을 사용하여 지표를 계산하고 `buy`/`sell` 로직을 정의합니다.
3.  **출력**: 플롯 데이터와 신호를 포함하는 특정 `output` 딕셔너리를 구성합니다.

---

## 2. 환경 및 데이터

스크립트는 샌드박스 처리된 Python 환경에서 실행됩니다.

### 2.1 사전 가져오기된 라이브러리
다음 라이브러리는 기본적으로 사용할 수 있습니다(`import`할 **필요 없음**):
*   `pd` (pandas)
*   `np` (numpy)

### 2.2 입력 데이터 (`df`)
`df`라는 이름의 Pandas DataFrame 변수가 전역 범위에 자동으로 존재합니다. 여기에는 선택한 심볼 및 시간대의 과거 시장 데이터가 포함되어 있습니다.

**열 (Columns):**
*   `time`: 타임스탬프 (datetime 또는 int, 컨텍스트에 따라 다름)
*   `open`: 시가 (float)
*   `high`: 고가 (float)
*   `low`: 저가 (float)
*   `close`: 종가 (float)
*   `volume`: 거래량 (float)

**예시:**
```python
# 종가 시리즈 가져오기
closes = df['close']

# 단순 이동 평균(SMA) 계산
sma_20 = df['close'].rolling(20).mean()
```

---

## 3. 전략 개발

표준 전략 스크립트는 세 부분으로 구성됩니다:
1.  **지표 계산**: 기술적 지표를 계산합니다.
2.  **신호 생성**: 매수 및 매도 신호 로직을 정의합니다.
3.  **출력 구성**: 차트 표시 및 실행 엔진을 위한 결과를 포맷팅합니다.

### 3.1 지표 계산
표준 Pandas 연산을 사용하여 지표를 계산할 수 있습니다.

```python
# 예시: MACD 계산
short_window = 12
long_window = 26
signal_window = 9

ema12 = df['close'].ewm(span=short_window, adjust=False).mean()
ema26 = df['close'].ewm(span=long_window, adjust=False).mean()
macd = ema12 - ema26
signal_line = macd.ewm(span=signal_window, adjust=False).mean()
```

### 3.2 신호 생성 (중요)

`df` 내에(또는 독립 변수로) `buy`와 `sell`이라는 이름의 두 개의 불리언(Boolean) Series를 **반드시 생성해야 합니다**.

*   `True`는 신호 트리거를 나타냅니다.
*   `False`는 신호 없음을 나타냅니다.

**중요: 엣지 트리거(Edge Triggering)**
연속된 캔들에서 반복적으로 신호가 발생하는 것을 방지하기 위해(백엔드 설정에 따라 중복 주문으로 이어질 수 있음), **엣지 트리거** 신호(조건이 참이 되는 순간에만 신호 발생)를 사용하는 것이 모범 사례입니다.

```python
# 조건: 종가가 SMA 20 상향 돌파
condition_buy = (df['close'] > sma_20) & (df['close'].shift(1) <= sma_20.shift(1))

# 조건: 종가가 SMA 20 하향 돌파
condition_sell = (df['close'] < sma_20) & (df['close'].shift(1) >= sma_20.shift(1))

# df에 할당 (백테스팅에 필수)
df['buy'] = condition_buy.fillna(False)
df['sell'] = condition_sell.fillna(False)
```

**신호 유형에 대한 참고:**
*   QuantDinger는 전략 구성(롱 전용, 숏 전용 또는 양방향)에 따라 신호를 정규화합니다.
*   스크립트는 단순히 "buy"(강세 의도) 또는 "sell"(약세 의도)을 출력하면 됩니다. 백엔드가 진입/청산 로직을 처리합니다.

### 3.3 시각적 마커
차트에 표시하기 위해 일반적으로 신호 아이콘을 캔들 위나 아래에 배치합니다.

```python
# 매수 마커를 저가보다 0.5% 아래에 배치
buy_marks = [
    df['low'].iloc[i] * 0.995 if df['buy'].iloc[i] else None 
    for i in range(len(df))
]

# 매도 마커를 고가보다 0.5% 위에 배치
sell_marks = [
    df['high'].iloc[i] * 1.005 if df['sell'].iloc[i] else None 
    for i in range(len(df))
]
```

### 3.4 `output` 변수 (필수)
마지막 단계는 `output` 변수에 딕셔너리를 할당하는 것입니다. 이는 프론트엔드에 무엇을 그릴지, 백엔드에 신호가 어디에 있는지를 알려줍니다.

**구조:**
```python
output = {
    "name": "내 전략 이름",
    "plots": [ ... ],   # 그릴 라인/지표 목록
    "signals": [ ... ]  # 신호 마커 목록
}
```

**Plots Schema (플롯 구성):**
*   `name`: 범례 이름 (예: "SMA 20")
*   `data`: 값 목록 (`df` 길이와 일치해야 함). `.tolist()`를 사용하여 변환.
*   `color`: 16진수 색상 문자열 (예: "#ff0000").
*   `overlay`: `True`는 메인 차트(가격) 위에 그리기, `False`는 보조 차트(RSI/MACD 등)에 그리기.

**Signals Schema (신호 구성):**
*   `type`: "buy" 또는 "sell"이어야 합니다.
*   `text`: 아이콘에 표시할 텍스트 (예: "B", "S").
*   `data`: 값 목록 (가격 위치). 신호 없는 곳은 `None`.
*   `color`: 아이콘 색상.

---

## 4. 전체 예제: 이중 이동 평균 교차 (Dual SMA)

다음은 SMA(10)이 SMA(30)을 상향 돌파할 때 매수하고, 하향 돌파할 때 매도하는 전체 복사 가능한 전략 예제입니다.

```python
# 1. 지표 계산
# -----------------------
# 단기 및 장기 SMA 계산
sma_short = df['close'].rolling(10).mean()
sma_long = df['close'].rolling(30).mean()

# 2. 신호 로직
# -----------------------
# 매수: 단기 SMA가 장기 SMA 상향 돌파
raw_buy = (sma_short > sma_long) & (sma_short.shift(1) <= sma_long.shift(1))

# 매도: 단기 SMA가 장기 SMA 하향 돌파
raw_sell = (sma_short < sma_long) & (sma_short.shift(1) >= sma_long.shift(1))

# NaN 정리 및 불리언 타입 보장
buy = raw_buy.fillna(False)
sell = raw_sell.fillna(False)

# df 열에 할당 (백엔드 실행의 핵심)
df['buy'] = buy
df['sell'] = sell

# 3. 시각적 포맷팅
# -----------------------
# 마커 위치 계산
buy_marks = [
    df['low'].iloc[i] * 0.995 if buy.iloc[i] else None 
    for i in range(len(df))
]

sell_marks = [
    df['high'].iloc[i] * 1.005 if sell.iloc[i] else None 
    for i in range(len(df))
]

# 4. 최종 출력
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

## 5. 모범 사례 및 문제 해결

### 5.1 NaN 처리
롤링 계산(`rolling(14)` 등)은 데이터 시작 부분에 `NaN` 값을 생성합니다.
*   **규칙**: 신호를 생성하기 전에 항상 `NaN`을 처리하십시오.
*   **수정**: 상황에 따라 `.fillna(0)` 또는 `.fillna(False)`를 사용하십시오.

### 5.2 미래 참조 편향 (Look-ahead Bias)
시스템은 캔들의 **종가**에서 발생한 신호를 기반으로 거래를 실행합니다.
*   백테스트 엔진은 일반적으로 **다음 캔들의 시가**에서 주문을 실행합니다.
*   신호 로직은 `close`(현재 완료된 캔들) 또는 `shift(1)`(이전 캔들)에 의존해야 합니다. `shift(-1)`은 절대 사용하지 마십시오.

### 5.3 성능
계산 로직에서 DataFrame 행을 반복(`for i in range(len(df)): ...`)하는 것을 피하십시오. 매우 느립니다.
*   **나쁨**: 루프를 사용하여 SMA 계산.
*   **좋음**: `df['close'].rolling(...)` 사용.
*   **예외**: `buy_marks`/`sell_marks` 리스트 구성에는 일반적으로 리스트 컴프리헨션이 필요하며, 이는 시각적 출력에만 사용되므로 허용됩니다.

### 5.4 디버깅
일부 실행 모드에서는 `print()` 출력을 쉽게 볼 수 없으므로, 전략 로드에 실패하면 백엔드 로그(`backend_api_python/logs/app.log`)를 확인하십시오.
*   일반적인 오류: `KeyError` (잘못된 열 이름).
*   일반적인 오류: `ValueError` (배열 길이 불일치). `plots`의 데이터 길이가 `df`와 일치하는지 확인하십시오.

