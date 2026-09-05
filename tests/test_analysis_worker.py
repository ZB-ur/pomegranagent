"""Durable analysis job leasing, projection, recovery, and retry contracts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Barrier, Event, Thread
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.backend import models, schemas
from app.backend.analysis_worker import AnalysisWorker
from app.backend.api_errors import APIError
from app.backend.database import SessionLocal
from app.backend.main import app
from app.backend.services import analysis


NOW = datetime(2026, 8, 23, 9, 0, tzinfo=timezone.utc)


def _ended_conversation_with_job(
    db_session,
    *,
    available_at=NOW,
    messages: list[tuple[str, str]] | None = None,
):
    child = models.Child(name="小雨", nickname="雨雨", active=True)
    db_session.add(child)
    db_session.flush()
    conversation = models.Conversation(
        child_id=child.id,
        date="2026-08-23",
        status="ended",
        ended_at=NOW,
        frozen_last_message_id=None,
    )
    db_session.add(conversation)
    db_session.flush()
    message_rows = []
    for role, text in messages or [("child", "我给小黄添了菜叶")]:
        message = models.Message(
            conversation_id=conversation.id,
            role=role,
            text=text,
        )
        db_session.add(message)
        db_session.flush()
        message_rows.append(message)
    conversation.frozen_last_message_id = message_rows[-1].id
    job = models.AnalysisJob(
        conversation_id=conversation.id,
        frozen_last_message_id=message_rows[-1].id,
        status="pending",
        available_at=available_at,
        created_at=NOW,
        updated_at=NOW,
    )
    db_session.add(job)
    db_session.commit()
    return conversation, job


class FakeAnalysisEngine:
    """In-process provider double: no network or application database access."""

    def __init__(self, *, extraction, assessment, on_call=None):
        self.extraction = extraction
        self.assessment = assessment
        self.on_call = on_call
        self.extract_calls: list[str] = []
        self.assessment_calls: list[tuple[str, list[dict]]] = []

    def extract_info(self, transcript: str) -> dict:
        self.extract_calls.append(transcript)
        if self.on_call is not None:
            self.on_call("extract")
        if isinstance(self.extraction, Exception):
            raise self.extraction
        return self.extraction

    def assess_conversation(self, transcript: str, dimensions: list[dict]) -> dict:
        self.assessment_calls.append((transcript, dimensions))
        if self.on_call is not None:
            self.on_call("assess")
        if isinstance(self.assessment, Exception):
            raise self.assessment
        return self.assessment


class TrackingSessionFactory:
    """Proves provider calls happen only after the read session is closed."""

    def __init__(self):
        self.open_sessions = 0

    def __call__(self):
        session = SessionLocal()
        original_close = session.close
        closed = False
        self.open_sessions += 1

        def close():
            nonlocal closed
            if not closed:
                closed = True
                self.open_sessions -= 1
            original_close()

        session.close = close
        return session


def _analysis_output():
    return {
        "feeding_logs": [
            {"category": "喂食", "content": " 给小黄添了菜叶 ", "duck_name": "小黄"},
            {"category": "观察", "content": "小黄吃完了", "duck_name": None},
        ],
        "emotion": {"emotion": "开心", "intensity": 4, "note": "愿意继续分享"},
        "insight": "会主动观察小鸭的食量。",
    }


def _assessment_output():
    return {
        "scores": [
            {"dimension_key": "language", "score": 4, "reason": "说清了菜叶。"},
            {"dimension_key": "empathy", "score": 5, "reason": "关心小黄。"},
            {"dimension_key": "diligence", "score": 3, "reason": "主动添菜叶。"},
        ],
        "overall": 99,
    }


def _wait_for_lease_extension(job_id: int, *, beyond: datetime) -> datetime:
    """Wait for a real heartbeat commit instead of sleeping for a guessed duration."""
    deadline = monotonic() + 1
    while monotonic() < deadline:
        session = SessionLocal()
        try:
            lease_expires_at = session.scalar(
                select(models.AnalysisJob.lease_expires_at).where(
                    models.AnalysisJob.id == job_id
                )
            )
        finally:
            session.close()
        if lease_expires_at is not None and lease_expires_at > beyond.replace(tzinfo=None):
            return lease_expires_at
        sleep(0.005)
    pytest.fail("analysis lease heartbeat did not extend the durable lease")


def _projection_counts(db_session, conversation_id: int) -> dict[str, int]:
    assessment_ids = select(models.Assessment.id).where(
        models.Assessment.conversation_id == conversation_id
    )
    return {
        "feeding": db_session.scalar(
            select(func.count(models.FeedingLog.id)).where(
                models.FeedingLog.conversation_id == conversation_id
            )
        ),
        "emotion": db_session.scalar(
            select(func.count(models.EmotionLog.id)).where(
                models.EmotionLog.conversation_id == conversation_id
            )
        ),
        "insight": db_session.scalar(
            select(func.count(models.InsightNote.id)).where(
                models.InsightNote.conversation_id == conversation_id
            )
        ),
        "assessment": db_session.scalar(
            select(func.count(models.Assessment.id)).where(
                models.Assessment.conversation_id == conversation_id
            )
        ),
        "scores": db_session.scalar(
            select(func.count(models.AssessmentScore.id)).where(
                models.AssessmentScore.assessment_id.in_(assessment_ids)
            )
        ),
    }


def _seed_existing_projection(db_session, conversation: models.Conversation) -> dict:
    dimensions = db_session.scalars(
        select(models.AssessmentDimension).order_by(models.AssessmentDimension.id)
    ).all()
    db_session.add_all([
        models.FeedingLog(
            conversation_id=conversation.id,
            child_id=conversation.child_id,
            category="清洁",
            content="已有的清洁记录",
        ),
        models.EmotionLog(
            conversation_id=conversation.id,
            child_id=conversation.child_id,
            emotion="平静",
            intensity=2,
            note="已有的情绪记录",
        ),
        models.InsightNote(
            conversation_id=conversation.id,
            child_id=conversation.child_id,
            content="已有的心得记录",
        ),
    ])
    assessment = models.Assessment(
        conversation_id=conversation.id,
        child_id=conversation.child_id,
        status="pending",
        overall=2.0,
    )
    db_session.add(assessment)
    db_session.flush()
    db_session.add_all([
        models.AssessmentScore(
            assessment_id=assessment.id,
            dimension_id=dimension.id,
            score=2,
            reason=f"已有的{dimension.key}评分",
        )
        for dimension in dimensions
    ])
    conversation.revision = 7
    db_session.commit()
    return _projection_snapshot(db_session, conversation.id)


def _projection_snapshot(db_session, conversation_id: int) -> dict:
    assessment = db_session.scalar(
        select(models.Assessment).where(models.Assessment.conversation_id == conversation_id)
    )
    assert assessment is not None
    conversation = db_session.get(models.Conversation, conversation_id)
    assert conversation is not None
    return {
        "revision": conversation.revision,
        "feeding": [
            (row.id, row.category, row.content, row.duck_id)
            for row in db_session.scalars(
                select(models.FeedingLog)
                .where(models.FeedingLog.conversation_id == conversation_id)
                .order_by(models.FeedingLog.id)
            )
        ],
        "emotion": [
            (row.id, row.emotion, row.intensity, row.note)
            for row in db_session.scalars(
                select(models.EmotionLog)
                .where(models.EmotionLog.conversation_id == conversation_id)
                .order_by(models.EmotionLog.id)
            )
        ],
        "insight": [
            (row.id, row.content)
            for row in db_session.scalars(
                select(models.InsightNote)
                .where(models.InsightNote.conversation_id == conversation_id)
                .order_by(models.InsightNote.id)
            )
        ],
        "assessment": (assessment.id, assessment.status, assessment.overall),
        "scores": [
            (row.id, row.dimension_id, row.score, row.reason)
            for row in db_session.scalars(
                select(models.AssessmentScore)
                .where(models.AssessmentScore.assessment_id == assessment.id)
                .order_by(models.AssessmentScore.id)
            )
        ],
    }


def test_claims_due_jobs_oldest_first_with_one_attempt_and_a_lease(db_session):
    """Catches choosing a newer job or claiming a job without durable ownership."""
    _, first = _ended_conversation_with_job(
        db_session,
        available_at=NOW - timedelta(seconds=2),
    )
    _, second = _ended_conversation_with_job(
        db_session,
        available_at=NOW - timedelta(seconds=1),
    )

    claimed = analysis.claim_next_analysis_job(
        db_session,
        worker_id="worker-a",
        now=NOW,
        lease_seconds=30,
    )

    assert claimed == first.id
    db_session.expire_all()
    first_saved = db_session.get(models.AnalysisJob, first.id)
    second_saved = db_session.get(models.AnalysisJob, second.id)
    assert first_saved is not None
    assert first_saved.status == "processing"
    assert first_saved.attempt_count == 1
    assert first_saved.lease_owner == "worker-a"
    assert first_saved.lease_expires_at == (NOW + timedelta(seconds=30)).replace(tzinfo=None)
    assert second_saved is not None
    assert second_saved.status == "pending"


def test_restart_recovers_only_expired_processing_jobs_and_preserves_attempts(db_session):
    """Catches startup recovery stealing a live lease or resetting retry history."""
    _, expired = _ended_conversation_with_job(db_session)
    _, live = _ended_conversation_with_job(db_session)
    expired.status = "processing"
    expired.attempt_count = 2
    expired.lease_owner = "former-worker"
    expired.lease_expires_at = NOW - timedelta(seconds=1)
    live.status = "processing"
    live.attempt_count = 1
    live.lease_owner = "live-worker"
    live.lease_expires_at = NOW + timedelta(seconds=30)
    db_session.commit()

    recovered = analysis.recover_expired_jobs(db_session, now=NOW)

    assert recovered == 1
    db_session.expire_all()
    expired_saved = db_session.get(models.AnalysisJob, expired.id)
    live_saved = db_session.get(models.AnalysisJob, live.id)
    assert expired_saved is not None
    assert expired_saved.status == "pending"
    assert expired_saved.attempt_count == 2
    assert expired_saved.lease_owner is None
    assert expired_saved.lease_expires_at is None
    assert expired_saved.available_at == NOW.replace(tzinfo=None)
    assert live_saved is not None
    assert live_saved.status == "processing"
    assert live_saved.lease_owner == "live-worker"


def test_lease_renewal_requires_the_exact_owner_and_attempt_fence(db_session):
    """Catches an old attempt extending a newer attempt that reused the same worker id."""
    _conversation, job = _ended_conversation_with_job(db_session)
    assert analysis.claim_next_analysis_job(
        db_session,
        worker_id="worker-a",
        now=NOW,
        lease_seconds=6,
    ) == job.id
    job_id = job.id
    db_session.rollback()

    assert analysis.renew_analysis_job_lease(
        SessionLocal,
        job_id=job_id,
        worker_id="worker-b",
        attempt_count=1,
        now=NOW + timedelta(seconds=2),
        lease_seconds=6,
    ) is False
    assert analysis.renew_analysis_job_lease(
        SessionLocal,
        job_id=job_id,
        worker_id="worker-a",
        attempt_count=2,
        now=NOW + timedelta(seconds=2),
        lease_seconds=6,
    ) is False
    assert analysis.renew_analysis_job_lease(
        SessionLocal,
        job_id=job_id,
        worker_id="worker-a",
        attempt_count=1,
        now=NOW + timedelta(seconds=2),
        lease_seconds=6,
    ) is True

    db_session.expire_all()
    saved = db_session.get(models.AnalysisJob, job_id)
    assert saved is not None
    assert saved.lease_expires_at == (NOW + timedelta(seconds=8)).replace(tzinfo=None)


def test_heartbeat_retries_after_one_transient_lease_write_failure(
    db_session,
    monkeypatch,
):
    """Catches one short SQLite write conflict disabling renewal for the whole attempt."""
    _conversation, job = _ended_conversation_with_job(db_session)
    job_id = job.id
    db_session.rollback()
    first_renewal_failed = Event()
    later_renewal_succeeded = Event()
    failures: list[BaseException] = []
    renewal_calls = 0
    original_renew = analysis.renew_analysis_job_lease

    def fail_once_then_renew(*args, **kwargs):
        nonlocal renewal_calls
        renewal_calls += 1
        if renewal_calls == 1:
            first_renewal_failed.set()
            raise RuntimeError("transient sqlite writer conflict")
        renewed = original_renew(*args, **kwargs)
        if renewed:
            later_renewal_succeeded.set()
        return renewed

    monkeypatch.setattr(analysis, "renew_analysis_job_lease", fail_once_then_renew)

    def wait_for_retry(method: str) -> None:
        if method == "extract":
            assert later_renewal_succeeded.wait(1)

    worker = AnalysisWorker(
        session_factory=SessionLocal,
        analyzer=FakeAnalysisEngine(
            extraction=_analysis_output(),
            assessment=_assessment_output(),
            on_call=wait_for_retry,
        ),
        clock=lambda: NOW,
        lease_seconds=6,
        heartbeat_interval_seconds=0.01,
    )

    def run_worker_once() -> None:
        try:
            worker.run_once()
        except BaseException as exc:  # Preserve the worker-thread failure for the assertion.
            failures.append(exc)

    thread = Thread(target=run_worker_once)
    thread.start()
    thread.join(2)

    assert first_renewal_failed.is_set()
    assert later_renewal_succeeded.is_set()
    assert renewal_calls >= 2
    assert not thread.is_alive()
    assert failures == []
    db_session.expire_all()
    saved = db_session.get(models.AnalysisJob, job_id)
    assert saved is not None
    assert saved.status == "succeeded"


def test_heartbeat_lease_loss_during_extraction_skips_the_second_provider_call(
    db_session,
    monkeypatch,
):
    """Catches a fenced-out attempt continuing to spend a second remote request."""
    _conversation, job = _ended_conversation_with_job(db_session)
    assert analysis.claim_next_analysis_job(
        db_session,
        worker_id="worker-a",
        now=NOW,
        lease_seconds=6,
    ) == job.id
    job_id = job.id
    db_session.rollback()
    renewal_rejected = Event()

    def reject_renewal(*_args, **_kwargs):
        renewal_rejected.set()
        return False

    monkeypatch.setattr(analysis, "renew_analysis_job_lease", reject_renewal)

    def wait_until_fenced(method: str) -> None:
        if method == "extract":
            assert renewal_rejected.wait(1)

    analyzer = FakeAnalysisEngine(
        extraction=_analysis_output(),
        assessment=_assessment_output(),
        on_call=wait_until_fenced,
    )

    result = analysis.process_analysis_job(
        SessionLocal,
        job_id=job_id,
        worker_id="worker-a",
        analyzer=analyzer,
        clock=lambda: NOW,
        lease_seconds=6,
        heartbeat_interval_seconds=0.01,
    )

    assert result == "lease_lost"
    assert analyzer.extract_calls
    assert analyzer.assessment_calls == []


def test_claim_compare_and_set_loser_does_not_increment_the_live_attempt(db_session):
    """Catches a second claimant overwriting the first durable lease."""
    _, job = _ended_conversation_with_job(db_session)

    assert analysis.claim_next_analysis_job(
        db_session,
        worker_id="worker-a",
        now=NOW,
        lease_seconds=30,
    ) == job.id
    assert analysis.claim_next_analysis_job(
        db_session,
        worker_id="worker-b",
        now=NOW,
        lease_seconds=30,
    ) is None

    db_session.expire_all()
    saved = db_session.get(models.AnalysisJob, job.id)
    assert saved is not None
    assert saved.attempt_count == 1
    assert saved.lease_owner == "worker-a"


def test_two_sessions_observing_one_pending_job_have_one_cas_claim_winner(db_session):
    """Catches a real concurrent claim race incrementing attempts or granting two owners."""
    _conversation, job = _ended_conversation_with_job(db_session)
    both_observed = Barrier(2)
    results: dict[str, int | None] = {}
    failures: list[BaseException] = []

    def claim_in_own_session(worker_id: str) -> None:
        session = SessionLocal()
        original_scalar = session.scalar
        waited = False

        def scalar(statement, *args, **kwargs):
            nonlocal waited
            result = original_scalar(statement, *args, **kwargs)
            if not waited and "analysis_jobs" in str(statement):
                waited = True
                both_observed.wait(timeout=2)
            return result

        session.scalar = scalar
        try:
            results[worker_id] = analysis.claim_next_analysis_job(
                session,
                worker_id=worker_id,
                now=NOW,
                lease_seconds=30,
            )
        except BaseException as exc:  # Keep both thread outcomes visible to the assertion.
            failures.append(exc)
        finally:
            session.close()

    first = Thread(target=claim_in_own_session, args=("worker-a",))
    second = Thread(target=claim_in_own_session, args=("worker-b",))
    first.start()
    second.start()
    first.join(3)
    second.join(3)

    assert not first.is_alive()
    assert not second.is_alive()
    assert failures == []
    winners = [worker_id for worker_id, result in results.items() if result == job.id]
    assert len(winners) == 1
    assert list(results.values()).count(None) == 1
    db_session.expire_all()
    saved = db_session.get(models.AnalysisJob, job.id)
    assert saved is not None
    assert saved.attempt_count == 1
    assert saved.lease_owner == winners[0]


def test_process_builds_the_frozen_input_outside_a_database_session_and_projects_once(
    db_session,
):
    """Catches provider work inside a transaction or a partial generated review."""
    conversation, job = _ended_conversation_with_job(
        db_session,
        messages=[
            ("child", "我给小黄添了菜叶"),
            ("diary", "它吃完了吗？"),
            ("child", "它吃完了"),
        ],
    )
    duck = models.Duck(name="小黄", active=True)
    db_session.add(duck)
    db_session.commit()
    assert analysis.claim_next_analysis_job(
        db_session,
        worker_id="worker-a",
        now=NOW,
        lease_seconds=30,
    ) == job.id
    factory = TrackingSessionFactory()
    analyzer = FakeAnalysisEngine(
        extraction=_analysis_output(),
        assessment=_assessment_output(),
        on_call=lambda _method: assert_no_open_analysis_session(factory),
    )

    analysis.process_analysis_job(
        factory,
        job_id=job.id,
        worker_id="worker-a",
        analyzer=analyzer,
        clock=lambda: NOW,
    )

    assert analyzer.extract_calls == [
        "child: 我给小黄添了菜叶\ndiary: 它吃完了吗？\nchild: 它吃完了"
    ]
    assert analyzer.assessment_calls == [
        (
            analyzer.extract_calls[0],
            [
                {
                    "key": "language",
                    "name": "语言表达能力",
                    "description": "能清晰、连贯地表达自己的观察与感受",
                },
                {
                    "key": "empathy",
                    "name": "同理心",
                    "description": "能体会并关心小鸭与同伴的感受",
                },
                {
                    "key": "diligence",
                    "name": "勤劳启蒙",
                    "description": "积极参与饲养劳动并承担责任",
                },
            ],
        )
    ]
    db_session.expire_all()
    assert _projection_counts(db_session, conversation.id) == {
        "feeding": 2,
        "emotion": 1,
        "insight": 1,
        "assessment": 1,
        "scores": 3,
    }
    saved_job = db_session.get(models.AnalysisJob, job.id)
    saved_conversation = db_session.get(models.Conversation, conversation.id)
    assessment = db_session.scalar(
        select(models.Assessment).where(models.Assessment.conversation_id == conversation.id)
    )
    feeding = db_session.scalars(
        select(models.FeedingLog)
        .where(models.FeedingLog.conversation_id == conversation.id)
        .order_by(models.FeedingLog.id)
    ).all()
    assert saved_job is not None
    assert saved_job.status == "succeeded"
    assert saved_job.lease_owner is None
    assert saved_job.lease_expires_at is None
    assert saved_conversation is not None
    assert saved_conversation.revision == 1
    assert assessment is not None
    assert assessment.status == "pending"
    assert assessment.overall == 4.0
    assert feeding[0].content == "给小黄添了菜叶"
    assert feeding[0].duck_id == duck.id


def test_worker_heartbeat_keeps_a_slow_success_owned_past_its_original_deadline(
    db_session,
):
    """Catches valid provider results being discarded solely because both calls crossed the lease."""
    conversation, job = _ended_conversation_with_job(db_session)
    job_id = job.id
    conversation_id = conversation.id
    db_session.rollback()
    clock_now = [NOW]
    provider_entered = Event()
    release_provider = Event()
    failures: list[BaseException] = []

    def pause_extraction(method: str) -> None:
        if method != "extract":
            return
        clock_now[0] = NOW + timedelta(seconds=4)
        provider_entered.set()
        assert release_provider.wait(2)

    worker = AnalysisWorker(
        session_factory=SessionLocal,
        analyzer=FakeAnalysisEngine(
            extraction=_analysis_output(),
            assessment=_assessment_output(),
            on_call=pause_extraction,
        ),
        clock=lambda: clock_now[0],
        lease_seconds=6,
        heartbeat_interval_seconds=0.01,
    )

    def run_worker_once() -> None:
        try:
            worker.run_once()
        except BaseException as exc:  # Preserve the worker-thread failure for the assertion.
            failures.append(exc)

    thread = Thread(target=run_worker_once)
    thread.start()
    try:
        assert provider_entered.wait(1)
        extended_to = _wait_for_lease_extension(
            job_id,
            beyond=NOW + timedelta(seconds=6),
        )
        clock_now[0] = NOW + timedelta(seconds=7)
    finally:
        release_provider.set()
        thread.join(2)

    assert extended_to == (NOW + timedelta(seconds=10)).replace(tzinfo=None)
    assert not thread.is_alive()
    assert failures == []
    db_session.expire_all()
    saved = db_session.get(models.AnalysisJob, job_id)
    assert saved is not None
    assert saved.status == "succeeded"
    assert _projection_counts(db_session, conversation_id)["assessment"] == 1


def test_worker_heartbeat_allows_a_slow_failure_to_leave_processing(db_session):
    """Catches a provider exception after the original deadline stranding the job forever."""
    _conversation, job = _ended_conversation_with_job(db_session)
    job_id = job.id
    db_session.rollback()
    clock_now = [NOW]
    provider_entered = Event()
    release_provider = Event()
    failures: list[BaseException] = []

    def pause_extraction(method: str) -> None:
        if method != "extract":
            return
        clock_now[0] = NOW + timedelta(seconds=4)
        provider_entered.set()
        assert release_provider.wait(2)

    worker = AnalysisWorker(
        session_factory=SessionLocal,
        analyzer=FakeAnalysisEngine(
            extraction=RuntimeError("slow provider failure"),
            assessment=_assessment_output(),
            on_call=pause_extraction,
        ),
        clock=lambda: clock_now[0],
        lease_seconds=6,
        heartbeat_interval_seconds=0.01,
    )

    def run_worker_once() -> None:
        try:
            worker.run_once()
        except BaseException as exc:  # Preserve the worker-thread failure for the assertion.
            failures.append(exc)

    thread = Thread(target=run_worker_once)
    thread.start()
    try:
        assert provider_entered.wait(1)
        _wait_for_lease_extension(job_id, beyond=NOW + timedelta(seconds=6))
        clock_now[0] = NOW + timedelta(seconds=7)
    finally:
        release_provider.set()
        thread.join(2)

    assert not thread.is_alive()
    assert failures == []
    db_session.expire_all()
    saved = db_session.get(models.AnalysisJob, job_id)
    assert saved is not None
    assert saved.status == "pending"
    assert saved.attempt_count == 1
    assert saved.lease_owner is None
    assert saved.available_at == (NOW + timedelta(seconds=8)).replace(tzinfo=None)


def test_worker_joins_an_inflight_heartbeat_before_projection_persistence(
    db_session,
    monkeypatch,
):
    """Catches the final SQLite transaction racing an in-flight heartbeat writer."""
    _conversation, job = _ended_conversation_with_job(db_session)
    job_id = job.id
    db_session.rollback()
    heartbeat_committed = Event()
    release_heartbeat = Event()
    assessment_returned = Event()
    projection_started = Event()
    failures: list[BaseException] = []
    original_renew = analysis.renew_analysis_job_lease
    original_replace = analysis._replace_projection

    def hold_heartbeat(*args, **kwargs):
        renewed = original_renew(*args, **kwargs)
        heartbeat_committed.set()
        assert release_heartbeat.wait(2)
        return renewed

    def observe_projection(*args, **kwargs):
        projection_started.set()
        return original_replace(*args, **kwargs)

    monkeypatch.setattr(analysis, "renew_analysis_job_lease", hold_heartbeat)
    monkeypatch.setattr(analysis, "_replace_projection", observe_projection)

    def coordinate_provider(method: str) -> None:
        if method == "extract":
            assert heartbeat_committed.wait(1)
        elif method == "assess":
            assessment_returned.set()

    worker = AnalysisWorker(
        session_factory=SessionLocal,
        analyzer=FakeAnalysisEngine(
            extraction=_analysis_output(),
            assessment=_assessment_output(),
            on_call=coordinate_provider,
        ),
        clock=lambda: NOW,
        lease_seconds=6,
        heartbeat_interval_seconds=0.01,
    )

    def run_worker_once() -> None:
        try:
            worker.run_once()
        except BaseException as exc:  # Preserve the worker-thread failure for the assertion.
            failures.append(exc)

    thread = Thread(target=run_worker_once)
    thread.start()
    try:
        assert heartbeat_committed.wait(1)
        assert assessment_returned.wait(1)
        assert not projection_started.wait(0.1)
    finally:
        release_heartbeat.set()
        thread.join(2)

    assert not thread.is_alive()
    assert failures == []
    assert projection_started.is_set()
    db_session.expire_all()
    saved = db_session.get(models.AnalysisJob, job_id)
    assert saved is not None
    assert saved.status == "succeeded"


def test_frozen_transcript_excludes_a_later_message_in_the_same_conversation(db_session):
    """Catches analysis silently including text that arrived after completion froze the job."""
    conversation, job = _ended_conversation_with_job(
        db_session,
        messages=[("child", "冻结前的观察")],
    )
    late = models.Message(
        conversation_id=conversation.id,
        role="child",
        text="冻结后绝不能分析的消息",
    )
    db_session.add(late)
    db_session.commit()
    assert late.id > job.frozen_last_message_id
    assert analysis.claim_next_analysis_job(
        db_session,
        worker_id="worker-a",
        now=NOW,
        lease_seconds=30,
    ) == job.id
    analyzer = FakeAnalysisEngine(extraction=_analysis_output(), assessment=_assessment_output())

    analysis.process_analysis_job(
        SessionLocal,
        job_id=job.id,
        worker_id="worker-a",
        analyzer=analyzer,
        clock=lambda: NOW,
    )

    assert analyzer.extract_calls == ["child: 冻结前的观察"]
    assert analyzer.assessment_calls[0][0] == "child: 冻结前的观察"
    assert "冻结后绝不能分析的消息" not in analyzer.extract_calls[0]


def assert_no_open_analysis_session(factory: TrackingSessionFactory) -> None:
    assert factory.open_sessions == 0


@pytest.mark.parametrize(
    "assessment",
    [
        RuntimeError("provider details must not leave the process"),
        {"scores": [{"dimension_key": "language", "score": 6, "reason": "bad"}]},
    ],
)
def test_assessment_failure_or_malformed_output_writes_no_partial_projection(
    db_session,
    assessment,
):
    """Catches persisting extraction rows before all untrusted output is valid."""
    conversation, job = _ended_conversation_with_job(db_session)
    assert analysis.claim_next_analysis_job(
        db_session,
        worker_id="worker-a",
        now=NOW,
        lease_seconds=30,
    ) == job.id

    analysis.process_analysis_job(
        SessionLocal,
        job_id=job.id,
        worker_id="worker-a",
        analyzer=FakeAnalysisEngine(extraction=_analysis_output(), assessment=assessment),
        clock=lambda: NOW,
    )

    db_session.expire_all()
    assert _projection_counts(db_session, conversation.id) == {
        "feeding": 0,
        "emotion": 0,
        "insight": 0,
        "assessment": 0,
        "scores": 0,
    }
    saved = db_session.get(models.AnalysisJob, job.id)
    assert saved is not None
    assert saved.status == "pending"
    assert saved.available_at == (NOW + timedelta(seconds=1)).replace(tzinfo=None)
    assert saved.last_error_code == "ANALYSIS_UPSTREAM_FAILED"
    assert saved.last_error_message == "分析服务暂时不可用"
    assert saved.lease_owner is None
    assert saved.lease_expires_at is None


@pytest.mark.parametrize("failure_kind", ["extraction", "assessment", "malformed"])
def test_ai_failure_or_malformed_output_preserves_every_existing_projection(
    db_session,
    failure_kind,
):
    """Catches a failed replacement deleting any retained generated record or revision."""
    conversation, job = _ended_conversation_with_job(db_session)
    before = _seed_existing_projection(db_session, conversation)
    assert analysis.claim_next_analysis_job(
        db_session,
        worker_id="worker-a",
        now=NOW,
        lease_seconds=30,
    ) == job.id
    if failure_kind == "extraction":
        analyzer = FakeAnalysisEngine(
            extraction=RuntimeError("extract provider failure"),
            assessment=_assessment_output(),
        )
    elif failure_kind == "assessment":
        analyzer = FakeAnalysisEngine(
            extraction=_analysis_output(),
            assessment=RuntimeError("assessment provider failure"),
        )
    else:
        analyzer = FakeAnalysisEngine(
            extraction=_analysis_output(),
            assessment={"scores": [{"dimension_key": "language", "score": 9, "reason": "坏输出"}]},
        )

    analysis.process_analysis_job(
        SessionLocal,
        job_id=job.id,
        worker_id="worker-a",
        analyzer=analyzer,
        clock=lambda: NOW,
    )

    db_session.expire_all()
    assert _projection_snapshot(db_session, conversation.id) == before
    saved = db_session.get(models.AnalysisJob, job.id)
    assert saved is not None
    assert saved.status == "pending"
    assert saved.available_at == (NOW + timedelta(seconds=1)).replace(tzinfo=None)
    assert saved.last_error_code == "ANALYSIS_UPSTREAM_FAILED"
    assert saved.last_error_message == "分析服务暂时不可用"


def test_rejects_a_frozen_message_id_from_another_conversation_without_calling_ai(
    db_session,
):
    """Catches trusting the job's foreign key instead of proving transcript ownership."""
    conversation, job = _ended_conversation_with_job(db_session)
    other_conversation, _ = _ended_conversation_with_job(db_session)
    foreign_message = db_session.scalar(
        select(models.Message)
        .where(models.Message.conversation_id == other_conversation.id)
    )
    assert foreign_message is not None
    conversation.frozen_last_message_id = foreign_message.id
    job.frozen_last_message_id = foreign_message.id
    db_session.commit()
    assert analysis.claim_next_analysis_job(
        db_session,
        worker_id="worker-a",
        now=NOW,
        lease_seconds=30,
    ) == job.id
    analyzer = FakeAnalysisEngine(extraction=_analysis_output(), assessment=_assessment_output())

    analysis.process_analysis_job(
        SessionLocal,
        job_id=job.id,
        worker_id="worker-a",
        analyzer=analyzer,
        clock=lambda: NOW,
    )

    assert analyzer.extract_calls == []
    assert analyzer.assessment_calls == []
    db_session.expire_all()
    saved = db_session.get(models.AnalysisJob, job.id)
    assert saved is not None
    assert saved.status == "pending"
    assert _projection_counts(db_session, conversation.id) == {
        "feeding": 0,
        "emotion": 0,
        "insight": 0,
        "assessment": 0,
        "scores": 0,
    }


