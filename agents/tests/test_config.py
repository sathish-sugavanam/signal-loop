import pytest

from signal_loop_agents.config import ConfigError, Settings, load_settings


def test_loads_all_settings():
    settings = load_settings({"LINEAR_WEBHOOK_SECRET": "s", "PORT": "9000"})
    assert settings == Settings(linear_webhook_secret="s", port=9000)


def test_port_defaults_to_5001():
    assert load_settings({"LINEAR_WEBHOOK_SECRET": "s"}).port == 5001


@pytest.mark.parametrize("secret", ["", "   "])
def test_missing_secret_fails(secret):
    with pytest.raises(ConfigError, match="LINEAR_WEBHOOK_SECRET"):
        load_settings({"LINEAR_WEBHOOK_SECRET": secret})


@pytest.mark.parametrize("port", ["abc", "0", "70000"])
def test_invalid_port_fails(port):
    with pytest.raises(ConfigError, match="PORT"):
        load_settings({"LINEAR_WEBHOOK_SECRET": "s", "PORT": port})


def test_reports_every_problem_at_once():
    with pytest.raises(ConfigError) as exc:
        load_settings({"PORT": "nope"})
    assert "LINEAR_WEBHOOK_SECRET" in str(exc.value)
    assert "PORT" in str(exc.value)
