"""
Trading Strategy API Routes
"""
from flask import g, jsonify, request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import json
import re
import traceback
import time

from app.services.strategy_compiler import StrategyCompiler
from app.services.ai_generation_contracts import (
    INDICATOR_TO_STRATEGY_SYSTEM_PROMPT,
    SCRIPT_STRATEGY_REPAIR_REQUIREMENTS,
    SCRIPT_STRATEGY_QUICK_TOOL_SYSTEM_PROMPT,
    SCRIPT_STRATEGY_SYSTEM_PROMPT,
)
from app.services.strategy_code_quality import (
    analyze_strategy_code_quality,
    strategy_ai_text,
    strategy_debug_summary,
    strategy_hint_to_text,
    strategy_human_summary,
    validate_strategy_code,
)
from app.services.strategy_live_guard import (
    find_live_strategy_conflict,
    live_conflict_message,
    strategy_live_lock_key,
)
from app.services.portfolio_strategy_runtime import validate_portfolio_strategy_code
from app.services.strategy import redact_strategy_row
from app.routes.strategy_blueprint import strategy_blp
from app.routes.strategy_services import get_strategy_service
from app import get_trading_executor
from app.utils.logger import get_logger
from app.utils.db import get_db_connection

from app.utils.auth import login_required

logger = get_logger(__name__)

# Register split strategy route modules on the shared blueprint.
from app.routes import strategy_account_routes  # noqa: E402,F401
from app.routes import strategy_deviation_routes  # noqa: E402,F401
from app.routes import strategy_grid_routes  # noqa: E402,F401
from app.routes import strategy_ledger_routes  # noqa: E402,F401
from app.routes import strategy_logs_routes  # noqa: E402,F401
from app.routes import strategy_notifications  # noqa: E402,F401
from app.routes import strategy_positions_routes  # noqa: E402,F401
from app.routes import strategy_review_routes  # noqa: E402,F401
from app.routes import strategy_asset_routes  # noqa: E402,F401
from app.routes import strategy_executor_routes  # noqa: E402,F401
from app.routes import script_source_routes  # noqa: E402,F401


def _strategy_live_lock_key(strategy: Dict[str, Any], user_id: int) -> Optional[Tuple[Any, ...]]:
    return strategy_live_lock_key(strategy, user_id)


def _find_live_strategy_conflict(strategy: Dict[str, Any], user_id: int) -> Optional[Dict[str, Any]]:
    return find_live_strategy_conflict(strategy, user_id)


def _live_conflict_message(conflict: Dict[str, Any]) -> str:
    return live_conflict_message(conflict)


def _extract_script_metadata_from_code(code: str) -> Dict[str, str]:
    source = str(code or "")
    meta = {"name": "", "description": ""}
    for key, names in (
        ("name", ("my_strategy_name", "strategy_name")),
        ("description", ("my_strategy_description", "strategy_description")),
    ):
        pattern = r"^\s*(?:" + "|".join(re.escape(name) for name in names) + r")\s*=\s*(['\"])(.*?)\1\s*$"
        match = re.search(pattern, source, flags=re.MULTILINE)
        if match:
            meta[key] = str(match.group(2) or "").strip()
    doc_match = re.match(r"\s*(\"\"\"|''')([\s\S]*?)\1", source)
    if doc_match:
        lines = [str(line or "").strip() for line in str(doc_match.group(2) or "").splitlines()]
        first_idx = next((idx for idx, line in enumerate(lines) if line), -1)
        if first_idx >= 0:
            if not meta["name"]:
                meta["name"] = lines[first_idx]
            if not meta["description"]:
                meta["description"] = "\n".join(lines[first_idx + 1:]).strip()
    return meta


def _analyze_strategy_code_quality(code: str) -> list[dict]:
    return analyze_strategy_code_quality(code)


def _validate_strategy_code_internal(code: str) -> dict:
    return validate_strategy_code(code)


def _strategy_debug_summary(validation: dict | None = None) -> dict:
    return strategy_debug_summary(validation)


def _request_lang(default: str = "zh-CN") -> str:
    raw = (
        request.headers.get("X-App-Lang")
        or request.headers.get("Accept-Language")
        or default
    )
    lang = str(raw or default).split(",", 1)[0].strip()
    return lang or default


def _is_zh_lang(lang: str | None) -> bool:
    return str(lang or "zh-CN").strip().lower().startswith("zh")


def _strategy_ai_text(key: str, lang: str = "zh-CN") -> str:
    return strategy_ai_text(key, lang)


def _strategy_hint_to_text(hint_code: str, params: dict | None = None, lang: str = "zh-CN") -> str:
    return strategy_hint_to_text(hint_code, params, lang)


def _strategy_human_summary(
    initial_validation: dict,
    final_validation: dict,
    auto_fix_applied: bool,
    auto_fix_succeeded: bool,
    returned_candidate: str,
    lang: str = "zh-CN",
) -> dict:
    return strategy_human_summary(
        initial_validation,
        final_validation,
        auto_fix_applied,
        auto_fix_succeeded,
        returned_candidate,
        lang=lang,
    )


def _strategy_performance_summary(initial_capital: float, equity_curve: list[dict] | None) -> dict:
    try:
        initial = float(initial_capital or 0.0)
    except Exception:
        initial = 0.0
    curve = equity_curve if isinstance(equity_curve, list) else []
    final = initial
    if curve:
        last = curve[-1] if isinstance(curve[-1], dict) else {}
        try:
            final = float(last.get("equity", last.get("value", initial)) or 0.0)
        except Exception:
            final = initial
    total_return = final - initial
    total_return_pct = (total_return / initial * 100.0) if initial > 0 else 0.0
    return {
        "initial_capital": round(initial, 8),
        "final_equity": round(final, 8),
        "total_return": round(total_return, 8),
        "total_return_pct": round(total_return_pct, 8),
    }


