"""Validated, durable storage for same-origin avatar media."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import stat
from typing import BinaryIO
from uuid import UUID, uuid4
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from .. import models
from ..api_errors import APIError


MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_IMAGE_EDGE = 4096
MAX_IMAGE_PIXELS = 16_777_216
OUTPUT_MAX_EDGE = 1024
OUTPUT_WEBP_QUALITY = 88

_AVATAR_URL_PREFIX = "/api/media/avatars/"
_SUPPORTED_TYPES = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}


@dataclass(frozen=True)
class AvatarBlob:
    media: models.AvatarMedia
    content: bytes


def _invalid_avatar() -> APIError:
    return APIError(422, "AVATAR_INVALID", "头像图片无效")


def _storage_unavailable() -> APIError:
    return APIError(
        500,
        "AVATAR_STORAGE_UNAVAILABLE",
        "头像暂时无法保存，请稍后重试",
        retryable=True,
    )


def _not_found() -> APIError:
    return APIError(404, "AVATAR_NOT_FOUND", "头像不存在")


def _absolute_without_symlink_resolution(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _safe_media_root(media_root: Path, *, create: bool) -> Path:
    """Return a canonical, non-symlink directory or fail closed."""

    root = _absolute_without_symlink_resolution(Path(media_root))
    try:
        if root.resolve(strict=False) != root:
            raise _storage_unavailable()
        if root.is_symlink():
            raise _storage_unavailable()
        if not root.exists():
            if not create:
                raise _not_found()
            root.mkdir(parents=True, exist_ok=False)
        root_stat = root.lstat()
        if not stat.S_ISDIR(root_stat.st_mode) or root.is_symlink():
            raise _storage_unavailable()
        if root.resolve(strict=True) != root:
            raise _storage_unavailable()
    except APIError:
        raise
    except (FileExistsError, FileNotFoundError, OSError):
        if create:
            raise _storage_unavailable() from None
        raise _not_found() from None
    return root


def _open_directory(root: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(root, flags)
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise _storage_unavailable()
    return descriptor


def _read_bounded(file_object: BinaryIO) -> bytes:
    chunks: list[bytes] = []
    remaining = MAX_UPLOAD_BYTES + 1
    while remaining > 0:
        chunk = file_object.read(min(64 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    data = b"".join(chunks)
    if len(data) > MAX_UPLOAD_BYTES:
        raise APIError(413, "AVATAR_TOO_LARGE", "头像文件不能超过 5 MiB")
    if not data:
        raise _invalid_avatar()
    return data


def _has_exact_container(data: bytes, image_format: str) -> bool:
    if image_format == "PNG":
        return (
            data.startswith(b"\x89PNG\r\n\x1a\n")
            and data.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82")
        )
    if image_format == "JPEG":
        return data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9")
    if image_format == "WEBP":
        return (
            len(data) >= 12
            and data[:4] == b"RIFF"
            and data[8:12] == b"WEBP"
            and int.from_bytes(data[4:8], "little") + 8 == len(data)
        )
    return False


def _validate_dimensions(image: Image.Image) -> None:
    width, height = image.size
    if (
        width <= 0
        or height <= 0
        or width > MAX_IMAGE_EDGE
        or height > MAX_IMAGE_EDGE
        or width * height > MAX_IMAGE_PIXELS
    ):
        raise _invalid_avatar()


def _transcode(data: bytes, declared_type: str) -> tuple[bytes, int, int]:
    expected_format = _SUPPORTED_TYPES.get(declared_type)
    if expected_format is None:
        raise APIError(415, "AVATAR_TYPE_UNSUPPORTED", "仅支持 JPEG、PNG 或 WebP 头像")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as probe:
                if probe.format != expected_format or not _has_exact_container(data, expected_format):
                    raise _invalid_avatar()
                _validate_dimensions(probe)
                if getattr(probe, "is_animated", False) or getattr(probe, "n_frames", 1) != 1:
                    raise _invalid_avatar()
                probe.verify()

            with Image.open(BytesIO(data)) as decoded:
                if decoded.format != expected_format:
                    raise _invalid_avatar()
                _validate_dimensions(decoded)
                if getattr(decoded, "is_animated", False) or getattr(decoded, "n_frames", 1) != 1:
                    raise _invalid_avatar()
                decoded.load()
                oriented = ImageOps.exif_transpose(decoded)
                has_alpha = "A" in oriented.getbands() or (
                    oriented.mode == "P" and "transparency" in oriented.info
                )
                converted = oriented.convert("RGBA" if has_alpha else "RGB")
                clean = Image.new(converted.mode, converted.size)
                clean.paste(converted)
                clean.thumbnail(
                    (OUTPUT_MAX_EDGE, OUTPUT_MAX_EDGE),
                    Image.Resampling.LANCZOS,
                )
                output = BytesIO()
                clean.save(
                    output,
                    format="WEBP",
                    quality=OUTPUT_WEBP_QUALITY,
                    method=6,
                    exif=b"",
                    icc_profile=None,
                    xmp=b"",
                )
                result = output.getvalue()
                width, height = clean.size
                return result, width, height
    except APIError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        EOFError,
        OSError,
        SyntaxError,
        ValueError,
    ):
        raise _invalid_avatar() from None


def _remove_directory_entry(directory_fd: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=directory_fd)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    except OSError:
        pass


def store_avatar(
    db: Session,
    upload: UploadFile,
    *,
    media_root: Path,
    now: datetime,
) -> models.AvatarMedia:
    """Validate, transcode, durably store, and record one avatar."""

    declared_type = upload.content_type or ""
    if declared_type not in _SUPPORTED_TYPES:
        raise APIError(415, "AVATAR_TYPE_UNSUPPORTED", "仅支持 JPEG、PNG 或 WebP 头像")
    raw = _read_bounded(upload.file)
    encoded, width, height = _transcode(raw, declared_type)
    root = _safe_media_root(Path(media_root), create=True)

    media_id = str(uuid4())
    while db.get(models.AvatarMedia, media_id) is not None or (root / f"{media_id}.webp").exists():
        media_id = str(uuid4())
    file_name = f"{media_id}.webp"
    directory_fd: int | None = None
    temporary_name: str | None = None
    file_installed = False
    try:
        directory_fd = _open_directory(root)
        temporary_name = f".avatar-{uuid4()}.tmp"
        file_descriptor = os.open(
            temporary_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
        with os.fdopen(file_descriptor, "wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(
            temporary_name,
            file_name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temporary_name = None
        file_installed = True
        os.fsync(directory_fd)

        row = models.AvatarMedia(
            id=media_id,
            file_name=file_name,
            mime_type="image/webp",
            width=width,
            height=height,
            size_bytes=len(encoded),
            sha256=sha256(encoded).hexdigest(),
            created_at=now.astimezone(UTC).replace(tzinfo=None),
        )
        db.add(row)
        db.commit()
        return row
    except APIError:
        db.rollback()
        if directory_fd is not None and file_installed:
            _remove_directory_entry(directory_fd, file_name)
        if directory_fd is not None and temporary_name is not None:
            _remove_directory_entry(directory_fd, temporary_name)
        raise
    except Exception:
        db.rollback()
        if directory_fd is not None and file_installed:
            _remove_directory_entry(directory_fd, file_name)
        if directory_fd is not None and temporary_name is not None:
            _remove_directory_entry(directory_fd, temporary_name)
        raise _storage_unavailable() from None
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


def _canonical_media_id(media_id: str | UUID) -> str:
    try:
        parsed = UUID(str(media_id))
    except (ValueError, TypeError, AttributeError):
        raise _not_found() from None
    canonical = str(parsed)
    if str(media_id) != canonical:
        raise _not_found()
    return canonical


def load_avatar(
    db: Session,
    media_id: str | UUID,
    *,
    media_root: Path,
) -> AvatarBlob:
    """Load a row-backed regular file without following links or escaping root."""

    canonical_id = _canonical_media_id(media_id)
    row = db.get(models.AvatarMedia, canonical_id)
    if row is None or row.file_name != f"{canonical_id}.webp":
        raise _not_found()
    if (
        row.mime_type != "image/webp"
        or row.size_bytes <= 0
        or row.size_bytes > MAX_UPLOAD_BYTES
        or len(row.sha256) != 64
    ):
        raise _not_found()

    try:
        root = _safe_media_root(Path(media_root), create=False)
    except APIError:
        raise _not_found() from None
    directory_fd: int | None = None
    try:
        directory_fd = _open_directory(root)
        path_stat = os.stat(
            row.file_name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if not stat.S_ISREG(path_stat.st_mode):
            raise _not_found()
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(row.file_name, flags, dir_fd=directory_fd)
        try:
            opened_stat = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or (opened_stat.st_dev, opened_stat.st_ino)
                != (path_stat.st_dev, path_stat.st_ino)
            ):
                raise _not_found()
            with os.fdopen(descriptor, "rb", closefd=False) as source:
                content = source.read(row.size_bytes + 1)
        finally:
            os.close(descriptor)
    except APIError:
        raise _not_found() from None
    except (FileNotFoundError, OSError, ValueError):
        raise _not_found() from None
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
    if len(content) != row.size_bytes or sha256(content).hexdigest() != row.sha256:
        raise _not_found()
    return AvatarBlob(media=row, content=content)


def validate_avatar_reference(
    db: Session,
    avatar: str | None,
    *,
    media_root: Path,
) -> None:
    """Require a canonical row-backed file before a resource mutation."""

    if avatar is None:
        return
    if not avatar.startswith(_AVATAR_URL_PREFIX):
        raise APIError(
            422,
            "VALIDATION_ERROR",
            "请求字段校验失败",
            {"body.avatar": ["头像文件不存在或不可用"]},
        )
    media_id = avatar.removeprefix(_AVATAR_URL_PREFIX)
    try:
        load_avatar(db, media_id, media_root=media_root)
    except APIError:
        raise APIError(
            422,
            "VALIDATION_ERROR",
            "请求字段校验失败",
            {"body.avatar": ["头像文件不存在或不可用"]},
        ) from None
