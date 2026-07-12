"""
Experiment runner service.
"""

from __future__ import annotations

import copy
import json
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from app.services.unified_backtest import UnifiedBacktestService
from app.services.experiment.evolution import StrategyEvolutionService
from app.services.experiment.overrides import enrich_experiment_candidate, enrich_experiment_overrides
from app.services.experiment.optimizers import make_optimizer
from app.services.experiment.prompts import (
    SYSTEM_PROMPT,
    build_round_prompt,
    extract_indicator_params,
    parse_llm_candidates,
)
from app.services.experiment.regime import MarketRegimeService
from app.services.experiment.scoring import StrategyScoringService
from app.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_MAX_ROUNDS = 3
DEFAULT_CANDIDATES_PER_ROUND = 5
EARLY_STOP_SCORE = 82.0


class ExperimentRunnerService:
    """Orchestrate market regime detection, batch backtests, scoring and evolution."""

    def __init__(
        self,
        *,
        backtest_service: Optional[UnifiedBacktestService] = None,
        regime_service: Optional[MarketRegimeService] = None,
        scoring_service: Optional[StrategyScoringService] = None,
        evolution_service: Optional[StrategyEvolutionService] = None,
    ):
        self.backtest_service = backtest_service or UnifiedBacktestService()
        self.regime_service = regime_service or MarketRegimeService()
        self.scoring_service = scoring_service or StrategyScoringService()
        self.evolution_service = evolution_service or StrategyEvolutionService()

    # ------------------------------------------------------------------
    # NEW: LLM-driven multi-round AI pipeline
    # ------------------------------------------------------------------

    def _scorer_for_payload(self, payload: Dict[str, Any]) -> StrategyScoringService:
        """Return a scorer honouring per-request ``scoring.customWeights``.

        Falls back to the shared service when no overrides are supplied so we
        keep regime-aware switching as the default behaviour.
        """
        scoring_cfg = (payload or {}).get('scoring') or {}
        custom = scoring_cfg.get('customWeights')
        if isinstance(custom, dict) and custom:
            return StrategyScoringService(custom_weights=custom)
        return self.scoring_service

    def run_ai_pipeline(
        self,
        *,
        user_id: int,
        payload: Dict[str, Any],
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """
        Multi-round LLM-driven optimization pipeline.

        Flow per round:
          1. Build prompt from indicator code + regime + previous results
          2. LLM proposes N candidate parameter sets
          3. Batch-backtest each candidate
          4. Score & rank
          5. If best score >= threshold or max rounds reached -> stop

        Args:
            user_id: Current user.
            payload: Request body (base config + optional overrides).
            on_progress: Optional callback invoked after each round with
                         partial results (used for SSE streaming).

        Returns:
            Full experiment result dict.
        """
        base = payload.get('base') or payload
        max_rounds = int(payload.get('maxRounds') or DEFAULT_MAX_ROUNDS)
        n_per_round = int(payload.get('candidatesPerRound') or DEFAULT_CANDIDATES_PER_ROUND)
        early_stop = float(payload.get('earlyStopScore') or EARLY_STOP_SCORE)
        scorer = self._scorer_for_payload(payload)

        snapshot, start_date, end_date = self._build_snapshot(base=base, user_id=user_id)
        indicator_code = snapshot.get('code') or ''
        indicator_params = extract_indicator_params(indicator_code)

        # OOS 70/30 split uses the same semantics as `run_structured_tune`. We train
        # on the first 70% to keep LLM round backtests deterministic, then
        # validate the final ranked list on the held-out 30%. Disabled
        # automatically when the window is too short to split cleanly.
        oos_enabled_input = payload.get('oosValidation', True)
        oos_window = self._compute_oos_window(start_date, end_date) if oos_enabled_input else None
        if oos_window is not None:
            train_start = oos_window['train_start']
            train_end = oos_window['train_end']
            oos_start = oos_window['oos_start']
            oos_end = oos_window['oos_end']
        else:
            train_start, train_end = start_date, end_date
            oos_start = oos_end = None

        # --- Step 1: detect market regime ---
        self._emit(on_progress, 'regime', {'status': 'running'})
        try:
            regime = self.detect_regime(base)
        except Exception as exc:
            logger.warning("Regime detection failed, continuing without: %s", exc)
            regime = None
        self._emit(on_progress, 'regime', {'status': 'done', 'regime': regime})

        # --- Step 2..N: multi-round LLM optimization ---
        from app.services.llm import LLMService
        llm = LLMService()

        all_rounds: List[Dict[str, Any]] = []
        global_best: Optional[Dict[str, Any]] = None
        global_best_score = -1.0
        previous_results: Optional[List[Dict[str, Any]]] = None
        evaluation_trace: List[Dict[str, Any]] = []

        for round_num in range(1, max_rounds + 1):
            round_start = time.time()
            self._emit(on_progress, 'round_start', {
                'round': round_num,
                'maxRounds': max_rounds,
                'status': 'running',
            })

            # 2a. Build prompt
            prompt = build_round_prompt(
                indicator_code=indicator_code,
                indicator_params=indicator_params,
                regime=regime,
                previous_results=previous_results,
                round_number=round_num,
                n_candidates=n_per_round,
            )

            # 2b. Call LLM
            try:
                raw_response = llm.call_llm_api(
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.7 + round_num * 0.05,
                    use_json_mode=True,
                )
                candidates_raw = parse_llm_candidates(raw_response)
            except Exception as exc:
                logger.error("LLM call failed in round %d: %s", round_num, exc)
                candidates_raw = []

            if not candidates_raw:
                logger.warning("Round %d produced no candidates, skipping", round_num)
                all_rounds.append({
                    'round': round_num,
                    'candidates': [],
                    'bestScore': global_best_score,
                    'error': 'LLM returned no valid candidates',
                })
                continue

            # 2c. Backtest each candidate
            round_ranked: List[Dict[str, Any]] = []
            n_cand = len(candidates_raw)
            for idx, cand in enumerate(candidates_raw, start=1):
                self._emit(on_progress, "candidate_backtest", {
                    "round": round_num,
                    "index": idx,
                    "total": n_cand,
                })
                cand_snapshot = self._apply_candidate_to_snapshot(
                    snapshot, cand, indicator_params,
                )
                try:
                    result = self._run_backtest_checked(
                        cand_snapshot,
                        start_date=train_start,
                        end_date=train_end,
                        candidate_name=str(cand.get('name') or f'R{round_num}_{idx}'),
                    )
                except Exception as exc:
                    logger.error("Backtest failed for %s: %s", cand.get('name'), exc)
                    continue

                score = scorer.score_result(result, regime=regime)
                candidate_item = {
                    'name': cand.get('name', f'R{round_num}_{idx}'),
                    'reasoning': cand.get('reasoning', ''),
                    'source': f'ai_round_{round_num}',
                    'overrides': {
                        'indicatorParams': cand.get('indicatorParams', {}),
                        'riskParams': cand.get('riskParams', {}),
                    },
                    'snapshot': cand_snapshot,
                    'score': score,
                    'result': self._slim_result(result),
                }
                round_ranked.append(candidate_item)
                evaluation_trace.append(self._trace_point(candidate_item, len(evaluation_trace) + 1, round_num))

            round_ranked = scorer.rank_results(round_ranked)
            round_best = round_ranked[0] if round_ranked else None
            round_best_score = float((round_best or {}).get('score', {}).get('overallScore', 0))

            if round_best and round_best_score > global_best_score:
                global_best = round_best
                global_best_score = round_best_score

            round_info = {
                'round': round_num,
                'candidates': round_ranked,
                'bestScore': round_best_score,
                'globalBestScore': global_best_score,
                'elapsed': round(time.time() - round_start, 1),
            }
            all_rounds.append(round_info)

            self._emit(on_progress, 'round_done', round_info)

            previous_results = round_ranked

            if global_best_score >= early_stop:
                logger.info("Early stop: score %.1f >= %.1f at round %d",
                            global_best_score, early_stop, round_num)
                break

        # --- Final output ---
        all_candidates = []
        for rd in all_rounds:
            all_candidates.extend(rd.get('candidates') or [])
        all_candidates = scorer.rank_results(all_candidates)

        oos_meta = None
        if oos_start is not None and oos_end is not None:
            self._evaluate_oos(
                all_candidates, oos_start=oos_start, oos_end=oos_end, regime=regime, scorer=scorer,
            )
            oos_meta = {
                'enabled': True,
                'trainStart': train_start.strftime('%Y-%m-%d'),
                'trainEnd': train_end.strftime('%Y-%m-%d'),
                'oosStart': oos_start.strftime('%Y-%m-%d'),
                'oosEnd': oos_end.strftime('%Y-%m-%d'),
                'trainRatio': 0.7,
            }

        output = {
            'regime': regime,
            'generatorHints': self._build_generator_hints(regime) if regime else {},
            'indicatorParams': indicator_params,
            'rounds': [{
                'round': r['round'],
                'bestScore': r.get('bestScore', 0),
                'globalBestScore': r.get('globalBestScore', 0),
                'candidateCount': len(r.get('candidates') or []),
                'elapsed': r.get('elapsed', 0),
                'error': r.get('error'),
            } for r in all_rounds],
            'rankedStrategies': all_candidates[:20],
            'bestStrategyOutput': self._build_best_output(global_best),
            'oosValidation': oos_meta,
            'scoringWeights': scorer.resolve_weights(regime),
            'analytics': self._build_optimizer_analytics(
                all_candidates,
                evaluation_trace=evaluation_trace,
                parameter_space={},
                method='llm',
            ),
            'experiment': {
                'totalRounds': len(all_rounds),
                'totalCandidates': len(all_candidates),
                'globalBestScore': global_best_score,
                'mode': 'ai',
                'method': 'llm',
            },
        }
        # Final payload is sent once via SSE route (__final__); avoid duplicating huge JSON on progress.
        return output

    def save_as_strategy(
        self,
        *,
        user_id: int,
        best_output: Dict[str, Any],
        strategy_name: str,
        market_category: str = 'Crypto',
    ) -> int:
        """Persist the best experiment candidate as a strategy record."""
        from app.services.strategy import StrategyService
        svc = StrategyService()

        snap = best_output.get('snapshot') or {}
        strategy_config = snap.get('strategy_config') or {}

        payload = {
            'user_id': user_id,
            'strategy_name': strategy_name,
            'strategy_type': 'ScriptStrategy',
            'market_category': market_category,
            'execution_mode': 'signal',
            'status': 'stopped',
            'strategy_code': snap.get('code') or '',
            'trading_config': {
                'symbol': snap.get('symbol'),
                'timeframe': snap.get('timeframe'),
                'initial_capital': snap.get('initial_capital', 10000),
                'leverage': snap.get('leverage', 1),
                'commission': snap.get('commission', 0),
                'slippage': snap.get('slippage', 0),
                'trade_direction': snap.get('trade_direction', 'long'),
                'market_type': 'swap',
                'strategy_config': strategy_config,
                'strict_mode': snap.get('strict_mode', True),
            },
            'exchange_config': {},
        }
        return svc.create_strategy(payload)

    # ------------------------------------------------------------------
    # Helpers for AI pipeline
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_candidate_to_snapshot(
        base_snapshot: Dict[str, Any],
        candidate: Dict[str, Any],
        indicator_params_def: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build a backtest snapshot by merging LLM candidate params."""
        snap = copy.deepcopy(base_snapshot)

        ind_params = candidate.get('indicatorParams') or {}
        if ind_params:
            snap['indicator_params'] = {**(snap.get('indicator_params') or {}), **ind_params}

        risk = candidate.get('riskParams') or {}
        sc = snap.get('strategy_config') or {}

        if risk.get('stopLossPct') is not None:
            sc.setdefault('risk', {})['stopLossPct'] = risk['stopLossPct']
        if risk.get('takeProfitPct') is not None:
            sc.setdefault('risk', {})['takeProfitPct'] = risk['takeProfitPct']
        if risk.get('entryPct') is not None:
            sc.setdefault('position', {})['entryPct'] = risk['entryPct']

        trailing = risk.get('trailingStop') or {}
        if trailing.get('enabled'):
            sc.setdefault('risk', {})['trailing'] = {
                'enabled': True,
                'pct': trailing.get('pct', 0.02),
                'activationPct': trailing.get('activationPct', 0.01),
            }

        if risk.get('leverage') is not None:
            snap['leverage'] = int(risk['leverage'])

        snap['strategy_config'] = sc
        return snap

    @staticmethod
    def _slim_result(result: Dict[str, Any]) -> Dict[str, Any]:
        """Strip heavy fields (equityCurve, trades list) to keep payload small."""
        if not result:
            return {}
        if result.get('error'):
            return {'error': str(result.get('error') or '')}
        return {
            'totalReturn': result.get('totalReturn'),
            'annualReturn': result.get('annualReturn'),
            'maxDrawdown': result.get('maxDrawdown'),
            'sharpeRatio': result.get('sharpeRatio'),
            'profitFactor': result.get('profitFactor'),
            'winRate': result.get('winRate'),
            'totalTrades': result.get('totalTrades'),
            'bestTrade': result.get('bestTrade'),
            'worstTrade': result.get('worstTrade'),
            'avgTrade': result.get('avgTrade'),
            'winningTrades': result.get('winningTrades'),
            'losingTrades': result.get('losingTrades'),
            'avgWin': result.get('avgWin'),
            'avgLoss': result.get('avgLoss'),
            'finalEquity': result.get('finalEquity'),
            'totalCommission': result.get('totalCommission'),
        }

    @staticmethod
    def _result_summary(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not result:
            return None
        return {
            'totalReturn': result.get('totalReturn'),
            'maxDrawdown': result.get('maxDrawdown'),
            'sharpeRatio': result.get('sharpeRatio'),
            'totalTrades': result.get('totalTrades'),
        }

    @staticmethod
    def _backtest_error(result: Dict[str, Any]) -> str:
        if not isinstance(result, dict):
            return 'Backtest returned an invalid result'
        err = result.get('error')
        return str(err).strip() if err else ''

    @staticmethod
    def _is_no_trade_error(error: Exception) -> bool:
        text = str(error or '').lower()
        return (
            'no signals generated' in text or
            'no trades executed' in text
        )

    @staticmethod
    def _empty_oos_result(error: Exception) -> Dict[str, Any]:
        return {
            'totalReturn': 0.0,
            'annualReturn': 0.0,
            'maxDrawdown': 0.0,
            'sharpeRatio': 0.0,
            'profitFactor': 0.0,
            'winRate': 0.0,
            'totalTrades': 0,
            'equityCurve': [],
            'oosNote': str(error or ''),
        }

    def _run_backtest_checked(
        self,
        snapshot: Dict[str, Any],
        *,
        start_date: datetime,
        end_date: datetime,
        candidate_name: str = '',
    ) -> Dict[str, Any]:
        result = self.backtest_service.run_strategy_snapshot(
            snapshot,
            start_date=start_date,
            end_date=end_date,
        )
        err = self._backtest_error(result)
        if err:
            label = f" for {candidate_name}" if candidate_name else ""
            raise ValueError(f"Backtest failed{label}: {err}")
        return result

    @staticmethod
    def _emit(callback: Optional[Callable], event: str, data: Dict[str, Any]) -> None:
        if callback:
            try:
                callback({'event': event, **data})
            except Exception:
                pass

    def run_pipeline(
        self,
        *,
        user_id: int,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        base = payload.get('base') or payload
        parameter_space = payload.get('parameterSpace') or {}
        snapshot, start_date, end_date = self._build_snapshot(base=base, user_id=user_id)

        regime = self.detect_regime(base)
        candidates = self._build_candidates(
            base_snapshot=snapshot,
            variants=payload.get('variants') or [],
            parameter_space=parameter_space,
            evolution=payload.get('evolution') or {},
        )

        ranked: List[Dict[str, Any]] = []
        failures: List[str] = []
        for candidate in candidates:
            try:
                result = self._run_backtest_checked(
                    candidate['snapshot'],
                    start_date=start_date,
                    end_date=end_date,
                    candidate_name=str(candidate.get('name') or ''),
                )
            except Exception as exc:
                logger.error("Pipeline backtest failed for %s: %s", candidate.get('name'), exc)
                failures.append(str(exc))
                continue
            score = self.scoring_service.score_result(result, regime=regime)
            ranked.append({
                'name': candidate['name'],
                'source': candidate['source'],
                'overrides': candidate.get('overrides') or {},
                'snapshot': candidate['snapshot'],
                'score': score,
                'result': self._slim_result(result),
            })

        if not ranked:
            detail = failures[0] if failures else 'No valid candidates were generated'
            raise ValueError(f'All tuning candidates failed backtest. {detail}')

        ranked = self.scoring_service.rank_results(ranked)
        best = ranked[0] if ranked else None

        return {
            'regime': regime,
            'generatorHints': self._build_generator_hints(regime),
            'experiment': {
                'candidateCount': len(ranked),
                'rankedCount': len(ranked),
            },
            'rankedStrategies': ranked,
            'bestStrategyOutput': self._build_best_output(best),
            'analytics': self._build_optimizer_analytics(
                ranked,
                evaluation_trace=self._build_evaluation_trace(ranked),
                parameter_space=parameter_space,
                method=str((payload.get('evolution') or {}).get('method') or 'grid'),
            ),
        }

    def run_structured_tune(
        self,
        *,
        user_id: int,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Grid or random search over parameterSpace (strategy_config paths, leverage, etc.).
        No LLM. Scores on full backtest result, then returns slim payloads for the client.
        """
        import time

        base = payload.get('base') or payload
        parameter_space = payload.get('parameterSpace') or {}
        if not isinstance(parameter_space, dict) or not parameter_space:
            raise ValueError('parameterSpace is required and must be a non-empty object')

        evolution = payload.get('evolution') or {}
        max_variants = int(evolution.get('maxVariants') or 48)
        method = str(evolution.get('method') or 'grid').lower()
        if method not in ('grid', 'random', 'de', 'tpe'):
            method = 'grid'
        include_baseline = payload.get('includeBaseline', True)
        scorer = self._scorer_for_payload(payload)

        t0 = time.time()
        snapshot, start_date, end_date = self._build_snapshot(base=base, user_id=user_id)
        parameter_space = self._normalize_parameter_space_for_execution(
            parameter_space,
            snapshot=snapshot,
            start_date=start_date,
            end_date=end_date,
        )
        regime = self.detect_regime(base)

        # OOS validation 70/30: train on the first 70% of the window, then
        # re-backtest the top-K on the last 30%. Off when the window is too
        # short to split meaningfully OR when the caller explicitly disables.
        oos_enabled_input = payload.get('oosValidation', True)
        oos_window = self._compute_oos_window(start_date, end_date) if oos_enabled_input else None
        if oos_window is not None:
            train_start = oos_window['train_start']
            train_end = oos_window['train_end']
            oos_start = oos_window['oos_start']
            oos_end = oos_window['oos_end']
        else:
            train_start, train_end = start_date, end_date
            oos_start = oos_end = None

        if method in ('de', 'tpe'):
            ranked = self._run_iterative_optimizer(
                method=method,
                base_snapshot=snapshot,
                parameter_space=parameter_space,
                regime=regime,
                train_start=train_start,
                train_end=train_end,
                max_evals=max_variants,
                include_baseline=include_baseline,
                scorer=scorer,
            )
        else:
            candidates = self._build_candidates(
                base_snapshot=snapshot,
                variants=payload.get('variants') or [],
                parameter_space=parameter_space,
                evolution={
                    'method': method,
                    'maxVariants': max_variants,
                    'parameterSpace': parameter_space,
                },
            )
            if not include_baseline:
                candidates = [c for c in candidates if c.get('source') != 'baseline']

            ranked = []
            failures: List[str] = []
            for candidate in candidates:
                try:
                    result = self._run_backtest_checked(
                        candidate['snapshot'],
                        start_date=train_start,
                        end_date=train_end,
                        candidate_name=str(candidate.get('name') or ''),
                    )
                except Exception as exc:
                    logger.error("structured_tune backtest failed for %s: %s", candidate.get('name'), exc)
                    failures.append(f"{candidate.get('name') or 'candidate'}: {exc}")
                    continue
                score = scorer.score_result(result, regime=regime)
                ranked.append(enrich_experiment_candidate({
                    'name': candidate['name'],
                    'reasoning': '',
                    'source': candidate['source'],
                    'overrides': candidate.get('overrides') or {},
                    'snapshot': candidate['snapshot'],
                    'score': score,
                    'result': self._slim_result(result),
                }))

            if not ranked:
                detail = failures[0] if failures else 'No valid candidates were generated'
                raise ValueError(f'All tuning candidates failed backtest. {detail}')

        oos_fallback_reason = None
        if oos_start is not None and oos_end is not None and self._all_candidates_no_trade(ranked):
            oos_fallback_reason = (
                'The in-sample split produced no trades for every candidate; '
                'ranking fell back to the full requested window.'
            )
            logger.info("structured_tune OOS fallback: %s", oos_fallback_reason)
            ranked = self._reevaluate_ranked_on_window(
                ranked,
                start_date=start_date,
                end_date=end_date,
                regime=regime,
                scorer=scorer,
            )
            train_start, train_end = start_date, end_date
            oos_start = oos_end = None

        evaluation_trace = self._build_evaluation_trace(ranked)
        ranked = scorer.rank_results(ranked)
        no_trade = self._all_candidates_no_trade(ranked)
        if oos_start is not None and oos_end is not None:
            self._evaluate_oos(ranked, oos_start=oos_start, oos_end=oos_end, regime=regime, scorer=scorer)
        best = ranked[0] if ranked else None
        elapsed = round(time.time() - t0, 1)
        global_best_score = float((best or {}).get('score', {}).get('overallScore', 0) or 0)

        indicator_code = snapshot.get('code') or ''
        indicator_params = extract_indicator_params(indicator_code)

        oos_meta = None
        if oos_start is not None and oos_end is not None:
            oos_meta = {
                'enabled': True,
                'trainStart': train_start.strftime('%Y-%m-%d'),
                'trainEnd': train_end.strftime('%Y-%m-%d'),
                'oosStart': oos_start.strftime('%Y-%m-%d'),
                'oosEnd': oos_end.strftime('%Y-%m-%d'),
                'trainRatio': 0.7,
            }
        elif oos_fallback_reason:
            oos_meta = {
                'enabled': False,
                'fallbackReason': oos_fallback_reason,
                'trainStart': train_start.strftime('%Y-%m-%d'),
                'trainEnd': train_end.strftime('%Y-%m-%d'),
            }

        return {
            'regime': regime,
            'generatorHints': self._build_generator_hints(regime) if regime else {},
            'indicatorParams': indicator_params,
            'rounds': [{
                'round': 1,
                'bestScore': global_best_score,
                'globalBestScore': global_best_score,
                'candidateCount': len(ranked),
                'elapsed': elapsed,
                'error': None,
            }],
            'rankedStrategies': [enrich_experiment_candidate(c) for c in ranked[:50]],
            'bestStrategyOutput': self._build_best_output(best),
            'oosValidation': oos_meta,
            'scoringWeights': scorer.resolve_weights(regime),
            'analytics': self._build_optimizer_analytics(
                ranked,
                evaluation_trace=evaluation_trace,
                parameter_space=parameter_space,
                method=method,
            ),
            'experiment': {
                'totalRounds': 1,
                'totalCandidates': len(ranked),
                'globalBestScore': global_best_score,
                'mode': 'structured',
                'method': method,
                'maxVariants': max_variants,
                'parameterCount': len(parameter_space or {}),
                'noTrade': no_trade,
                'warning': (
                    'No candidate generated trades in this window. Extend the date range, '
                    'reduce lookback thresholds, or loosen filters.'
                ) if no_trade else None,
            },
        }

    def detect_regime(self, base: Dict[str, Any]) -> Dict[str, Any]:
        market = str(base.get('market') or 'Crypto')
        symbol = str(base.get('symbol') or '')
        timeframe = str(base.get('timeframe') or '1D')
        start_date, end_date = self._parse_dates(base)
        df = self.backtest_service._fetch_kline_data(market, symbol, timeframe, start_date, end_date)
        return self.regime_service.detect(df, symbol=symbol, market=market, timeframe=timeframe)

    def _run_iterative_optimizer(
        self,
        *,
        method: str,
        base_snapshot: Dict[str, Any],
        parameter_space: Dict[str, Any],
        regime: Dict[str, Any],
        train_start: datetime,
        train_end: datetime,
        max_evals: int,
        include_baseline: bool = True,
        scorer: Optional[StrategyScoringService] = None,
    ) -> List[Dict[str, Any]]:
        """Drive a DE/TPE optimizer through ``ask`` / ``tell`` batches.

        Each ``ask`` returns a batch of override dicts; we materialise them
        into snapshots, backtest, score, then feed the scores back via
        ``tell``. The loop exits once the optimizer's eval budget is used up
        OR it stops proposing new candidates.
        """
        active_scorer = scorer or self.scoring_service
        try:
            optimizer = make_optimizer(
                method, parameter_space, max_evals=max(8, int(max_evals)),
            )
        except ValueError as exc:
            logger.warning("Failed to build %s optimizer: %s; falling back to grid", method, exc)
            optimizer = None

        if optimizer is None:
            # Defensive fallback: caller should have routed grid/random to the
            # legacy path, but if we get here just emulate a one-shot grid.
            candidates = self._build_candidates(
                base_snapshot=base_snapshot,
                variants=[],
                parameter_space=parameter_space,
                evolution={
                    'method': 'grid',
                    'maxVariants': max(8, int(max_evals)),
                    'parameterSpace': parameter_space,
                },
            )
            ranked: List[Dict[str, Any]] = []
            failures: List[str] = []
            for candidate in candidates:
                try:
                    result = self._run_backtest_checked(
                        candidate['snapshot'],
                        start_date=train_start,
                        end_date=train_end,
                        candidate_name=str(candidate.get('name') or ''),
                    )
                except Exception as exc:
                    logger.error("fallback backtest failed: %s", exc)
                    failures.append(str(exc))
                    continue
                score = active_scorer.score_result(result, regime=regime)
                ranked.append({
                    'name': candidate['name'],
                    'reasoning': '',
                    'source': candidate['source'],
                    'overrides': candidate.get('overrides') or {},
                    'snapshot': candidate['snapshot'],
                    'score': score,
                    'result': self._slim_result(result),
                })
            if not ranked:
                detail = failures[0] if failures else 'No valid candidates were generated'
                raise ValueError(f'All tuning candidates failed backtest. {detail}')
            return ranked

        ranked: List[Dict[str, Any]] = []
        failures: List[str] = []

        # Optionally evaluate the baseline first so the user always sees how
        # the unmodified strategy compares to optimizer-found candidates.
        if include_baseline:
            try:
                base_result = self._run_backtest_checked(
                    copy.deepcopy(base_snapshot),
                    start_date=train_start,
                    end_date=train_end,
                    candidate_name='baseline',
                )
            except Exception as exc:
                logger.error("baseline backtest failed: %s", exc)
                failures.append(str(exc))
            else:
                base_score = active_scorer.score_result(base_result, regime=regime)
                ranked.append({
                    'name': 'baseline',
                    'reasoning': '',
                    'source': 'baseline',
                    'overrides': {},
                    'snapshot': copy.deepcopy(base_snapshot),
                    'score': base_score,
                    'result': self._slim_result(base_result),
                })

        gen_idx = 0
        while True:
            batch = optimizer.ask()
            if not batch:
                break
            gen_idx += 1
            tell_buffer: List[tuple[Dict[str, Any], float]] = []
            for cand_idx, overrides in enumerate(batch, start=1):
                snap = self._apply_overrides_to_snapshot(base_snapshot, overrides)
                try:
                    result = self._run_backtest_checked(
                        snap, start_date=train_start, end_date=train_end,
                        candidate_name=f'{method}_g{gen_idx}_c{cand_idx}',
                    )
                except Exception as exc:
                    logger.error("%s backtest failed for gen=%d cand=%d: %s",
                                 method, gen_idx, cand_idx, exc)
                    failures.append(str(exc))
                    continue
                score = active_scorer.score_result(result, regime=regime)
                overall = float((score or {}).get('overallScore') or 0.0)
                tell_buffer.append((overrides, overall))
                ranked.append({
                    'name': f'{method}_g{gen_idx}_c{cand_idx}',
                    'reasoning': '',
                    'source': f'evolution_{method}',
                    'overrides': overrides,
                    'snapshot': snap,
                    'score': score,
                    'result': self._slim_result(result),
                })
            if not tell_buffer:
                break
            optimizer.tell(tell_buffer)

        if not ranked:
            detail = failures[0] if failures else 'No valid candidates were generated'
            raise ValueError(f'All tuning candidates failed backtest. {detail}')
        return ranked

    @staticmethod
    def _candidate_trade_count(candidate: Dict[str, Any]) -> int:
        result = candidate.get('result') or {}
        try:
            return int(float(result.get('totalTrades') or 0))
        except Exception:
            return 0

    @classmethod
    def _all_candidates_no_trade(cls, ranked: List[Dict[str, Any]]) -> bool:
        return bool(ranked) and all(cls._candidate_trade_count(item) <= 0 for item in ranked)

    def _reevaluate_ranked_on_window(
        self,
        ranked: List[Dict[str, Any]],
        *,
        start_date: datetime,
        end_date: datetime,
        regime: Dict[str, Any],
        scorer: StrategyScoringService,
    ) -> List[Dict[str, Any]]:
        refreshed: List[Dict[str, Any]] = []
        failures: List[str] = []
        for candidate in ranked:
            try:
                result = self._run_backtest_checked(
                    candidate.get('snapshot') or {},
                    start_date=start_date,
                    end_date=end_date,
                    candidate_name=str(candidate.get('name') or ''),
                )
            except Exception as exc:
                logger.warning("fallback full-window backtest failed for %s: %s", candidate.get('name'), exc)
                failures.append(str(exc))
                continue
            updated = dict(candidate)
            updated['result'] = self._slim_result(result)
            updated['score'] = scorer.score_result(result, regime=regime)
            refreshed.append(enrich_experiment_candidate(updated))
        if refreshed:
            return refreshed
        if failures:
            logger.warning("All fallback full-window tuning candidates failed: %s", failures[0])
        return ranked

    @staticmethod
    def _apply_overrides_to_snapshot(
        base_snapshot: Dict[str, Any],
        overrides: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Materialise an override dict (dot-paths -> values) into a snapshot."""
        from app.services.experiment.evolution import StrategyEvolutionService
        evo = StrategyEvolutionService()
        snap = copy.deepcopy(base_snapshot)
        for key, value in (overrides or {}).items():
            parts = evo._normalize_key(key).split('.')
            evo._set_nested(snap, parts, value)
        return ExperimentRunnerService._sync_snapshot_param_aliases(snap, overrides)

    @staticmethod
    def _param_name_from_path(path: str) -> Optional[str]:
        """Return the leaf name for supported tunable-parameter override paths."""
        normalized = str(path or '').strip().replace('strategyConfig.', 'strategy_config.')
        prefixes = (
            'indicator_params.',
            'indicatorParams.',
            'script_params.',
            'scriptParams.',
            'params.',
            'paramOverrides.',
            'strategy_config.indicator_params.',
            'strategy_config.indicatorParams.',
            'strategy_config.script_params.',
            'strategy_config.scriptParams.',
            'strategy_config.params.',
            'strategy_config.paramOverrides.',
        )
        for prefix in prefixes:
            if normalized.startswith(prefix):
                name = normalized[len(prefix):].split('.')[-1].strip()
                return name or None
        return None

    @staticmethod
    def _is_period_like_param(name: str) -> bool:
        key = str(name or '').strip().lower()
        return any(token in key for token in (
            'period', 'lookback', 'window', 'length', 'len', 'bars',
            'ema', 'sma', 'rsi', 'adx', 'atr', 'ma',
        ))

    @staticmethod
    def _normalize_param_value_for_execution(name: str, value: Any) -> Any:
        """Return parameter values exactly as supplied by ScriptStrategy code/UI."""
        return value

    @staticmethod
    def _resolve_space_values(spec: Any) -> List[Any]:
        if isinstance(spec, list):
            return list(spec)
        if isinstance(spec, tuple):
            return list(spec)
        if isinstance(spec, dict):
            minimum = spec.get('min')
            maximum = spec.get('max')
            step = spec.get('step', 1)
            if minimum is None or maximum is None:
                return []
            if step == 0:
                return [minimum]
            try:
                cursor = float(minimum)
                max_value = float(maximum)
                step_value = float(step)
            except (TypeError, ValueError):
                return []
            if step_value <= 0:
                return []
            values: List[Any] = []
            while cursor <= max_value + 1e-12 and len(values) < 200:
                values.append(round(cursor, 10))
                cursor += step_value
            return values
        return [spec]

    @staticmethod
    def _expand_period_values(name: str, values: List[Any]) -> List[Any]:
        nums: List[int] = []
        lower = str(name or '').lower()
        allow_zero = any(token in lower for token in ('cooldown', 'delay', 'wait', 'pause'))
        for value in values:
            try:
                n = int(round(float(value)))
            except (TypeError, ValueError):
                continue
            nums.append(max(0 if allow_zero else 1, n))
        if not nums:
            return values

        positive = [n for n in nums if n > 0]
        current_max = max(positive or [max(nums)])
        anchors = [0, 2, 4, 6, 8, 12] if allow_zero else [3, 5, 8, 13, 21]
        if not allow_zero and current_max >= 34:
            anchors.extend([34, 55])
        if not allow_zero and current_max >= 89:
            anchors.append(89)
        if not allow_zero and current_max >= 144:
            anchors.append(144)
        cap = max(current_max, max(anchors))
        return [n for n in nums + anchors if n <= cap]

    @staticmethod
    def _dedupe_numeric_values(values: List[Any]) -> List[Any]:
        out: List[Any] = []
        seen = set()
        for value in values:
            try:
                num = float(value)
                normalized: Any = int(round(num)) if abs(num - round(num)) < 1e-9 else round(num, 10)
            except (TypeError, ValueError):
                normalized = value
            key = json.dumps(normalized, sort_keys=True, ensure_ascii=False) if isinstance(normalized, (dict, list)) else str(normalized)
            if key in seen:
                continue
            seen.add(key)
            out.append(normalized)
        out.sort(key=lambda item: float(item) if isinstance(item, (int, float)) else 0.0)
        return out

    @staticmethod
    def _normalize_parameter_space_for_execution(
        parameter_space: Dict[str, Any],
        *,
        snapshot: Optional[Dict[str, Any]] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        if not isinstance(parameter_space, dict):
            return {}
        normalized: Dict[str, Any] = {}
        for raw_path, spec in parameter_space.items():
            path = str(raw_path or '').strip()
            if not path:
                continue
            name = ExperimentRunnerService._param_name_from_path(path) or path.split('.')[-1]
            values = ExperimentRunnerService._resolve_space_values(spec)
            if not values:
                continue
            values = [
                ExperimentRunnerService._normalize_param_value_for_execution(name, value)
                for value in values
            ]
            if ExperimentRunnerService._is_period_like_param(name):
                values = ExperimentRunnerService._expand_period_values(name, values)
            normalized[path] = ExperimentRunnerService._dedupe_numeric_values(values)[:8]
        return normalized

    @staticmethod
    def _sync_snapshot_param_aliases(
        snapshot: Dict[str, Any],
        overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Keep all strategy parameter aliases aligned before ScriptStrategy backtesting.

        Historical call-sites used several equivalent containers: top-level
        ``indicator_params``/``script_params`` plus strategy_config
        ``params``/``paramOverrides``. Candidate tuning must update all aliases
        together; otherwise a changed value in ``script_params`` can be
        overwritten by the old value from ``params`` during execution.
        """
        if not isinstance(snapshot, dict):
            return snapshot

        strategy_config = snapshot.setdefault('strategy_config', {})
        if not isinstance(strategy_config, dict):
            strategy_config = {}
            snapshot['strategy_config'] = strategy_config

        merged: Dict[str, Any] = {}
        for source in (
            snapshot.get('indicator_params'),
            snapshot.get('indicatorParams'),
            snapshot.get('script_params'),
            snapshot.get('scriptParams'),
            snapshot.get('params'),
            snapshot.get('paramOverrides'),
            strategy_config.get('indicator_params'),
            strategy_config.get('indicatorParams'),
            strategy_config.get('script_params'),
            strategy_config.get('scriptParams'),
            strategy_config.get('params'),
            strategy_config.get('paramOverrides'),
        ):
            if isinstance(source, dict):
                merged.update(source)

        for path, value in (overrides or {}).items():
            name = ExperimentRunnerService._param_name_from_path(str(path))
            if name:
                merged[name] = ExperimentRunnerService._normalize_param_value_for_execution(name, value)

        if not merged:
            return snapshot

        merged = {
            str(name): ExperimentRunnerService._normalize_param_value_for_execution(str(name), value)
            for name, value in dict(merged).items()
        }
        snapshot['indicator_params'] = merged
        snapshot['indicatorParams'] = merged
        snapshot['script_params'] = merged
        snapshot['scriptParams'] = merged
        snapshot['params'] = merged
        snapshot['paramOverrides'] = merged
        strategy_config['indicator_params'] = merged
        strategy_config['indicatorParams'] = merged
        strategy_config['script_params'] = merged
        strategy_config['scriptParams'] = merged
        strategy_config['params'] = merged
        strategy_config['paramOverrides'] = merged

        config_snapshot = snapshot.get('config_snapshot')
        if isinstance(config_snapshot, dict):
            signal_config = config_snapshot.setdefault('signalConfig', {})
            if isinstance(signal_config, dict):
                signal_config['indicatorParams'] = merged
                signal_config['scriptParams'] = merged
                signal_config['params'] = merged
        return snapshot

    def _build_candidates(
        self,
        *,
        base_snapshot: Dict[str, Any],
        variants: List[Dict[str, Any]],
        parameter_space: Dict[str, Any],
        evolution: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        base_snapshot = self._sync_snapshot_param_aliases(copy.deepcopy(base_snapshot))
        candidates = [{
            'name': 'baseline',
            'snapshot': self._sync_snapshot_param_aliases(copy.deepcopy(base_snapshot)),
            'overrides': {},
            'source': 'baseline',
        }]

        for idx, variant in enumerate(variants, start=1):
            snapshot = copy.deepcopy(base_snapshot)
            overrides = variant.get('overrides') or variant
            for key, value in overrides.items():
                self.evolution_service._set_nested(
                    snapshot,
                    self.evolution_service._normalize_key(key).split('.'),
                    value,
                )
            snapshot = self._sync_snapshot_param_aliases(snapshot, overrides)
            candidates.append({
                'name': str(variant.get('name') or f'candidate_{idx}'),
                'snapshot': snapshot,
                'overrides': overrides,
                'source': 'manual_variant',
            })

        evo_conf = evolution or {}
        max_variants = int(evo_conf.get('maxVariants') or 0)
        effective_space = parameter_space or evo_conf.get('parameterSpace') or {}
        if effective_space:
            generated = self.evolution_service.build_variants(
                base_snapshot=base_snapshot,
                parameter_space=effective_space,
                max_variants=max_variants or 12,
                method=str(evo_conf.get('method') or 'grid'),
            )
            for candidate in generated:
                candidate['snapshot'] = self._sync_snapshot_param_aliases(
                    candidate.get('snapshot') or {},
                    candidate.get('overrides') or {},
                )
            candidates.extend(generated)

        unique: List[Dict[str, Any]] = []
        seen = set()
        for candidate in candidates:
            key = str(candidate.get('snapshot'))
            if key in seen:
                continue
            seen.add(key)
            unique.append(candidate)
        return unique

    def _build_snapshot(self, *, base: Dict[str, Any], user_id: int) -> tuple[Dict[str, Any], datetime, datetime]:
        start_date, end_date = self._parse_dates(base)
        snapshot = copy.deepcopy(base.get('snapshot') or {})
        if not snapshot:
            snapshot = self._resolve_base_snapshot(base=base, user_id=user_id)
        snapshot['user_id'] = user_id
        strategy_config = snapshot.setdefault('strategy_config', {})
        if snapshot.get('indicator_params'):
            strategy_config.setdefault('indicator_params', snapshot.get('indicator_params') or {})
        if snapshot.get('script_params'):
            strategy_config.setdefault('script_params', snapshot.get('script_params') or {})
            strategy_config.setdefault('params', snapshot.get('script_params') or {})
        snapshot = self._sync_snapshot_param_aliases(snapshot)
        return snapshot, start_date, end_date

    @staticmethod
    def _dict_value(value: Any) -> Dict[str, Any]:
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

    @staticmethod
    def _int_or_none(value: Any) -> Optional[int]:
        try:
            if value is None or str(value).strip() == "":
                return None
            return int(value)
        except Exception:
            return None

    @staticmethod
    def _asset_identity(base: Dict[str, Any]) -> tuple[str, Optional[int]]:
        asset_type = str(
            base.get('assetType')
            or base.get('asset_type')
            or base.get('type')
            or ''
        ).strip().lower()
        if asset_type in ('indicator_code',):
            asset_type = 'indicator'
        elif asset_type in ('script_source', 'script-strategy'):
            asset_type = 'script'
        elif asset_type in ('template', 'preset'):
            asset_type = 'bot'
        asset_id = ExperimentRunnerService._int_or_none(
            base.get('assetId')
            or base.get('asset_id')
            or base.get('sourceId')
            or base.get('source_id')
            or base.get('indicatorId')
            or base.get('scriptSourceId')
            or base.get('strategyId')
        )
        return asset_type, asset_id

    def _collect_param_overrides(self, base: Dict[str, Any]) -> Dict[str, Any]:
        strategy_config = self._dict_value(base.get('strategyConfig') or base.get('strategy_config'))
        override_config = self._dict_value(base.get('overrideConfig') or base.get('override_config'))
        merged: Dict[str, Any] = {}
        for source in (
            self._dict_value(base.get('indicatorParams')),
            self._dict_value(base.get('scriptParams')),
            self._dict_value(base.get('params')),
            self._dict_value(base.get('paramOverrides') or base.get('param_overrides')),
            self._dict_value(strategy_config.get('indicator_params') or strategy_config.get('indicatorParams')),
            self._dict_value(strategy_config.get('script_params') or strategy_config.get('scriptParams')),
            self._dict_value(strategy_config.get('params') or strategy_config.get('paramOverrides')),
            self._dict_value(override_config.get('indicator_params') or override_config.get('indicatorParams')),
            self._dict_value(override_config.get('script_params') or override_config.get('scriptParams')),
            self._dict_value(override_config.get('params') or override_config.get('paramOverrides')),
        ):
            merged.update(source)
        return merged

    def _runtime_override(self, base: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        strategy_config = self._dict_value(base.get('strategyConfig') or base.get('strategy_config'))
        override = self._dict_value(base.get('overrideConfig') or base.get('override_config'))
        for source_key, target_key in (
            ('market', 'market'),
            ('symbol', 'symbol'),
            ('timeframe', 'timeframe'),
            ('marketType', 'market_type'),
            ('market_type', 'market_type'),
            ('exchangeId', 'exchange_id'),
            ('exchange_id', 'exchange_id'),
            ('initialCapital', 'initialCapital'),
            ('initial_capital', 'initialCapital'),
            ('investmentAmount', 'investment_amount'),
            ('investment_amount', 'investment_amount'),
            ('leverage', 'leverage'),
            ('tradeDirection', 'trade_direction'),
            ('trade_direction', 'trade_direction'),
            ('commission', 'commission'),
            ('slippage', 'slippage'),
            ('fundingRateAnnual', 'fundingRateAnnual'),
            ('fundingIntervalHours', 'fundingIntervalHours'),
            ('strictMode', 'strictMode'),
            ('strict_mode', 'strict_mode'),
        ):
            if source_key in base:
                override[target_key] = base.get(source_key)
        for key in ('fees', 'risk', 'position', 'scale', 'execution'):
            if isinstance(strategy_config.get(key), dict):
                current = self._dict_value(override.get(key))
                current.update(strategy_config.get(key) or {})
                override[key] = current
        if params:
            override['indicator_params'] = dict(params)
            override['script_params'] = dict(params)
            override['params'] = dict(params)
            override['paramOverrides'] = dict(params)
        market_type = str(override.get('market_type') or '').strip().lower()
        if market_type in ('futures', 'future', 'perp', 'perpetual'):
            market_type = 'swap'
            override['market_type'] = market_type
        if market_type == 'spot':
            override['leverage'] = 1
            override['trade_direction'] = 'long'
        return override

    def _resolve_base_snapshot(self, *, base: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        """Build the same strategy snapshot shape used by the public backtest center.

        Experiment tuning must not invent a separate execution model. It tunes
        by producing candidate overrides, then every candidate goes through the
        single V2 backtest engine via StrategySnapshotResolver.
        """
        from app.services.strategy_snapshot import StrategySnapshotResolver

        asset_type, asset_id = self._asset_identity(base)
        params = self._collect_param_overrides(base)
        override = self._runtime_override(base, params)
        market = str(override.get('market') or base.get('market') or 'Crypto').strip() or 'Crypto'

        script_source_id = self._int_or_none(base.get('scriptSourceId') or base.get('sourceId'))
        indicator_id = self._int_or_none(base.get('indicatorId'))
        strategy_id = self._int_or_none(base.get('strategyId'))
        if asset_type == 'script':
            script_source_id = script_source_id or asset_id
        elif asset_type == 'indicator':
            indicator_id = indicator_id or asset_id
        elif asset_type == 'bot':
            strategy_id = strategy_id or asset_id

        if script_source_id:
            from app.services.script_source import get_script_source_service

            source = get_script_source_service().get_source(script_source_id, user_id=user_id)
            if not source:
                raise ValueError("Script source not found")
            strategy = {
                'id': None,
                'strategy_name': override.get('strategy_name') or source.get('name') or f'Script Source #{script_source_id}',
                'strategy_type': 'ScriptStrategy',
                'strategy_mode': 'script',
                'strategy_code': '',
                'market_category': market,
                'status': 'draft',
                'trading_config': {
                    **override,
                    'market_category': market,
                    'script_source_id': script_source_id,
                },
            }
        elif strategy_id:
            from app.routes.strategy_services import get_strategy_service

            strategy = get_strategy_service().get_strategy(strategy_id, user_id=user_id)
            if not strategy:
                raise ValueError("Strategy not found")
        elif str(base.get('indicatorCode') or '').strip():
            indicator_code = str(base.get('indicatorCode') or '').strip()
            strategy = {
                'id': None,
                'strategy_name': override.get('strategy_name') or base.get('name') or 'Inline Experiment Script',
                'strategy_type': 'ScriptStrategy',
                'strategy_mode': 'script',
                'strategy_code': indicator_code,
                'market_category': market,
                'status': 'draft',
                'trading_config': {
                    **override,
                    'market_category': market,
                },
            }
        else:
            raise ValueError(
                "Indicators are chart-only. Convert the indicator to a script strategy before running experiments."
            )

        snapshot = StrategySnapshotResolver(user_id=user_id).resolve(strategy, override)
        snapshot['user_id'] = user_id
        strategy_config = snapshot.setdefault('strategy_config', {})
        if params:
            snapshot['indicator_params'] = dict(params)
            snapshot['script_params'] = dict(params)
            strategy_config['indicator_params'] = dict(params)
            strategy_config['script_params'] = dict(params)
            strategy_config['params'] = dict(params)
            strategy_config['paramOverrides'] = dict(params)
        if snapshot.get('market_type'):
            strategy_config['market_type'] = snapshot.get('market_type')
        if str(snapshot.get('market_type') or '').strip().lower() == 'spot':
            snapshot['leverage'] = 1
            snapshot['trade_direction'] = 'long'
        return snapshot

    @staticmethod
    def _parse_dates(base: Dict[str, Any]) -> tuple[datetime, datetime]:
        start_raw = base.get('startDate') or base.get('start_date')
        end_raw = base.get('endDate') or base.get('end_date')
        if not start_raw or not end_raw:
            raise ValueError('startDate/start_date and endDate/end_date are required (YYYY-MM-DD)')
        start_date = datetime.strptime(str(start_raw), '%Y-%m-%d')
        requested_end = datetime.strptime(str(end_raw), '%Y-%m-%d').date()
        latest_complete_day = datetime.now().date() - timedelta(days=1)
        end_day = min(requested_end, latest_complete_day)
        end_date = datetime.combine(end_day, datetime.min.time()).replace(hour=23, minute=59, second=59)
        if end_date <= start_date:
            raise ValueError('Backtest end date must be before today and later than start date')
        return start_date, end_date

    @staticmethod
    def _compute_oos_window(
        start_date: datetime,
        end_date: datetime,
        train_ratio: float = 0.7,
        min_total_days: int = 30,
        min_oos_days: int = 7,
    ) -> Optional[Dict[str, datetime]]:
        """Split the backtest window into in-sample (train) + out-of-sample (test).

        Returns ``None`` when the window is too short to split meaningfully;
        callers should then fall back to the full window. We require at least
        ``min_total_days`` of data and ``min_oos_days`` of OOS to avoid trying
        to validate on a noisy 2-day tail.
        """
        from datetime import timedelta as _td
        if not start_date or not end_date or end_date <= start_date:
            return None
        total_seconds = (end_date - start_date).total_seconds()
        total_days = total_seconds / 86400.0
        if total_days < min_total_days:
            return None
        train_seconds = total_seconds * float(train_ratio)
        train_end = start_date + _td(seconds=train_seconds)
        oos_start = train_end
        oos_days = (end_date - oos_start).total_seconds() / 86400.0
        if oos_days < min_oos_days:
            return None
        return {
            'train_start': start_date,
            'train_end': train_end,
            'oos_start': oos_start,
            'oos_end': end_date,
        }

    def _evaluate_oos(
        self,
        ranked: List[Dict[str, Any]],
        *,
        oos_start: datetime,
        oos_end: datetime,
        regime: Dict[str, Any],
        top_k: Optional[int] = None,
        scorer: Optional[StrategyScoringService] = None,
    ) -> List[Dict[str, Any]]:
        """Re-backtest candidates on OOS data and annotate the rank list.

        We attach compact OOS metrics and a degradation flag so the client
        can flag overfit candidates. The mutation is in-place; the same list
        is returned for chaining.
        """
        if not ranked or oos_end <= oos_start:
            return ranked
        active_scorer = scorer or self.scoring_service
        limit = len(ranked) if top_k is None else max(0, min(int(top_k), len(ranked)))
        for candidate in ranked[:limit]:
            try:
                oos_result = self._run_backtest_checked(
                    candidate.get('snapshot') or {},
                    start_date=oos_start,
                    end_date=oos_end,
                    candidate_name=str(candidate.get('name') or ''),
                )
            except Exception as exc:
                logger.warning(
                    "OOS backtest failed for %s: %s", candidate.get('name'), exc
                )
                if self._is_no_trade_error(exc):
                    oos_result = self._empty_oos_result(exc)
                    oos_score = active_scorer.score_result(oos_result, regime=regime)
                    is_overall = float(((candidate.get('score') or {}).get('overallScore') or 0))
                    oos_overall = float((oos_score or {}).get('overallScore') or 0)
                    degradation = round((is_overall - oos_overall) / is_overall, 4) if is_overall > 0 else None
                    candidate['oosScore'] = oos_score
                    candidate['oosResult'] = self._slim_result(oos_result)
                    candidate['oosSummary'] = self._result_summary(candidate['oosResult'])
                    candidate['oosDegradation'] = degradation
                    candidate['oosOverfit'] = bool(
                        degradation is not None and degradation > 0.4
                    )
                    candidate['oosNote'] = 'No OOS trades were generated.'
                    continue
                candidate['oosError'] = str(exc)
                continue
            oos_score = active_scorer.score_result(oos_result, regime=regime)
            is_overall = float(((candidate.get('score') or {}).get('overallScore') or 0))
            oos_overall = float((oos_score or {}).get('overallScore') or 0)
            degradation = None
            if is_overall > 0:
                degradation = round((is_overall - oos_overall) / is_overall, 4)
            candidate['oosScore'] = oos_score
            candidate['oosResult'] = self._slim_result(oos_result)
            candidate['oosSummary'] = self._result_summary(candidate['oosResult'])
            candidate['oosDegradation'] = degradation
            # Severely overfit if OOS score collapses by 40%+ from IS.
            candidate['oosOverfit'] = bool(
                degradation is not None and degradation > 0.4
            )
        return ranked

    @staticmethod
    def _build_generator_hints(regime: Dict[str, Any]) -> Dict[str, Any]:
        families = regime.get('strategyFamilies') or []
        return {
            'preferredFamilies': families[:3],
            'regime': regime.get('regime'),
            'promptHint': (
                f"Focus on {', '.join(families[:2]) or 'robust'} setups under "
                f"{regime.get('label') or 'current'} conditions with risk controls."
            ),
        }

    @staticmethod
    def _trace_point(candidate: Dict[str, Any], index: int, round_num: Optional[int] = None) -> Dict[str, Any]:
        score = float(((candidate.get('score') or {}).get('overallScore')) or 0.0)
        result = candidate.get('result') or {}
        point = {
            'index': index,
            'name': candidate.get('name'),
            'source': candidate.get('source'),
            'score': round(score, 4),
            'totalReturn': result.get('totalReturn'),
            'maxDrawdown': result.get('maxDrawdown'),
            'sharpeRatio': result.get('sharpeRatio'),
            'totalTrades': result.get('totalTrades'),
        }
        if round_num is not None:
            point['round'] = round_num
        return point

    def _build_evaluation_trace(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [self._trace_point(candidate, idx) for idx, candidate in enumerate(candidates or [], start=1)]

    def _build_optimizer_analytics(
        self,
        ranked: List[Dict[str, Any]],
        *,
        evaluation_trace: Optional[List[Dict[str, Any]]] = None,
        parameter_space: Optional[Dict[str, Any]] = None,
        method: str = '',
    ) -> Dict[str, Any]:
        """Return audit-grade analytics derived only from evaluated backtests."""
        ranked = ranked or []
        trace = list(evaluation_trace or self._build_evaluation_trace(ranked))
        if not ranked:
            return {
                'summary': {
                    'method': method or '',
                    'evaluationCount': 0,
                    'parameterCount': len(parameter_space or {}),
                    'dataSource': 'backtest',
                },
                'convergence': [],
                'oosMatrix': [],
                'parameterSensitivity': [],
                'scoreDistribution': {},
            }

        best_score = float('-inf')
        best_name = None
        convergence: List[Dict[str, Any]] = []
        for raw in trace:
            score = float(raw.get('score') or 0.0)
            if score >= best_score:
                best_score = score
                best_name = raw.get('name')
            point = dict(raw)
            point['bestScore'] = round(max(best_score, 0.0), 4)
            point['bestName'] = best_name
            convergence.append(point)

        traced_names = {str(p.get('name')) for p in trace if p.get('name') is not None}
        if len(traced_names) < len(ranked):
            for candidate in ranked:
                if str(candidate.get('name')) in traced_names:
                    continue
                idx = len(convergence) + 1
                point = self._trace_point(candidate, idx)
                score = float(point.get('score') or 0.0)
                if score >= best_score:
                    best_score = score
                    best_name = point.get('name')
                point['bestScore'] = round(max(best_score, 0.0), 4)
                point['bestName'] = best_name
                convergence.append(point)

        oos_matrix = []
        for candidate in ranked:
            oos_score = candidate.get('oosScore') or {}
            if not oos_score:
                continue
            result = candidate.get('result') or {}
            oos_result = candidate.get('oosResult') or {}
            oos_matrix.append({
                'name': candidate.get('name'),
                'rank': candidate.get('rank'),
                'isScore': ((candidate.get('score') or {}).get('overallScore')),
                'oosScore': oos_score.get('overallScore'),
                'isReturn': result.get('totalReturn'),
                'oosReturn': oos_result.get('totalReturn'),
                'isDrawdown': result.get('maxDrawdown'),
                'oosDrawdown': oos_result.get('maxDrawdown'),
                'degradation': candidate.get('oosDegradation'),
                'overfit': bool(candidate.get('oosOverfit')),
            })

        scores = [float(((c.get('score') or {}).get('overallScore')) or 0.0) for c in ranked]
        distribution = self._score_distribution(scores)

        return {
            'summary': {
                'method': method or '',
                'evaluationCount': len(trace) or len(ranked),
                'rankedCount': len(ranked),
                'parameterCount': len(parameter_space or {}),
                'parameterKeys': list((parameter_space or {}).keys())[:20],
                'dataSource': 'backtest',
                'oosCount': len(oos_matrix),
            },
            'convergence': convergence[:200],
            'oosMatrix': oos_matrix,
            'parameterSensitivity': self._parameter_sensitivity(ranked),
            'scoreDistribution': distribution,
        }

    @staticmethod
    def _score_distribution(scores: List[float]) -> Dict[str, Any]:
        if not scores:
            return {}
        ordered = sorted(scores)
        n = len(ordered)

        def pct(p: float) -> float:
            if n == 1:
                return ordered[0]
            pos = (n - 1) * p
            lo = int(pos)
            hi = min(n - 1, lo + 1)
            frac = pos - lo
            return ordered[lo] * (1 - frac) + ordered[hi] * frac

        mean = sum(ordered) / n
        variance = sum((x - mean) ** 2 for x in ordered) / n
        return {
            'count': n,
            'min': round(ordered[0], 4),
            'p25': round(pct(0.25), 4),
            'median': round(pct(0.5), 4),
            'p75': round(pct(0.75), 4),
            'max': round(ordered[-1], 4),
            'mean': round(mean, 4),
            'std': round(variance ** 0.5, 4),
        }

    @staticmethod
    def _parameter_sensitivity(ranked: List[Dict[str, Any]], *, limit: int = 8) -> List[Dict[str, Any]]:
        """Estimate parameter impact from observed candidates, not synthetic modelling."""
        buckets_by_key: Dict[str, Dict[str, Dict[str, Any]]] = {}
        numeric_pairs: Dict[str, List[tuple[float, float]]] = {}

        for candidate in ranked or []:
            score = float(((candidate.get('score') or {}).get('overallScore')) or 0.0)
            result = candidate.get('result') or {}
            overrides = candidate.get('overrides') or {}
            flat = ExperimentRunnerService._flatten_overrides(overrides)
            for key, value in flat.items():
                label = ExperimentRunnerService._stable_value_label(value)
                by_value = buckets_by_key.setdefault(key, {})
                bucket = by_value.setdefault(label, {
                    'value': value,
                    'label': label,
                    'count': 0,
                    'scoreSum': 0.0,
                    'returnSum': 0.0,
                    'drawdownSum': 0.0,
                })
                bucket['count'] += 1
                bucket['scoreSum'] += score
                bucket['returnSum'] += float(result.get('totalReturn') or 0.0)
                bucket['drawdownSum'] += abs(float(result.get('maxDrawdown') or 0.0))
                try:
                    numeric_pairs.setdefault(key, []).append((float(value), score))
                except (TypeError, ValueError):
                    pass

        out: List[Dict[str, Any]] = []
        for key, raw_buckets in buckets_by_key.items():
            buckets = []
            for bucket in raw_buckets.values():
                count = max(1, int(bucket['count']))
                buckets.append({
                    'value': bucket['value'],
                    'label': bucket['label'],
                    'count': count,
                    'avgScore': round(bucket['scoreSum'] / count, 4),
                    'avgReturn': round(bucket['returnSum'] / count, 4),
                    'avgDrawdown': round(bucket['drawdownSum'] / count, 4),
                })
            if len(buckets) < 2:
                continue
            buckets.sort(key=lambda x: x['avgScore'], reverse=True)
            best = buckets[0]
            worst = buckets[-1]
            effect = float(best['avgScore'] - worst['avgScore'])
            corr = ExperimentRunnerService._pearson(numeric_pairs.get(key) or [])
            importance = abs(corr) if corr is not None else effect / 100.0
            out.append({
                'key': key,
                'kind': 'numeric' if corr is not None else 'categorical',
                'sampleCount': sum(int(b['count']) for b in buckets),
                'uniqueCount': len(buckets),
                'importance': round(max(0.0, min(1.0, float(importance))), 4),
                'correlation': None if corr is None else round(corr, 4),
                'effect': round(effect, 4),
                'bestValue': best['value'],
                'worstValue': worst['value'],
                'bestAvgScore': best['avgScore'],
                'worstAvgScore': worst['avgScore'],
                'buckets': buckets[:10],
            })

        out.sort(key=lambda item: (float(item.get('importance') or 0.0), float(item.get('effect') or 0.0)), reverse=True)
        return out[:limit]

    @staticmethod
    def _flatten_overrides(overrides: Dict[str, Any]) -> Dict[str, Any]:
        flat: Dict[str, Any] = {}

        def walk(prefix: str, value: Any) -> None:
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    next_key = f'{prefix}.{sub_key}' if prefix else str(sub_key)
                    walk(next_key, sub_value)
            else:
                flat[prefix] = value

        walk('', overrides or {})
        return flat

    @staticmethod
    def _stable_value_label(value: Any) -> str:
        if isinstance(value, float):
            return f'{value:.8g}'
        if isinstance(value, (dict, list, tuple)):
            try:
                return json.dumps(value, sort_keys=True, ensure_ascii=False)
            except Exception:
                return str(value)
        return str(value)

    @staticmethod
    def _pearson(pairs: List[tuple[float, float]]) -> Optional[float]:
        if len(pairs) < 3:
            return None
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        if len(set(xs)) < 2 or len(set(ys)) < 2:
            return None
        mx = sum(xs) / len(xs)
        my = sum(ys) / len(ys)
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        vx = sum((x - mx) ** 2 for x in xs)
        vy = sum((y - my) ** 2 for y in ys)
        if vx <= 0 or vy <= 0:
            return None
        return cov / ((vx * vy) ** 0.5)

    @staticmethod
    def _build_best_output(best: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Shape the best candidate for the frontend.

        Includes both IS (training-window) and, when available, OOS
        (held-out 30% window) summaries so the UI can show them side
        by side. Previously only IS was returned, which made the
        headline +X% return look like the candidate's real expected
        performance and led to surprises when users re-ran the
        candidate on the full window.
        """
        if not best:
            return None
        result = best.get('result') or {}
        oos_result = best.get('oosResult') or {}
        oos_summary = best.get('oosSummary')
        if oos_summary is None and oos_result:
            oos_summary = ExperimentRunnerService._result_summary(oos_result)
        overrides = enrich_experiment_overrides(best.get('overrides') or {})
        params = dict(overrides.get('params') or {})
        script_params = dict(overrides.get('scriptParams') or params)
        indicator_params = dict(overrides.get('indicatorParams') or params)
        return {
            'name': best.get('name'),
            'score': best.get('score'),
            'source': best.get('source'),
            'overrides': overrides,
            'params': params,
            'paramOverrides': params,
            'scriptParams': script_params,
            'indicatorParams': indicator_params,
            'snapshot': best.get('snapshot'),
            'result': result,
            'summary': ExperimentRunnerService._result_summary(result),
            'oosSummary': oos_summary,
            'oosScore': best.get('oosScore'),
            'oosDegradation': best.get('oosDegradation'),
            'oosOverfit': bool(best.get('oosOverfit')),
            'oosError': best.get('oosError'),
            'oosNote': best.get('oosNote'),
        }
