"""Teacher upload and public delivery routes for avatar media."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartParser

from .. import models, schemas
from ..api_errors import APIError
from ..auth import require_teacher_session
from ..business_time import BusinessClock
from ..database import SETTINGS, get_db
from ..services.avatar_media import MAX_UPLOAD_BYTES, load_avatar, store_avatar


router = APIRouter()
BUSINESS_CLOCK = BusinessClock(SETTINGS.business_timezone)
MAX_MULTIPART_OVERHEAD = 64 * 1024


class _AvatarStreamTooLarge(Exception):
    pass


class _BoundedMultiPartParser(MultiPartParser):
    """Stop consuming a file part as soon as its encoded limit is exceeded."""

    def on_part_begin(self) -> None:
        super().on_part_begin()
        self._avatar_part_size = 0

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        if self._current_part.file is not None:
            self._avatar_part_size += end - start
            if self._avatar_part_size > MAX_UPLOAD_BYTES:
                raise _AvatarStreamTooLarge()
        super().on_part_data(data, start, end)


def _validate_content_length(request: Request) -> None:
    values = request.headers.getlist("content-length")
    if not values:
        return
    if len(values) != 1:
        raise APIError(400, "AVATAR_INVALID", "头像上传请求无效")
    try:
        length = int(values[0])
    except ValueError:
        raise APIError(400, "AVATAR_INVALID", "头像上传请求无效") from None
    if length < 0:
        raise APIError(400, "AVATAR_INVALID", "头像上传请求无效")
    if length > MAX_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD:
        raise APIError(413, "AVATAR_TOO_LARGE", "头像文件不能超过 5 MiB")


@router.post("/api/media/avatars", response_model=schemas.AvatarMediaResponse)
async def upload_avatar(
    request: Request,
    _teacher: models.TeacherSession = Depends(require_teacher_session),
    db: Session = Depends(get_db),
) -> schemas.AvatarMediaResponse:
    """Authenticate before asking Starlette to parse the multipart body."""

    _validate_content_length(request)
    try:
        form = await _BoundedMultiPartParser(
            request.headers,
            request.stream(),
            max_files=1,
            max_fields=0,
            max_part_size=MAX_UPLOAD_BYTES + 1,
        ).parse()
    except _AvatarStreamTooLarge:
        raise APIError(413, "AVATAR_TOO_LARGE", "头像文件不能超过 5 MiB") from None
    except Exception:
        raise APIError(422, "AVATAR_INVALID", "头像上传请求无效") from None
    try:
        items = list(form.multi_items())
        if len(items) != 1 or items[0][0] != "file" or not isinstance(items[0][1], UploadFile):
            raise APIError(422, "AVATAR_INVALID", "头像上传请求无效")
        upload = items[0][1]
        row = store_avatar(
            db,
            upload,
            media_root=SETTINGS.media_root,
            now=BUSINESS_CLOCK.utc_now(),
        )
        return schemas.AvatarMediaResponse(
            id=UUID(row.id),
            url=f"/api/media/avatars/{row.id}",
            mime_type="image/webp",
            width=row.width,
            height=row.height,
            size_bytes=row.size_bytes,
            sha256=row.sha256,
        )
    finally:
        try:
            await form.close()
        except Exception:
            pass


@router.get("/api/media/avatars/{media_id}")
def get_avatar(
    media_id: str,
    db: Session = Depends(get_db),
) -> Response:
    blob = load_avatar(db, media_id, media_root=SETTINGS.media_root)
    return Response(
        content=blob.content,
        media_type="image/webp",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": f'"{blob.media.sha256}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
