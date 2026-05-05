"""
Backtest API routes
"""
from flask import Blueprint, request, jsonify, g
from datetime import datetime
import calendar
import traceback
import json
import time
import os

from app.services.backtest import BacktestService
from app.data_sources.factory import DataSourceFactory
from app.utils.logger import get_logger
from app.utils.db import get_db_connection
from app.utils.auth import login_required
from app.utils.safe_exec import validate_code_safety
import requests

logger = get_logger(__name__)

backtest_bp = Blueprint('backtest', __name__)
backtest_service = BacktestService()


def _add_months(dt: datetime, months: int) -> datetime:
    """Add calendar months while keeping the day within the target month."""
    month_index = (dt.month - 1) + int(months or 0)
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _backtest_range_limit(timeframe: str, start_date: datetime) -> tuple[datetime, str]:
    """Return the max allowed end date and human-readable label for a timeframe."""
    tf = str(timeframe or '').strip()
    if tf == '1m':
        return _add_months(start_date, 1), '1 month'
    if tf == '5m':
        return _add_months(start_date, 6), '6 months'
    if tf in ['15m', '30m']:
        return _add_months(start_date, 12), '1 year'
    return _add_months(start_date, 36), '3 years'


def _openrouter_base_and_key() -> tuple[str, str]:
    from app.config import APIKeys
    # Use APIKeys to get the key (handles env var + config cache properly)
    key = APIKeys.OPENROUTER_API_KEY or ""
    base = os.getenv("OPENROUTER_BASE_URL", "").strip()
    if not base:
        api_url = os.getenv("OPENROUTER_API_URL", "").strip()
        if api_url.endswith("/chat/completions"):
            base = api_url[: -len("/chat/completions")]
    if not base:
        base = "https://openrouter.ai/api/v1"
    return base, key


def _normalize_lang(lang: str | None) -> str:
    """
    Normalize language code for AI output.

    This should align with frontend i18n locales in the private Vue app (`src/locales/lang`).
    Supported:
      - zh-CN, zh-TW, en-US, ko-KR, th-TH, vi-VN, ar-SA, de-DE, fr-FR, ja-JP
    Default: zh-CN
    """
    supported = {
        "zh-CN",
        "zh-TW",
        "en-US",
        "ko-KR",
        "th-TH",
        "vi-VN",
        "ar-SA",
        "de-DE",
        "fr-FR",
        "ja-JP",
    }
    l = (lang or "").strip()
    if not l:
        return "zh-CN"
    alias = {
        "zh": "zh-CN",
        "zh-cn": "zh-CN",
        "zh-hans": "zh-CN",
        "zh-tw": "zh-TW",
        "zh-hant": "zh-TW",
        "en": "en-US",
        "en-us": "en-US",
        "ko": "ko-KR",
        "ko-kr": "ko-KR",
        "ja": "ja-JP",
        "ja-jp": "ja-JP",
        "fr": "fr-FR",
        "fr-fr": "fr-FR",
        "de": "de-DE",
        "de-de": "de-DE",
        "vi": "vi-VN",
        "vi-vn": "vi-VN",
        "th": "th-TH",
        "th-th": "th-TH",
        "ar": "ar-SA",
        "ar-sa": "ar-SA",
    }
    l2 = alias.get(l.lower(), l)
    return l2 if l2 in supported else "zh-CN"


@backtest_bp.route('/backtest/precision-info', methods=['GET'])
def get_precision_info():
    """
    获取回测精度信息（用于前端提示）
    
    Params (Query String):
        market: 市场类型
        startDate: 开始日期 (YYYY-MM-DD)
        endDate: 结束日期 (YYYY-MM-DD)
        
    Returns:
        精度信息，包含推荐的执行时间框架和预估K线数量
    """
    try:
        # Use request.args for GET params
        market = request.args.get('market', 'crypto')
        start_date_str = request.args.get('startDate', '')
        end_date_str = request.args.get('endDate', '')
        
        if not start_date_str or not end_date_str:
            return jsonify({'code': 0, 'msg': 'startDate and endDate are required'}), 400
        
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        
        exec_tf, precision_info = backtest_service.get_execution_timeframe(start_date, end_date, market)
        
        return jsonify({
            'code': 1,
            'msg': 'success',
            'data': precision_info
        })
    except Exception as e:
        logger.error(f"Get precision info failed: {e}")
        return jsonify({'code': 0, 'msg': str(e)}), 400


