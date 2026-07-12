from datetime import datetime, timezone

from app.services.market_schedule import latest_completed_session, next_rebalance_run


def test_us_daily_schedule_skips_independence_day_observed_holiday():
    result = next_rebalance_run(
        "USStock",
        "daily",
        datetime(2025, 7, 3, 21, 0, tzinfo=timezone.utc),
        data_delay_minutes=15,
    )

    assert result == datetime(2025, 7, 7, 20, 15)


def test_us_weekly_schedule_uses_last_session_when_friday_is_closed():
    result = next_rebalance_run(
        "USStock",
        "weekly",
        datetime(2025, 6, 30, 0, 0, tzinfo=timezone.utc),
        data_delay_minutes=15,
    )

    assert result == datetime(2025, 7, 3, 17, 15)


def test_latest_completed_session_waits_for_data_delay():
    before_delay = latest_completed_session(
        "USStock",
        datetime(2025, 7, 7, 20, 10, tzinfo=timezone.utc),
        data_delay_minutes=15,
    )
    after_delay = latest_completed_session(
        "USStock",
        datetime(2025, 7, 7, 20, 16, tzinfo=timezone.utc),
        data_delay_minutes=15,
    )

    assert before_delay.date().isoformat() == "2025-07-03"
    assert after_delay.date().isoformat() == "2025-07-07"


def test_crypto_daily_schedule_uses_utc_data_boundary():
    result = next_rebalance_run(
        "Crypto",
        "daily",
        datetime(2025, 7, 7, 20, 10, tzinfo=timezone.utc),
        data_delay_minutes=15,
    )

    assert result == datetime(2025, 7, 8, 0, 15)
