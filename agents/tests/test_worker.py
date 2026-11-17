from signal_loop_agents.config import WorkerSettings
from signal_loop_agents.worker import STALE_CHECK_INTERVAL_SECONDS, create_app

SETTINGS = WorkerSettings(
    database_url="postgresql://unused",
    broker_url="memory://",
    poll_interval_seconds=2.0,
    lease_seconds=3600.0,
)


def test_app_registers_both_tasks():
    app = create_app(SETTINGS)
    assert {"signal_loop_agents.check_pending_tasks", "signal_loop_agents.fail_stale_tasks"} <= set(
        app.tasks
    )


def test_beat_polls_inbox_and_ticks_expire_at_the_interval():
    schedule = create_app(SETTINGS).conf.beat_schedule
    assert schedule["check-pending-tasks"]["task"] == "signal_loop_agents.check_pending_tasks"
    assert schedule["check-pending-tasks"]["schedule"] == 2.0
    assert schedule["check-pending-tasks"]["options"] == {"expires": 2.0}
    assert schedule["fail-stale-tasks"]["schedule"] == STALE_CHECK_INTERVAL_SECONDS


def test_results_are_not_stored():
    app = create_app(SETTINGS)
    assert app.conf.task_ignore_result is True
    assert app.conf.worker_prefetch_multiplier == 1
