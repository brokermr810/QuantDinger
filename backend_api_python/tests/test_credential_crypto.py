from app.utils.credential_crypto import decrypt_credential_blob, encrypt_credential_blob


def test_dedicated_credential_key_survives_secret_key_rotation(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "credential-key-a")
    monkeypatch.setenv("SECRET_KEY", "session-key-a")
    encrypted = encrypt_credential_blob('{"exchange_id":"alpaca"}')

    monkeypatch.setenv("SECRET_KEY", "session-key-b")

    assert decrypt_credential_blob(encrypted) == '{"exchange_id":"alpaca"}'


def test_legacy_secret_key_ciphertext_remains_readable(monkeypatch):
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("SECRET_KEY", "legacy-session-key")
    encrypted = encrypt_credential_blob("legacy-secret")

    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "new-credential-key")

    assert decrypt_credential_blob(encrypted) == "legacy-secret"
