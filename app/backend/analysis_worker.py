"""Single-process background runner for durable analysis jobs."""
from __future__ import annotations

import logging
import math
import threading
import uuid
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from .services.analysis import (
    AnalysisEngine,
    claim_next_analysis_job,
    process_analysis_job,
    recover_expired_jobs,
)


logger = logging.getLogger("duck_diary.analysis_worker")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AnalysisWorker:
    """A stoppable daemon which owns one UUID lease identity for its lifetime."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        analyzer: AnalysisEngine,
        clock: Callable[[], datetime] = _utc_now,
        lease_seconds: int = 45,
        poll_interval_seconds: float = 0.25,
        heartbeat_interval_seconds: float | None = None,
    ) -> None:
        effective_heartbeat_interval = (
            lease_seconds / 3
            if heartbeat_interval_seconds is None
            else heartbeat_interval_seconds
        )
        if (
            not math.isfinite(lease_seconds)
            or not math.isfinite(effective_heartbeat_interval)
            or lease_seconds <= 0
            or effective_heartbeat_interval <= 0
            or effective_heartbeat_interval > lease_seconds / 3
        ):
            raise ValueError(
                "analysis heartbeat interval must be finite, positive, and no more than lease/3"
            )
        self._session_factory = session_factory
        self._analyzer = analyzer
        self._clock = clock
        self._lease_seconds = lease_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self.worker_id = str(uuid.uuid4())
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state = "stopped"
        self._active_job_id: int | None = None

    def _set_state(self, state: str, *, active_job_id: int | None = None) -> None:
        with self._lock:
            self._state = state
            self._active_job_id = active_job_id

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("analysis worker is already running")
            self._stop_event.clear()
            self._state = "starting"
            self._active_job_id = None
            self._thread = threading.Thread(
                target=self._run,
                name="analysis-worker",
                daemon=True,
            )
            self._thread.start()

    def _run(self) -> None:
        try:
            db = self._session_factory()
            try:
                recover_expired_jobs(db, now=self._clock())
            finally:
                db.close()
            self._set_state("idle")
            while not self._stop_event.is_set():
                worked = self.run_once()
                if not worked:
                    self._stop_event.wait(self._poll_interval_seconds)
        except Exception as exc:  # Startup recovery and direct job failures share health state.
            logger.exception("analysis worker failed error_type=%s", type(exc).__name__)
            self._set_state("failed")
        finally:
            if self.status() != "failed":
                self._set_state("stopped")

    def run_once(self) -> bool:
        try:
            db = self._session_factory()
            try:
                now = self._clock()
                recover_expired_jobs(db, now=now)
                job_id = claim_next_analysis_job(
                    db,
                    worker_id=self.worker_id,
                    now=now,
                    lease_seconds=self._lease_seconds,
                )
            finally:
                db.close()
            if job_id is None:
                if not self._stop_event.is_set():
                    self._set_state("idle")
                return False
            self._set_state("processing", active_job_id=job_id)
            process_analysis_job(
                self._session_factory,
                job_id=job_id,
                worker_id=self.worker_id,
                analyzer=self._analyzer,
                clock=self._clock,
                lease_seconds=self._lease_seconds,
                heartbeat_interval_seconds=self._heartbeat_interval_seconds,
            )
            if not self._stop_event.is_set():
                self._set_state("idle")
            return True
        except Exception:
            self._set_state("failed")
            raise

    def stop(self, timeout_seconds: float = 5.0) -> None:
        self._stop_event.set()
        with self._lock:
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout_seconds)
        if (thread is None or not thread.is_alive()) and self.status() != "failed":
            self._set_state("stopped")

    def status(self) -> str:
        with self._lock:
            return self._state
