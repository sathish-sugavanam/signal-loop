"""Settings for the agent services.

The environment is read once, at boot, by `load_settings`. Nothing else in
the package touches `os.environ`; code receives the values it needs as
arguments.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    linear_webhook_secret: str
    port: int = 5001


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    errors: list[str] = []

    secret = env.get("LINEAR_WEBHOOK_SECRET", "").strip()
    if not secret:
        errors.append("LINEAR_WEBHOOK_SECRET is not set")

    port_raw = env.get("PORT", "5001")
    try:
        port = int(port_raw)
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        errors.append(f"PORT must be an integer between 1 and 65535, got {port_raw!r}")
        port = 0

    if errors:
        raise ConfigError("; ".join(errors))

    return Settings(linear_webhook_secret=secret, port=port)
