import ast
import re
from typing import Any, Dict, List


RUN_PANEL_PARAM_NAMES = {
    "direction",
    "trade_direction",
    "market_type",
    "symbol",
    "timeframe",
    "investment_amount",
    "initial_capital",
    "leverage",
    "base_notional",
}


def _literal_string(node: ast.AST | None) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def _ctx_param_calls(raw: str) -> List[Dict[str, Any]]:
    try:
        tree = ast.parse(raw)
    except SyntaxError:
        return []

    calls: List[Dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "param"
            and isinstance(func.value, ast.Name)
            and func.value.id == "ctx"
        ):
            calls.append({
                "name": _literal_string(node.args[0] if node.args else None),
                "argc": len(node.args),
                "lineno": getattr(node, "lineno", 0),
            })
    return calls


def _basket_contract_hints(raw: str) -> List[Dict[str, Any]]:
    try:
        tree = ast.parse(raw)
    except SyntaxError:
        return []

    hints: List[Dict[str, Any]] = []
    invalid_sides: List[Dict[str, Any]] = []
    missing_child_order_args: List[Dict[str, Any]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "open_child_order"
        ):
            keyword_names = {str(kw.arg) for kw in node.keywords if kw.arg}
            missing = [name for name in ("layer", "order") if name not in keyword_names]
            if missing:
                missing_child_order_args.append({
                    "line": getattr(node, "lineno", 0),
                    "missing": missing,
                })
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "basket"
            and isinstance(func.value, ast.Name)
            and func.value.id == "ctx"
        ):
            side = _literal_string(node.args[0] if node.args else None).strip().lower()
            if side and side not in {"long", "short"}:
                invalid_sides.append({
                    "side": side,
                    "line": getattr(node, "lineno", 0),
                })

    if missing_child_order_args:
        hints.append({
            "severity": "error",
            "code": "BASKET_CHILD_ORDER_MISSING_LAYER_ORDER",
            "params": {
                "calls": missing_child_order_args[:8],
                "count": len(missing_child_order_args),
            },
        })
    if invalid_sides:
        hints.append({
            "severity": "warn",
            "code": "BASKET_SIDE_MUST_BE_LONG_OR_SHORT",
            "params": {
                "calls": invalid_sides[:8],
                "count": len(invalid_sides),
            },
        })
    return hints


def analyze_strategy_code_quality(code: str) -> List[Dict[str, Any]]:
    hints: List[Dict[str, Any]] = []
    raw = (code or "").strip()
    if not raw:
        return [{"severity": "error", "code": "EMPTY_CODE", "params": {}}]

    has_on_init = bool(re.search(r"^\s*def\s+on_init\s*\(", raw, re.MULTILINE))
    has_on_bar = bool(re.search(r"^\s*def\s+on_bar\s*\(", raw, re.MULTILINE))
    has_ctx_param = bool(re.search(r"\bctx\.param\s*\(", raw))
    has_order_intent = bool(
        re.search(
            r"\bctx\.(buy|sell|close_position|open_long|add_long|close_long|reduce_long|open_short|add_short|close_short|reduce_short|order_value|order_target|basket)\s*\(",
            raw,
        )
    )

    if not has_on_init:
        hints.append({"severity": "warn", "code": "MISSING_ON_INIT", "params": {}})
    if not has_on_bar:
        hints.append({"severity": "error", "code": "MISSING_ON_BAR", "params": {}})
    if not has_ctx_param:
        hints.append({"severity": "info", "code": "NO_CTX_PARAM_DEFAULTS", "params": {}})
    if not has_order_intent:
        hints.append({"severity": "info", "code": "NO_ORDER_INTENT", "params": {}})
    if (
        has_order_intent
        and "ctx.investment_amount" in raw
        and "ctx.available_capital" not in raw
        and "ctx.equity" not in raw
    ):
        hints.append({
            "severity": "warn",
            "code": "INITIAL_STAKE_WITHOUT_DYNAMIC_CAPITAL",
            "params": {},
        })

    if re.search(r"^\s*output\s*=\s*\{|^\s*(plots|layers|signals|calculatedVars)\s*=", raw, re.MULTILINE):
        hints.append({"severity": "error", "code": "INDICATOR_OUTPUT_CONTRACT", "params": {}})

    param_calls = _ctx_param_calls(raw)
    params_with_defaults = {
        str(call.get("name") or "")
        for call in param_calls
        if call.get("name") and call.get("argc", 0) >= 2
    }
    no_default = []
    run_panel_params = []
    for call in param_calls:
        name = call.get("name") or ""
        if call.get("argc", 0) < 2 and name not in params_with_defaults:
            no_default.append({"name": name or "unknown", "line": call.get("lineno", 0)})
        if name in RUN_PANEL_PARAM_NAMES:
            run_panel_params.append({"name": name, "line": call.get("lineno", 0)})
    if no_default:
        hints.append({
            "severity": "warn",
            "code": "CTX_PARAM_MISSING_DEFAULT",
            "params": {"calls": no_default[:8], "count": len(no_default)},
        })
    if run_panel_params:
        hints.append({
            "severity": "error",
            "code": "CTX_PARAM_RUN_PANEL_FIELD",
            "params": {"calls": run_panel_params[:8], "count": len(run_panel_params)},
        })
    hints.extend(_basket_contract_hints(raw))

    has_short_order = bool(re.search(r"\b(open_short|add_short|close_short)\s*\(|\.basket\s*\(\s*['\"]short['\"]", raw))
    bullish_names = bool(re.search(r"\b(red_count|red_signal|buy_signal|bull|bullish|entry_red|buy)\b", raw, re.IGNORECASE))
    if has_short_order and bullish_names:
        hints.append({
            "severity": "warn",
            "code": "POSSIBLE_BULLISH_SIGNAL_FOR_SHORT",
            "params": {},
        })
    return hints