@pytest.mark.parametrize(
    ("attempt_count", "expected_status", "delay_seconds"),
    [
        (1, "pending", 1),
        (2, "pending", 5),
        (3, "failed", 0),
    ],
)
def test_failure_uses_bounded_backoff_then_a_sanitized_terminal_state(
    db_session,
    attempt_count,
    expected_status,
    delay_seconds,
):
    """Catches retry timing that either hammers the provider or never terminates."""
    _conversation, job = _ended_conversation_with_job(db_session)
    job.status = "processing"
    job.attempt_count = attempt_count
    job.max_attempts = 3
    job.lease_owner = "worker-a"
    job.lease_expires_at = NOW + timedelta(seconds=30)
    db_session.commit()

    analysis.process_analysis_job(
        SessionLocal,
        job_id=job.id,
        worker_id="worker-a",
        analyzer=FakeAnalysisEngine(
            extraction=RuntimeError("provider secret URL must never persist"),
            assessment=_assessment_output(),
        ),
        clock=lambda: NOW,
    )

    db_session.expire_all()
    saved = db_session.get(models.AnalysisJob, job.id)
    assert saved is not None
    assert saved.status == expected_status
    assert saved.available_at == (NOW + timedelta(seconds=delay_seconds)).replace(tzinfo=None)
    assert saved.last_error_code == "ANALYSIS_UPSTREAM_FAILED"
    assert saved.last_error_message == "分析服务暂时不可用"
    assert saved.lease_owner is None
    assert saved.lease_expires_at is None
    assert saved.finished_at == (NOW.replace(tzinfo=None) if attempt_count == 3 else None)


