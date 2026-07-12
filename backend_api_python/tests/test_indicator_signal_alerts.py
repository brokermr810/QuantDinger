from __future__ import annotations

import pandas as pd

from app.services.indicator_signal_alerts import IndicatorSignalAlertService


def _df(count: int = 4) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": list(range(count)),
            "open": [10.0 + i for i in range(count)],
            "high": [10.5 + i for i in range(count)],
            "low": [9.5 + i for i in range(count)],
            "close": [10.2 + i for i in range(count)],
            "volume": [100.0 for _ in range(count)],
        }
    )


def test_signal_alert_static_text_does_not_trigger_every_bar():
    service = IndicatorSignalAlertService()
    output = {
        "signals": [
            {
                "type": "buy",
                "text": "Cross Up",
                "data": [None, 9.9, None, None],
            }
        ]
    }

    assert service._latest_matching_signal(output, _df(4), ["any"]) is None


def test_signal_alert_uses_closed_signal_bar_on_next_bar_open():
    service = IndicatorSignalAlertService()
    output = {
        "signals": [
            {
                "type": "buy",
                "text": "Cross Up",
                "data": [None, None, 11.9, None],
            }
        ]
    }

    signal = service._latest_matching_signal(output, _df(4), ["any"])

    assert signal is not None
    assert signal["label"] == "Cross Up"
    assert signal["bar_index"] == 2
    assert signal["bar_time"] == "1970-01-01T00:00:02"
    assert signal["notify_bar_index"] == 3
