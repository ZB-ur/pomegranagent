"""SQLAlchemy 数据模型（与需求规格数据模型一致）。"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class TeacherCredential(Base):
    __tablename__ = "teacher_credentials"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    pin_salt: Mapped[str] = mapped_column(String(64))
    pin_hash: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class TeacherSession(Base):
    __tablename__ = "teacher_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Child(Base):
    __tablename__ = "children"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    nickname: Mapped[str | None] = mapped_column(String(64), nullable=True)
    avatar: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Duck(Base):
    __tablename__ = "ducks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    avatar: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AvatarMedia(Base):
    __tablename__ = "avatar_media"
    __table_args__ = (
        CheckConstraint("width > 0", name="ck_avatar_media_width_positive"),
        CheckConstraint("height > 0", name="ck_avatar_media_height_positive"),
        CheckConstraint("size_bytes > 0", name="ck_avatar_media_size_positive"),
        CheckConstraint("mime_type = 'image/webp'", name="ck_avatar_media_webp"),
        CheckConstraint(
            "length(sha256) = 64",
            name="ck_avatar_media_sha256_length",
        ),
        UniqueConstraint("file_name", name="uq_avatar_media_file_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(32), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DutyRoster(Base):
    __tablename__ = "duty_rosters"
    __table_args__ = (
        UniqueConstraint("date", "child_id", name="uq_roster_date_child"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle: Mapped[str] = mapped_column(String(64))  # 周期标识，如 "2026-W33"
    date: Mapped[str] = mapped_column(String(16))   # 值班日期 YYYY-MM-DD
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"))


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index(
            "uq_conversations_child_active",
            "child_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
        ),
        Index(
            "ix_conversations_status_date_ended_id",
            "status",
            "date",
            "ended_at",
            "id",
        ),
        Index(
            "ix_conversations_child_status_date_ended_id",
            "child_id",
            "status",
            "date",
            "ended_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"))
    date: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active"
    )  # active / ended
    end_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pending_end_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    frozen_last_message_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    # 三种结束原因：max_rounds / complete / manual

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_id_id", "conversation_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    role: Mapped[str] = mapped_column(String(16))  # child / diary
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class ChatRequestRecord(Base):
    """Durable idempotency ledger for one child chat submission.

    ``base_last_message_id`` is the claim-time transcript boundary.  It is
    deliberately kept after success/failure so a later service can reject an
    AI result whose conversation changed while the request was leased.
    """

    __tablename__ = "chat_requests"

    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    child_id: Mapped[int] = mapped_column(
        ForeignKey("children.id"),
        nullable=False,
    )
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id"),
        nullable=True,
    )
    base_last_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id"),
        nullable=True,
    )
    child_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id"),
        nullable=True,
    )
    diary_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id"),
        nullable=True,
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="processing",
        index=True,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        index=True,
    )
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class AnalysisJob(Base):
    """One durable, leaseable analysis job for a frozen conversation."""

    __tablename__ = "analysis_jobs"
    __table_args__ = (
        UniqueConstraint("conversation_id", name="uq_analysis_job_conversation"),
        Index(
            "ix_analysis_jobs_status_conversation_id",
            "status",
            "conversation_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"),
        nullable=False,
    )
    frozen_last_message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        index=True,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        index=True,
    )
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class RosterRequest(Base):
    """Durable idempotency ledger for manual and automatic roster writes."""

    __tablename__ = "roster_requests"

    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    operation: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="processing",
        index=True,
    )
    response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class FeedingLog(Base):
    __tablename__ = "feeding_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"))
    duck_id: Mapped[int | None] = mapped_column(ForeignKey("ducks.id"), nullable=True)
    category: Mapped[str] = mapped_column(String(32))  # 喂食/清洁/观察/其它
    content: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class EmotionLog(Base):
    __tablename__ = "emotion_logs"
    __table_args__ = (
        UniqueConstraint("conversation_id", name="uq_emotion_conversation"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"))
    emotion: Mapped[str] = mapped_column(String(32))  # 开心/平静/疲惫/期待...
    intensity: Mapped[int] = mapped_column(Integer, default=3)  # 1-5
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class InsightNote(Base):
    __tablename__ = "insight_notes"
    __table_args__ = (
        UniqueConstraint("conversation_id", name="uq_insight_conversation"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AssessmentDimension(Base):
    __tablename__ = "assessment_dimensions"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Assessment(Base):
    __tablename__ = "assessments"
    __table_args__ = (
        UniqueConstraint("conversation_id", name="uq_assessment_conversation"),
        Index(
            "ix_assessments_status_conversation_id",
            "status",
            "conversation_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/confirmed
    overall: Mapped[float | None] = mapped_column(Float, nullable=True)

    scores: Mapped[list["AssessmentScore"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )


class AssessmentScore(Base):
    __tablename__ = "assessment_scores"
    __table_args__ = (
        UniqueConstraint(
            "assessment_id",
            "dimension_id",
            name="uq_assessment_dimension",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id"))
    dimension_id: Mapped[int] = mapped_column(ForeignKey("assessment_dimensions.id"))
    score: Mapped[int] = mapped_column(Integer)  # 1-5
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    assessment: Mapped["Assessment"] = relationship(back_populates="scores")


class DuckArchive(Base):
    __tablename__ = "duck_archives"

    id: Mapped[int] = mapped_column(primary_key=True)
    duck_id: Mapped[int] = mapped_column(ForeignKey("ducks.id"))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
