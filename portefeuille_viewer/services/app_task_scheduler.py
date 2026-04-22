from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, QTimer

from portefeuille_viewer.data.update_run_repository import (
    finish_update_run,
    has_successful_run_today,
    start_update_run,
)
from portefeuille_viewer.services.dividend_calendar_service import DividendCalendarService


@dataclass(frozen=True)
class ScheduledTask:
    task_name: str
    run_reason: str
    startup_delay_ms: int
    check_interval_ms: int
    runner: Callable[[], object]


class AppTaskScheduler(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tasks: list[ScheduledTask] = []
        self._timers: dict[str, QTimer] = {}
        self._running: set[str] = set()
        self._started = False

    def register_default_tasks(self) -> None:
        self.register_task(
            ScheduledTask(
                task_name="dividend_calendar_refresh",
                run_reason="scheduled_daily_dividend_calendar_refresh",
                startup_delay_ms=5 * 60 * 1000,
                check_interval_ms=60 * 60 * 1000,
                runner=lambda: DividendCalendarService().refresh(),
            )
        )

    def register_task(self, task: ScheduledTask) -> None:
        if any(existing.task_name == task.task_name for existing in self._tasks):
            return
        self._tasks.append(task)

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        for task in self._tasks:
            startup_timer = QTimer(self)
            startup_timer.setSingleShot(True)
            startup_timer.setInterval(max(0, int(task.startup_delay_ms)))
            startup_timer.timeout.connect(lambda task=task: self._maybe_start_task(task))
            startup_timer.start()
            self._timers[f"{task.task_name}:startup"] = startup_timer

            interval_timer = QTimer(self)
            interval_timer.setSingleShot(False)
            interval_timer.setInterval(max(60_000, int(task.check_interval_ms)))
            interval_timer.timeout.connect(lambda task=task: self._maybe_start_task(task))
            interval_timer.start()
            self._timers[f"{task.task_name}:interval"] = interval_timer

    def _maybe_start_task(self, task: ScheduledTask) -> None:
        if task.task_name in self._running:
            return
        try:
            if has_successful_run_today(task.task_name):
                print(f"[app-task-scheduler] skip {task.task_name}: already ok today")
                return
        except Exception as exc:
            print(f"[app-task-scheduler] runlog check failed for {task.task_name}: {exc}")
            return

        self._running.add(task.task_name)
        run_id = start_update_run(
            task_name=task.task_name,
            run_reason=task.run_reason,
            source="app_task_scheduler",
        )
        thread = threading.Thread(
            target=self._run_task_thread,
            args=(task, run_id),
            daemon=True,
            name=f"app-task-{task.task_name}",
        )
        thread.start()

    def _run_task_thread(self, task: ScheduledTask, run_id: int | None) -> None:
        try:
            print(f"[app-task-scheduler] start {task.task_name}")
            result = task.runner()
            if task.task_name == "dividend_calendar_refresh":
                from portefeuille_viewer.data import repository

                repository.load_asset_dividend_calendar_snapshot()
            rows_processed = getattr(result, "rows_processed", None)
            rows_ok = getattr(result, "rows_ok", None)
            rows_error = getattr(result, "rows_error", None)
            message = str(getattr(result, "message", "ok") or "ok")
            finish_update_run(
                run_id,
                status="ok",
                message=message,
                rows_processed=rows_processed,
                rows_ok=rows_ok,
                rows_error=rows_error,
                payload={
                    "task_name": task.task_name,
                    "run_reason": task.run_reason,
                    "rows_processed": rows_processed,
                    "rows_ok": rows_ok,
                    "rows_error": rows_error,
                },
            )
            print(f"[app-task-scheduler] finish {task.task_name}: {message}")
        except Exception as exc:
            message = f"{exc}\n{traceback.format_exc()}"
            finish_update_run(
                run_id,
                status="failed",
                message=message,
                payload={"task_name": task.task_name, "run_reason": task.run_reason},
            )
            print(f"[app-task-scheduler] failed {task.task_name}: {exc}")
        finally:
            self._running.discard(task.task_name)
