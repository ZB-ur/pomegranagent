"""Pydantic 请求/响应模型。"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
    child_id: int
    text: str | None = None  # 幼儿说的话（前端 ASR 结果）
    conversation_id: int | None = None  # 为空则新建会话
    max_rounds: int = 3


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
