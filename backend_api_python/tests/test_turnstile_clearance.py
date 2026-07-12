from app.services.security_service import SecurityService


def test_turnstile_clearance_accepts_same_ip(monkeypatch):
    monkeypatch.setenv("TURNSTILE_SITE_KEY", "site-key")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "secret-key")
    monkeypatch.setenv("TURNSTILE_CLEARANCE_TTL_SECONDS", "600")
    service = SecurityService()

    clearance = service.issue_turnstile_clearance("203.0.113.10")

    assert service.verify_turnstile_clearance(clearance, "203.0.113.10") == (True, "verified")
    assert service.verify_turnstile_or_clearance(clearance=clearance, ip_address="203.0.113.10") == (True, "verified")


def test_turnstile_clearance_rejects_different_ip(monkeypatch):
    monkeypatch.setenv("TURNSTILE_SITE_KEY", "site-key")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "secret-key")
    service = SecurityService()

    clearance = service.issue_turnstile_clearance("203.0.113.10")

    ok, msg = service.verify_turnstile_clearance(clearance, "203.0.113.11")
    assert ok is False
    assert msg == "turnstile_clearance_invalid"
