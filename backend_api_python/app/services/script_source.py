"""Script source library service.

Script sources are reusable code assets. Runtime/live strategies reference a
source by id and keep market, account, notification, and risk settings in
``qd_strategies_trading``.
"""

from __future__ import annotations

import json
import hashlib
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.utils.db import get_db_connection
from app.utils.logger import get_logger
from app.services.portfolio_strategy_examples import list_portfolio_strategy_examples

logger = get_logger(__name__)


CURRENT_SYSTEM_TEMPLATE_KEYS = (
    "ema_trend_pullback",
    "donchian_breakout",
    "atr_channel_breakout",
    "rsi_mean_reversion",
    "macd_momentum",
    "bollinger_reversion",
    "turtle_breakout_lite",
    "volatility_stop_trend",
)

LEGACY_SYSTEM_TEMPLATE_KEYS = (
    "classic_ema_atr_trend",
    "donchian_breakout_pyramid",
    "bollinger_reversion_basket",
    "range_grid_basket",
    "dca_accumulator",
    "sequential_martingale",
    "layered_martingale_basket",
    "keltner_retest_breakout",
)

CURRENT_SYSTEM_TEMPLATE_VERSION = 3
CURRENT_TEMPLATE_SEED_MARKER = "-- ===== Script strategy templates v3 seed ====="
CURRENT_TEMPLATE_SEED_END_MARKER = "-- ============================================================================="
LEGACY_EMA_TEMPLATE_BODY_MD5 = {
    "5bc01a3d642eba482a80a3de0e24035a",
    "f2fbd80cb8eee598c5df3f2bdcd18387",
    "5c462fb5c697864fa0d6a16f8138b726",
}


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


def _json_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
    return []


def _json_dump(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=False)