@backtest_bp.route('/backtest', methods=['POST'])
@login_required
def run_backtest():
    """
    Run indicator backtest for the current user.
    
    Params:
        indicatorId: Indicator ID (optional)
        indicatorCode: Indicator Python code
        symbol: Symbol
        market: Market type
        timeframe: Timeframe
        startDate: Start date (YYYY-MM-DD)
        endDate: End date (YYYY-MM-DD)
        initialCapital: Initial capital (default 10000)
        commission: Commission rate (default 0.001)
        enableMtf: Enable multi-timeframe backtest (default true, only for crypto)
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'code': 0,
                'msg': 'Request body is required',
                'data': None
            }), 400
        
        # Extract params - use current user's ID
        user_id = g.user_id
        indicator_code = data.get('indicatorCode', '')
        is_safe_code, unsafe_reason = validate_code_safety(indicator_code or '')
        if not is_safe_code:
            return jsonify({
                'code': 0,
                'msg': f'Unsafe indicator code: {unsafe_reason}',
                'data': None
            }), 400
        indicator_id = data.get('indicatorId')
        symbol = (data.get('symbol') or '').strip()
        market = (data.get('market') or '').strip()
        # 数据源仅由请求里的市场分类决定（与前端自选一致）；此处只做大小写/别名规范化
        market = DataSourceFactory.normalize_market(market)
        timeframe = data.get('timeframe', '1D')
        start_date_str = data.get('startDate', '')
        end_date_str = data.get('endDate', '')
        initial_capital = float(data.get('initialCapital', 10000))
        commission = float(data.get('commission', 0.001))
        slippage = float(data.get('slippage', 0.0))
        leverage = int(data.get('leverage', 1))
        trade_direction = data.get('tradeDirection', 'long')  # long, short, both
        strategy_config = data.get('strategyConfig') or {}
        # 多时间框架回测开关（默认开启，仅加密货币市场有效）
        enable_mtf = data.get('enableMtf', True)
        if isinstance(enable_mtf, str):
            enable_mtf = enable_mtf.lower() in ['true', '1', 'yes']
        # persist toggle: skip DB write when False for faster iteration
        persist = data.get('persist', True)
        if isinstance(persist, str):
            persist = persist.lower() in ['true', '1', 'yes']
        
        # (Debug) log received params if needed
        
        # If frontend only provides indicatorId, load code from local DB.
        if (not indicator_code or not str(indicator_code).strip()) and indicator_id:
            try:
                iid = int(indicator_id)
                with get_db_connection() as db:
                    cur = db.cursor()
                    cur.execute("SELECT code FROM qd_indicator_codes WHERE id = ?", (iid,))
                    row = cur.fetchone()
                    cur.close()
                if row and row.get('code'):
                    indicator_code = row.get('code')
            except Exception:
                pass

        # 参数验证
        if not all([indicator_code, symbol, market, timeframe, start_date_str, end_date_str]):
            return jsonify({
                'code': 0,
                'msg': 'Missing required parameters',
                'data': None
            }), 400
        
        # 转换日期
        # 开始日期：当天的 00:00:00
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        # 结束日期：当天的 23:59:59，确保包含整天的数据
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)

        # 验证时间范围限制
        days_diff = (end_date - start_date).days
        max_end_date, max_range_text = _backtest_range_limit(timeframe, start_date)
        max_end_date = max_end_date.replace(hour=23, minute=59, second=59)

        if end_date > max_end_date:
            max_days = (max_end_date - start_date).days
            # 生成友好的错误提示
            suggestion = ""
            if timeframe == '1m':
                suggestion = "建议：切换到更长周期（如 5m、15m、1h）或缩短回测时间范围"
            elif timeframe == '5m':
                suggestion = "建议：切换到更长周期（如 15m、30m、1h）或缩短回测时间范围"
            elif timeframe in ['15m', '30m']:
                suggestion = "建议：切换到更长周期（如 1h、4h、1d）以获得更长回测范围"
            else:
                suggestion = "建议：切换到更长周期（如 4h、1d）以获得更长回测范围"

            return jsonify({
                'code': 0,
                'msg': f'回测时间范围超出限制\n\n当前周期：{timeframe}\n支持最大范围：{max_range_text}（{max_days}天）\n您选择的天数：{days_diff}天\n\n{suggestion}\n\n各周期支持的最大回测范围：\n• 1m → 1个月\n• 5m → 6个月\n• 15m/30m → 1年\n• 1h/4h/1d → 3年',
                'data': None
            }), 400

        # Explicit audit log so we can always trace exactly which window the user asked for.
        logger.info(
            f"[BacktestRequest] user={user_id} indicator={indicator_id} {market}:{symbol} "
            f"tf={timeframe} range=[{start_date_str} ~ {end_date_str}] ({days_diff}d) "
            f"capital={initial_capital} leverage={leverage} direction={trade_direction} "
            f"mtf={enable_mtf}"
        )

        # 执行回测（支持多时间框架高精度回测）
        # 加密货币市场且启用MTF时，使用多时间框架回测
        if enable_mtf and market.lower() in ['crypto', 'cryptocurrency']:
            result = backtest_service.run_multi_timeframe(
                indicator_code=indicator_code,
                market=market,
                symbol=symbol,
                timeframe=timeframe,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                commission=commission,
                slippage=slippage,
                leverage=leverage,
                trade_direction=trade_direction,
                strategy_config=strategy_config,
                enable_mtf=True
            )
        else:
            result = backtest_service.run(
                indicator_code=indicator_code,
                market=market,
                symbol=symbol,
                timeframe=timeframe,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                commission=commission,
                slippage=slippage,
                leverage=leverage,
                trade_direction=trade_direction,
                strategy_config=strategy_config
            )
            # 添加标准回测的精度信息
            result['precision_info'] = {
                'enabled': False,
                'timeframe': timeframe,
                'precision': 'standard',
                'message': '使用标准K线回测'
            }

        run_id = None
        if persist:
            run_id = backtest_service.persist_run(
                user_id=user_id,
                indicator_id=int(indicator_id) if indicator_id is not None else None,
                run_type='indicator',
                market=market,
                symbol=symbol,
                timeframe=timeframe,
                start_date_str=start_date_str,
                end_date_str=end_date_str,
                initial_capital=initial_capital,
                commission=commission,
                slippage=slippage,
                leverage=leverage,
                trade_direction=trade_direction,
                strategy_config=strategy_config,
                config_snapshot={'indicatorId': int(indicator_id) if indicator_id is not None else None},
                status='success',
                error_message='',
                result=result,
                code=indicator_code,
            )
        
        return jsonify({
            'code': 1,
            'msg': 'Backtest succeeded',
            'data': {
                'runId': run_id,
                'result': result
            }
        })
        
    except ValueError as e:
        logger.warning(f"Invalid backtest parameters: {str(e)}")
        return jsonify({
            'code': 0,
            'msg': str(e),
            'data': None
        }), 400
    except Exception as e:
        logger.error(f"Backtest failed: {str(e)}")
        logger.error(traceback.format_exc())
        try:
            data = data if isinstance(data, dict) else {}
            user_id = g.user_id
            indicator_id = data.get('indicatorId')
            backtest_service.persist_run(
                user_id=user_id,
                indicator_id=int(indicator_id) if indicator_id is not None else None,
                run_type='indicator',
                market=str(data.get('market', '') or ''),
                symbol=str(data.get('symbol', '') or ''),
                timeframe=str(data.get('timeframe', '') or ''),
                start_date_str=str(data.get('startDate', '') or ''),
                end_date_str=str(data.get('endDate', '') or ''),
                initial_capital=float(data.get('initialCapital', 0) or 0),
                commission=float(data.get('commission', 0) or 0),
                slippage=float(data.get('slippage', 0) or 0),
                leverage=int(data.get('leverage', 1) or 1),
                trade_direction=str(data.get('tradeDirection', 'long') or 'long'),
                strategy_config=data.get('strategyConfig') or {},
                config_snapshot={'indicatorId': int(indicator_id) if indicator_id is not None else None},
                status='failed',
                error_message=str(e),
                result=None,
                code=str(data.get('indicatorCode', '') or ''),
            )
        except Exception:
            pass
        return jsonify({
            'code': 0,
            'msg': f'Backtest failed: {str(e)}',
            'data': None
        }), 500


@backtest_bp.route('/backtest/history', methods=['GET'])
@login_required
def get_backtest_history():
    """
    Get backtest run history for the current user.

    Params (Query String):
        limit: Page size (default 50, max 200)
        offset: Offset (default 0)
        indicatorId: Optional indicator id filter
        symbol: Optional symbol filter
        market: Optional market filter
        timeframe: Optional timeframe filter
    """
    try:
        # Use current user's ID
        user_id = g.user_id
        limit = int(request.args.get('limit') or 50)
        offset = int(request.args.get('offset') or 0)
        limit = max(1, min(limit, 200))
        offset = max(0, offset)

        indicator_id = request.args.get('indicatorId')
        strategy_id = request.args.get('strategyId')
        run_type = (request.args.get('runType') or '').strip()
        symbol = (request.args.get('symbol') or '').strip()
        market = (request.args.get('market') or '').strip()
        timeframe = (request.args.get('timeframe') or '').strip()
        rows = backtest_service.list_runs(
            user_id=user_id,
            limit=limit,
            offset=offset,
            indicator_id=int(indicator_id) if indicator_id is not None and str(indicator_id).strip() != "" else None,
            strategy_id=int(strategy_id) if strategy_id is not None and str(strategy_id).strip() != "" else None,
            run_type=run_type or None,
            symbol=symbol,
            market=market,
            timeframe=timeframe,
        )

        return jsonify({'code': 1, 'msg': 'OK', 'data': rows})
    except Exception as e:
        logger.error(f"get_backtest_history failed: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'code': 0, 'msg': str(e), 'data': None}), 500


@backtest_bp.route('/backtest/get', methods=['GET'])
@login_required
def get_backtest_run():
    """
    Get a backtest run detail by run id for the current user.

    Params (Query String):
        runId: Backtest run id (required)
    """
    try:
        user_id = g.user_id
        run_id = int(request.args.get('runId') or 0)
        if not run_id:
            return jsonify({'code': 0, 'msg': 'runId is required', 'data': None}), 400

        row = backtest_service.get_run(user_id=user_id, run_id=run_id)
        if not row:
            return jsonify({'code': 0, 'msg': 'run not found', 'data': None}), 404

        return jsonify({'code': 1, 'msg': 'OK', 'data': row})
    except Exception as e:
        logger.error(f"get_backtest_run failed: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'code': 0, 'msg': str(e), 'data': None}), 500


def _heuristic_ai_advice(runs: list[dict], lang: str) -> str:
    """
    Heuristic fallback when no model key is configured.
    Returns Chinese suggestions for parameter tuning.
    """
    if not runs:
        msg_map = {
            "zh-CN": "未找到可分析的回测记录。",
            "zh-TW": "未找到可分析的回測記錄。",
            "en-US": "No backtest runs selected.",
            "ko-KR": "분석할 백테스트 기록을 찾을 수 없습니다.",
            "th-TH": "ไม่พบประวัติแบ็กเทสต์สำหรับการวิเคราะห์",
            "vi-VN": "Không tìm thấy lịch sử backtest để phân tích.",
            "ar-SA": "لم يتم العثور على سجلات اختبار خلفي لتحليلها.",
            "de-DE": "Keine Backtest-Läufe zur Analyse ausgewählt.",
            "fr-FR": "Aucune exécution de backtest sélectionnée pour analyse.",
            "ja-JP": "分析するバックテスト記録が見つかりません。",
        }
        return msg_map.get(lang, msg_map["en-US"])

    # Use the last run as primary context, but mention multi-run comparison if provided.
    r0 = runs[0]
    result = (r0.get("result") or {}) if isinstance(r0, dict) else {}
    cfg = (r0.get("strategy_config") or {}) if isinstance(r0, dict) else {}
    risk = cfg.get("risk") or {}
    pos = cfg.get("position") or {}
    scale = cfg.get("scale") or {}

    total_return = float(result.get("totalReturn") or 0.0)
    max_dd = float(result.get("maxDrawdown") or 0.0)
    sharpe = float(result.get("sharpeRatio") or 0.0)
    win_rate = float(result.get("winRate") or 0.0)
    profit_factor = float(result.get("profitFactor") or 0.0)
    trades = int(result.get("totalTrades") or 0)

    stop_loss = float(risk.get("stopLossPct") or 0.0)
    take_profit = float(risk.get("takeProfitPct") or 0.0)
    trailing = (risk.get("trailing") or {}) if isinstance(risk.get("trailing"), dict) else {}
    trailing_enabled = bool(trailing.get("enabled"))
    trailing_pct = float(trailing.get("pct") or 0.0)
    trailing_act = float(trailing.get("activationPct") or 0.0)

    entry_pct = float(pos.get("entryPct") or 1.0)
    trend_add = scale.get("trendAdd") or {}
    dca_add = scale.get("dcaAdd") or {}
    trend_reduce = scale.get("trendReduce") or {}
    adverse_reduce = scale.get("adverseReduce") or {}

    # Minimal localized headings to keep heuristic readable across locales.
    headings = {
        "zh-CN": {"overall": "【总体建议】", "params": "【参数建议（可直接改回测配置测试）】", "next": "【下一步建议的回测方法】"},
        "zh-TW": {"overall": "【總體建議】", "params": "【參數建議（可直接改回測配置測試）】", "next": "【下一步回測方法建議】"},
        "en-US": {"overall": "Overall", "params": "Parameter suggestions (edit backtest config and re-run)", "next": "Next steps"},
        "ko-KR": {"overall": "요약", "params": "파라미터 제안(백테스트 설정 변경)", "next": "다음 단계"},
        "th-TH": {"overall": "สรุป", "params": "ข้อเสนอแนะพารามิเตอร์ (ปรับค่าที่ตั้งแบ็กเทสต์)", "next": "ขั้นตอนถัดไป"},
        "vi-VN": {"overall": "Tổng quan", "params": "Gợi ý tham số (sửa cấu hình backtest và chạy lại)", "next": "Bước tiếp theo"},
        "ar-SA": {"overall": "ملخص", "params": "اقتراحات المعلمات (عدّل إعدادات الاختبار وأعد التشغيل)", "next": "الخطوات التالية"},
        "de-DE": {"overall": "Überblick", "params": "Parameter-Vorschläge (Backtest-Konfiguration anpassen)", "next": "Nächste Schritte"},
        "fr-FR": {"overall": "Vue d’ensemble", "params": "Suggestions de paramètres (modifier la config et relancer)", "next": "Étapes suivantes"},
        "ja-JP": {"overall": "概要", "params": "パラメータ提案（設定変更→再バックテスト）", "next": "次のステップ"},
    }
    h = headings.get(lang, headings["en-US"])

    lines = []
    if lang == "en-US":
        if len(runs) > 1:
            lines.append(f"Received {len(runs)} backtest runs. Suggestions below focus on run #{r0.get('id','')}; validate with A/B tests across runs.")
        lines.append(h["overall"])
    elif lang == "zh-TW":
        if len(runs) > 1:
            lines.append(f"已收到 {len(runs)} 條回測記錄。以下以記錄 #{r0.get('id','')} 為主給出參數調整建議，並建議你用多組記錄做 A/B 驗證。")
        lines.append(h["overall"])
    else:
        if len(runs) > 1:
            if lang == "ko-KR":
                lines.append(f"{len(runs)}개의 백테스트 기록을 받았습니다. 아래는 #{r0.get('id','')} 기준으로 제안하며, 여러 기록으로 A/B 검증을 권장합니다.")
            elif lang == "th-TH":
                lines.append(f"ได้รับประวัติแบ็กเทสต์ {len(runs)} รายการ ข้อเสนอแนะด้านล่างอิงจาก #{r0.get('id','')} และแนะนำให้ทำ A/B test เทียบหลายชุด")
            elif lang == "vi-VN":
                lines.append(f"Đã nhận {len(runs)} bản ghi backtest. Gợi ý bên dưới tập trung vào #{r0.get('id','')} và khuyến nghị A/B test với nhiều bản ghi.")
            elif lang == "ar-SA":
                lines.append(f"تم استلام {len(runs)} من سجلات الاختبار الخلفي. تركّز الاقتراحات أدناه على التشغيل #{r0.get('id','')} مع توصية باختبارات A/B.")
            elif lang == "de-DE":
                lines.append(f"{len(runs)} Backtest-Läufe empfangen. Vorschläge unten fokussieren auf Lauf #{r0.get('id','')}; A/B-Tests über mehrere Läufe empfohlen.")
            elif lang == "fr-FR":
                lines.append(f"{len(runs)} exécutions de backtest reçues. Suggestions ci-dessous centrées sur #{r0.get('id','')}; A/B tests recommandés.")
            elif lang == "ja-JP":
                lines.append(f"{len(runs)} 件のバックテスト記録を受け取りました。以下は #{r0.get('id','')} を中心に提案し、複数記録でA/B検証を推奨します。")
            else:
                lines.append(f"Received {len(runs)} backtest runs. Suggestions below focus on run #{r0.get('id','')}; validate with A/B tests across runs.")
        lines.append(h["overall"])
    if sharpe < 0 or total_return < 0:
        if lang == "en-US":
            lines.append("- Strategy is losing/unstable: reduce risk first (lower entryPct, fewer/smaller scale-ins), then refine signal filters.")
        elif lang == "zh-TW":
            lines.append("- 目前策略偏虧損/不穩定：先降低風險暴露（降低開倉資金占比 entryPct、減少加倉次數/比例），再調整信號過濾。")
        else:
            lines.append("- 当前策略整体偏亏损/不稳定：优先降低风险暴露（降低开仓资金占比 entryPct、减少加仓次数/比例），再调信号过滤。")
    if max_dd > 30:
        if lang == "en-US":
            lines.append("- Max drawdown is high: tighten stop-loss or reduce leverage/entry size; consider enabling trailing to protect profits.")
        elif lang == "zh-TW":
            lines.append("- 最大回撤偏大：建議優先收緊止損或降低槓桿/開倉倉位；同時考慮啟用移動止盈以保護盈利回撤。")
        else:
            lines.append("- 最大回撤较大：建议优先收紧止损或降低杠杆/开仓仓位；同时考虑启用移动止盈保护盈利回撤。")
    if trades < 10:
        if lang == "en-US":
            lines.append("- Too few trades: rules may be too strict; relax thresholds or remove one filter to get enough samples.")
        elif lang == "zh-TW":
            lines.append("- 交易次數偏少：可能條件過嚴，建議適度放寬信號門檻或減少過濾條件，確保有足夠樣本驗證。")
        else:
            lines.append("- 交易次数偏少：可能条件过严，建议适当放宽信号阈值或减少过滤条件，确保有足够样本验证。")
    if win_rate < 35 and profit_factor >= 1.2:
        if lang == "en-US":
            lines.append("- Low win rate but decent PF: consider slightly wider stop-loss and use trailing to lock profits.")
        elif lang == "zh-TW":
            lines.append("- 勝率偏低但盈虧比不差：可考慮略放寬止損（讓盈利單跑起來），並用移動止盈鎖住利潤。")
        else:
            lines.append("- 胜率偏低但盈亏比不差：可以考虑放宽止损（让盈利单跑起来）并用移动止盈锁利润。")
    if win_rate >= 55 and profit_factor < 1.1:
        if lang == "en-US":
            lines.append("- Win rate is OK but PF is low: raise take-profit or enable trailing to improve winners; avoid taking profits too early.")
        elif lang == "zh-TW":
            lines.append("- 勝率不低但盈虧比偏小：考慮提高止盈或啟用移動止盈，讓單筆盈利更充分；避免過早止盈。")
        else:
            lines.append("- 胜率不低但盈亏比偏小：考虑提高止盈或启用移动止盈，让单笔盈利更充分；避免过早止盈。")

    lines.append("\n" + h["params"])
    if stop_loss <= 0:
        if lang == "en-US":
            lines.append("- Stop-loss: set stopLossPct (margin PnL basis). For crypto leverage, start with 2%~6% (then consider leverage conversion) and grid test.")
        elif lang == "zh-TW":
            lines.append("- 止損：建議設定 stopLossPct（按保證金口徑）。在加密+槓桿下，先從 2%~6%（再結合槓桿換算）做網格測試。")
        else:
            lines.append("- 止损：建议设置 stopLossPct（按保证金口径）。在加密+杠杆下，先从 2%~6%（再结合杠杆换算）做网格测试。")
    else:
        if lang == "en-US":
            lines.append(f"- Stop-loss: current stopLossPct={stop_loss:.4f} (margin basis). Test ±30% around it and monitor drawdown/liquidations.")
        elif lang == "zh-TW":
            lines.append(f"- 止損：目前 stopLossPct={stop_loss:.4f}（保證金口徑）。建議圍繞它做 ±30% 區間測試，並觀察回撤/爆倉次數變化。")
        else:
            lines.append(f"- 止损：当前 stopLossPct={stop_loss:.4f}（保证金口径）。建议围绕它做 ±30% 的区间测试，并观察回撤/爆仓次数变化。")
    if take_profit > 0 and (not trailing_enabled):
        if lang == "en-US":
            lines.append(f"- Take-profit: current takeProfitPct={take_profit:.4f}. Also test enabling trailing to reduce profit giveback.")
        elif lang == "zh-TW":
            lines.append(f"- 止盈：目前 takeProfitPct={take_profit:.4f}。建議同時測試啟用移動止盈（trailing）以降低盈利回撤。")
        else:
            lines.append(f"- 止盈：当前 takeProfitPct={take_profit:.4f}。建议同时测试开启移动止盈（trailing）以降低盈利回撤。")
    if trailing_enabled:
        if lang == "en-US":
            lines.append(f"- Trailing: enabled, pct={trailing_pct:.4f}, activationPct={trailing_act:.4f}. Set activation near typical winner PnL and test pct at 0.5x~1.5x.")
        elif lang == "zh-TW":
            lines.append(f"- 移動止盈：已啟用，pct={trailing_pct:.4f}, activationPct={trailing_act:.4f}。建議將 activationPct 設為略低於常見單筆盈利水平，並把 pct 做 0.5x~1.5x 測試。")
        else:
            lines.append(f"- 移动止盈：已启用，pct={trailing_pct:.4f}, activationPct={trailing_act:.4f}。建议把 activationPct 设为略低于常见单笔盈利水平，并把 pct 做 0.5x~1.5x 测试。")
    else:
        if lang == "en-US":
            lines.append("- Trailing: consider trailing.enabled=true; start with pct=1%~3% (margin basis) and test.")
        elif lang == "zh-TW":
            lines.append("- 移動止盈：建議開啟 trailing.enabled=true，並從 pct=1%~3%（保證金口徑換算後）開始測試。")
        else:
            lines.append("- 移动止盈：建议开启 trailing.enabled=true，并从 pct=1%~3%（保证金口径换算后）开始测试。")
    if lang == "en-US":
        lines.append(f"- Entry sizing: entryPct={entry_pct:.4f}. Test 0.2/0.3/0.5/0.8 to find a better return/drawdown sweet spot.")
    elif lang == "zh-TW":
        lines.append(f"- 開倉倉位：目前 entryPct={entry_pct:.4f}。建議先用 0.2/0.3/0.5/0.8 分層回測，找收益/回撤更優的甜區。")
    else:
        lines.append(f"- 开仓仓位：当前 entryPct={entry_pct:.4f}。建议先用 0.2/0.3/0.5/0.8 做分层回测，找收益/回撤更优的甜区。")

    # Scaling (very light guidance)
    if isinstance(trend_add, dict) and trend_add.get("enabled"):
        if lang == "en-US":
            lines.append("- Trend scale-in: reduce sizePct or maxTimes to avoid drawdown expansion; verify same-bar conflict rules match expectations.")
        elif lang == "zh-TW":
            lines.append("- 順勢加倉：建議優先降低 sizePct 或 maxTimes，避免回撤擴大；並確認同K線主信號禁用加減倉規則符合預期。")
        else:
            lines.append("- 顺势加仓：建议优先降低 sizePct 或 maxTimes，避免回撤扩大；并确保同K线主信号禁用加减仓的规则与你预期一致。")
    if isinstance(dca_add, dict) and dca_add.get("enabled"):
        if lang == "en-US":
            lines.append("- DCA scale-in: very risky under leverage; keep maxTimes small, sizePct low, and use stricter stop-loss.")
        elif lang == "zh-TW":
            lines.append("- 逆勢加倉：加密槓桿下風險極高，建議 maxTimes 更小、sizePct 更低，並採用更嚴格止損。")
        else:
            lines.append("- 逆势加仓：加密杠杆下风险极高，建议 maxTimes 更小、sizePct 更低，并强制更严格止损。")
    if isinstance(trend_reduce, dict) and trend_reduce.get("enabled"):
        if lang == "en-US":
            lines.append("- Trend reduce: can lower volatility but may reduce returns; test together with trailing.")
        elif lang == "zh-TW":
            lines.append("- 順勢減倉：有助降低波動，但可能降低收益；建議搭配移動止盈一起做對比測試。")
        else:
            lines.append("- 顺势减仓：适合降低波动，但可能降低收益；建议和移动止盈一起对比测试。")
    if isinstance(adverse_reduce, dict) and adverse_reduce.get("enabled"):
        if lang == "en-US":
            lines.append("- Adverse reduce: can control drawdowns but increases fees/slippage; consider enabling under higher leverage.")
        elif lang == "zh-TW":
            lines.append("- 逆勢減倉：可用於控回撤，但可能增加手續費/滑點成本；建議優先在高槓桿時開啟。")
        else:
            lines.append("- 逆势减仓：可用于控回撤，但可能增加手续费/滑点成本；建议优先在高杠杆时开启。")

    lines.append("\n" + h["next"])
    if lang == "zh-CN":
        lines.append("- 固定信号逻辑不变，只用参数做网格/分组测试（先粗再细）。每次只改 1~2 个参数，避免结论不可归因。")
        lines.append("- 重点同时看：总收益、最大回撤、夏普、交易次数、爆仓/止损触发次数。")
    elif lang == "zh-TW":
        lines.append("- 固定信號邏輯不變，只用參數做網格/分組測試（先粗後細）。每次只改 1~2 個參數，避免結論不可歸因。")
        lines.append("- 重點同時看：總收益、最大回撤、夏普、交易次數、爆倉/止損觸發次數。")
    else:
        # Keep English for other locales to ensure readability in fallback mode.
        lines.append("- Keep signal logic fixed; run parameter grid tests (coarse → fine). Change only 1-2 params per run.")
        lines.append("- Track: total return, max drawdown, Sharpe, trade count, liquidation/stop-loss triggers.")
    return "\n".join(lines)


@backtest_bp.route('/backtest/aiAnalyze', methods=['POST'])
@login_required
def ai_analyze_backtest_runs():
    """
    AI analyze selected backtest runs and provide strategy_config tuning suggestions
    for the current user.

    Params:
        runIds: list[int] (required)
    """
    try:
        data = request.get_json() or {}
        user_id = g.user_id
        backtest_service.ensure_storage_schema()
        lang = _normalize_lang(data.get('lang'))
        run_ids = data.get('runIds') or []
        if not isinstance(run_ids, list) or not run_ids:
            return jsonify({'code': 0, 'msg': 'runIds is required', 'data': None}), 400

        # Limit to avoid huge prompts / payload.
        run_ids = [int(x) for x in run_ids if str(x).strip().isdigit()]
        run_ids = run_ids[:10]
        if not run_ids:
            return jsonify({'code': 0, 'msg': 'runIds is required', 'data': None}), 400

        placeholders = ",".join(["?"] * len(run_ids))
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                f"""
                SELECT id, user_id, indicator_id, strategy_id, strategy_name, run_type, market, symbol, timeframe,
                       start_date, end_date, initial_capital, commission, slippage,
                       leverage, trade_direction, strategy_config, config_snapshot, status, error_message,
                       result_json, created_at
                FROM qd_backtest_runs
                WHERE user_id = ? AND id IN ({placeholders})
                ORDER BY id DESC
                """,
                (user_id, *run_ids),
            )
            rows = cur.fetchall() or []
            cur.close()

        runs: list[dict] = []
        for r in rows:
            try:
                r['strategy_config'] = json.loads(r.get('strategy_config') or '{}')
            except Exception:
                r['strategy_config'] = {}
            try:
                r['config_snapshot'] = json.loads(r.get('config_snapshot') or '{}')
            except Exception:
                r['config_snapshot'] = {}
            try:
                r['result'] = json.loads(r.get('result_json') or '{}')
            except Exception:
                r['result'] = {}
            r.pop('result_json', None)
            runs.append(r)

        if not runs:
            return jsonify({'code': 0, 'msg': 'runs not found', 'data': None}), 404

        # OpenRouter (optional)
        base_url, api_key = _openrouter_base_and_key()
        if not api_key:
            analysis = _heuristic_ai_advice(runs, lang)
            return jsonify({'code': 1, 'msg': 'OK', 'data': {'analysis': analysis, 'mode': 'heuristic', 'lang': lang}})

        model = (os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini") or "").strip() or "openai/gpt-4o-mini"
        temperature = float(os.getenv("OPENROUTER_TEMPERATURE", "0.4") or 0.4)

        output_lang_map = {
            "zh-CN": "Simplified Chinese",
            "zh-TW": "Traditional Chinese",
            "en-US": "English",
            "ko-KR": "Korean",
            "th-TH": "Thai",
            "vi-VN": "Vietnamese",
            "ar-SA": "Arabic",
            "de-DE": "German",
            "fr-FR": "French",
            "ja-JP": "Japanese",
        }
        output_lang = output_lang_map.get(lang, "English")

        system_prompt = (
            "You are an expert quantitative trading researcher specialized in crypto leveraged trading. "
            "Your job is to analyze backtest configurations and results, then propose actionable parameter tuning suggestions. "
            f"Output in {output_lang}. Be concise and practical. "
            "Do NOT change indicator code logic. Focus on strategy_config parameters only: risk (stopLossPct/takeProfitPct/trailing), "
            "position (entryPct), scale (trendAdd/dcaAdd/trendReduce/adverseReduce), execution assumptions. "
            "Provide: (1) diagnosis, (2) recommended parameter ranges, (3) suggested A/B test plan (few steps). "
            "Avoid investment advice language; focus on engineering/experimental recommendations."
        )

        user_payload = {
            "selectedRuns": [
                {
                    "id": r.get("id"),
                    "strategy_id": r.get("strategy_id"),
                    "strategy_name": r.get("strategy_name"),
                    "run_type": r.get("run_type"),
                    "market": r.get("market"),
                    "symbol": r.get("symbol"),
                    "timeframe": r.get("timeframe"),
                    "start_date": r.get("start_date"),
                    "end_date": r.get("end_date"),
                    "leverage": r.get("leverage"),
                    "trade_direction": r.get("trade_direction"),
                    "strategy_config": r.get("strategy_config") or {},
                    "config_snapshot": r.get("config_snapshot") or {},
                    "result": r.get("result") or {},
                    "status": r.get("status"),
                }
                for r in runs
            ]
        }

        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "temperature": temperature,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
            },
            timeout=30,
        )
        try:
            resp.raise_for_status()
            j = resp.json()
            content = (((j.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
            analysis = content.strip()
            if not analysis:
                analysis = _heuristic_ai_advice(runs, lang)
                return jsonify({'code': 1, 'msg': 'OK', 'data': {'analysis': analysis, 'mode': 'heuristic_fallback', 'lang': lang}})
            return jsonify({'code': 1, 'msg': 'OK', 'data': {'analysis': analysis, 'mode': 'llm', 'lang': lang}})
        except requests.exceptions.RequestException as e:
            # Do not fail the whole endpoint if LLM provider is misconfigured or rate-limited.
            logger.error(f"OpenRouter request failed, falling back to heuristic: {e}")
            analysis = _heuristic_ai_advice(runs, lang)
            return jsonify(
                {
                    'code': 1,
                    'msg': 'OK',
                    'data': {
                        'analysis': analysis,
                        'mode': 'heuristic_fallback',
                        'lang': lang,
                        'llmError': str(e),
                    },
                }
            )

    except Exception as e:
        logger.error(f"ai_analyze_backtest_runs failed: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'code': 0, 'msg': str(e), 'data': None}), 500