def test_lease_loss_preserves_existing_projection_and_stale_worker_cannot_fail_it(
    db_session,
    caplog,
):
    """Catches an old worker deleting results or resetting a lease taken by another worker."""
    conversation, job = _ended_conversation_with_job(db_session)
    db_session.add(
        models.FeedingLog(
            conversation_id=conversation.id,
            child_id=conversation.child_id,
            category="观察",
            content="保留的教师结果",
        )
    )
    db_session.commit()
    assert analysis.claim_next_analysis_job(
        db_session,
        worker_id="worker-a",
        now=NOW,
        lease_seconds=30,
    ) == job.id

    taken_over = False

    def take_over(_method: str) -> None:
        nonlocal taken_over
        if taken_over:
            return
        taken_over = True
        other = SessionLocal()
        try:
            current = other.get(models.AnalysisJob, job.id)
            assert current is not None
            current.lease_owner = "worker-b"
            current.lease_expires_at = NOW + timedelta(seconds=30)
            other.commit()
        finally:
            other.close()

    result = analysis.process_analysis_job(
        SessionLocal,
        job_id=job.id,
        worker_id="worker-a",
        analyzer=FakeAnalysisEngine(
            extraction=_analysis_output(),
            assessment=RuntimeError("stale provider failure"),
            on_call=take_over,
        ),
        clock=lambda: NOW,
    )

    db_session.expire_all()
    saved = db_session.get(models.AnalysisJob, job.id)
    logs = db_session.scalars(
        select(models.FeedingLog).where(models.FeedingLog.conversation_id == conversation.id)
    ).all()
    assert saved is not None
    assert saved.status == "processing"
    assert saved.lease_owner == "worker-b"
    assert saved.last_error_code is None
    assert [log.content for log in logs] == ["保留的教师结果"]
    assert result == "lease_lost"
    assert "analysis lease lost before failure recording" in caplog.text


