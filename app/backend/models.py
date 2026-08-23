"""SQLAlchemy 数据模型（与需求规格数据模型一致）。"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
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
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Duck(Base):
    __tablename__ = "ducks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    avatar: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class DutyRoster(Base):
    __tablename__ = "duty_rosters"

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle: Mapped[str] = mapped_column(String(64))  # 周期标识，如 "2026-W33"
    date: Mapped[str] = mapped_column(String(16))   # 值班日期 YYYY-MM-DD
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"))


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"))
    date: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active / ended
    end_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 三种结束原因：max_rounds / complete / manual

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    role: Mapped[str] = mapped_column(String(16))  # child / diary
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


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

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"))
    emotion: Mapped[str] = mapped_column(String(32))  # 开心/平静/疲惫/期待...
    intensity: Mapped[int] = mapped_column(Integer, default=3)  # 1-5
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class InsightNote(Base):
    __tablename__ = "insight_notes"

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
