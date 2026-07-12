"""Indicator code version history helpers."""

from app.utils.db import get_db_connection


def ensure_indicator_version_schema(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS qd_indicator_code_versions (
            id SERIAL PRIMARY KEY,
            indicator_id INTEGER NOT NULL REFERENCES qd_indicator_codes(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES qd_users(id) ON DELETE CASCADE,
            version_no INTEGER NOT NULL,
            name VARCHAR(255) NOT NULL DEFAULT '',
            description TEXT DEFAULT '',
            code TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_indicator_code_versions_indicator
        ON qd_indicator_code_versions (indicator_id, version_no DESC)
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_indicator_code_versions_user
        ON qd_indicator_code_versions (user_id)
        """
    )
    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_indicator_code_versions_no
        ON qd_indicator_code_versions (indicator_id, version_no)
        """
    )


def insert_indicator_version(cur, indicator_id: int, user_id: int, name: str, description: str, code: str) -> int:
    cur.execute(
        """
        SELECT COALESCE(MAX(version_no), 0) + 1 AS next_version
        FROM qd_indicator_code_versions
        WHERE indicator_id = ? AND user_id = ?
        """,
        (indicator_id, user_id),
    )
    row = cur.fetchone() or {}
    version_no = int(row.get("next_version") or 1)
    cur.execute(
        """
        INSERT INTO qd_indicator_code_versions
          (indicator_id, user_id, version_no, name, description, code, created_at)
        VALUES (?, ?, ?, ?, ?, ?, NOW())
        """,
        (indicator_id, user_id, version_no, name or "", description or "", code or ""),
    )
    return version_no


def list_versions(user_id: int, indicator_id: int) -> tuple[bool, list]:
    """Return indicator versions when the indicator belongs to the user."""
    with get_db_connection() as db:
        cur = db.cursor()
        ensure_indicator_version_schema(cur)
        cur.execute(
            "SELECT id FROM qd_indicator_codes WHERE id = ? AND user_id = ?",
            (indicator_id, user_id),
        )
        if not cur.fetchone():
            cur.close()
            return False, []
        cur.execute(
            """
            SELECT id, indicator_id, version_no, name, description, created_at
            FROM qd_indicator_code_versions
            WHERE indicator_id = ? AND user_id = ?
            ORDER BY version_no DESC
            LIMIT 100
            """,
            (indicator_id, user_id),
        )
        rows = cur.fetchall() or []
        db.commit()
        cur.close()
    return True, rows


def get_version(user_id: int, version_id: int) -> dict | None:
    """Return one saved version for the user."""
    with get_db_connection() as db:
        cur = db.cursor()
        ensure_indicator_version_schema(cur)
        cur.execute(
            """
            SELECT id, indicator_id, version_no, name, description, code, created_at
            FROM qd_indicator_code_versions
            WHERE id = ? AND user_id = ?
            """,
            (version_id, user_id),
        )
        row = cur.fetchone()
        db.commit()
        cur.close()
    return row


def restore_version(user_id: int, version_id: int, now_ts: int) -> dict | None:
    """Restore one version and record the restore as a new version."""
    with get_db_connection() as db:
        cur = db.cursor()
        ensure_indicator_version_schema(cur)
        cur.execute(
            """
            SELECT v.indicator_id, v.name, v.description, v.code
            FROM qd_indicator_code_versions v
            JOIN qd_indicator_codes i ON i.id = v.indicator_id
            WHERE v.id = ? AND v.user_id = ? AND i.user_id = ?
            """,
            (version_id, user_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            cur.close()
            return None

        indicator_id = int(row.get("indicator_id") or 0)
        name = row.get("name") or ""
        description = row.get("description") or ""
        code = row.get("code") or ""
        cur.execute(
            """
            UPDATE qd_indicator_codes
            SET name = ?, description = ?, code = ?, updatetime = ?, updated_at = NOW()
            WHERE id = ? AND user_id = ?
            """,
            (name, description, code, now_ts, indicator_id, user_id),
        )
        version_no = insert_indicator_version(cur, indicator_id, user_id, name, description, code)
        db.commit()
        cur.close()

    return {
        "indicator_id": indicator_id,
        "version_no": version_no,
        "name": name,
        "description": description,
        "code": code,
    }