def test_lease_loss_before_projection_writes_nothing_even_after_valid_ai_results(
    db_session,
    caplog,
):
    """Catches a stale worker replacing results after its lease was taken over."""
    conversation, job = _ended_conversation_with_job(db_session)
    db_session.add(
        models.InsightNote(
            conversation_id=conversation.id,
            child_id=conversation.child_id,
            content="保留的心得",
        )
    )
    db_session.commit()
    assert analysis.claim_next_analysis_job(
        db_session,
        worker_id="worker-a",
        now=NOW,
        lease_seconds=30,
    ) == job.id

    taken_over = False

    def take_over(_method: str) -> None:
        nonlocal taken_over
        if taken_over:
            return
        taken_over = True
        other = SessionLocal()
        try:
            current = other.get(models.AnalysisJob, job.id)
            assert current is not None
            current.lease_owner = "worker-b"
            current.lease_expires_at = NOW + timedelta(seconds=30)
            other.commit()
        finally:
            other.close()

    result = analysis.process_analysis_job(
        SessionLocal,
        job_id=job.id,
        worker_id="worker-a",
        analyzer=FakeAnalysisEngine(
            extraction=_analysis_output(),
            assessment=_assessment_output(),
            on_call=take_over,
        ),
        clock=lambda: NOW,
    )

    db_session.expire_all()
    saved = db_session.get(models.AnalysisJob, job.id)
    insight = db_session.scalar(
        select(models.InsightNote).where(models.InsightNote.conversation_id == conversation.id)
    )
    assert saved is not None
    assert saved.status == "processing"
    assert saved.lease_owner == "worker-b"
    assert insight is not None
    assert insight.content == "保留的心得"
    assert _projection_counts(db_session, conversation.id)["assessment"] == 0
    assert result == "lease_lost"
    assert "analysis lease lost before projection" in caplog.text