@strategy_blp.route('/strategies', methods=['GET'])
@login_required
def list_strategies():
    """
    List strategies for the current user.
    """
    try:
        user_id = g.user_id
        items = get_strategy_service().list_strategies(user_id=user_id)
        return jsonify({
            'code': 1,
            'msg': 'success',
            'data': {'strategies': [redact_strategy_row(item) for item in items]},
        })
    except Exception as e:
        logger.error(f"list_strategies failed: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'code': 0, 'msg': str(e), 'data': {'strategies': []}}), 500


@strategy_blp.route('/strategies/detail', methods=['GET'])
@login_required
def get_strategy_detail():
    try:
        user_id = g.user_id
        strategy_id = request.args.get('id', type=int)
        if not strategy_id:
            return jsonify({'code': 0, 'msg': 'Missing strategy id parameter', 'data': None}), 400
        st = get_strategy_service().get_strategy(strategy_id, user_id=user_id)
        if not st:
            return jsonify({'code': 0, 'msg': 'Strategy not found', 'data': None}), 404
        return jsonify({'code': 1, 'msg': 'success', 'data': redact_strategy_row(st)})
    except Exception as e:
        logger.error(f"get_strategy_detail failed: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'code': 0, 'msg': str(e), 'data': None}), 500


@strategy_blp.route('/strategies/create', methods=['POST'])
@login_required
def create_strategy():
    try:
        user_id = g.user_id
        payload = request.get_json() or {}
        # Use current user's ID
        payload['user_id'] = user_id
        payload['strategy_type'] = payload.get('strategy_type') or 'ScriptStrategy'
        new_id = get_strategy_service().create_strategy(payload)
        return jsonify({'code': 1, 'msg': 'success', 'data': {'id': new_id}})
    except ValueError as e:
        return jsonify({'code': 0, 'msg': str(e), 'data': None}), 400
    except Exception as e:
        logger.error(f"create_strategy failed: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'code': 0, 'msg': str(e), 'data': None}), 500


@strategy_blp.route('/strategies/batch-create', methods=['POST'])
@login_required
def batch_create_strategies():
    """
    Batch create strategies (multiple symbols)
    
    Request body:
        strategy_name: Base strategy name
        symbols: Array of symbols, e.g. ["Crypto:BTC/USDT", "Crypto:ETH/USDT"]
        ... other strategy config
    """
    try:
        user_id = g.user_id
        payload = request.get_json() or {}
        payload['user_id'] = user_id
        payload['strategy_type'] = payload.get('strategy_type') or 'ScriptStrategy'
        
        result = get_strategy_service().batch_create_strategies(payload)
        
        if result['success']:
            return jsonify({
                'code': 1,
                'msg': f"Successfully created {result['total_created']} strategies",
                'data': result
            })
        else:
            return jsonify({
                'code': 0,
                'msg': 'Batch creation failed',
                'data': result
            })
    except ValueError as e:
        return jsonify({'code': 0, 'msg': str(e), 'data': None}), 400
    except Exception as e:
        logger.error(f"batch_create_strategies failed: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'code': 0, 'msg': str(e), 'data': None}), 500


@strategy_blp.route('/strategies/batch-start', methods=['POST'])
@login_required
def batch_start_strategies():
    """
    Batch start strategies
    
    Request body:
        strategy_ids: Array of strategy IDs
        or
        strategy_group_id: Strategy group ID
    """
    try:
        user_id = g.user_id
        payload = request.get_json() or {}
        strategy_ids = payload.get('strategy_ids') or []
        strategy_group_id = payload.get('strategy_group_id')
        
        # If strategy_group_id provided, get all strategies in the group
        if strategy_group_id and not strategy_ids:
            strategy_ids = get_strategy_service().get_strategies_by_group(strategy_group_id, user_id=user_id)
        
        if not strategy_ids:
            return jsonify({'code': 0, 'msg': 'Please provide strategy IDs', 'data': None}), 400

        seen_live_keys: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
        batch_conflicts: List[Dict[str, Any]] = []
        for sid in strategy_ids:
            st = get_strategy_service().get_strategy(int(sid), user_id=user_id)
            if not st:
                continue
            existing_conflict = _find_live_strategy_conflict(st, user_id)
            if existing_conflict:
                batch_conflicts.append({
                    'strategy_id': int(sid),
                    'conflict': existing_conflict,
                    'message': _live_conflict_message(existing_conflict),
                })
                continue
            key = _strategy_live_lock_key(st, user_id)
            if key and key in seen_live_keys:
                other = seen_live_keys[key]
                conflict = {
                    'strategy_id': other.get('id'),
                    'strategy_name': other.get('strategy_name') or other.get('name') or str(other.get('id')),
                    'symbol': key[-1],
                    'market_type': key[-2],
                    'exchange_id': key[-3],
                }
                batch_conflicts.append({
                    'strategy_id': int(sid),
                    'conflict': conflict,
                    'message': _live_conflict_message(conflict),
                })
            elif key:
                seen_live_keys[key] = st

        if batch_conflicts:
            return jsonify({
                'code': 0,
                'msg': 'Live strategy conflict',
                'data': {'conflicts': batch_conflicts},
            }), 409
        
        # Update database status first
        result = get_strategy_service().batch_start_strategies(strategy_ids, user_id=user_id)
        
        # Then start executor
        executor = get_trading_executor()
        for sid in result.get('success_ids', []):
            try:
                executor.start_strategy(sid)
            except Exception as e:
                logger.error(f"Failed to start executor for strategy {sid}: {e}")
        
        return jsonify({
            'code': 1 if result['success'] else 0,
            'msg': f"Successfully started {len(result.get('success_ids', []))} strategies",
            'data': result
        })
    except Exception as e:
        logger.error(f"batch_start_strategies failed: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'code': 0, 'msg': str(e), 'data': None}), 500


@strategy_blp.route('/strategies/batch-stop', methods=['POST'])
@login_required
def batch_stop_strategies():
    """
    Batch stop strategies
    
    Request body:
        strategy_ids: Array of strategy IDs
        or
        strategy_group_id: Strategy group ID
    """
    try:
        user_id = g.user_id
        payload = request.get_json() or {}
        strategy_ids = payload.get('strategy_ids') or []
        strategy_group_id = payload.get('strategy_group_id')
        
        if strategy_group_id and not strategy_ids:
            strategy_ids = get_strategy_service().get_strategies_by_group(strategy_group_id, user_id=user_id)
        
        if not strategy_ids:
            return jsonify({'code': 0, 'msg': 'Please provide strategy IDs', 'data': None}), 400
        
        # Persist stop intent first so restart restore will not resume them.
        result = get_strategy_service().batch_stop_strategies(strategy_ids, user_id=user_id)
        stopped_ids = list(result.get('success_ids') or [])
        executor_failed = []
        executor = get_trading_executor()
        for sid in stopped_ids:
            try:
                if not executor.stop_strategy(sid, persist_status=False):
                    executor_failed.append({'id': sid, 'error': 'runtime stop failed'})
            except Exception as e:
                logger.error(f"Failed to stop executor for strategy {sid}: {e}")
                executor_failed.append({'id': sid, 'error': str(e)})
        if executor_failed:
            result.setdefault('failed_ids', []).extend(executor_failed)
        success_count = len(result.get('success_ids', []))
        failed_count = len(result.get('failed_ids', []))
        ok = result['success'] and not executor_failed
        
        return jsonify({
            'code': 1 if ok else 0,
            'msg': (
                f"Stopped {success_count} strategies"
                if ok else
                f"Stopped {success_count} strategies; {failed_count} failed"
            ),
            'data': result
        })
    except Exception as e:
        logger.error(f"batch_stop_strategies failed: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'code': 0, 'msg': str(e), 'data': None}), 500


@strategy_blp.route('/strategies/batch-delete', methods=['DELETE'])
@login_required
def batch_delete_strategies():
    """
    Batch delete strategies
    
    Request body:
        strategy_ids: Array of strategy IDs
        or
        strategy_group_id: Strategy group ID
    """
    try:
        user_id = g.user_id
        payload = request.get_json() or {}
        strategy_ids = payload.get('strategy_ids') or []
        strategy_group_id = payload.get('strategy_group_id')
        
        if strategy_group_id and not strategy_ids:
            strategy_ids = get_strategy_service().get_strategies_by_group(strategy_group_id, user_id=user_id)
        
        if not strategy_ids:
            return jsonify({'code': 0, 'msg': 'Please provide strategy IDs', 'data': None}), 400
        
        # Stop executor first
        executor = get_trading_executor()
        for sid in strategy_ids:
            try:
                executor.stop_strategy(sid)
            except Exception as e:
                pass  # Ignore stop errors
        
        # Then delete
        result = get_strategy_service().batch_delete_strategies(strategy_ids, user_id=user_id)
        
        return jsonify({
            'code': 1 if result['success'] else 0,
            'msg': f"Successfully deleted {len(result.get('success_ids', []))} strategies",
            'data': result
        })
    except Exception as e:
        logger.error(f"batch_delete_strategies failed: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'code': 0, 'msg': str(e), 'data': None}), 500


@strategy_blp.route('/strategies/update', methods=['PUT'])
@login_required
def update_strategy():
    try:
        user_id = g.user_id
        strategy_id = request.args.get('id', type=int)
        if not strategy_id:
            return jsonify({'code': 0, 'msg': 'Missing strategy id parameter', 'data': None}), 400
        payload = request.get_json() or {}
        ok = get_strategy_service().update_strategy(strategy_id, payload, user_id=user_id)
        if not ok:
            return jsonify({'code': 0, 'msg': 'Strategy not found', 'data': None}), 404
        return jsonify({'code': 1, 'msg': 'success', 'data': None})
    except ValueError as e:
        return jsonify({'code': 0, 'msg': str(e), 'data': None}), 400
    except Exception as e:
        logger.error(f"update_strategy failed: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'code': 0, 'msg': str(e), 'data': None}), 500


@strategy_blp.route('/strategies/delete', methods=['DELETE'])
@login_required
def delete_strategy():
    try:
        user_id = g.user_id
        strategy_id = request.args.get('id', type=int)
        if not strategy_id:
            return jsonify({'code': 0, 'msg': 'Missing strategy id parameter', 'data': None}), 400
        ok = get_strategy_service().delete_strategy(strategy_id, user_id=user_id)
        return jsonify({'code': 1 if ok else 0, 'msg': 'success' if ok else 'failed', 'data': None})
    except Exception as e:
        logger.error(f"delete_strategy failed: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'code': 0, 'msg': str(e), 'data': None}), 500


@strategy_blp.route('/strategies/stop', methods=['POST'])
@login_required
def stop_strategy():
    """
    Stop a strategy for the current user.
    
    Params:
        id: Strategy ID
    """
    try:
        user_id = g.user_id
        strategy_id = request.args.get('id', type=int)
        
        if not strategy_id:
            return jsonify({
                'code': 0,
                'msg': 'Missing strategy id parameter',
                'data': None
            }), 400
        
        # Verify strategy belongs to user
        st = get_strategy_service().get_strategy(strategy_id, user_id=user_id)
        if not st:
            return jsonify({'code': 0, 'msg': 'Strategy not found', 'data': None}), 404

        # Get strategy type
        strategy_type = get_strategy_service().get_strategy_type(strategy_id)
        
        # Local backend: AI strategy executor was removed. Only indicator strategies are supported.
        if strategy_type == 'PromptBasedStrategy':
            return jsonify({'code': 0, 'msg': 'AI strategy has been removed; local edition does not support starting/stopping AI strategies', 'data': None}), 400

        # Persist the user's stop intent first.  Startup restore only resumes
        # rows still marked as running, so this write is the critical contract.
        status_ok = get_strategy_service().update_strategy_status(strategy_id, 'stopped', user_id=user_id)
        if not status_ok:
            return jsonify({
                'code': 0,
                'msg': 'Failed to persist stopped status; strategy may resume on restart',
                'data': None
            }), 500

        executor_ok = get_trading_executor().stop_strategy(strategy_id, persist_status=False)
        if not executor_ok:
            return jsonify({
                'code': 0,
                'msg': 'Stopped status was saved, but runtime thread stop failed; please refresh and retry',
                'data': {'status': 'stopped'}
            }), 500

        latest = get_strategy_service().get_strategy(strategy_id, user_id=user_id)
        if not latest or str(latest.get('status') or '').lower() != 'stopped':
            return jsonify({
                'code': 0,
                'msg': 'Stop verification failed; strategy status is not stopped',
                'data': {'status': latest.get('status') if latest else None}
            }), 500
        
        return jsonify({
            'code': 1,
            'msg': 'Stopped successfully',
            'data': {'status': 'stopped'}
        })
        
    except Exception as e:
        logger.error(f"Failed to stop strategy: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            'code': 0,
            'msg': f'Failed to stop strategy: {str(e)}',
            'data': None
        }), 500


@strategy_blp.route('/strategies/start', methods=['POST'])
@login_required
def start_strategy():
    """
    Start a strategy for the current user.
    
    Params:
        id: Strategy ID
    """
    try:
        user_id = g.user_id
        strategy_id = request.args.get('id', type=int)
        
        if not strategy_id:
            return jsonify({
                'code': 0,
                'msg': 'Missing strategy id parameter',
                'data': None
            }), 400
        
        # Verify strategy belongs to user
        st = get_strategy_service().get_strategy(strategy_id, user_id=user_id)
        if not st:
            return jsonify({'code': 0, 'msg': 'Strategy not found', 'data': None}), 404
        
        # Get strategy type
        strategy_type = get_strategy_service().get_strategy_type(strategy_id)

        # Only ScriptStrategy is executable. Indicators are chart-only.
        if strategy_type != 'ScriptStrategy':
            return jsonify({
                'code': 0,
                'msg': 'Indicators are chart-only. Convert the indicator to a ScriptStrategy before live trading.',
                'data': None
            }), 400

        conflict = _find_live_strategy_conflict(st, user_id)
        if conflict:
            msg = _live_conflict_message(conflict)
            return jsonify({
                'code': 0,
                'msg': msg,
                'data': {'conflict': conflict},
            }), 409

        get_strategy_service().update_strategy_status(strategy_id, 'running', user_id=user_id)

        executor = get_trading_executor()
        success = executor.start_strategy(strategy_id)

        if not success:
            # If start failed, restore status
            get_strategy_service().update_strategy_status(strategy_id, 'stopped', user_id=user_id)
            detail = getattr(executor, "_last_start_failure", "") or ""
            msg = "Failed to start strategy executor"
            if detail:
                msg = f"{msg}: {detail}"
            return jsonify({'code': 0, 'msg': msg, 'data': {'detail': detail} if detail else None}), 500

        alive, hint = executor.wait_strategy_running(strategy_id, timeout=3.0)
        if not alive:
            get_strategy_service().update_strategy_status(strategy_id, 'stopped', user_id=user_id)
            msg = f"Strategy exited immediately after startup: {hint}"
            return jsonify({
                'code': 0,
                'msg': msg,
                'data': {'detail': hint, 'status': 'stopped'},
            }), 500
        
        return jsonify({
            'code': 1,
            'msg': 'Started successfully',
            'data': None
        })
        
    except Exception as e:
        logger.error(f"Failed to start strategy: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            'code': 0,
            'msg': f'Failed to start strategy: {str(e)}',
            'data': None
        }), 500


@strategy_blp.route('/strategies/test-connection', methods=['POST'])
@login_required
def test_connection():
    """
    Test exchange connection.
    
    Request body:
        exchange_config: Exchange configuration (may contain credential_id or inline keys)
    """
    try:
        data = request.get_json() or {}
        
        # Log request keys for debugging without logging sensitive values.
        logger.debug(f"Connection test request keys: {list(data.keys())}")
        
        # Read exchange configuration.
        exchange_config = data.get('exchange_config', data)
        
        # Local deployment: no encryption/decryption; accept dict or JSON string.
        if isinstance(exchange_config, str):
            try:
                import json
                exchange_config = json.loads(exchange_config)
            except Exception:
                pass
        
        # Validate exchange_config is a dictionary.
        if not isinstance(exchange_config, dict):
            logger.error(f"Invalid exchange_config type: {type(exchange_config)}, data: {str(exchange_config)[:200]}")
            # Frontend expects HTTP 200 with {code:0} for business failures.
            return jsonify({'code': 0, 'msg': 'Invalid exchange config format; please check your payload', 'data': None})

        # Demo/testnet toggles and base_url are often sent on the JSON root while keys live under exchange_config.
        if isinstance(data, dict) and "exchange_config" in data:
            from app.services.live_trading.factory import merge_root_exchange_config_overlay

            exchange_config = merge_root_exchange_config_overlay(root=data, exchange_config=exchange_config)

        # Resolve credential_id to full config (merges credential keys with any overrides).
        # This allows the frontend to send just {credential_id: 5} without raw api_key/secret_key.
        from app.services.exchange_execution import resolve_exchange_config
        from app.utils.local_brokers import desktop_broker_cloud_reject_message, local_desktop_brokers_allowed

        user_id = g.user_id if hasattr(g, 'user_id') else 1
        resolved = resolve_exchange_config(exchange_config, user_id=user_id)

        # Validate required fields after credential merge.
        ex_id = (resolved.get('exchange_id') or '').strip().lower()
        if not ex_id:
            return jsonify({'code': 0, 'msg': 'Please select an exchange', 'data': None})

        if ex_id == 'ibkr':
            if not local_desktop_brokers_allowed():
                return jsonify({'code': 0, 'msg': desktop_broker_cloud_reject_message(), 'data': None})
            logger.info("Testing connection: exchange_id=%s (local desktop broker, skipping API key check)", ex_id)
        else:
            api_key = resolved.get('api_key', '')
            secret_key = resolved.get('secret_key', '')

            # Detailed diagnostics for connection tests.
            logger.info(f"Testing connection: exchange_id={resolved.get('exchange_id')}")
            if api_key:
                logger.info(f"API Key: {api_key[:5]}... (len={len(api_key)})")
            if secret_key:
                logger.info(f"Secret Key: {secret_key[:5]}... (len={len(secret_key)})")

            # Check for accidental leading or trailing whitespace.
            if api_key and api_key.strip() != api_key:
                logger.warning("API key contains leading/trailing whitespace")
            if secret_key and secret_key.strip() != secret_key:
                logger.warning("Secret key contains leading/trailing whitespace")

            if not api_key or not secret_key:
                return jsonify({'code': 0, 'msg': 'Please provide API key and secret key', 'data': None})

        # Pass the resolved config (with actual keys) to the service
        result = get_strategy_service().test_exchange_connection(resolved, user_id=user_id)
        
        if result['success']:
            return jsonify({'code': 1, 'msg': result.get('message') or 'Connection successful', 'data': result.get('data')})
        # Always return HTTP 200 for business-level failures.
        return jsonify({'code': 0, 'msg': result.get('message') or 'Connection failed', 'data': result.get('data')})
        
    except Exception as e:
        logger.error(f"Connection test failed: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            'code': 0,
            'msg': f'Connection test failed: {str(e)}',
            'data': None
        }), 500


# ===== Script Strategy Endpoints =====

@strategy_blp.route('/strategies/verify-code', methods=['POST'])
@login_required
def verify_strategy_code():
    """Verify script strategy code syntax and safety."""
    try:
        payload = request.get_json() or {}
        code = payload.get('code', '')
        if not code.strip():
            return jsonify({'success': False, 'message': 'Code is empty'})

        asset_type = str(payload.get('assetType') or payload.get('asset_type') or 'script').strip().lower()
        if asset_type == 'portfolio_strategy':
            try:
                validate_portfolio_strategy_code(code)
                validation = {'success': True, 'hints': [], 'errors': [], 'warnings': []}
            except (SyntaxError, ValueError) as exc:
                validation = {
                    'success': False,
                    'hints': [{'code': 'PORTFOLIO_CONTRACT_INVALID', 'severity': 'error', 'params': {'message': str(exc)}}],
                    'errors': [str(exc)],
                    'warnings': [],
                    'message': str(exc),
                }
        else:
            validation = _validate_strategy_code_internal(code)
        if validation.get('success'):
            strategy_id = int(payload.get('strategyId') or payload.get('strategy_id') or 0)
            source_id = int(payload.get('scriptSourceId') or payload.get('script_source_id') or payload.get('sourceId') or 0)
            if strategy_id:
                try:
                    get_strategy_service().patch_trading_config(
                        strategy_id,
                        {
                            'lifecycle_verified': True,
                            'script_verified': True,
                            'lifecycle_verified_at': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
                        },
                        user_id=g.user_id,
                    )
                except Exception as _lc_err:
                    logger.warning(f"lifecycle_verified patch skipped: {_lc_err}")
            if source_id:
                try:
                    with get_db_connection() as db:
                        cur = db.cursor()
                        cur.execute(
                            "SELECT metadata FROM qd_script_sources WHERE id = ? AND user_id = ?",
                            (source_id, g.user_id),
                        )
                        row = cur.fetchone() or {}
                        metadata = row.get('metadata') if isinstance(row, dict) else {}
                        if isinstance(metadata, str):
                            try:
                                metadata = json.loads(metadata)
                            except Exception:
                                metadata = {}
                        if not isinstance(metadata, dict):
                            metadata = {}
                        metadata.update({
                            'lifecycle_verified': True,
                            'script_verified': True,
                            'lifecycle_verified_at': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
                        })
                        cur.execute(
                            """
                            UPDATE qd_script_sources
                            SET metadata = ?::jsonb, updated_at = NOW()
                            WHERE id = ? AND user_id = ?
                            """,
                            (json.dumps(metadata, ensure_ascii=False), source_id, g.user_id),
                        )
                        db.commit()
                        cur.close()
                except Exception as _source_err:
                    logger.warning(f"script source verified metadata patch skipped: {_source_err}")
        return jsonify(validation)
    except Exception as e:
        logger.error(f"verify_strategy_code failed: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})


@strategy_blp.route('/strategies/publish-template', methods=['POST'])
@login_required
def publish_strategy_template():
    """Publish script strategy code to marketplace as script_template asset."""
    try:
        payload = request.get_json() or {}
        source_id = int(payload.get('sourceId') or payload.get('source_id') or payload.get('scriptSourceId') or 0)
        source = None
        if source_id:
            from app.services.script_source import get_script_source_service
            source = get_script_source_service().get_source(source_id, user_id=g.user_id)
            if not source:
                return jsonify({'code': 0, 'msg': 'Script source not found', 'data': None}), 404

        strategy_id = int(payload.get('strategyId') or payload.get('strategy_id') or 0)
        if not strategy_id and not source:
            return jsonify({'code': 0, 'msg': 'strategyId is required', 'data': None}), 400

        strategy = None
        if strategy_id:
            strategy = get_strategy_service().get_strategy(strategy_id, user_id=g.user_id)
            if not strategy:
                return jsonify({'code': 0, 'msg': 'Strategy not found', 'data': None}), 404

        code = ((source or {}).get('code') or (strategy or {}).get('strategy_code') or '').strip()
        if not code:
            return jsonify({'code': 0, 'msg': 'Strategy has no script code', 'data': None}), 400

        validation = _validate_strategy_code_internal(code)
        if not validation.get('success'):
            return jsonify({
                'code': 0,
                'msg': validation.get('message') or 'Code verification failed',
                'data': validation,
            }), 400

        name = (payload.get('name') or (source or {}).get('name') or (strategy or {}).get('strategy_name') or '').strip()
        description = (payload.get('description') or (source or {}).get('description') or '').strip()
        pricing_type = (payload.get('pricingType') or payload.get('pricing_type') or 'free').strip() or 'free'
        try:
            price = float(payload.get('price') or 0)
        except Exception:
            price = 0.0
        existing_indicator_id = int(payload.get('indicatorId') or payload.get('indicator_id') or 0)

        user_role = getattr(g, 'user_role', 'user')
        is_admin = user_role == 'admin'

        from app.services.community_service import get_community_service
        ok, msg, data = get_community_service().publish_script_template_from_strategy(
            user_id=g.user_id,
            strategy_id=strategy_id,
            code=code,
            name=name,
            description=description,
            pricing_type=pricing_type,
            price=price,
            vip_free=bool(payload.get("vipFree") or payload.get("vip_free") or False),
            code_hidden=bool(payload.get("codeHidden") or payload.get("code_hidden") or payload.get("hideCode") or False),
            is_admin=is_admin,
            existing_indicator_id=existing_indicator_id,
            source_id=source_id,
        )
        if data is not None and source_id:
            data['source_id'] = source_id
        if not ok:
            return jsonify({'code': 0, 'msg': msg, 'data': data}), 400
        return jsonify({'code': 1, 'msg': 'success', 'data': data})
    except Exception as e:
        logger.error(f"publish_strategy_template failed: {str(e)}")
        return jsonify({'code': 0, 'msg': str(e), 'data': None}), 500


@strategy_blp.route('/strategies/publish-bot-preset', methods=['POST'])
@login_required
def publish_bot_preset():
    """Deprecated: bot presets are now published as editable script templates."""
    return jsonify({
        'code': 0,
        'msg': 'bot_preset publishing is deprecated; publish the generated script as a script template',
        'data': None,
    }), 410


@strategy_blp.route('/strategies/ai-generate', methods=['POST'])
@login_required
def ai_generate_strategy():
    """Generate strategy code or suggest template parameter updates using AI."""
    try:
        payload = request.get_json() or {}
        lang = _request_lang()
        prompt = payload.get('prompt', '')
        if not prompt.strip():
            return jsonify({'code': '', 'msg': _strategy_ai_text('prompt_empty', lang), 'params': None})

        intent = (payload.get('intent') or 'generate_code').strip()
        from app.services.llm import LLMService
        llm = LLMService()
        api_key = llm.get_api_key()
        if not api_key:
            return jsonify({'code': '', 'msg': _strategy_ai_text('no_llm_key', lang), 'params': None})

        from app.services.billing_service import get_billing_service
        billing = get_billing_service()
        user_id = g.user_id
        billing_feature = 'ai_indicator_to_strategy' if intent == 'indicator_to_strategy' else 'ai_code_gen'
        billing_ref = payload.get('source_indicator_id') if intent == 'indicator_to_strategy' else ''
        ok, billing_msg = billing.check_and_consume(
            user_id=user_id,
            feature=billing_feature,
            reference_id=str(billing_ref or f"ai_strategy_{intent}_{user_id}_{int(time.time())}")
        )
        if not ok:
            msg = f'Insufficient credits: {billing_msg}' if billing_msg else _strategy_ai_text('insufficient_credits', lang)
            return jsonify({'code': '', 'msg': msg, 'params': None})

        if intent == 'bot_recommend':
            from app.services.strategy_bot_recommend import recommend_bot_strategy

            try:
                result = recommend_bot_strategy(llm, prompt)
            except ValueError as exc:
                return jsonify({'code': '', 'params': None, 'bot_recommend': None, 'msg': str(exc)})
            return jsonify({'code': '', 'params': None, 'bot_recommend': result, 'msg': 'success'})

        if intent == 'adjust_params':
            template_key = payload.get('template_key') or ''
            current_params = payload.get('params') or {}
            code_snapshot = (payload.get('code') or '')[:8000]
            system_prompt = """You tune QuantDinger script-code template parameters from the user's request.
Return ONLY a single JSON object: keys are parameter names (strings), values are JSON numbers or booleans.
You may return a partial object (only keys that should change) or a full object.
Do not use markdown fences, do not add explanations before or after the JSON.

Hard boundary:
- Do not return symbol, timeframe, market_type, direction, trade_direction, investment_amount, initial_capital, leverage, or base_notional.
- Those fields are selected in the run panel, not tuned as script template parameters.

Percent parameter convention (IMPORTANT):
- Script template params are code-native values. Do not convert percent-like keys to UI percent numbers.
- For *_pct, *_ratio, allocation, weight, or position-size fields, return the exact ratio value that should
  be written into ctx.param(...): 0.08 means 8%, 0.8 means 80%, and 1 means 100%.
- Never return 8 when the user means 8%; return 0.08.
"""

            user_content = (
                f"Template key: {template_key}\n"
                f"Current parameters (JSON):\n{json.dumps(current_params, ensure_ascii=False)}\n\n"
                f"Strategy code excerpt (context):\n{code_snapshot}\n\n"
                f"User request:\n{prompt.strip()}\n\n"
                "Respond with JSON only."
            )

            content = llm.call_llm_api(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                model=llm.get_code_generation_model(),
                temperature=0.3,
                use_json_mode=False
            )

            raw = (content or '').strip()
            if raw.startswith('```'):
                raw = re.sub(r'^```[a-zA-Z]*', '', raw).strip()
                if raw.endswith('```'):
                    raw = raw[:-3].strip()
            updates = None
            try:
                updates = json.loads(raw)
            except json.JSONDecodeError:
                m = re.search(r'\{[\s\S]*\}', raw)
                if m:
                    try:
                        updates = json.loads(m.group(0))
                    except json.JSONDecodeError:
                        updates = None
            if not isinstance(updates, dict):
                return jsonify({'code': '', 'params': None, 'msg': _strategy_ai_text('invalid_json_params', lang)})
            return jsonify({'code': '', 'params': updates, 'msg': _strategy_ai_text('success', lang)})

        source = str(payload.get('source') or payload.get('entry_source') or '').strip().lower()
        if intent == 'indicator_to_strategy':
            system_prompt = INDICATOR_TO_STRATEGY_SYSTEM_PROMPT
        elif source in ('copilot_quick_tool', 'homepage_ai_assistant', 'ai_assistant_quick_tool'):
            system_prompt = SCRIPT_STRATEGY_QUICK_TOOL_SYSTEM_PROMPT
        else:
            system_prompt = SCRIPT_STRATEGY_SYSTEM_PROMPT

        extra = ''
        template_key = payload.get('template_key')
        params = payload.get('params')
        code_ctx = (payload.get('code') or '').strip()
        if template_key or params is not None or code_ctx:
            extra_parts = []
            if template_key:
                extra_parts.append(f"Current template key: {template_key}")
            if isinstance(params, dict) and params:
                extra_parts.append('Current template parameters (JSON):\n' + json.dumps(params, ensure_ascii=False))
            if code_ctx:
                extra_parts.append('Current code (may be long):\n' + code_ctx[:12000])
            extra = '\n\n' + '\n\n'.join(extra_parts)

        user_prompt = prompt.strip() + extra

        content = llm.call_llm_api(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model=llm.get_code_generation_model(),
            temperature=0.7,
            use_json_mode=False
        )

        content = content.strip()
        if content.startswith("```python"):
            content = content[9:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        AUTO_FIX_HINT_CODES = {
            'MISSING_ON_INIT',
            'MISSING_ON_BAR',
            'CTX_PARAM_MISSING_DEFAULT',
            'CTX_PARAM_RUN_PANEL_FIELD',
            'INDICATOR_OUTPUT_CONTRACT',
            'BASKET_CHILD_ORDER_MISSING_LAYER_ORDER',
            'BASKET_SIDE_MUST_BE_LONG_OR_SHORT',
        }

        def _needs_auto_fix_strategy(validation: dict) -> bool:
            if not validation.get('success'):
                return True
            hint_codes = {h.get('code') for h in (validation.get('hints') or [])}
            if intent == 'indicator_to_strategy' and 'INITIAL_STAKE_WITHOUT_DYNAMIC_CAPITAL' in hint_codes:
                return True
            return bool(hint_codes & AUTO_FIX_HINT_CODES)

        def _format_strategy_validation_issues(validation: dict) -> str:
            issues = []
            if not validation.get('success'):
                issues.append(f"- Verification failed: {validation.get('message')}")
                if validation.get('details'):
                    issues.append(f"- Details: {validation.get('details')}")
            for hint in validation.get('hints') or []:
                code_name = hint.get('code') or 'UNKNOWN'
                params_obj = hint.get('params') or {}
                if params_obj:
                    issues.append(f"- Hint {code_name}: {json.dumps(params_obj, ensure_ascii=False)}")
                else:
                    issues.append(f"- Hint {code_name}")
            return "\n".join(issues) if issues else "- No issues provided"

        def _repair_strategy_code_via_llm(bad_code: str, validation: dict) -> str:
            repair_prompt = (
                "You produced QuantDinger strategy script code that failed automatic validation. "
                "Fix the code while preserving the user's trading idea. Return one full replacement script only.\n\n"
                f"# Original user request\n{prompt.strip()}\n\n"
                f"# Validation issues to fix\n{_format_strategy_validation_issues(validation)}\n\n"
                "# Current code\n```python\n"
                + bad_code.strip()
                + "\n```\n\n"
                + SCRIPT_STRATEGY_REPAIR_REQUIREMENTS
            )
            repaired_content = llm.call_llm_api(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": repair_prompt},
                ],
                model=llm.get_code_generation_model(),
                temperature=0.2,
                use_json_mode=False
            )
            repaired_content = (repaired_content or '').strip()
            if repaired_content.startswith("```python"):
                repaired_content = repaired_content[9:]
            elif repaired_content.startswith("```"):
                repaired_content = repaired_content[3:]
            if repaired_content.endswith("```"):
                repaired_content = repaired_content[:-3]
            return repaired_content.strip() or bad_code

        validation = _validate_strategy_code_internal(content)
        debug = {
            'auto_fix_applied': False,
            'auto_fix_succeeded': False,
            'returned_candidate': 'initial',
            'initial_validation': _strategy_debug_summary(validation),
            'final_validation': _strategy_debug_summary(validation),
        }
        debug['human_summary'] = _strategy_human_summary(validation, validation, False, False, 'initial', lang=lang)

        if _needs_auto_fix_strategy(validation):
            logger.warning("ai_generate_strategy produced code needing auto-fix: %s", _format_strategy_validation_issues(validation))
            try:
                repaired = _repair_strategy_code_via_llm(content, validation)
                repaired_validation = _validate_strategy_code_internal(repaired)
                debug = {
                    'auto_fix_applied': True,
                    'auto_fix_succeeded': repaired_validation.get('success', False),
                    'returned_candidate': 'repaired' if repaired_validation.get('success') else 'initial',
                    'initial_validation': _strategy_debug_summary(validation),
                    'final_validation': _strategy_debug_summary(repaired_validation),
                }
                debug['human_summary'] = _strategy_human_summary(
                    validation,
                    repaired_validation,
                    True,
                    repaired_validation.get('success', False),
                    'repaired' if repaired_validation.get('success') else 'initial',
                    lang=lang
                )
                logger.info("ai_generate_strategy debug=%s", json.dumps(debug, ensure_ascii=False))
                if repaired_validation.get('success'):
                    content = repaired
                else:
                    logger.warning("ai_generate_strategy auto-fix failed, keeping initial candidate")
            except Exception as repair_err:
                debug = {
                    'auto_fix_applied': True,
                    'auto_fix_succeeded': False,
                    'returned_candidate': 'initial',
                    'initial_validation': _strategy_debug_summary(validation),
                    'final_validation': _strategy_debug_summary(validation),
                    'auto_fix_error': str(repair_err),
                }
                debug['human_summary'] = _strategy_human_summary(validation, validation, True, False, 'initial', lang=lang)
                logger.error("ai_generate_strategy auto-fix failed: %s", repair_err)
        else:
            debug['human_summary'] = _strategy_human_summary(validation, validation, False, False, 'initial', lang=lang)
            logger.info("ai_generate_strategy debug=%s", json.dumps(debug, ensure_ascii=False))

        if content:
            saved_source = None
            if payload.get('save_script_source') or payload.get('saveScriptSource'):
                try:
                    code_meta = _extract_script_metadata_from_code(content)
                    source_name = str(
                        code_meta.get('name')
                        or payload.get('script_source_name')
                        or payload.get('source_name')
                        or payload.get('strategy_name')
                        or 'AI Generated Strategy'
                    ).strip() or 'AI Generated Strategy'
                    source_description = str(
                        code_meta.get('description')
                        or payload.get('script_source_description')
                        or payload.get('description')
                        or ''
                    )
                    metadata = payload.get('script_source_metadata') or payload.get('metadata') or {}
                    if not isinstance(metadata, dict):
                        metadata = {}
                    metadata.update({
                        'generated_by': 'ai_strategy_generator',
                        'ai_generate_intent': intent,
                        'source_indicator_id': payload.get('source_indicator_id') or metadata.get('source_indicator_id') or '',
                        'script_verified': bool(debug.get('final_validation', {}).get('success')),
                        'lifecycle_verified': bool(debug.get('final_validation', {}).get('success')),
                    })
                    from app.services.script_source import get_script_source_service
                    service = get_script_source_service()
                    source_id = service.create_source({
                        'user_id': user_id,
                        'name': source_name,
                        'description': source_description,
                        'code': content,
                        'template_key': payload.get('template_key') or '',
                        'param_schema': {},
                        'metadata': metadata,
                    })
                    saved_source = service.get_source(source_id, user_id=user_id) or {'id': source_id}
                except Exception as save_err:
                    logger.error("ai_generate_strategy save script source failed: %s", save_err)
                    return jsonify({
                        'code': content,
                        'msg': f"{_strategy_ai_text('success', lang)}, but saving script source failed: {save_err}",
                        'params': None,
                        'debug': debug,
                        'data': {'source': None, 'source_id': None, 'save_error': str(save_err)}
                    }), 500
            data = {'source': saved_source, 'source_id': saved_source.get('id') if isinstance(saved_source, dict) else None} if saved_source else None
            return jsonify({'code': content, 'msg': _strategy_ai_text('success', lang), 'params': None, 'debug': debug, 'data': data})
        else:
            return jsonify({'code': '', 'msg': _strategy_ai_text('ai_empty_result', lang), 'params': None, 'debug': debug})
    except Exception as e:
        logger.error(f"ai_generate_strategy failed: {str(e)}")
        return jsonify({'code': '', 'msg': str(e), 'params': None, 'debug': None})


# openapi-compat: legacy import name
strategy_bp = strategy_blp
