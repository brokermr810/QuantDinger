"""Strategy asset read model for executable strategy workbenches.

Indicators are chart-only and stay on the indicator APIs. This service returns
only code-backed assets that can be backtested or deployed as strategies.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from app.utils.db import get_db_connection
from app.utils.logger import get_logger
from app.services.portfolio_strategy_examples import list_portfolio_strategy_examples

logger = get_logger(__name__)


def _json_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}


def _iso(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")


def _is_live_only_bot_code(code: str) -> bool:
    text = str(code or "")
    return (
        not text.strip()
        or "live execution uses resting limit-order engine" in text
        or "__QD_LIVE_ONLY_GRID_TEMPLATE__" in text
    )


class StrategyAssetService:
    """Build a normalized list for the executable strategy workbench."""

    def list_assets(self, user_id: int) -> List[Dict[str, Any]]:
        assets: List[Dict[str, Any]] = []
        assets.extend(self._list_script_sources(user_id))
        assets.extend(self._list_portfolio_examples())
        assets.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return assets

    @staticmethod
    def _list_portfolio_examples() -> List[Dict[str, Any]]:
        return [
            {
                "asset_key": f"portfolio_strategy:{item['id']}",
                "asset_type": "portfolio_strategy",
                "storage": "builtin_portfolio_example",
                "id": item["id"],
                "source_id": item["id"],
                "name": item["template_key"],
                "description": "",
                "name_i18n_key": item["name_i18n_key"],
                "description_i18n_key": item["description_i18n_key"],
                "code": item["code"],
                "code_hidden": 0,
                "is_purchased": 0,
                "is_published": 0,
                "template_key": item["template_key"],
                "param_schema": {},
                "metadata": {"builtin_example": True},
                "can_edit_code": False,
                "can_backtest": True,
                "can_live": False,
                "engine": "portfolio_strategy",
                "created_at": "",
                "updated_at": "",
            }
            for item in list_portfolio_strategy_examples()
        ]

    def _list_script_sources(self, user_id: int) -> List[Dict[str, Any]]:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                SELECT id, user_id, name, description, code, asset_type, template_key, param_schema,
                       source_marketplace_indicator_id, source_script_source_id,
                       visibility, status, metadata, created_at, updated_at
                FROM qd_script_sources
                WHERE user_id = ?
                ORDER BY updated_at DESC, id DESC
                """,
                (int(user_id),),
            )
            rows = cur.fetchall() or []
            cur.close()

        out: List[Dict[str, Any]] = []
        for row in rows:
            meta = _json_dict(row.get("metadata"))
            hidden = bool(meta.get("code_hidden") or meta.get("hide_code"))
            asset_type = str(row.get("asset_type") or "script").strip().lower()
            if asset_type not in {"script", "portfolio_strategy"}:
                asset_type = "script"
            out.append(
                {
                    "asset_key": f"{asset_type}:{row.get('id')}",
                    "asset_type": asset_type,
                    "storage": "qd_script_sources",
                    "id": row.get("id"),
                    "source_id": row.get("id"),
                    "marketplace_asset_id": row.get("source_marketplace_indicator_id"),
                    "name": row.get("name") or f"Script #{row.get('id')}",
                    "description": row.get("description") or "",
                    "code": "" if hidden else (row.get("code") or ""),
                    "code_hidden": 1 if hidden else 0,
                    "is_purchased": 1 if row.get("source_marketplace_indicator_id") else 0,
                    "is_published": 1 if row.get("visibility") == "public" else 0,
                    "template_key": row.get("template_key") or "",
                    "param_schema": _json_dict(row.get("param_schema")),
                    "metadata": meta,
                    "can_edit_code": not hidden,
                    "can_backtest": True,
                    "can_live": True,
                    "engine": asset_type,
                    "created_at": _iso(row.get("created_at")),
                    "updated_at": _iso(row.get("updated_at") or row.get("created_at")),
                }
            )
        return out

_service: StrategyAssetService | None = None


def get_strategy_asset_service() -> StrategyAssetService:
    global _service
    if _service is None:
        _service = StrategyAssetService()
    return _service