def test_a_succeeded_job_is_a_no_op_and_never_replaces_its_projection(db_session):
    """Catches a duplicate worker run deleting retained successful analysis."""
    conversation, job = _ended_conversation_with_job(db_session)
    assert analysis.claim_next_analysis_job(
        db_session,
        worker_id="worker-a",
        now=NOW,
        lease_seconds=30,
    ) == job.id
    analysis.process_analysis_job(
        SessionLocal,
        job_id=job.id,
        worker_id="worker-a",
        analyzer=FakeAnalysisEngine(extraction=_analysis_output(), assessment=_assessment_output()),
        clock=lambda: NOW,
    )
    before = _projection_counts(db_session, conversation.id)
    duplicate = FakeAnalysisEngine(
        extraction=RuntimeError("a succeeded job must not call providers"),
        assessment=_assessment_output(),
    )

    analysis.process_analysis_job(
        SessionLocal,
        job_id=job.id,
        worker_id="worker-a",
        analyzer=duplicate,
        clock=lambda: NOW,
    )

    db_session.expire_all()
    assert duplicate.extract_calls == []
    assert _projection_counts(db_session, conversation.id) == before


def test_teacher_retry_requires_session_and_reuses_the_failed_job(client, db_session):
    """Catches an unauthenticated retry or a retry that silently creates another job."""
    conversation, job = _ended_conversation_with_job(db_session)
    job.status = "failed"
    job.attempt_count = 3
    job.lease_owner = "old-worker"
    job.lease_expires_at = NOW
    job.last_error_code = "ANALYSIS_UPSTREAM_FAILED"
    job.last_error_message = "分析服务暂时不可用"
    job.started_at = NOW
    job.finished_at = NOW
    db_session.commit()

    unauthenticated = client.post(f"/api/conversations/{conversation.id}/analysis/retry")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"]["code"] == "TEACHER_AUTH_REQUIRED"

    assert client.post("/api/auth/setup", json={"pin": "1234"}).status_code == 200
    retried = client.post(f"/api/conversations/{conversation.id}/analysis/retry")

    assert retried.status_code == 200
    assert retried.json() == {
        "conversation_id": conversation.id,
        "analysis_job_id": job.id,
        "analysis_status": "pending",
        "attempt_count": 0,
        "retry_accepted": True,
        "replayed": False,
    }
    db_session.expire_all()
    saved = db_session.get(models.AnalysisJob, job.id)
    assert saved is not None
    assert saved.status == "pending"
    assert saved.attempt_count == 0
    assert saved.lease_owner is None
    assert saved.lease_expires_at is None
    assert saved.last_error_code is None
    assert saved.last_error_message is None
    assert saved.started_at is None
    assert saved.finished_at is None
    assert db_session.scalar(
        select(func.count(models.AnalysisJob.id)).where(
            models.AnalysisJob.conversation_id == conversation.id
        )
    ) == 1


