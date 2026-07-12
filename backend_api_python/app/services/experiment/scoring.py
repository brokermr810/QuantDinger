"""
Strategy scoring service.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


class StrategyScoringService:
    """Convert backtest results into comparable multi-factor scores."""

    DEFAULT_WEIGHTS = {
        'return': 0.22,
        'annual_return': 0.12,
        'sharpe': 0.18,
        'profit_factor': 0.14,
        'win_rate': 0.09,
        'drawdown': 0.15,
        'stability': 0.10,
    }

    # Regime-specific weight profiles. Each profile MUST keep the same 7 keys
    # so the weighted sum stays comparable across runs. The numbers are picked
    # so that:
    #   - trending regimes reward absolute return and sharpe more,
    #   - ranging regimes punish whipsaw via win_rate + stability,
    #   - high-volatility regimes weight drawdown heavily so we don't crown
    #     fragile candidates that survived a quiet stretch.
    # Falls back to ``DEFAULT_WEIGHTS`` when the regime key is unknown.
    REGIME_WEIGHTS = {
        'bull_trend': {
            'return': 0.30, 'annual_return': 0.18, 'sharpe': 0.16,
            'profit_factor': 0.10, 'win_rate': 0.06, 'drawdown': 0.12, 'stability': 0.08,
        },
        'bear_trend': {
            'return': 0.16, 'annual_return': 0.10, 'sharpe': 0.20,
            'profit_factor': 0.16, 'win_rate': 0.06, 'drawdown': 0.22, 'stability': 0.10,
        },
        'range_compression': {
            'return': 0.10, 'annual_return': 0.06, 'sharpe': 0.14,
            'profit_factor': 0.18, 'win_rate': 0.20, 'drawdown': 0.12, 'stability': 0.20,
        },
        'high_volatility': {
            'return': 0.14, 'annual_return': 0.08, 'sharpe': 0.16,
            'profit_factor': 0.18, 'win_rate': 0.06, 'drawdown': 0.26, 'stability': 0.12,
        },
    }

    def __init__(self, *, custom_weights: Dict[str, float] | None = None) -> None:
        # ``custom_weights`` overrides regime defaults globally for this
        # service instance; runners can construct a fresh scorer per request
        # if the user provides UI-side weights.
        self._custom_weights = self._sanitize_weights(custom_weights) if custom_weights else None

    def resolve_weights(self, regime: Dict[str, Any] | None = None) -> Dict[str, float]:
        """Pick the weight vector for a given regime.

        Resolution order: explicit per-instance override → regime profile →
        ``DEFAULT_WEIGHTS``. Result is renormalised so its components sum to
        1.0 — guards against profiles that drift due to manual edits.
        """
        if self._custom_weights:
            return self._custom_weights
        regime_key = str((regime or {}).get('regime') or '').lower()
        weights = self.REGIME_WEIGHTS.get(regime_key) or self.DEFAULT_WEIGHTS
        return self._sanitize_weights(weights)

    @staticmethod
    def _sanitize_weights(weights: Dict[str, float]) -> Dict[str, float]:
        """Ensure all 7 keys exist and the vector sums to 1.0."""
        keys = ('return', 'annual_return', 'sharpe', 'profit_factor',
                'win_rate', 'drawdown', 'stability')
        cleaned: Dict[str, float] = {}
        for key in keys:
            try:
                cleaned[key] = max(0.0, float(weights.get(key, 0.0)))
            except (TypeError, ValueError):
                cleaned[key] = 0.0
        total = sum(cleaned.values()) or 1.0
        return {key: round(value / total, 4) for key, value in cleaned.items()}

    def score_result(self, result: Dict[str, Any], *, regime: Dict[str, Any] | None = None) -> Dict[str, Any]:
        result = result or {}
        total_return = self._as_float(result.get('totalReturn'))
        annual_return = self._as_float(result.get('annualReturn'))
        max_drawdown = abs(self._as_float(result.get('maxDrawdown')))
        sharpe = self._as_float(result.get('sharpeRatio'))
        profit_factor = self._as_float(result.get('profitFactor'))
        win_rate = self._as_float(result.get('winRate'))
        total_trades = int(self._as_float(result.get('totalTrades')))

        components = {
            'returnScore': self._bounded_score(total_return, floor=-20.0, ceiling=80.0),
            'annualReturnScore': self._bounded_score(annual_return, floor=-20.0, ceiling=120.0),
            'sharpeScore': self._bounded_score(sharpe, floor=-1.0, ceiling=3.0),
            'profitFactorScore': self._bounded_score(profit_factor, floor=0.7, ceiling=2.5),
            'winRateScore': self._bounded_score(win_rate, floor=35.0, ceiling=70.0),
            'drawdownScore': self._inverse_score(max_drawdown, floor=5.0, ceiling=45.0),
            'stabilityScore': self._stability_score(result.get('equityCurve') or []),
            'sampleSizeScore': self._bounded_score(total_trades, floor=5.0, ceiling=80.0),
        }

        if total_trades <= 0:
            components.update({
                'returnScore': 0.0,
                'annualReturnScore': 0.0,
                'sharpeScore': 0.0,
                'profitFactorScore': 0.0,
                'winRateScore': 0.0,
                'sampleSizeScore': 0.0,
                'regimeFitScore': 0.0,
            })
            return {
                'overallScore': 0.0,
                'grade': 'E',
                'components': {key: round(value, 2) for key, value in components.items()},
                'summary': {
                    'totalTrades': 0,
                    'riskAdjustedReturn': 0.0,
                    'consistency': 0.0,
                    'noTrade': True,
                    'note': 'No trades were generated; this candidate is not eligible as a best parameter set.',
                },
                'weights': self.resolve_weights(regime),
            }

        regime_fit = 50.0
        if regime:
            regime_fit = self._estimate_regime_fit(regime, components)
            components['regimeFitScore'] = regime_fit

        weights = self.resolve_weights(regime)
        weighted = (
            components['returnScore'] * weights['return'] +
            components['annualReturnScore'] * weights['annual_return'] +
            components['sharpeScore'] * weights['sharpe'] +
            components['profitFactorScore'] * weights['profit_factor'] +
            components['winRateScore'] * weights['win_rate'] +
            components['drawdownScore'] * weights['drawdown'] +
            components['stabilityScore'] * weights['stability']
        )

        if total_trades < 3:
            weighted -= 24.0
        elif total_trades < 5:
            weighted -= 14.0
        elif total_trades < 12:
            weighted -= 5.0

        overall = max(0.0, min(100.0, weighted * 0.88 + regime_fit * 0.12))

        return {
            'overallScore': round(overall, 2),
            'grade': self._score_grade(overall),
            'components': {key: round(value, 2) for key, value in components.items()},
            'summary': {
                'totalTrades': total_trades,
                'riskAdjustedReturn': round((components['sharpeScore'] + components['drawdownScore']) / 2.0, 2),
                'consistency': round((components['stabilityScore'] + components['winRateScore']) / 2.0, 2),
            },
            'weights': weights,
        }

    def rank_results(self, items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ranked = list(items)

        def sort_key(item: Dict[str, Any]) -> tuple:
            score = float(((item.get('score') or {}).get('overallScore')) or 0.0)
            result = item.get('result') or {}
            trades = int(self._as_float(result.get('totalTrades')))
            total_return = self._as_float(result.get('totalReturn'))
            max_drawdown = abs(self._as_float(result.get('maxDrawdown')))
            has_overrides = 1 if (item.get('overrides') or {}) else 0
            non_baseline = 0 if str(item.get('source') or '').lower() == 'baseline' else 1
            return (
                score,
                min(trades, 1000),
                non_baseline,
                has_overrides,
                total_return,
                -max_drawdown,
            )

        ranked.sort(key=sort_key, reverse=True)
        for idx, item in enumerate(ranked, start=1):
            item['rank'] = idx
        return ranked

    def _estimate_regime_fit(self, regime: Dict[str, Any], components: Dict[str, float]) -> float:
        regime_key = str(regime.get('regime') or '')
        if regime_key in ('bull_trend', 'bear_trend'):
            return min(100.0, components['sharpeScore'] * 0.5 + components['returnScore'] * 0.5)
        if regime_key == 'range_compression':
            return min(100.0, components['winRateScore'] * 0.6 + components['stabilityScore'] * 0.4)
        if regime_key == 'high_volatility':
            return min(100.0, components['drawdownScore'] * 0.6 + components['profitFactorScore'] * 0.4)
        return min(100.0, components['stabilityScore'] * 0.5 + components['sharpeScore'] * 0.5)

    @staticmethod
    def _stability_score(equity_curve: List[Dict[str, Any]]) -> float:
        if len(equity_curve) < 3:
            return 45.0
        values = [float((point or {}).get('value') or 0.0) for point in equity_curve]
        positive_steps = 0
        total_steps = 0
        for prev, curr in zip(values, values[1:]):
            total_steps += 1
            if curr >= prev:
                positive_steps += 1
        monotonicity = positive_steps / max(total_steps, 1)
        return max(0.0, min(100.0, monotonicity * 100.0))

    @staticmethod
    def _bounded_score(value: float, *, floor: float, ceiling: float) -> float:
        if ceiling <= floor:
            return 50.0
        ratio = (value - floor) / (ceiling - floor)
        return max(0.0, min(100.0, ratio * 100.0))

    @staticmethod
    def _inverse_score(value: float, *, floor: float, ceiling: float) -> float:
        if ceiling <= floor:
            return 50.0
        ratio = (value - floor) / (ceiling - floor)
        return max(0.0, min(100.0, (1.0 - ratio) * 100.0))

    @staticmethod
    def _score_grade(score: float) -> str:
        if score >= 85:
            return 'A'
        if score >= 72:
            return 'B'
        if score >= 60:
            return 'C'
        if score >= 45:
            return 'D'
        return 'E'

    @staticmethod
    def _as_float(value: Any) -> float:
        try:
            return float(value or 0.0)
        except Exception:
            return 0.0
