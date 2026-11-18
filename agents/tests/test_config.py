import pytest

from signal_loop_agents.config import load_webhook_settings, load_worker_settings


def test_worker_settings_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://agents:pw@db/agents")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp-secret")
    monkeypatch.setenv("GITHUB_REPO", "o/r")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    settings = load_worker_settings()
    assert settings.agent_env == {"ANTHROPIC_API_KEY": "sk-secret"}
    assert "ghp-secret" not in repr(settings) and "sk-secret" not in repr(settings)
    assert (settings.poll_interval_seconds, settings.lease_seconds) == (2.0, 3600.0)
    assert "pw" not in repr(settings)


def test_webhook_settings_defaults(monkeypatch):
    monkeypatch.setenv("LINEAR_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://agents:pw@db/agents")
    settings = load_webhook_settings()
    assert settings.port == 5001
    assert "s3cret" not in repr(settings)


def test_worker_needs_an_agent_credential(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        load_worker_settings()


def test_openrouter_settings_reach_the_run_container(monkeypatch):
    for name, value in {
        "DATABASE_URL": "postgresql://a:pw@db/agents",
        "REDIS_URL": "redis://redis:6379/0",
        "GITHUB_TOKEN": "ghp-secret",
        "GITHUB_REPO": "o/r",
        "ANTHROPIC_BASE_URL": "https://openrouter.ai/api",
        "ANTHROPIC_AUTH_TOKEN": "or-secret",
        "DEV_AGENT_MODEL": "nvidia/nemotron-3.5-lightning:free",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-be-blanked")
    assert load_worker_settings().agent_env == {
        "ANTHROPIC_AUTH_TOKEN": "or-secret",
        "ANTHROPIC_BASE_URL": "https://openrouter.ai/api",
        "DEV_AGENT_MODEL": "nvidia/nemotron-3.5-lightning:free",
        "ANTHROPIC_API_KEY": "",
    }