@pytest.mark.parametrize(
    ("status", "attempt_count", "http_status", "code"),
    [
        ("pending", 2, 200, None),
        ("processing", 1, 409, "ANALYSIS_IN_PROGRESS"),
        ("succeeded", 1, 409, "ANALYSIS_ALREADY_SUCCEEDED"),
    ],
)
def test_teacher_retry_has_frozen_pending_and_terminal_state_contracts(
    client,
    db_session,
    status,
    attempt_count,
    http_status,
    code,
):
    """Catches retry accepting a live/succeeded job or changing a pending attempt."""
    conversation, job = _ended_conversation_with_job(db_session)
    job.status = status
    job.attempt_count = attempt_count
    if status == "processing":
        job.lease_owner = "worker-a"
        job.lease_expires_at = NOW + timedelta(seconds=30)
    db_session.commit()
    assert client.post("/api/auth/setup", json={"pin": "1234"}).status_code == 200

    response = client.post(f"/api/conversations/{conversation.id}/analysis/retry")

    assert response.status_code == http_status
    if code is None:
        assert response.json() == {
            "conversation_id": conversation.id,
            "analysis_job_id": job.id,
            "analysis_status": "pending",
            "attempt_count": 2,
            "retry_accepted": False,
            "replayed": True,
        }
    else:
        assert response.json()["error"]["code"] == code
    db_session.expire_all()
    saved = db_session.get(models.AnalysisJob, job.id)
    assert saved is not None
    assert saved.status == status
    assert saved.attempt_count == attempt_count


def test_teacher_retry_reports_the_frozen_not_found_contract(client):
    """Catches retry turning an absent conversation/job into a new pending job."""
    assert client.post("/api/auth/setup", json={"pin": "1234"}).status_code == 200

    response = client.post("/api/conversations/99999/analysis/retry")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


def test_teacher_retry_treats_a_conversation_without_its_required_job_as_not_found(
    client,
    db_session,
):
    """Catches retry inventing a job for a malformed ended conversation."""
    child = models.Child(name="小雨", active=True)
    db_session.add(child)
    db_session.flush()
    conversation = models.Conversation(child_id=child.id, date="2026-08-23", status="ended")
    db_session.add(conversation)
    db_session.commit()
    assert client.post("/api/auth/setup", json={"pin": "1234"}).status_code == 200

    response = client.post(f"/api/conversations/{conversation.id}/analysis/retry")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
    assert db_session.scalar(
        select(func.count(models.AnalysisJob.id)).where(
            models.AnalysisJob.conversation_id == conversation.id
        )
    ) == 0


