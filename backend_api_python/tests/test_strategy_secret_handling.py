import pytest

from app.services.strategy import (
    redact_strategy_row,
    reject_inline_strategy_secrets,
    strip_strategy_secrets,
)


def test_reject_inline_strategy_secrets_without_credential_id():
    with pytest.raises(ValueError, match="INLINE_STRATEGY_SECRETS_NOT_ALLOWED"):
        reject_inline_strategy_secrets({"exchange_id": "binance", "secret_key": "s"})


def test_allow_strategy_credential_reference_and_strip_inline_keys():
    cfg = strip_strategy_secrets({
        "exchange_id": "binance",
        "credential_id": 12,
        "secret_key": "s",
        "nested": {"apiKey": "k"},
    })
    reject_inline_strategy_secrets(cfg)
    assert cfg == {"exchange_id": "binance", "credential_id": 12, "nested": {}}


def test_credentials_id_alias_allows_credential_reference():
    reject_inline_strategy_secrets({
        "exchange_id": "binance",
        "credentials_id": 12,
        "secret_key": "s",
    })


def test_redact_strategy_row_masks_nested_secrets():
    row = {
        "id": 1,
        "exchange_config": {"api_key": "k"},
        "trading_config": {"exchange_config": {"secretKey": "s"}},
        "notification_config": {"webhook-secret": "w"},
    }
    out = redact_strategy_row(row)
    assert out["exchange_config"]["api_key"] == "***"
    assert out["trading_config"]["exchange_config"]["secretKey"] == "***"
    assert out["notification_config"]["webhook-secret"] == "***"
