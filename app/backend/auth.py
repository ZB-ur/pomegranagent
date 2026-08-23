"""Teacher PIN credentials and revocable browser sessions."""
from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models, schemas
from .api_errors import APIError
from .database import get_db

COOKIE_NAME = "duck_teacher_session"
router = APIRouter(prefix="/api/auth", tags=["teacher-auth"])


def _pin_digest(pin: str, salt_hex: str) -> str:
    return hashlib.scrypt(
        pin.encode("ascii"),
        salt=bytes.fromhex(salt_hex),
        n=2**14,
        r=8,
        p=1,
    ).hex()


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _find_session(request: Request, db: Session) -> models.TeacherSession | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return db.scalar(
        select(models.TeacherSession).where(
            models.TeacherSession.token_hash == _token_digest(token)
        )
    )


def require_teacher_session(
    request: Request,
    db: Session = Depends(get_db),
) -> models.TeacherSession:
    session = _find_session(request, db)
    if session is None:
        raise APIError(401, "TEACHER_AUTH_REQUIRED", "请先输入教师 PIN 解锁")
    return session


def _issue_session(response: Response, db: Session) -> None:
    token = secrets.token_urlsafe(32)
    db.add(models.TeacherSession(token_hash=_token_digest(token)))
    db.commit()
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="strict",
        secure=False,
        path="/",
    )


@router.get("/status", response_model=schemas.TeacherAuthStatus)
def status(request: Request, db: Session = Depends(get_db)):
    configured = db.scalar(select(models.TeacherCredential.id)) is not None
    return {
        "configured": configured,
        "authenticated": _find_session(request, db) is not None,
    }


@router.post("/setup", response_model=schemas.TeacherAuthStatus)
def setup(
    payload: schemas.TeacherPinRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    if db.scalar(select(models.TeacherCredential.id)) is not None:
        raise APIError(409, "PIN_ALREADY_CONFIGURED", "教师 PIN 已设置")
    salt = secrets.token_bytes(16).hex()
    db.add(models.TeacherCredential(
        id=1,
        pin_salt=salt,
        pin_hash=_pin_digest(payload.pin, salt),
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise APIError(409, "PIN_ALREADY_CONFIGURED", "教师 PIN 已设置")
    _issue_session(response, db)
    return {"configured": True, "authenticated": True}


@router.post("/unlock", response_model=schemas.TeacherAuthStatus)
def unlock(
    payload: schemas.TeacherPinRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    credential = db.get(models.TeacherCredential, 1)
    if credential is None:
        raise APIError(409, "PIN_NOT_CONFIGURED", "请先设置教师 PIN")
    if not hmac.compare_digest(
        credential.pin_hash,
        _pin_digest(payload.pin, credential.pin_salt),
    ):
        raise APIError(401, "PIN_INVALID", "PIN 不正确")
    _issue_session(response, db)
    return {"configured": True, "authenticated": True}


@router.post("/lock", response_model=schemas.TeacherAuthStatus)
def lock(request: Request, response: Response, db: Session = Depends(get_db)):
    session = _find_session(request, db)
    if session is not None:
        db.delete(session)
        db.commit()
    response.delete_cookie(COOKIE_NAME, path="/", samesite="strict")
    configured = db.scalar(select(models.TeacherCredential.id)) is not None
    return {"configured": configured, "authenticated": False}
