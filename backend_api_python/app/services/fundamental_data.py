"""Point-in-time fundamental observations and panel enrichment."""

from __future__ import annotations

import json
from typing import Any, Mapping

import pandas as pd

from app.utils.db import get_db_connection
from app.utils.logger import get_logger

logger = get_logger(__name__)

FUNDAMENTAL_FIELDS = (
    "revenue",
    "net_income",
    "book_value",
    "shareholder_equity",
    "total_debt",
    "free_cash_flow",
    "shares_outstanding",
    "market_cap",
)


class FundamentalDataService:
    """Load only observations that were public at each simulated date."""

    def enrich_panel(
        self,
        frames: Mapping[str, pd.DataFrame],
        members: list[dict],
    ) -> dict[str, pd.DataFrame]:
        identities = {str(item.get("symbol") or "").upper(): str(item.get("market") or "") for item in members}
        output = {}
        for symbol, frame in frames.items():
            output[symbol] = self.enrich_frame(
                market=identities.get(symbol, ""),
                symbol=symbol,
                frame=frame,
            )
        return output

    def enrich_frame(self, *, market: str, symbol: str, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty or not market or not symbol:
            return frame
        try:
            rows = self._load_rows(market, symbol, frame.index.max())
        except Exception as exc:
            logger.warning("fundamental point-in-time load failed market=%s symbol=%s: %s", market, symbol, exc)
            return frame
        if not rows:
            return frame
        enriched = frame.copy()
        dates = pd.DatetimeIndex(enriched.index).normalize()
        observations = pd.DataFrame(rows)
        observations["available_at"] = pd.to_datetime(observations["available_at"])
        observations = observations.sort_values(["available_at", "period_end"]).drop_duplicates("available_at", keep="last")
        observations = observations.set_index("available_at")
        for field in FUNDAMENTAL_FIELDS:
            values = pd.to_numeric(observations[field], errors="coerce")
            enriched[field] = values.reindex(dates, method="ffill").to_numpy()
        derived_market_cap = pd.to_numeric(enriched["close"], errors="coerce") * pd.to_numeric(
            enriched["shares_outstanding"], errors="coerce"
        )
        enriched["market_cap"] = pd.to_numeric(enriched["market_cap"], errors="coerce").fillna(derived_market_cap)
        return enriched

    @staticmethod
    def _load_rows(market: str, symbol: str, end: Any) -> list[dict]:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                SELECT period_end, available_at, revenue, net_income, book_value,
                       shareholder_equity, total_debt, free_cash_flow,
                       shares_outstanding, market_cap
                FROM qd_fundamental_snapshots
                WHERE market = ? AND symbol = ? AND available_at <= ?
                ORDER BY available_at, period_end, ingested_at
                """,
                (market, symbol, pd.Timestamp(end).date()),
            )
            rows = cur.fetchall() or []
            cur.close()
        return rows

    @staticmethod
    def upsert(payload: dict) -> None:
        values = [payload.get(field) for field in FUNDAMENTAL_FIELDS]
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                f"""
                INSERT INTO qd_fundamental_snapshots
                  (market, symbol, period_end, available_at, frequency, currency,
                   {', '.join(FUNDAMENTAL_FIELDS)}, source, source_version, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, {', '.join(['?'] * len(FUNDAMENTAL_FIELDS))}, ?, ?, ?)
                ON CONFLICT (market, symbol, period_end, available_at, source) DO UPDATE SET
                  {', '.join(f'{field} = EXCLUDED.{field}' for field in FUNDAMENTAL_FIELDS)},
                  frequency = EXCLUDED.frequency,
                  currency = EXCLUDED.currency,
                  source_version = EXCLUDED.source_version,
                  metadata_json = EXCLUDED.metadata_json,
                  ingested_at = NOW()
                """,
                (
                    str(payload.get("market") or ""),
                    str(payload.get("symbol") or "").upper(),
                    payload.get("period_end"),
                    payload.get("available_at"),
                    str(payload.get("frequency") or "quarterly"),
                    str(payload.get("currency") or ""),
                    *values,
                    str(payload.get("source") or "manual"),
                    str(payload.get("source_version") or ""),
                    json.dumps(payload.get("metadata") or {}, ensure_ascii=False),
                ),
            )
            db.commit()
            cur.close()


_service: FundamentalDataService | None = None


def get_fundamental_data_service() -> FundamentalDataService:
    global _service
    if _service is None:
        _service = FundamentalDataService()
    return _service
