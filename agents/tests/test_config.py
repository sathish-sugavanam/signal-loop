from signal_loop_agents.config import load_webhook_settings, load_worker_settings


def test_worker_settings_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://agents:pw@db/agents")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    settings = load_worker_settings()
    assert (settings.poll_interval_seconds, settings.lease_seconds) == (2.0, 3600.0)
    assert "pw" not in repr(settings)


def test_webhook_settings_defaults(monkeypatch):
    monkeypatch.setenv("LINEAR_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://agents:pw@db/agents")
    settings = load_webhook_settings()
    assert settings.port == 5001
    assert "s3cret" not in repr(settings)
