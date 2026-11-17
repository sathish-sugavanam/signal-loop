"""Celery entry point: reads the environment once and builds the app.

    celery -A signal_loop_agents.celery_app worker --concurrency=1
    celery -A signal_loop_agents.celery_app beat
"""

from signal_loop_agents.config import load_worker_settings
from signal_loop_agents.worker import create_app

app = create_app(load_worker_settings())
