"""Strategy universe APIs."""

from flask import g, jsonify, request

from app.openapi.blueprint import HumanBlueprint as Blueprint
from app.services.universe import UniverseError, get_universe_service
from app.utils.auth import admin_required, login_required
from app.utils.logger import get_logger


logger = get_logger(__name__)
universe_blp = Blueprint("universe", __name__)


def _success(data=None, *, status: int = 200):
    return jsonify({"code": 1, "msg": "success", "data": data}), status


def _failure(exc: UniverseError):
    return jsonify({"code": 0, "msg": exc.code, "data": None}), exc.status_code


@universe_blp.route("", methods=["GET"])
@login_required
def list_universes():
    try:
        return _success(get_universe_service().list_universes(g.user_id))
    except Exception as exc:
        logger.exception("list universes failed")
        return jsonify({"code": 0, "msg": "universe.listFailed", "data": None}), 500


@universe_blp.route("", methods=["POST"])
@login_required
def create_universe():
    try:
        payload = request.get_json(silent=True) or {}
        universe_type = str(payload.get("universe_type") or payload.get("universeType") or "manual")
        if universe_type != "manual":
            raise UniverseError("universe.createTypeUnsupported")
        return _success(get_universe_service().create_manual(g.user_id, payload), status=201)
    except UniverseError as exc:
        return _failure(exc)
    except Exception:
        logger.exception("create universe failed")
        return jsonify({"code": 0, "msg": "universe.createFailed", "data": None}), 500


@universe_blp.route("/<int:universe_id>/clone", methods=["POST"])
@login_required
def clone_universe(universe_id: int):
    try:
        payload = request.get_json(silent=True) or {}
        result = get_universe_service().clone_system(
            g.user_id,
            universe_id,
            name=str(payload.get("name") or ""),
        )
        return _success(result, status=201)
    except UniverseError as exc:
        return _failure(exc)
    except Exception:
        logger.exception("clone universe failed")
        return jsonify({"code": 0, "msg": "universe.cloneFailed", "data": None}), 500


@universe_blp.route("/admin/overview", methods=["GET"])
@login_required
@admin_required
def system_universe_overview():
    try:
        return _success(get_universe_service().system_overview())
    except Exception:
        logger.exception("system universe overview failed")
        return jsonify({"code": 0, "msg": "universe.overviewFailed", "data": None}), 500


@universe_blp.route("/admin/sync", methods=["POST"])
@login_required
@admin_required
def sync_system_universes():
    try:
        from datetime import date
        from scripts.refresh_public_universe_snapshots import HK_FACTSHEETS, LOADERS, apply_snapshot

        payload = request.get_json(silent=True) or {}
        requested = payload.get("codes") or list(LOADERS)
        codes = [str(code).strip() for code in requested if str(code).strip()]
        if not codes or any(code not in LOADERS for code in codes):
            raise UniverseError("universe.invalidSyncSelection")
        as_of = date.fromisoformat(str(payload.get("as_of") or payload.get("asOf") or date.today().isoformat()))
        expected = {
            "csi300": (300, 300), "csi500": (500, 500), "sp500": (500, 510),
            "nasdaq100": (100, 102), "crypto_top100": (95, 100),
            "hk_etf": (1, 1000), "us_etf": (1, 1000),
            **{code: (count, count) for code, (_factsheet, count) in HK_FACTSHEETS.items()},
        }
        results = []
        for code in codes:
            members = LOADERS[code]()
            count = len({item.get("symbol") for item in members if item.get("symbol")})
            minimum, maximum = expected[code]
            if not minimum <= count <= maximum:
                raise RuntimeError(f"{code} member count failed validation: {count}")
            results.append(apply_snapshot(code, members, as_of))
        return _success({"as_of": as_of.isoformat(), "results": results})
    except UniverseError as exc:
        return _failure(exc)
    except Exception:
        logger.exception("system universe sync failed")
        return jsonify({"code": 0, "msg": "universe.syncFailed", "data": None}), 500


@universe_blp.route("/<int:universe_id>", methods=["GET"])
@login_required
def get_universe(universe_id: int):
    try:
        return _success(get_universe_service().get_universe(g.user_id, universe_id))
    except UniverseError as exc:
        return _failure(exc)
    except Exception:
        logger.exception("get universe failed")
        return jsonify({"code": 0, "msg": "universe.getFailed", "data": None}), 500


@universe_blp.route("/<int:universe_id>/members", methods=["GET"])
@login_required
def get_universe_members(universe_id: int):
    try:
        members = get_universe_service().resolve_members(
            g.user_id,
            universe_id,
            as_of=request.args.get("as_of") or request.args.get("asOf"),
        )
        return _success({"universe_id": universe_id, "members": members, "count": len(members)})
    except UniverseError as exc:
        return _failure(exc)
    except Exception:
        logger.exception("get universe members failed")
        return jsonify({"code": 0, "msg": "universe.membersFailed", "data": None}), 500


@universe_blp.route("/<int:universe_id>/members", methods=["PUT"])
@login_required
def replace_universe_members(universe_id: int):
    try:
        payload = request.get_json(silent=True) or {}
        members = get_universe_service().replace_manual_members(
            g.user_id,
            universe_id,
            payload.get("members") or [],
        )
        return _success({"universe_id": universe_id, "members": members, "count": len(members)})
    except UniverseError as exc:
        return _failure(exc)
    except Exception:
        logger.exception("replace universe members failed")
        return jsonify({"code": 0, "msg": "universe.updateFailed", "data": None}), 500


@universe_blp.route("/<int:universe_id>/snapshots", methods=["POST"])
@login_required
def create_universe_snapshot(universe_id: int):
    try:
        payload = request.get_json(silent=True) or {}
        snapshot = get_universe_service().create_snapshot(
            g.user_id,
            universe_id,
            as_of=payload.get("as_of") or payload.get("asOf"),
        )
        return _success(snapshot, status=201)
    except UniverseError as exc:
        return _failure(exc)
    except Exception:
        logger.exception("create universe snapshot failed")
        return jsonify({"code": 0, "msg": "universe.snapshotFailed", "data": None}), 500
