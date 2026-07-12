import math

import pandas as pd

from app.services.fundamental_data import FundamentalDataService


def test_fundamentals_enter_panel_only_when_public_and_market_cap_can_be_derived(monkeypatch):
    service = FundamentalDataService()
    monkeypatch.setattr(
        service,
        "_load_rows",
        lambda market, symbol, end: [
            {
                "period_end": "2025-12-31",
                "available_at": "2026-01-05",
                "revenue": 500,
                "net_income": 50,
                "book_value": 300,
                "shareholder_equity": 300,
                "total_debt": 100,
                "free_cash_flow": 40,
                "shares_outstanding": 10,
                "market_cap": None,
            },
            {
                "period_end": "2026-03-31",
                "available_at": "2026-01-10",
                "revenue": 600,
                "net_income": 60,
                "book_value": 330,
                "shareholder_equity": 330,
                "total_debt": 90,
                "free_cash_flow": 45,
                "shares_outstanding": 11,
                "market_cap": 2_000,
            },
        ],
    )
    frame = pd.DataFrame(
        {"open": [100, 100, 100], "high": [100, 100, 100], "low": [100, 100, 100], "close": [100, 100, 100]},
        index=pd.to_datetime(["2026-01-01", "2026-01-05", "2026-01-10"]),
    )

    enriched = service.enrich_frame(market="USStock", symbol="AAA", frame=frame)

    assert math.isnan(enriched.loc["2026-01-01", "net_income"])
    assert enriched.loc["2026-01-05", "net_income"] == 50
    assert enriched.loc["2026-01-05", "market_cap"] == 1_000
    assert enriched.loc["2026-01-10", "net_income"] == 60
    assert enriched.loc["2026-01-10", "market_cap"] == 2_000
