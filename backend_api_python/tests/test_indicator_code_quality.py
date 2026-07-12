"""Tests for indicator_code_quality heuristics."""

from app.services.indicator_code_quality import analyze_indicator_code_quality


def test_empty_code():
    hints = analyze_indicator_code_quality("")
    assert any(h["code"] == "EMPTY_CODE" for h in hints)


def test_minimal_valid_style():
    code = """
my_indicator_name = "T"
my_indicator_description = "D"
df = df.copy()
buy_signal = df['close'] > df['close'].rolling(10).mean()
output = {'name': 'T', 'plots': [], 'signals': []}
"""
    hints = analyze_indicator_code_quality(code)
    codes = {h["code"] for h in hints}
    assert "MISSING_OUTPUT" not in codes
    assert "STRATEGY_ANNOTATIONS_IGNORED_FOR_INDICATOR" not in codes


def test_execution_columns_are_ignored_for_chart_indicators():
    code = """
my_indicator_name = "T"
my_indicator_description = "D"
df = df.copy()
df['open_long'] = True
df['close_long'] = False
df['open_short'] = True
df['close_short'] = False
output = {'name': 'T', 'plots': [], 'signals': []}
"""
    hints = analyze_indicator_code_quality(code)
    codes = [h["code"] for h in hints]
    assert "EXECUTION_COLUMNS_IGNORED_FOR_INDICATOR" in codes


def test_strategy_annotations_are_ignored_for_chart_indicators():
    code = """
my_indicator_name = "T"
my_indicator_description = "D"
# @strategy tradeDirection long
# @strategy entryPct 1
df = df.copy()
output = {'name': 'T', 'plots': [], 'signals': []}
"""
    hints = analyze_indicator_code_quality(code)
    assert any(h["code"] == "STRATEGY_ANNOTATIONS_IGNORED_FOR_INDICATOR" for h in hints)


def test_strategy_signal_form_metadata_is_blocked_for_chart_indicators():
    code = """
my_indicator_name = "T"
my_indicator_description = "D"
# signal_form: four_way
# exit_owner: indicator
# flip_mode: R2
df = df.copy()
output = {'name': 'T', 'plots': [], 'signals': []}
"""
    hints = analyze_indicator_code_quality(code)
    match = [h for h in hints if h["code"] == "STRATEGY_ANNOTATIONS_IGNORED_FOR_INDICATOR"]
    assert match
    assert match[0]["severity"] == "error"


def test_legacy_leverage_line_not_flagged_unknown():
    code = """
my_indicator_name = "T"
my_indicator_description = "D"
# @strategy leverage 2
df = df.copy()
output = {'name': 'T', 'plots': [], 'signals': []}
"""
    hints = analyze_indicator_code_quality(code)
    assert not any(h["code"] == "UNKNOWN_STRATEGY_KEY" for h in hints)
    assert any(h["code"] == "STRATEGY_ANNOTATIONS_IGNORED_FOR_INDICATOR" for h in hints)


def test_unknown_strategy_keys_are_no_longer_parsed_on_indicators():
    code = """
my_indicator_name = "T"
my_indicator_description = "D"
# @strategy signalTiming same_bar_close
df = df.copy()
output = {'name': 'T', 'plots': [], 'signals': []}
"""
    hints = analyze_indicator_code_quality(code)
    assert not any(h["code"] == "UNKNOWN_STRATEGY_KEY" for h in hints)
    assert any(h["code"] == "STRATEGY_ANNOTATIONS_IGNORED_FOR_INDICATOR" for h in hints)


def test_declared_params_must_be_read_via_params_get():
    code = """
my_indicator_name = "T"
my_indicator_description = "D"
# @param fast_period int 10 Fast MA
df = df.copy()
ma = df['close'].rolling(window=fast_period).mean()
output = {'name': 'T', 'plots': [], 'signals': []}
"""
    hints = analyze_indicator_code_quality(code)
    assert any(h["code"] == "DECLARED_PARAMS_NOT_READ_VIA_PARAMS_GET" for h in hints)


def test_declared_params_read_via_params_get_is_ok():
    code = """
my_indicator_name = "T"
my_indicator_description = "D"
# @param fast_period int 10 Fast MA
fast_period = params.get('fast_period', 10)
df = df.copy()
ma = df['close'].rolling(window=fast_period).mean()
output = {'name': 'T', 'plots': [], 'signals': []}
"""
    hints = analyze_indicator_code_quality(code)
    assert not any(h["code"] == "DECLARED_PARAMS_NOT_READ_VIA_PARAMS_GET" for h in hints)


def test_declared_params_read_via_params_helper_is_ok():
    code = """
my_indicator_name = "T"
my_indicator_description = "D"
# @param fast_period int 10 Fast MA
# @param strict_mode bool true Strict mode
try:
    params
except NameError:
    params = {}

def _param(name, default, cast):
    try:
        return cast(params.get(name, default))
    except Exception:
        return default

fast_period = _param("fast_period", 10, int)
strict_mode = _param("strict_mode", True, bool)
df = df.copy()
ma = df['close'].rolling(window=fast_period).mean()
output = {'name': 'T', 'plots': [], 'signals': [], 'calculatedVars': {'strict': strict_mode}}
"""
    hints = analyze_indicator_code_quality(code)
    assert not any(h["code"] == "DECLARED_PARAMS_NOT_READ_VIA_PARAMS_GET" for h in hints)


def test_four_way_columns_no_missing_buy_sell_warn():
    code = """
my_indicator_name = "T"
my_indicator_description = "D"
# @strategy stopLossPct 0.02
# @strategy takeProfitPct 0.04
df = df.copy()
df['open_long'] = False
df['close_long'] = False
df['open_short'] = False
df['close_short'] = False
output = {'name': 'T', 'plots': [], 'signals': []}
"""
    hints = analyze_indicator_code_quality(code)
    codes = {h["code"] for h in hints}
    assert "MISSING_BUY_SELL_COLUMNS" not in codes
    assert "EXECUTION_COLUMNS_IGNORED_FOR_INDICATOR" in codes
    assert "STRATEGY_ANNOTATIONS_IGNORED_FOR_INDICATOR" in codes


def test_where_none_signal_markers_warned():
    code = """
my_indicator_name = "T"
my_indicator_description = "D"
df = df.copy()
entry_marks = df['close'].where(df['close'] > df['close'].rolling(5).mean(), None).tolist()
output = {'name': 'T', 'plots': [], 'signals': [{'type': 'entry', 'data': entry_marks}]}
"""
    hints = analyze_indicator_code_quality(code)
    assert any(h["code"] == "SIGNAL_MARKERS_USE_WHERE_NONE" for h in hints)
