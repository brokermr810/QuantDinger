"""Token administration.

Issuance is HUMAN-only — these endpoints require a regular admin JWT, not an
agent token, so an agent can never escalate its own privileges or mint new
tokens for itself or for other tenants.

Endpoints:
  POST   /admin/tokens         issue a new token (admin only)
  GET    /admin/tokens         list tokens (admin only)
  DELETE /admin/tokens/{id}    revoke (admin only)

Deployment-mode hardening
-------------------------
When the env var ``QUANTDINGER_DEPLOYMENT_MODE`` is set to ``saas`` (or
``shared`` / ``hosted``), this module applies extra guards on token issuance:

* ``paper_only`` is forced to ``True`` regardless of what the operator passes.
* The ``T`` (Trading) scope is rejected outright — multi-tenant SaaS instances
  must never let a token route real-money orders, even with an additional
  server-side switch. Self-hosted deployments leave the env var unset and
  retain full flexibility.

The flag is intentionally **operator-controlled** (set in `env.example` /
docker-compose), not user-controlled, so a SaaS operator opts into the
hardened mode by deployment configuration.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from app.utils.agent_auth import (
    ALL_SCOPES,
    ensure_agent_gateway_schema,
    generate_token,
    parse_csv_list,
    parse_scopes,
)
from app.utils.auth import admin_required, get_current_user_id, login_required
from app.utils.db import get_db_connection
from app.utils.logger import get_logger
from flask import request

from . import agent_v1_bp
from ._helpers import envelope, error, get_json_or_400

logger = get_logger(__name__)


# ──────────────────────────── deployment-mode guard ───────────────────────────
# These spellings all map to "this is a multi-tenant hosted instance, lock down
# anything that could touch real money or cross-tenant blast radius".
_SAAS_MODE_VALUES = {"saas", "shared", "hosted", "multitenant", "multi-tenant"}


def _is_saas_mode() -> bool:
    raw = (os.environ.get("QUANTDINGER_DEPLOYMENT_MODE") or "").strip().lower()
    return raw in _SAAS_MODE_VALUES


def _normalize_expiry(days: int | None) -> datetime | None:
    if not days:
        return None
    try:
        d = int(days)
    except Exception:
        return None
    if d <= 0:
        return None
    return datetime.utcnow() + timedelta(days=d)


@agent_v1_bp.route("/admin/tokens", methods=["POST"])
@login_required
@admin_required
def issue_token():
    """Issue a new agent token for the calling admin's tenant.

    The full token value is returned EXACTLY ONCE; only its hash is stored.
    Body fields:
      name, scopes (e.g. "R,B"), markets (csv), instruments (csv),
      paper_only (bool), rate_limit_per_min (int), expires_in_days (int)
    """
    ensure_agent_gateway_schema()
    body, err = get_json_or_400()
    if err:
        return err

    name = (body.get("name") or "").strip() or f"agent-{int(datetime.utcnow().timestamp())}"
    scopes = parse_scopes(body.get("scopes")) or {"R"}
    if not scopes.issubset(set(ALL_SCOPES)):
        return error(400, f"Unknown scope in {sorted(scopes)}")

    saas_mode = _is_saas_mode()

    # In multi-tenant hosted mode, a token must never route real-money trades.
    # Reject the request loudly so the caller knows their request was modified —
    # silently downgrading scopes would be a privacy/clarity footgun.
    if saas_mode and "T" in scopes:
        return error(
            403,
            "T-scope (live trading) tokens are not available on this hosted "
            "deployment. Self-host QuantDinger if you need to route real-money "
            "orders through the Agent Gateway.",
            details="QUANTDINGER_DEPLOYMENT_MODE=saas blocks T-scope at issuance.",
            http=403,
        )

    markets = parse_csv_list(body.get("markets"), default="*")
    instruments = parse_csv_list(body.get("instruments"), default="*")
    paper_only = bool(body.get("paper_only", True))
    if "T" in scopes and not paper_only:
        # Operator can opt-in by passing paper_only=false explicitly; we never
        # silently grant live trading to a token created without that flag.
        paper_only = False
    if saas_mode:
        # Belt + suspenders: even if T is somehow re-introduced, paper-only
        # stays pinned for hosted deployments.
        paper_only = True

    rate_limit = int(body.get("rate_limit_per_min") or 60)
    expires_at = _normalize_expiry(body.get("expires_in_days"))

    full_token, prefix, token_hash = generate_token()

    user_id = int(get_current_user_id() or 1)
    with get_db_connection() as db:
        cur = db.cursor()
        cur.execute(
            """
            INSERT INTO qd_agent_tokens
              (user_id, name, token_prefix, token_hash, scopes, markets, instruments,
               paper_only, rate_limit_per_min, status, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s)
            RETURNING id, created_at
            """,
            (
                user_id, name, prefix, token_hash,
                ",".join(sorted(scopes)),
                ",".join(markets),
                ",".join(instruments),
                paper_only, rate_limit, expires_at,
            ),
        )
        row = cur.fetchone()
        db.commit()
        cur.close()

    return envelope({
        "id": row["id"],
        "name": name,
        "token": full_token,                  # shown ONCE
        "token_prefix": prefix,
        "scopes": sorted(scopes),
        "markets": markets,
        "instruments": instruments,
        "paper_only": paper_only,
        "rate_limit_per_min": rate_limit,
        "expires_at": (expires_at.isoformat() + "Z") if expires_at else None,
        "created_at": row["created_at"].isoformat() + "Z" if row.get("created_at") else None,
    }, message="issued")


@agent_v1_bp.route("/admin/tokens", methods=["GET"])
@login_required
@admin_required
def list_tokens():
    """List tokens for the calling admin's tenant (no secrets)."""
    ensure_agent_gateway_schema()
    user_id = int(get_current_user_id() or 1)
    with get_db_connection() as db:
        cur = db.cursor()
        cur.execute(
            """
            SELECT id, name, token_prefix, scopes, markets, instruments,
                   paper_only, rate_limit_per_min, status, expires_at,
                   last_used_at, created_at
            FROM qd_agent_tokens
            WHERE user_id = %s
            ORDER BY id DESC
            """,
            (user_id,),
        )
        rows = cur.fetchall() or []
        cur.close()
    return envelope(rows)


