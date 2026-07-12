"""Portfolio backtest orchestration across universes, data, engine, and history."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

import pandas as pd

from app.services.backtest_execution import parse_rate
from app.services.portfolio_backtest import PortfolioBacktestConfig, PortfolioBacktestEngine
from app.services.portfolio_strategy_runtime import rebalance_dates
from app.services.fundamental_data import get_fundamental_data_service
from app.services.unified_backtest import UnifiedBacktestService
from app.services.universe import UniverseError, UniverseService, get_universe_service


class PortfolioBacktestRequestError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class PortfolioBacktestService:
    """Run a reproducible portfolio backtest from a point-in-time universe."""

    def __init__(
        self,
        *,
        universe_service: Optional[UniverseService] = None,
        unified_service: Optional[UnifiedBacktestService] = None,
        frame_fetcher: Optional[Callable[..., pd.DataFrame]] = None,
    ):
        self.universe_service = universe_service or get_universe_service()
        self.unified_service = unified_service or UnifiedBacktestService()
        self.frame_fetcher = frame_fetcher or self.unified_service._fetch_kline_data

    def run(self, *, user_id: int, payload: dict) -> tuple[Optional[int], dict]:
        config = _request_config(payload)
        universe_id = _required_int(payload.get("universeId") or payload.get("universe_id"), "portfolio.universeRequired")
        code = str(payload.get("code") or payload.get("strategyCode") or payload.get("strategy_code") or "").strip()
        if not code:
            raise PortfolioBacktestRequestError("portfolio.strategyCodeRequired")
        params = payload.get("params") or payload.get("paramOverrides") or {}
        if not isinstance(params, dict):
            raise PortfolioBacktestRequestError("portfolio.invalidParameters")

        universe = self.universe_service.get_universe(user_id, universe_id)
        candidates = self.universe_service.candidate_members(
            user_id,
            universe_id,
            start=config["start"].date(),
            end=config["end"].date(),
        )
        if not candidates:
            raise PortfolioBacktestRequestError("portfolio.universeHasNoData")
        max_symbols = max(1, int(os.getenv("PORTFOLIO_BACKTEST_MAX_SYMBOLS", "600") or 600))
        if len(candidates) > max_symbols:
            raise PortfolioBacktestRequestError("portfolio.universeTooLarge")
        markets = {str(member.get("market") or "").strip() for member in candidates}
        if len(markets) > 1:
            raise PortfolioBacktestRequestError("portfolio.mixedMarketUniverseNotSupported")
        _reject_ambiguous_symbols(candidates)

        fetch_start = config["start"] - timedelta(days=max(30, config["startup_bars"] * 2))
        frames, skipped = self._fetch_panel(candidates, fetch_start, config["end"])
        if not frames:
            raise PortfolioBacktestRequestError("portfolio.noMarketData")
        frames = get_fundamental_data_service().enrich_panel(frames, candidates)

        calendar = _calendar(frames)
        live_calendar = pd.DatetimeIndex([item for item in calendar if item >= pd.Timestamp(config["start"])])
        schedule = rebalance_dates(live_calendar, config["frequency"])
        dated_universes: dict[pd.Timestamp, list[str]] = {}
        snapshots = []
        for session in schedule:
            members = self.universe_service.resolve_members(
                user_id,
                universe_id,
                as_of=session.date(),
            )
            dated_universes[session] = [member["symbol"] for member in members if member["symbol"] in frames]
            snapshot = self.universe_service.create_snapshot(
                user_id,
                universe_id,
                as_of=session.date(),
            )
            snapshots.append({
                "snapshot_id": snapshot["snapshot_id"],
                "as_of": snapshot["as_of"],
                "content_hash": snapshot["content_hash"],
                "member_count": snapshot["member_count"],
            })

        engine_config = PortfolioBacktestConfig(
            initial_capital=config["initial_capital"],
            commission_rate=config["commission"],
            slippage_rate=config["slippage"],
            rebalance_frequency=config["frequency"],
            max_weight=config["max_weight"],
            min_trade_value=config["min_trade_value"],
            allow_fractional=config["allow_fractional"],
            trading_start=config["start"],
        )
        result = PortfolioBacktestEngine(
            config=engine_config,
            code=code,
            params=params,
        ).run(frames, universe_by_date=dated_universes)
        result["diagnostics"].update({
            "symbolsRequested": len(candidates),
            "symbolsUsed": len(frames),
            "symbolsSkipped": skipped,
            "universeSnapshots": snapshots,
        })
        result["config"].update({
            "universeId": universe_id,
            "universeCode": universe.get("code") or "",
            "universeType": universe.get("universe_type") or "",
            "startDate": config["start"].date().isoformat(),
            "endDate": config["end"].date().isoformat(),
            "startupCandleCount": config["startup_bars"],
        })

        run_id = None
        if config["persist"]:
            strategy_id = _optional_int(payload.get("strategyId") or payload.get("strategy_id"))
            asset_id = _optional_int(payload.get("assetId") or payload.get("asset_id"))
            strategy_name = str(payload.get("strategyName") or payload.get("strategy_name") or "")
            run_id = self.unified_service.persist_run(
                user_id=int(user_id),
                market=str(universe.get("market") or "Mixed"),
                symbol=f"universe:{universe_id}",
                timeframe="1D",
                exchange_id="",
                market_type="spot",
                instrument_id="",
                start_date_str=config["start"].date().isoformat(),
                end_date_str=config["end"].date().isoformat(),
                initial_capital=config["initial_capital"],
                commission=config["commission"],
                slippage=config["slippage"],
                leverage=1,
                trade_direction="long",
                strategy_config={"params": params},
                config_snapshot={
                    "universe": universe,
                    "universeSnapshots": snapshots,
                    "portfolioConfig": result["config"],
                },
                status="success",
                result=result,
                strategy_id=strategy_id,
                strategy_name=strategy_name,
                run_type="portfolio_strategy",
                asset_type="portfolio_strategy",
                asset_id=asset_id,
                code=code,
            )
        return run_id, result

    def _fetch_panel(
        self,
        candidates: list[dict],
        start: datetime,
        end: datetime,
    ) -> tuple[dict[str, pd.DataFrame], list[dict]]:
        frames: dict[str, pd.DataFrame] = {}
        skipped: list[dict] = []

        def fetch(member: dict):
            frame = self.frame_fetcher(
                member["market"],
                member["symbol"],
                "1D",
                start,
                end,
                market_type=member.get("market_type") or "spot",
                exchange_id=member.get("exchange_id") or "",
            )
            return member, frame

        workers = min(8, max(1, len(candidates)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="portfolio-data") as executor:
            futures = [executor.submit(fetch, member) for member in candidates]
            for future in as_completed(futures):
                try:
                    member, frame = future.result()
                    if frame is None or frame.empty:
                        skipped.append({"symbol": member["symbol"], "reason": "portfolio.noMarketData"})
                        continue
                    frames[member["symbol"]] = _normalize_daily_frame(frame)
                except Exception as exc:
                    skipped.append({"symbol": "", "reason": "portfolio.dataFetchFailed", "detail": str(exc)[:300]})
        return dict(sorted(frames.items())), sorted(skipped, key=lambda item: item.get("symbol") or "")


def _normalize_daily_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    index = pd.DatetimeIndex(pd.to_datetime(normalized.index))
    if index.tz is not None:
        index = index.tz_convert("UTC").tz_localize(None)
    normalized.index = index.normalize()
    return normalized[~normalized.index.duplicated(keep="last")].sort_index()


def _request_config(payload: dict) -> dict:
    try:
        start = datetime.strptime(str(payload.get("startDate") or payload.get("start_date")), "%Y-%m-%d")
        end = datetime.strptime(str(payload.get("endDate") or payload.get("end_date")), "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise PortfolioBacktestRequestError("portfolio.invalidDateRange") from exc
    if end <= start:
        raise PortfolioBacktestRequestError("portfolio.invalidDateRange")
    frequency = str(payload.get("rebalanceFrequency") or payload.get("rebalance_frequency") or "weekly").strip().lower()
    rebalance_dates([], frequency)
    initial_capital = _positive(payload.get("initialCapital") or payload.get("initial_capital") or 100000, "portfolio.invalidInitialCapital")
    commission = parse_rate(
        payload.get("commission"),
        pct_value=payload.get("commissionPct"),
        default=0.0005,
    )
    slippage = parse_rate(
        payload.get("slippage"),
        pct_value=payload.get("slippagePct"),
        default=0.0005,
    )
    max_weight = _positive(payload.get("maxWeight") or payload.get("max_weight") or 0.1, "portfolio.invalidMaxWeight")
    if max_weight > 1:
        raise PortfolioBacktestRequestError("portfolio.invalidMaxWeight")
    startup_bars = max(0, min(1000, int(payload.get("startupCandleCount") or payload.get("startup_candle_count") or 120)))
    return {
        "start": start,
        "end": end,
        "frequency": frequency,
        "initial_capital": initial_capital,
        "commission": commission,
        "slippage": slippage,
        "max_weight": max_weight,
        "min_trade_value": max(0.0, float(payload.get("minTradeValue") or payload.get("min_trade_value") or 0)),
        "allow_fractional": _bool(payload.get("allowFractional"), default=True),
        "startup_bars": startup_bars,
        "persist": _bool(payload.get("persist"), default=True),
    }


def _calendar(frames: dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex([])
    for frame in frames.values():
        index = index.union(pd.DatetimeIndex(frame.index))
    return index.sort_values().unique()


def _reject_ambiguous_symbols(members: list[dict]) -> None:
    identities = {}
    for member in members:
        symbol = member["symbol"]
        identity = (
            member["market"], member.get("exchange_id") or "",
            member.get("market_type") or "", member.get("instrument_id") or "",
        )
        previous = identities.get(symbol)
        if previous is not None and previous != identity:
            raise PortfolioBacktestRequestError("portfolio.ambiguousSymbolIdentity")
        identities[symbol] = identity


def _required_int(value: Any, code: str) -> int:
    parsed = _optional_int(value)
    if parsed is None or parsed <= 0:
        raise PortfolioBacktestRequestError(code)
    return parsed


def _optional_int(value: Any) -> Optional[int]:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _positive(value: Any, code: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise PortfolioBacktestRequestError(code) from exc
    if not pd.notna(parsed) or parsed <= 0:
        raise PortfolioBacktestRequestError(code)
    return parsed


def _bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
