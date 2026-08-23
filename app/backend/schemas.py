"""Pydantic 请求/响应模型。"""
from datetime import date, datetime
from typing import Annotated, Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VersionResponse(BaseModel):
    release_id: str
    api_version: str
    schema_version: str


class HealthResponse(VersionResponse):
    db_mode: Literal["app", "test"]
    analysis_worker_status: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    field_errors: dict[str, list[str]]
    retryable: bool
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class TeacherPinRequest(BaseModel):
    pin: str = Field(pattern=r"^[0-9]{4,6}$")


class TeacherAuthStatus(BaseModel):
    configured: bool
    authenticated: bool


# ---------- 幼儿 ----------
class ChildBase(BaseModel):
    name: str
    nickname: str | None = None
    avatar: str | None = None
    active: bool = True


class ChildCreate(ChildBase):
    pass


class ChildOut(ChildBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ---------- 小鸭 ----------
class DuckBase(BaseModel):
    name: str
    avatar: str | None = None
    status: str | None = None
    note: str | None = None


class DuckCreate(DuckBase):
    pass


class DuckOut(DuckBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ---------- 排班 ----------
class RosterIn(BaseModel):
    cycle: str
    date: str
    child_ids: list[int]


class RosterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    cycle: str
    date: str
    child_id: int


# ---------- 对话 ----------
class ChatRequest(BaseModel):
    """One idempotent child chat turn, normalized before payload hashing."""

    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    child_id: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=2000)
    conversation_id: int | None = Field(default=None, gt=0)
    max_rounds: int = Field(default=3, ge=1, le=10)

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class ChatReply(BaseModel):
    conversation_id: int
    reply: str
    ended: bool
    end_reason: str | None = None
    round: int


# ---------- 评估 ----------
class ScorePatch(BaseModel):
    score: int | None = None
    reason: str | None = None


class AssessmentConfirm(BaseModel):
    scores: dict[int, ScorePatch] | None = None  # dimension_id -> patch


# ---------- 提炼修正 ----------
class LogPatch(BaseModel):
    content: str | None = None
    category: str | None = None
    emotion: str | None = None
    intensity: int | None = None


# ---------- 可靠对话流水线 ----------
EndReason: TypeAlias = Literal["max_rounds", "complete"]
ConversationEndReason: TypeAlias = Literal["max_rounds", "complete", "manual"]
AnalysisJobStatus: TypeAlias = Literal["pending", "processing", "succeeded", "failed"]
ReviewAction: TypeAlias = Literal["save_draft", "confirm"]
ReviewQueue: TypeAlias = Literal["pending", "processing", "failed"]
ReviewStatus: TypeAlias = Literal["pending", "draft", "confirmed", "unavailable"]
FeedingCategory: TypeAlias = Literal["喂食", "清洁", "观察", "其它"]
PositiveInt = Annotated[int, Field(gt=0)]


class MutableRequestModel(BaseModel):
    """Base for public mutation DTOs; unknown input must be rejected."""

    model_config = ConfigDict(extra="forbid")


class StrictResponseModel(BaseModel):
    """Base for frozen public response shapes; unknown output is a contract bug."""

    model_config = ConfigDict(extra="forbid")


class RosterTodayChild(StrictResponseModel):
    id: PositiveInt
    name: str
    nickname: str | None = None
    avatar: str | None = None


class ConversationMessage(StrictResponseModel):
    id: PositiveInt
    role: Literal["child", "diary"]
    text: str


class ActiveConversation(StrictResponseModel):
    id: PositiveInt
    child_id: PositiveInt
    status: Literal["active"]
    revision: int = Field(ge=0)
    round: int = Field(ge=0)
    last_message_id: PositiveInt | None = None
    messages: list[ConversationMessage]


class ActiveConversationResponse(StrictResponseModel):
    conversation: ActiveConversation | None


class ChatResponse(StrictResponseModel):
    request_id: UUID
    conversation_id: PositiveInt
    child_message_id: PositiveInt
    diary_message_id: PositiveInt
    reply: str
    round: int = Field(ge=1)
    ended: bool
    end_reason: EndReason | None = None
    replayed: bool


class ConversationCompleteRequest(MutableRequestModel):
    expected_last_message_id: PositiveInt


class ConversationCompleteResponse(StrictResponseModel):
    conversation_id: PositiveInt
    conversation_saved: bool
    status: Literal["completed"]
    completed_at: datetime
    message_count: int = Field(ge=1)
    last_message_id: PositiveInt
    analysis_job_id: PositiveInt
    analysis_status: Literal["pending"]
    replayed: bool


class ChildIdentity(StrictResponseModel):
    id: PositiveInt
    name: str
    nickname: str | None = None
    avatar: str | None = None


class ConversationQueueItem(StrictResponseModel):
    id: PositiveInt
    child: ChildIdentity
    date: date
    started_at: datetime
    completed_at: datetime
    message_count: int = Field(ge=1)
    round: int = Field(ge=0)
    status: Literal["ended"]
    end_reason: ConversationEndReason
    analysis_status: AnalysisJobStatus
    review_status: ReviewStatus
    revision: int = Field(ge=0)


class AnalysisError(StrictResponseModel):
    code: Literal["ANALYSIS_UPSTREAM_FAILED"]
    message: Literal["分析服务暂时不可用"]


class ConversationAnalysis(StrictResponseModel):
    job_id: PositiveInt
    status: AnalysisJobStatus
    attempt_count: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    error: AnalysisError | None = None
    updated_at: datetime


class ReviewFeedingLog(StrictResponseModel):
    id: PositiveInt
    category: FeedingCategory
    content: str
    duck_id: PositiveInt | None = None


class ReviewEmotion(StrictResponseModel):
    emotion: str
    intensity: int = Field(ge=1, le=5)
    note: str | None = None


class ReviewScore(StrictResponseModel):
    dimension_id: PositiveInt
    dimension_name: str
    score: int = Field(ge=1, le=5)
    reason: str


class ReviewDocument(StrictResponseModel):
    feeding_logs: list[ReviewFeedingLog]
    emotion: ReviewEmotion
    insight: str
    scores: list[ReviewScore]
    overall: float


class ConversationDetail(StrictResponseModel):
    id: PositiveInt
    child: ChildIdentity
    date: date
    started_at: datetime
    completed_at: datetime
    status: Literal["ended"]
    end_reason: ConversationEndReason
    message_count: int = Field(ge=1)
    round: int = Field(ge=0)
    last_message_id: PositiveInt
    revision: int = Field(ge=0)
    analysis: ConversationAnalysis
    review_status: ReviewStatus
    messages: list[ConversationMessage]
    review: ReviewDocument | None = None


class ReviewFeedingLogRequest(MutableRequestModel):
    id: PositiveInt | None = None
    category: FeedingCategory
    content: str = Field(min_length=1, max_length=500)
    duck_id: PositiveInt | None = None

    @field_validator("content", mode="before")
    @classmethod
    def normalize_content(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class ReviewEmotionRequest(MutableRequestModel):
    emotion: str = Field(min_length=1, max_length=32)
    intensity: int = Field(ge=1, le=5)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("emotion", "note", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class ReviewScoreRequest(MutableRequestModel):
    dimension_id: PositiveInt
    score: int = Field(ge=1, le=5)
    reason: str = Field(max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class ReviewRequest(MutableRequestModel):
    revision: int = Field(ge=0)
    feeding_logs: list[ReviewFeedingLogRequest]
    emotion: ReviewEmotionRequest
    insight: str = Field(min_length=1, max_length=2000)
    scores: list[ReviewScoreRequest]
    action: ReviewAction

    @field_validator("insight", mode="before")
    @classmethod
    def normalize_insight(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("scores")
    @classmethod
    def require_unique_score_dimensions(
        cls,
        value: list[ReviewScoreRequest],
    ) -> list[ReviewScoreRequest]:
        dimension_ids = [score.dimension_id for score in value]
        if len(dimension_ids) != len(set(dimension_ids)):
            raise ValueError("scores must contain unique dimension_id values")
        return value


class ReviewResponse(StrictResponseModel):
    saved: bool
    conversation_id: PositiveInt
    review_status: Literal["draft", "confirmed"]
    revision: int = Field(ge=0)
    saved_at: datetime
    review: ReviewDocument


class AnalysisRetryResponse(StrictResponseModel):
    conversation_id: PositiveInt
    analysis_job_id: PositiveInt
    analysis_status: Literal["pending"]
    attempt_count: int = Field(ge=0)
    retry_accepted: bool
    replayed: bool


class DailyRosterRequest(MutableRequestModel):
    request_id: UUID
    cycle: str = Field(min_length=1, max_length=64)
    child_ids: list[PositiveInt] = Field(min_length=2, max_length=2)

    @field_validator("cycle", mode="before")
    @classmethod
    def normalize_cycle(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("child_ids")
    @classmethod
    def require_distinct_children(cls, value: list[int]) -> list[int]:
        if len(set(value)) != 2:
            raise ValueError("child_ids must contain two distinct child IDs")
        return value


class DailyRosterResponse(StrictResponseModel):
    request_id: UUID
    date: date
    cycle: str
    child_ids: list[PositiveInt]
    replayed: bool


class AutoRosterRequest(MutableRequestModel):
    request_id: UUID
    start_date: date
    days: int = Field(ge=1, le=31)
    cycle: str = Field(min_length=1, max_length=64)
    replace_existing: bool = False

    @field_validator("cycle", mode="before")
    @classmethod
    def normalize_cycle(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class AutoRosterScheduleItem(StrictResponseModel):
    date: date
    child_ids: list[PositiveInt]


class AutoRosterResponse(StrictResponseModel):
    request_id: UUID
    schedule: list[AutoRosterScheduleItem]
    replayed: bool


class DeactivationResponse(StrictResponseModel):
    id: PositiveInt
    kind: Literal["child", "duck"]
    name: str
    active: bool
    deactivated_at: datetime | None = None
    affected_future_roster_entries: int = Field(ge=0)
    changed: bool


class TeacherChildOut(ChildIdentity):
    active: bool
    deactivated_at: datetime | None = None
    future_roster_entries: int = Field(ge=0)
    has_active_conversation: bool


class TeacherDuckOut(StrictResponseModel):
    id: PositiveInt
    name: str
    avatar: str | None = None
    status: str | None = None
    note: str | None = None
    active: bool
    deactivated_at: datetime | None = None
    historical_feeding_log_count: int = Field(ge=0)