@pytest.mark.parametrize(
    ("advanced_status", "expected_code"),
    [
        ("processing", "ANALYSIS_IN_PROGRESS"),
        ("succeeded", "ANALYSIS_ALREADY_SUCCEEDED"),
    ],
)
def test_stale_failed_retry_cannot_overwrite_a_newer_worker_state(
    db_session,
    advanced_status,
    expected_code,
):
    """Catches a stale ORM job write resetting a job already advanced elsewhere."""
    conversation, job = _ended_conversation_with_job(db_session)
    job.status = "failed"
    job.attempt_count = 3
    db_session.commit()
    stale_session = SessionLocal(expire_on_commit=False)
    advancing_session = SessionLocal()
    try:
        stale = stale_session.get(models.AnalysisJob, job.id)
        assert stale is not None and stale.status == "failed"
        stale_session.commit()  # End SQLite's read transaction while retaining stale ORM values.

        accepted = analysis.retry_analysis(
            advancing_session,
            conversation.id,
            now=NOW,
        )
        assert accepted.retry_accepted is True
        advanced = advancing_session.get(models.AnalysisJob, job.id)
        assert advanced is not None
        advanced.status = advanced_status
        if advanced_status == "processing":
            advanced.attempt_count = 1
            advanced.lease_owner = "worker-b"
            advanced.lease_expires_at = NOW + timedelta(seconds=30)
        advancing_session.commit()

        with pytest.raises(APIError) as raised:
            analysis.retry_analysis(stale_session, conversation.id, now=NOW)

        assert raised.value.code == expected_code
        db_session.expire_all()
        saved = db_session.get(models.AnalysisJob, job.id)
        assert saved is not None
        assert saved.status == advanced_status
    finally:
        stale_session.close()
        advancing_session.close()


def test_two_concurrent_retries_have_one_accept_and_one_pending_replay(db_session):
    """Catches two failed-state readers both reporting that they reset the same job."""
    conversation, job = _ended_conversation_with_job(db_session)
    conversation_id = conversation.id
    job.status = "failed"
    job.attempt_count = 3
    db_session.commit()
    both_read = Barrier(2)
    results: list[schemas.AnalysisRetryResponse] = []
    failures: list[BaseException] = []

    def retry_in_own_session() -> None:
        session = SessionLocal()
        original_scalar = session.scalar
        waited = False

        def scalar(statement, *args, **kwargs):
            nonlocal waited
            result = original_scalar(statement, *args, **kwargs)
            if not waited and "analysis_jobs" in str(statement):
                waited = True
                both_read.wait(timeout=2)
            return result

        session.scalar = scalar
        try:
            results.append(analysis.retry_analysis(session, conversation_id, now=NOW))
        except BaseException as exc:  # Captured so the assertion reports both worker outcomes.
            failures.append(exc)
        finally:
            session.close()

    first = Thread(target=retry_in_own_session)
    second = Thread(target=retry_in_own_session)
    first.start()
    second.start()
    first.join(3)
    second.join(3)

    assert not first.is_alive()
    assert not second.is_alive()
    assert failures == []
    assert sorted((result.retry_accepted, result.replayed) for result in results) == [
        (False, True),
        (True, False),
    ]
    db_session.expire_all()
    saved = db_session.get(models.AnalysisJob, job.id)
    assert saved is not None
    assert saved.status == "pending"
    assert saved.attempt_count == 0


def test_retry_serializes_a_terminal_failure_that_happens_after_its_initial_read(
    db_session,
):
    """Catches retry misclassifying a new terminal failure as analysis-in-progress."""
    conversation, job = _ended_conversation_with_job(db_session)
    job.status = "failed"
    job.attempt_count = 1
    job.max_attempts = 1
    db_session.commit()
    retrying_session = SessionLocal()
    original_rollback = retrying_session.rollback
    advanced_to_failed = Event()
    initial_read_released = False

    def reset_then_terminally_fail() -> None:
        reset_session = SessionLocal()
        try:
            accepted = analysis.retry_analysis(reset_session, conversation.id, now=NOW)
            assert accepted.retry_accepted is True
        finally:
            reset_session.close()
        claim_session = SessionLocal()
        try:
            claimed = analysis.claim_next_analysis_job(
                claim_session,
                worker_id="worker-b",
                now=NOW,
                lease_seconds=30,
            )
            assert claimed == job.id
        finally:
            claim_session.close()
        analysis.process_analysis_job(
            SessionLocal,
            job_id=job.id,
            worker_id="worker-b",
            analyzer=FakeAnalysisEngine(
                extraction=RuntimeError("terminal failure after reset"),
                assessment=_assessment_output(),
            ),
            clock=lambda: NOW,
        )
        advanced_to_failed.set()

    def rollback_after_initial_read() -> None:
        nonlocal initial_read_released
        original_rollback()
        if not initial_read_released:
            initial_read_released = True
            reset_then_terminally_fail()

    retrying_session.rollback = rollback_after_initial_read
    try:
        response = analysis.retry_analysis(retrying_session, conversation.id, now=NOW)

        assert advanced_to_failed.is_set()
        assert response.retry_accepted is True
        assert response.replayed is False
        assert response.analysis_job_id == job.id
        assert not retrying_session.in_transaction()
        db_session.expire_all()
        saved = db_session.get(models.AnalysisJob, job.id)
        assert saved is not None
        assert saved.status == "pending"
        assert saved.attempt_count == 0
    finally:
        retrying_session.close()


def test_worker_start_recovers_once_rejects_double_start_and_stops_cleanly(
    db_session,
    monkeypatch,
):
    """Catches an unbounded worker lifecycle or recovery skipped on process restart."""
    import app.backend.analysis_worker as worker_module

    _conversation, job = _ended_conversation_with_job(db_session)
    job.status = "processing"
    job.attempt_count = 2
    job.lease_owner = "former-worker"
    job.lease_expires_at = NOW - timedelta(seconds=1)
    db_session.commit()
    worker = AnalysisWorker(
        session_factory=SessionLocal,
        analyzer=FakeAnalysisEngine(extraction=_analysis_output(), assessment=_assessment_output()),
        clock=lambda: NOW,
        poll_interval_seconds=60,
    )
    entered_recovery = Event()
    allow_exit = Event()
    original_recover = worker_module.recover_expired_jobs

    def recover_then_pause(db, *, now):
        result = original_recover(db, now=now)
        entered_recovery.set()
        assert allow_exit.wait(1)
        return result

    monkeypatch.setattr(worker_module, "recover_expired_jobs", recover_then_pause)

    worker.start()
    assert entered_recovery.wait(1)
    with pytest.raises(RuntimeError, match="already running"):
        worker.start()
    allow_exit.set()
    worker.stop()

    db_session.expire_all()
    saved = db_session.get(models.AnalysisJob, job.id)
    assert saved is not None
    assert saved.status == "pending"
    assert saved.attempt_count == 2
    assert saved.lease_owner is None
    assert worker.status() == "stopped"


@pytest.mark.parametrize(
    ("lease_seconds", "heartbeat_interval_seconds"),
    [
        (0, None),
        (6, 0),
        (6, 3),
        (6, float("nan")),
    ],
)
def test_worker_rejects_an_unsafe_heartbeat_configuration_before_claiming(
    db_session,
    lease_seconds,
    heartbeat_interval_seconds,
):
    """Catches invalid timing configuration claiming a job it cannot keep alive."""
    _conversation, job = _ended_conversation_with_job(db_session)

    with pytest.raises(ValueError, match="heartbeat"):
        AnalysisWorker(
            session_factory=SessionLocal,
            analyzer=FakeAnalysisEngine(
                extraction=_analysis_output(),
                assessment=_assessment_output(),
            ),
            clock=lambda: NOW,
            lease_seconds=lease_seconds,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
        )

    db_session.expire_all()
    saved = db_session.get(models.AnalysisJob, job.id)
    assert saved is not None
    assert saved.status == "pending"
    assert saved.attempt_count == 0


