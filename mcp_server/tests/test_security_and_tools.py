"""MCP security + tool registry tests."""
from __future__ import annotations

import importlib
import sys

import pytest

pytest.importorskip("mcp")


@pytest.fixture
def fresh_module(monkeypatch):
    monkeypatch.setenv("QUANTDINGER_BASE_URL", "http://localhost:8888")
    monkeypatch.setenv("QUANTDINGER_AGENT_TOKEN", "qd_agent_test_token")
    sys.modules.pop("quantdinger_mcp.server", None)
    sys.modules.pop("quantdinger_mcp.security", None)
    import os
    src_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "src")
    )
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    return importlib.import_module("quantdinger_mcp.server")


def test_mcp_tool_registry_complete(fresh_module):
    assert len(fresh_module.MCP_TOOL_NAMES) == 29
    # Every exported name should correspond to a registered @mcp.tool function.
    for name in fresh_module.MCP_TOOL_NAMES:
        assert hasattr(fresh_module, name), f"missing tool function: {name}"


def test_ai_optimize_requires_confirmation(fresh_module):
    out = fresh_module.submit_ai_optimize({"base": {}})
    assert out.get("error") is True
    assert out.get("status") == 400


def test_update_strategy_blocks_running_without_trade_scope(fresh_module):
    out = fresh_module.update_strategy(1, {"status": "running"})
    assert out.get("error") is True
    assert out.get("status") == 403


def test_create_strategy_rejects_legacy_indicator_strategy(fresh_module):
    out = fresh_module.create_strategy(
        "Legacy indicator strategy",
        "Crypto",
        {"symbol": "BTC/USDT"},
        strategy_type="IndicatorStrategy",
    )
    assert out.get("error") is True
    assert out.get("status") == 400
    assert "ScriptStrategy" in out["body"]["message"]


def test_create_strategy_requires_script_code_or_source_id(fresh_module):
    out = fresh_module.create_strategy(
        "Empty script strategy",
        "Crypto",
        {"symbol": "BTC/USDT"},
    )
    assert out.get("error") is True
    assert out.get("status") == 400


def test_stop_strategy_requires_confirmation(fresh_module):
    out = fresh_module.stop_strategy(1)
    assert out.get("error") is True
    assert out.get("status") == 400


def test_place_quick_order_requires_confirmation(fresh_module):
    out = fresh_module.place_quick_order("Crypto", "BTC/USDT", "buy", 0.001)
    assert out.get("error") is True
    assert out.get("status") == 400


def test_indicator_code_size_rejected_in_mcp(monkeypatch, fresh_module):
    from quantdinger_mcp import security as sec

    huge = "x" * (sec.MAX_INDICATOR_CODE_BYTES + 1)
    with pytest.raises(ValueError, match="KiB"):
        fresh_module.validate_indicator_code(huge)


def test_submit_backtest_uses_script_strategy_payload(monkeypatch, fresh_module):
    captured = {}

    def fake_post(path, json=None, headers=None):
        captured["path"] = path
        captured["json"] = json
        captured["headers"] = headers
        return {"job_id": "job-test"}

    monkeypatch.setattr(fresh_module, "_post", fake_post)
    out = fresh_module.submit_backtest(
        "def on_init(ctx):\n    pass\n\ndef on_bar(ctx, bar):\n    pass\n",
        "Crypto",
        "BTC/USDT",
        "1H",
        "2024-01-01",
        "2024-06-30",
        script_params={"fast": 10},
        market_type="swap",
        idempotency_key="same-key",
    )

    assert out == {"job_id": "job-test"}
    assert captured["path"] == "/api/agent/v1/backtest/run"
    assert captured["json"]["script_params"] == {"fast": 10}
    assert "indicator_params" not in captured["json"]
    assert captured["json"]["market_type"] == "swap"
    assert captured["headers"] == {"Idempotency-Key": "same-key"}


def test_parse_sse_chunk():
    from quantdinger_mcp.security import parse_sse_chunk

    text = (
        'event: snapshot\n'
        'data: {"status":"running"}\n\n'
        'event: result\n'
        'data: {"status":"succeeded"}\n\n'
    )
    frames = parse_sse_chunk(text)
    assert frames[0][0] == "snapshot"
    assert frames[1][0] == "result"
    assert frames[1][1]["status"] == "succeeded"