def _json_dump_any(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _source_asset_type(value: Any) -> str:
    normalized = str(value or "script").strip().lower()
    if normalized in {"portfolio", "cross_section", "cross-section"}:
        normalized = "portfolio_strategy"
    if normalized not in {"script", "portfolio_strategy"}:
        raise ValueError("strategy.invalidAssetType")
    return normalized


def _ensure_script_metadata_header(code: str, title: str, description: str) -> str:
    source = str(code or "")
    clean_title = str(title or "").strip()
    clean_description = str(description or "").strip()
    if not source.strip() or not clean_title:
        return source

    doc_match = re.match(r"\s*(\"\"\"|''')([\s\S]*?)\1", source)
    if not doc_match:
        body = clean_title
        if clean_description:
            body += "\n" + clean_description
        return f'"""\n{body}\n"""\n\n{source.lstrip()}'

    quote = doc_match.group(1)
    doc_body = str(doc_match.group(2) or "")
    lines = [str(line or "").rstrip() for line in doc_body.splitlines()]
    first_idx = next((idx for idx, line in enumerate(lines) if line.strip()), -1)
    if first_idx < 0:
        lines = [clean_title]
        if clean_description:
            lines.append(clean_description)
    else:
        lines[first_idx] = clean_title
        has_description = any(line.strip() for line in lines[first_idx + 1:])
        if clean_description and not has_description:
            lines.insert(first_idx + 1, clean_description)

    next_doc = f"{quote}\n" + "\n".join(lines).strip() + f"\n{quote}"
    return next_doc + source[doc_match.end():]



class ScriptSourceService:
    """CRUD and delivery helpers for script strategy source code."""

    def _current_template_seed_sql(self) -> str:
        init_sql = Path(__file__).resolve().parent.parent.parent / "migrations" / "init.sql"
        try:
            sql = init_sql.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("current script template seed read failed: %s", exc)
            return ""
        start = sql.find(CURRENT_TEMPLATE_SEED_MARKER)
        if start < 0:
            return ""
        end = sql.find(CURRENT_TEMPLATE_SEED_END_MARKER, start)
        if end < 0:
            end = len(sql)
        return sql[start:end].strip()

    def _quoted_template_keys(self, keys: tuple[str, ...]) -> str:
        return ", ".join("'" + key.replace("'", "''") + "'" for key in keys)

    def _template_seed_needs_refresh(self, cur) -> bool:
        current_keys_sql = self._quoted_template_keys(CURRENT_SYSTEM_TEMPLATE_KEYS)
        legacy_keys_sql = self._quoted_template_keys(LEGACY_SYSTEM_TEMPLATE_KEYS)
        cur.execute(
            f"""
            SELECT template_key, is_active, metadata, code
            FROM qd_script_templates
            WHERE template_key IN ({current_keys_sql}, {legacy_keys_sql})
            """
        )
        rows = cur.fetchall() or []
        active_current = set()
        active_legacy = set()
        current_version_ok = set()
        for row in rows:
            key = str(row.get("template_key") or "")
            active = bool(row.get("is_active"))
            metadata = _json_dict(row.get("metadata"))
            if key in CURRENT_SYSTEM_TEMPLATE_KEYS and active:
                active_current.add(key)
                has_current_direction_contract = (
                    key != "ema_trend_pullback"
                    or "def _requested_sides(ctx):" in str(row.get("code") or "")
                )
                if (
                    int(metadata.get("version") or 0) >= CURRENT_SYSTEM_TEMPLATE_VERSION
                    and has_current_direction_contract
                ):
                    current_version_ok.add(key)
            if key in LEGACY_SYSTEM_TEMPLATE_KEYS and active:
                active_legacy.add(key)
        expected = set(CURRENT_SYSTEM_TEMPLATE_KEYS)
        return bool(active_legacy) or active_current != expected or current_version_ok != expected

    def _sync_current_system_templates(self, db, cur) -> None:
        try:
            if not self._template_seed_needs_refresh(cur):
                return
            current_keys_sql = self._quoted_template_keys(CURRENT_SYSTEM_TEMPLATE_KEYS)
            cur.execute(
                f"SELECT template_key, code FROM qd_script_templates WHERE template_key IN ({current_keys_sql})"
            )
            previous_codes = {
                str(row.get("template_key") or ""): str(row.get("code") or "")
                for row in (cur.fetchall() or [])
            }
            seed_sql = self._current_template_seed_sql()
            if not seed_sql:
                logger.warning("current script template seed block is missing")
                return
            cur.execute(seed_sql)
            cur.execute(
                f"SELECT template_key, code FROM qd_script_templates WHERE template_key IN ({current_keys_sql})"
            )
            next_codes = {
                str(row.get("template_key") or ""): str(row.get("code") or "")
                for row in (cur.fetchall() or [])
            }
            cur.execute(
                f"SELECT id, template_key, code FROM qd_script_sources WHERE template_key IN ({current_keys_sql})"
            )
            for source in cur.fetchall() or []:
                key = str(source.get("template_key") or "")
                old_code = previous_codes.get(key) or ""
                new_code = next_codes.get(key) or ""
                source_code = str(source.get("code") or "")
                if not old_code or not new_code or old_code == new_code:
                    continue
                if source_code == old_code:
                    upgraded_code = new_code
                elif source_code.endswith(old_code):
                    upgraded_code = source_code[:-len(old_code)] + new_code
                else:
                    continue
                cur.execute(
                    "UPDATE qd_script_sources SET code = ?, updated_at = NOW() WHERE id = ?",
                    (upgraded_code, int(source["id"])),
                )
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            logger.warning("current script template sync failed: %s", exc)

    def _upgrade_untouched_system_sources(self, cur) -> None:
        cur.execute(
            "SELECT code FROM qd_script_templates WHERE template_key = ? AND is_active = TRUE LIMIT 1",
            ("ema_trend_pullback",),
        )
        template = cur.fetchone() or {}
        next_code = str(template.get("code") or "")
        next_direction_start = next_code.find("def _requested_sides(ctx):")
        if next_direction_start < 0:
            return
        cur.execute(
            "SELECT id, code FROM qd_script_sources WHERE template_key = ?",
            ("ema_trend_pullback",),
        )
        for source in cur.fetchall() or []:
            source_code = str(source.get("code") or "")
            body_start = source_code.find("# timeframe:")
            if body_start < 0:
                continue
            body = source_code[body_start:]
            if hashlib.md5(body.encode("utf-8")).hexdigest() not in LEGACY_EMA_TEMPLATE_BODY_MD5:
                continue
            old_direction_start = source_code.find("def _side(ctx):", body_start)
            if old_direction_start < 0:
                continue
            upgraded_code = source_code[:old_direction_start] + next_code[next_direction_start:]
            cur.execute(
                "UPDATE qd_script_sources SET code = ?, updated_at = NOW() WHERE id = ?",
                (upgraded_code, int(source["id"])),
            )

    def ensure_schema(self) -> None:
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS qd_script_sources (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES qd_users(id) ON DELETE CASCADE,
                        name VARCHAR(255) NOT NULL,
                        description TEXT DEFAULT '',
                        code TEXT NOT NULL DEFAULT '',
                        asset_type VARCHAR(32) NOT NULL DEFAULT 'script',
                        template_key VARCHAR(80) DEFAULT '',
                        param_schema JSONB DEFAULT '{}'::jsonb,
                        source_marketplace_indicator_id INTEGER,
                        source_script_source_id INTEGER,
                        visibility VARCHAR(32) DEFAULT 'private',
                        status VARCHAR(32) DEFAULT 'draft',
                        metadata JSONB DEFAULT '{}'::jsonb,
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_script_sources_user_id ON qd_script_sources(user_id)")
                cur.execute("ALTER TABLE qd_script_sources ADD COLUMN IF NOT EXISTS asset_type VARCHAR(32) NOT NULL DEFAULT 'script'")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_script_sources_asset_type ON qd_script_sources(user_id, asset_type)")
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_script_sources_marketplace ON qd_script_sources(source_marketplace_indicator_id)"
                )
                self._ensure_version_schema(cur)
                self._ensure_template_schema(cur)
                self._upgrade_untouched_system_sources(cur)
                db.commit()
                cur.close()
        except Exception as exc:
            logger.warning("script source schema ensure failed: %s", exc)

    def _ensure_template_schema(self, cur) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS qd_script_templates (
                id SERIAL PRIMARY KEY,
                template_key VARCHAR(80) UNIQUE NOT NULL,
                title VARCHAR(255) NOT NULL,
                description TEXT DEFAULT '',
                code TEXT NOT NULL DEFAULT '',
                param_schema JSONB DEFAULT '{}'::jsonb,
                tags JSONB DEFAULT '[]'::jsonb,
                icon VARCHAR(64) DEFAULT 'appstore',
                accent VARCHAR(32) DEFAULT 'blue',
                sort_order INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE,
                metadata JSONB DEFAULT '{}'::jsonb,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_script_templates_active ON qd_script_templates(is_active, sort_order)")

    def _ensure_version_schema(self, cur) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS qd_script_source_versions (
                id SERIAL PRIMARY KEY,
                source_id INTEGER NOT NULL REFERENCES qd_script_sources(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES qd_users(id) ON DELETE CASCADE,
                version_no INTEGER NOT NULL,
                name VARCHAR(255) NOT NULL DEFAULT '',
                description TEXT DEFAULT '',
                code TEXT NOT NULL DEFAULT '',
                template_key VARCHAR(80) DEFAULT '',
                param_schema JSONB DEFAULT '{}'::jsonb,
                metadata JSONB DEFAULT '{}'::jsonb,
                created_at TIMESTAMP DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_script_source_versions_source
            ON qd_script_source_versions (source_id, version_no DESC)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_script_source_versions_user
            ON qd_script_source_versions (user_id)
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_script_source_versions_no
            ON qd_script_source_versions (source_id, version_no)
            """
        )

    def _insert_version(
        self,
        cur,
        source_id: int,
        user_id: int,
        name: str,
        description: str,
        code: str,
        template_key: str,
        param_schema: Any,
        metadata: Any,
    ) -> int:
        self._ensure_version_schema(cur)
        cur.execute(
            """
            SELECT COALESCE(MAX(version_no), 0) + 1 AS next_version
            FROM qd_script_source_versions
            WHERE source_id = ? AND user_id = ?
            """,
            (int(source_id), int(user_id)),
        )
        row = cur.fetchone() or {}
        version_no = int(row.get("next_version") or 1)
        cur.execute(
            """
            INSERT INTO qd_script_source_versions
              (source_id, user_id, version_no, name, description, code,
               template_key, param_schema, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?::jsonb, NOW())
            """,
            (
                int(source_id),
                int(user_id),
                version_no,
                name or "",
                description or "",
                code or "",
                template_key or "",
                _json_dump(param_schema),
                _json_dump(metadata),
            ),
        )
        return version_no

    def _row(self, row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not row:
            return None
        item = dict(row)
        item["param_schema"] = _json_dict(item.get("param_schema"))
        item["metadata"] = _json_dict(item.get("metadata"))
        return item

    def _version_row(self, row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not row:
            return None
        item = dict(row)
        if "param_schema" in item:
            item["param_schema"] = _json_dict(item.get("param_schema"))
        if "metadata" in item:
            item["metadata"] = _json_dict(item.get("metadata"))
        return item

    def _template_row(self, row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not row:
            return None
        item = dict(row)
        item["asset_type"] = _source_asset_type(item.get("asset_type"))
        item["param_schema"] = _json_dict(item.get("param_schema"))
        item["params"] = _json_list(item["param_schema"].get("params"))
        item["tags"] = _json_list(item.get("tags"))
        item["metadata"] = _json_dict(item.get("metadata"))
        item["key"] = item.get("template_key") or ""
        item["desc"] = item.get("description") or ""
        item["code"] = _ensure_script_metadata_header(
            item.get("code") or "",
            item.get("title") or item["key"],
            item.get("description") or "",
        )
        return item

    def list_templates(self) -> List[Dict[str, Any]]:
        self.ensure_schema()
        with get_db_connection() as db:
            cur = db.cursor()
            self._ensure_template_schema(cur)
            self._sync_current_system_templates(db, cur)
            cur.execute(
                """
                SELECT id, template_key, title, description, code, param_schema, tags,
                       icon, accent, sort_order, is_active, metadata, created_at, updated_at
                FROM qd_script_templates
                WHERE is_active = TRUE
                ORDER BY sort_order ASC, id ASC
                """
            )
            rows = cur.fetchall() or []
            db.commit()
            cur.close()
        templates = [self._template_row(row) for row in rows if row]
        portfolio_templates = []
        for item in list_portfolio_strategy_examples():
            param_schema = _json_dict(item.get("param_schema"))
            portfolio_templates.append(
                {
                    "id": item.get("id"),
                    "template_key": item.get("template_key") or "",
                    "key": item.get("template_key") or "",
                    "title": item.get("template_key") or "",
                    "description": "",
                    "desc": "",
                    "code": item.get("code") or "",
                    "asset_type": "portfolio_strategy",
                    "param_schema": param_schema,
                    "params": _json_list(param_schema.get("params")),
                    "tags": ["portfolio", "cross_sectional"],
                    "icon": item.get("icon") or "appstore",
                    "accent": item.get("accent") or "blue",
                    "name_i18n_key": item.get("name_i18n_key") or "",
                    "description_i18n_key": item.get("description_i18n_key") or "",
                    "metadata": {"builtin_portfolio_example": True},
                }
            )
        return [item for item in templates if item] + portfolio_templates

    def list_sources(self, user_id: int) -> List[Dict[str, Any]]:
        self.ensure_schema()
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
            rows = cur.fetchall()
            cur.close()
        return [self._row(row) for row in rows if row]

    def get_source(self, source_id: int, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        self.ensure_schema()
        with get_db_connection() as db:
            cur = db.cursor()
            if user_id is None:
                cur.execute(
                    """
                    SELECT id, user_id, name, description, code, asset_type, template_key, param_schema,
                           source_marketplace_indicator_id, source_script_source_id,
                           visibility, status, metadata, created_at, updated_at
                    FROM qd_script_sources
                    WHERE id = ?
                    """,
                    (int(source_id),),
                )
            else:
                cur.execute(
                    """
                    SELECT id, user_id, name, description, code, asset_type, template_key, param_schema,
                           source_marketplace_indicator_id, source_script_source_id,
                           visibility, status, metadata, created_at, updated_at
                    FROM qd_script_sources
                    WHERE id = ? AND user_id = ?
                    """,
                    (int(source_id), int(user_id)),
                )
            row = cur.fetchone()
            cur.close()
        return self._row(row)

    def create_source(self, payload: Dict[str, Any]) -> int:
        self.ensure_schema()
        user_id = int(payload.get("user_id") or 1)
        name = str(payload.get("name") or payload.get("strategy_name") or "Untitled Script").strip() or "Untitled Script"
        code = str(payload.get("code") or payload.get("strategy_code") or "")
        description = str(payload.get("description") or "")
        template_key = str(payload.get("template_key") or payload.get("templateKey") or "")
        param_schema = payload.get("param_schema") or payload.get("paramSchema") or {}
        metadata = payload.get("metadata") or {}
        asset_type = _source_asset_type(payload.get("asset_type") or payload.get("assetType"))
        source_marketplace_indicator_id = payload.get("source_marketplace_indicator_id") or payload.get("sourceMarketplaceIndicatorId")
        source_script_source_id = payload.get("source_script_source_id") or payload.get("sourceScriptSourceId")

        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO qd_script_sources
                  (user_id, name, description, code, asset_type, template_key, param_schema,
                   source_marketplace_indicator_id, source_script_source_id,
                   visibility, status, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?::jsonb, ?, ?, ?, ?, ?::jsonb, NOW(), NOW())
                """,
                (
                    user_id,
                    name,
                    description,
                    code,
                    asset_type,
                    template_key,
                    _json_dump(param_schema),
                    int(source_marketplace_indicator_id) if source_marketplace_indicator_id else None,
                    int(source_script_source_id) if source_script_source_id else None,
                    str(payload.get("visibility") or "private"),
                    str(payload.get("status") or "draft"),
                    _json_dump(metadata),
                ),
            )
            new_id = int(cur.lastrowid or 0)
            self._insert_version(
                cur,
                new_id,
                user_id,
                name,
                description,
                code,
                template_key,
                param_schema,
                metadata,
            )
            db.commit()
            cur.close()
        return new_id

    def update_source(self, source_id: int, user_id: int, payload: Dict[str, Any]) -> bool:
        self.ensure_schema()
        existing = self.get_source(source_id, user_id=user_id)
        if not existing:
            return False
        name = str(payload.get("name") or payload.get("strategy_name") or existing.get("name") or "Untitled Script").strip()
        code = str(payload.get("code") if payload.get("code") is not None else payload.get("strategy_code", existing.get("code") or ""))
        description = str(payload.get("description") if payload.get("description") is not None else existing.get("description") or "")
        template_key = str(payload.get("template_key") or payload.get("templateKey") or existing.get("template_key") or "")
        param_schema = payload.get("param_schema") if "param_schema" in payload else payload.get("paramSchema", existing.get("param_schema") or {})
        metadata = payload.get("metadata") if "metadata" in payload else existing.get("metadata") or {}
        asset_type = _source_asset_type(
            payload.get("asset_type") if "asset_type" in payload
            else payload.get("assetType", existing.get("asset_type") or "script")
        )

        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                UPDATE qd_script_sources
                SET name = ?, description = ?, code = ?, asset_type = ?, template_key = ?,
                    param_schema = ?::jsonb, metadata = ?::jsonb, updated_at = NOW()
                WHERE id = ? AND user_id = ?
                """,
                (
                    name,
                    description,
                    code,
                    asset_type,
                    template_key,
                    _json_dump(param_schema),
                    _json_dump(metadata),
                    int(source_id),
                    int(user_id),
                ),
            )
            ok = cur.rowcount > 0
            if ok:
                self._insert_version(
                    cur,
                    source_id,
                    user_id,
                    name,
                    description,
                    code,
                    template_key,
                    param_schema,
                    metadata,
                )
            db.commit()
            cur.close()
        return ok

    def list_versions(self, source_id: int, user_id: int) -> tuple[bool, List[Dict[str, Any]]]:
        self.ensure_schema()
        with get_db_connection() as db:
            cur = db.cursor()
            self._ensure_version_schema(cur)
            cur.execute("SELECT id FROM qd_script_sources WHERE id = ? AND user_id = ?", (int(source_id), int(user_id)))
            if not cur.fetchone():
                cur.close()
                return False, []
            cur.execute(
                """
                SELECT id, source_id, user_id, version_no, name, description, template_key, created_at
                FROM qd_script_source_versions
                WHERE source_id = ? AND user_id = ?
                ORDER BY version_no DESC
                LIMIT 100
                """,
                (int(source_id), int(user_id)),
            )
            rows = cur.fetchall() or []
            db.commit()
            cur.close()
        return True, [self._version_row(row) for row in rows if row]

    def get_version(self, version_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        self.ensure_schema()
        with get_db_connection() as db:
            cur = db.cursor()
            self._ensure_version_schema(cur)
            cur.execute(
                """
                SELECT id, source_id, user_id, version_no, name, description, code,
                       template_key, param_schema, metadata, created_at
                FROM qd_script_source_versions
                WHERE id = ? AND user_id = ?
                """,
                (int(version_id), int(user_id)),
            )
            row = cur.fetchone()
            db.commit()
            cur.close()
        return self._version_row(row)

    def restore_version(self, version_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        self.ensure_schema()
        with get_db_connection() as db:
            cur = db.cursor()
            self._ensure_version_schema(cur)
            cur.execute(
                """
                SELECT v.source_id, v.name, v.description, v.code, v.template_key,
                       v.param_schema, v.metadata
                FROM qd_script_source_versions v
                JOIN qd_script_sources s ON s.id = v.source_id
                WHERE v.id = ? AND v.user_id = ? AND s.user_id = ?
                """,
                (int(version_id), int(user_id), int(user_id)),
            )
            row = self._version_row(cur.fetchone())
            if not row:
                cur.close()
                return None

            source_id = int(row.get("source_id") or 0)
            name = row.get("name") or "Untitled Script"
            description = row.get("description") or ""
            code = row.get("code") or ""
            template_key = row.get("template_key") or ""
            param_schema = row.get("param_schema") or {}
            metadata = row.get("metadata") or {}
            cur.execute(
                """
                UPDATE qd_script_sources
                SET name = ?, description = ?, code = ?, template_key = ?,
                    param_schema = ?::jsonb, metadata = ?::jsonb, updated_at = NOW()
                WHERE id = ? AND user_id = ?
                """,
                (
                    name,
                    description,
                    code,
                    template_key,
                    _json_dump(param_schema),
                    _json_dump(metadata),
                    source_id,
                    int(user_id),
                ),
            )
            if cur.rowcount <= 0:
                cur.close()
                return None
            version_no = self._insert_version(
                cur,
                source_id,
                user_id,
                name,
                description,
                code,
                template_key,
                param_schema,
                metadata,
            )
            db.commit()
            cur.close()

        restored = self.get_source(source_id, user_id=user_id) or {}
        restored["version_no"] = version_no
        return restored

    def delete_source(self, source_id: int, user_id: int) -> bool:
        self.ensure_schema()
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute("DELETE FROM qd_script_sources WHERE id = ? AND user_id = ?", (int(source_id), int(user_id)))
            ok = cur.rowcount > 0
            db.commit()
            cur.close()
        return ok

    def create_from_marketplace_asset(self, buyer_id: int, asset: Dict[str, Any]) -> int:
        now = int(time.time())
        return self.create_source(
            {
                "user_id": buyer_id,
                "name": asset.get("name") or "Purchased Script",
                "description": asset.get("description") or "",
                "code": asset.get("code") or "",
                "source_marketplace_indicator_id": asset.get("id"),
                "visibility": "private",
                "status": "draft",
                "metadata": {
                    "from_marketplace": True,
                    "purchased_at": now,
                    "asset_type": "script_template",
                    "code_hidden": bool(asset.get("is_encrypted") or asset.get("code_hidden") or False),
                },
            }
        )


_service: Optional[ScriptSourceService] = None


def get_script_source_service() -> ScriptSourceService:
    global _service
    if _service is None:
        _service = ScriptSourceService()
    return _service