def validate_strategy_code(code: str) -> Dict[str, Any]:
    from app.services.strategy_script_runtime import compile_strategy_script_handlers

    raw = (code or "").strip()
    hints = analyze_strategy_code_quality(raw)
    if not raw:
        return {
            "success": False,
            "message": "Code is empty",
            "error_type": "EmptyCode",
            "details": None,
            "hints": hints,
        }

    try:
        compile(raw, "<strategy>", "exec")
    except SyntaxError as se:
        return {
            "success": False,
            "message": f"Syntax error at line {se.lineno}: {se.msg}",
            "error_type": "SyntaxError",
            "details": str(se),
            "hints": hints,
        }

    required_funcs = ["on_bar", "on_init"]
    found = [func for func in required_funcs if f"def {func}" in raw]
    missing = [func for func in required_funcs if func not in found]
    if missing:
        return {
            "success": False,
            "message": f"Missing required functions: {', '.join(missing)}",
            "error_type": "MissingFunctions",
            "details": None,
            "hints": hints,
        }

    error_hints = [hint for hint in hints if hint.get("severity") == "error"]
    if error_hints:
        codes = ", ".join(str(hint.get("code") or "UNKNOWN") for hint in error_hints)
        return {
            "success": False,
            "message": f"Strategy quality checks failed: {codes}",
            "error_type": "QualityError",
            "details": None,
            "hints": hints,
        }

    try:
        compile_strategy_script_handlers(raw)
    except Exception as exc:
        return {
            "success": False,
            "message": f"Runtime Error: {exc}",
            "error_type": "RuntimeError",
            "details": str(exc),
            "hints": hints,
        }

    return {
        "success": True,
        "message": "Code verification passed",
        "error_type": None,
        "details": None,
        "hints": hints,
    }


def strategy_debug_summary(validation: Dict[str, Any] | None = None) -> Dict[str, Any]:
    validation = validation or {}
    hints = validation.get("hints") or []
    return {
        "success": bool(validation.get("success")),
        "message": validation.get("message"),
        "error_type": validation.get("error_type"),
        "hint_codes": [hint.get("code") for hint in hints if hint.get("code")],
        "warning_codes": [hint.get("code") for hint in hints if hint.get("severity") == "warn" and hint.get("code")],
        "error_codes": [hint.get("code") for hint in hints if hint.get("severity") == "error" and hint.get("code")],
        "hint_count": len(hints),
    }


def strategy_ai_text(key: str, lang: str = "zh-CN") -> str:
    texts = {
        "prompt_empty": "Prompt cannot be empty",
        "no_llm_key": "No LLM API key configured",
        "insufficient_credits": "Insufficient credits. Please top up and try again.",
        "invalid_json_params": "AI did not return valid JSON parameters",
        "ai_empty_result": "AI generation returned empty result",
        "success": "success",
    }
    return texts.get(key, key)