@agent_v1_bp.route("/admin/tokens/<int:token_id>", methods=["DELETE"])
@login_required
@admin_required
def revoke_token(token_id: int):
    """Revoke a token (sets status='revoked'; cannot be re-activated)."""
    ensure_agent_gateway_schema()
    user_id = int(get_current_user_id() or 1)
    with get_db_connection() as db:
        cur = db.cursor()
        cur.execute(
            "UPDATE qd_agent_tokens SET status = 'revoked' WHERE id = %s AND user_id = %s",
            (token_id, user_id),
        )
        affected = cur.rowcount
        db.commit()
        cur.close()
    if not affected:
        return error(404, "Token not found", http=404)
    return envelope({"id": token_id, "status": "revoked"})


@agent_v1_bp.route("/admin/audit", methods=["GET"])
@login_required
@admin_required
def list_audit():
    """Recent audit entries for this tenant (admin only)."""
    ensure_agent_gateway_schema()
    user_id = int(get_current_user_id() or 1)
    try:
        limit = max(1, min(int(request.args.get("limit") or 100), 500))
    except Exception:
        limit = 100
    with get_db_connection() as db:
        cur = db.cursor()
        cur.execute(
            """
            SELECT id, agent_name, route, method, scope_class, status_code,
                   idempotency_key, duration_ms, created_at
            FROM qd_agent_audit
            WHERE user_id = %s
            ORDER BY id DESC LIMIT %s
            """,
            (user_id, limit),
        )
        rows = cur.fetchall() or []
        cur.close()
    return envelope(rows)