def test_worker_run_once_recovers_and_reclaims_an_expired_job_without_restart(db_session):
    """Catches normal polling ignoring a lease that expired after worker startup."""
    conversation, job = _ended_conversation_with_job(db_session)
    job.status = "processing"
    job.attempt_count = 1
    job.lease_owner = "dead-worker"
    job.lease_expires_at = NOW - timedelta(seconds=1)
    db_session.commit()
    analyzer = FakeAnalysisEngine(
        extraction=_analysis_output(),
        assessment=_assessment_output(),
    )
    worker = AnalysisWorker(
        session_factory=SessionLocal,
        analyzer=analyzer,
        clock=lambda: NOW,
    )

    assert worker.run_once() is True

    db_session.expire_all()
    saved = db_session.get(models.AnalysisJob, job.id)
    assert saved is not None
    assert saved.status == "succeeded"
    assert saved.attempt_count == 2
    assert analyzer.extract_calls
    assert _projection_counts(db_session, conversation.id)["assessment"] == 1


def test_worker_poll_terminally_fails_an_expired_job_at_max_attempts(db_session):
    """Catches expired processing jobs cycling past max_attempts forever."""
    _conversation, job = _ended_conversation_with_job(db_session)
    job.status = "processing"
    job.attempt_count = 3
    job.max_attempts = 3
    job.lease_owner = "dead-worker"
    job.lease_expires_at = NOW - timedelta(seconds=1)
    db_session.commit()
    analyzer = FakeAnalysisEngine(
        extraction=RuntimeError("must not call a provider after max attempts"),
        assessment=_assessment_output(),
    )
    worker = AnalysisWorker(
        session_factory=SessionLocal,
        analyzer=analyzer,
        clock=lambda: NOW,
    )

    assert worker.run_once() is False

    db_session.expire_all()
    saved = db_session.get(models.AnalysisJob, job.id)
    assert saved is not None
    assert saved.status == "failed"
    assert saved.attempt_count == 3
    assert saved.lease_owner is None
    assert saved.lease_expires_at is None
    assert saved.last_error_code == "ANALYSIS_UPSTREAM_FAILED"
    assert saved.last_error_message == "分析服务暂时不可用"
    assert saved.finished_at == NOW.replace(tzinfo=None)
    assert analyzer.extract_calls == []


def test_worker_poll_terminally_fails_a_legacy_exhausted_pending_job(db_session):
    """Catches pre-upgrade recovery output remaining pending but permanently unclaimable."""
    _conversation, job = _ended_conversation_with_job(db_session)
    job.attempt_count = 3
    job.max_attempts = 3
    db_session.commit()
    analyzer = FakeAnalysisEngine(
        extraction=RuntimeError("must not call a provider after max attempts"),
        assessment=_assessment_output(),
    )
    worker = AnalysisWorker(
        session_factory=SessionLocal,
        analyzer=analyzer,
        clock=lambda: NOW,
    )

    assert worker.run_once() is False

    db_session.expire_all()
    saved = db_session.get(models.AnalysisJob, job.id)
    assert saved is not None
    assert saved.status == "failed"
    assert saved.attempt_count == 3
    assert saved.last_error_code == "ANALYSIS_UPSTREAM_FAILED"
    assert saved.finished_at == NOW.replace(tzinfo=None)
    assert analyzer.extract_calls == []


def test_worker_run_once_uses_the_injected_engine_and_durable_claim(db_session):
    """Catches a worker bypassing the test engine or leaving a claimed job unprocessed."""
    conversation, job = _ended_conversation_with_job(db_session)
    analyzer = FakeAnalysisEngine(extraction=_analysis_output(), assessment=_assessment_output())
    worker = AnalysisWorker(
        session_factory=SessionLocal,
        analyzer=analyzer,
        clock=lambda: NOW,
    )

    assert worker.run_once() is True

    db_session.expire_all()
    saved = db_session.get(models.AnalysisJob, job.id)
    assert saved is not None
    assert saved.status == "succeeded"
    assert analyzer.extract_calls
    assert _projection_counts(db_session, conversation.id)["assessment"] == 1


def test_direct_run_once_claim_fault_sets_failed_before_reraising(monkeypatch):
    """Catches the public worker seam reporting an old idle/stopped state after failure."""
    import app.backend.analysis_worker as worker_module

    worker = AnalysisWorker(
        session_factory=SessionLocal,
        analyzer=FakeAnalysisEngine(extraction=_analysis_output(), assessment=_assessment_output()),
        clock=lambda: NOW,
    )

    def claim_fault(*_args, **_kwargs):
        raise RuntimeError("claim database fault")

    monkeypatch.setattr(worker_module, "claim_next_analysis_job", claim_fault)

    with pytest.raises(RuntimeError, match="claim database fault"):
        worker.run_once()

    assert worker.status() == "failed"


def test_startup_recovery_fault_remains_failed_for_health(monkeypatch):
    """Catches lifespan health claiming stopped when startup recovery actually failed."""
    import app.backend.analysis_worker as worker_module

    worker = AnalysisWorker(
        session_factory=SessionLocal,
        analyzer=FakeAnalysisEngine(extraction=_analysis_output(), assessment=_assessment_output()),
        clock=lambda: NOW,
    )
    attempted = Event()

    def recovery_fault(*_args, **_kwargs):
        attempted.set()
        raise RuntimeError("recovery database fault")

    monkeypatch.setattr(worker_module, "recover_expired_jobs", recovery_fault)

    worker.start()
    assert attempted.wait(1)
    worker.stop()

    assert worker.status() == "failed"


def test_lifespan_uses_the_injected_single_worker_for_health_and_teardown(monkeypatch):
    """Catches TestClient lifespan constructing a second uncontrolled worker."""
    instances = []

    class LifecycleWorker:
        def __init__(self):
            self.started = 0
            self.stopped = 0

        def start(self):
            self.started += 1

        def stop(self, timeout_seconds=5.0):
            assert timeout_seconds == 5.0
            self.stopped += 1

        def status(self):
            return "idle"

    def factory():
        worker = LifecycleWorker()
        instances.append(worker)
        return worker

    monkeypatch.setattr(app.state, "analysis_worker_factory", factory, raising=False)

    with TestClient(app) as test_client:
        assert len(instances) == 1
        assert instances[0].started == 1
        assert test_client.get("/api/health").json()["analysis_worker_status"] == "idle"

    assert instances[0].stopped == 1
    assert app.state.analysis_worker_status_provider() == "not_started"


def test_default_testclient_lifespan_never_starts_a_real_worker(client, db_session):
    """Catches test lifespan stealing a deterministic pending analysis job."""
    _conversation, job = _ended_conversation_with_job(db_session)

    assert client.get("/api/health").json()["analysis_worker_status"] == "not_started"

    db_session.expire_all()
    saved = db_session.get(models.AnalysisJob, job.id)
    assert saved is not None
    assert saved.status == "pending"