def strategy_hint_to_text(hint_code: str, params: Dict[str, Any] | None = None, lang: str = "zh-CN") -> str:
    params = params or {}
    if hint_code == "CTX_PARAM_MISSING_DEFAULT":
        count = params.get("count") or 0
        return f"Found {count} ctx.param(...) call(s) without defaults. Declare parameters in on_init as ctx.xxx = ctx.param('name', default)."
    if hint_code == "CTX_PARAM_RUN_PANEL_FIELD":
        names = ", ".join(sorted({str(item.get("name")) for item in params.get("calls", []) if item.get("name")}))
        return f"Run-panel fields must not be declared with ctx.param: {names}. Read them from ctx.direction / ctx.market_type / ctx.investment_amount / ctx.leverage."
    if hint_code == "INDICATOR_OUTPUT_CONTRACT":
        return "Indicator output structures were detected. ScriptStrategy code must not keep output/plots/layers/signals contracts."
    if hint_code == "BASKET_CHILD_ORDER_MISSING_LAYER_ORDER":
        return "ctx.basket(...).open_child_order(...) must include layer= and order= keyword arguments."
    if hint_code == "BASKET_SIDE_MUST_BE_LONG_OR_SHORT":
        return "ctx.basket(side) expects 'long' or 'short', not 'buy'/'sell'."
    if hint_code == "POSSIBLE_BULLISH_SIGNAL_FOR_SHORT":
        return "The script may use bullish/buy-style signals for short entries. Indicator conversion should default to long-only unless explicit bearish short rules are provided."
    if hint_code == "INITIAL_STAKE_WITHOUT_DYNAMIC_CAPITAL":
        return "The script sizes from ctx.investment_amount only. Use ctx.available_capital with an investment_amount fallback when the intended sizing should compound after profits or losses."
    texts = {
        "MISSING_ON_INIT": "Missing on_init(ctx) function.",
        "MISSING_ON_BAR": "Missing on_bar(ctx, bar) function.",
        "NO_CTX_PARAM_DEFAULTS": "No parameter defaults were declared via ctx.param(...).",
        "NO_ORDER_INTENT": "No explicit order intent was detected. Use ctx.open_long/add_long/close_long or ctx.open_short/add_short/close_short.",
        "EMPTY_CODE": "Strategy code is empty.",
    }
    return texts.get(hint_code, f"Strategy hint detected: {hint_code}")

def strategy_human_summary(
    initial_validation: Dict[str, Any],
    final_validation: Dict[str, Any],
    auto_fix_applied: bool,
    auto_fix_succeeded: bool,
    returned_candidate: str,
    lang: str = "zh-CN",
) -> Dict[str, Any]:
    initial_hints = initial_validation.get("hints") or []
    final_hints = final_validation.get("hints") or []
    initial_codes = {hint.get("code") for hint in initial_hints if hint.get("code")}
    final_codes = {hint.get("code") for hint in final_hints if hint.get("code")}
    fixed_codes = sorted(initial_codes - final_codes)
    remaining_codes = sorted(final_codes)

    fixed_messages = [
        strategy_hint_to_text(hint.get("code"), hint.get("params"), lang=lang)
        for hint in initial_hints
        if hint.get("code") in fixed_codes
    ]
    remaining_messages = [
        strategy_hint_to_text(hint.get("code"), hint.get("params"), lang=lang)
        for hint in final_hints
        if hint.get("code") in remaining_codes
    ]

    if auto_fix_applied and auto_fix_succeeded:
        title = "AI auto-fixed the strategy code and returned a more stable version"
    elif auto_fix_applied:
        title = "AI attempted to auto-fix the strategy code, but some issues still remain"
    else:
        title = "AI generated strategy code and it passed the current QA flow"

    returned_text = (
        "The returned code is the auto-fixed version."
        if returned_candidate == "repaired"
        else "The returned code is the initially generated version."
    )

    return {
        "title": title,
        "returned_text": returned_text,
        "fixed_messages": fixed_messages,
        "remaining_messages": remaining_messages,
    }
