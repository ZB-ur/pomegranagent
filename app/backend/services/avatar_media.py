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
from sqlalchemy.exc import IntegrityError
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


def _root_error(*, create: bool) -> APIError:
    return _storage_unavailable() if create else _not_found()


def _open_media_root_fd(media_root: Path, *, create: bool) -> int:
    """Walk from a trusted slash fd so parent swaps cannot redirect the root."""

    root = _absolute_without_symlink_resolution(Path(media_root))
    parts = root.parts
    if not root.is_absolute() or len(parts) < 2 or parts[0] != "/":
        raise _root_error(create=create)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor: int | None = None
    try:
        descriptor = os.open("/", flags)
        for component in parts[1:]:
            if component in {"", ".", ".."}:
                raise _root_error(create=create)
            child: int | None = None
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise _not_found() from None
                try:
                    os.mkdir(component, mode=0o700, dir_fd=descriptor)
                    os.fsync(descriptor)
                except FileExistsError:
                    pass
                child = os.open(component, flags, dir_fd=descriptor)
            try:
                child_stat = os.fstat(child)
                if not stat.S_ISDIR(child_stat.st_mode):
                    raise _root_error(create=create)
            except Exception:
                os.close(child)
                raise
            os.close(descriptor)
            descriptor = child
        return descriptor
    except APIError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except (FileNotFoundError, NotADirectoryError, OSError, ValueError):
        if descriptor is not None:
            os.close(descriptor)
        raise _root_error(create=create) from None


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


def _png_has_exact_end(data: bytes) -> bool:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    offset = 8
    while offset < len(data):
        if len(data) - offset < 12:
            return False
        length = int.from_bytes(data[offset:offset + 4], "big")
        end = offset + 12 + length
        if end > len(data):
            return False
        kind = data[offset + 4:offset + 8]
        if kind == b"IEND":
            return (
                length == 0
                and data[offset:end] == b"\x00\x00\x00\x00IEND\xaeB`\x82"
                and end == len(data)
            )
        offset = end
    return False


def _jpeg_has_exact_end(data: bytes) -> bool:
    if not data.startswith(b"\xff\xd8"):
        return False
    offset = 2
    in_scan = False
    while offset < len(data):
        if in_scan:
            marker = data.find(b"\xff", offset)
            if marker < 0:
                return False
            offset = marker + 1
        else:
            if data[offset] != 0xFF:
                return False
            offset += 1
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            return False
        code = data[offset]
        offset += 1
        if in_scan and code == 0x00:
            continue
        if in_scan and 0xD0 <= code <= 0xD7:
            continue
        in_scan = False
        if code == 0xD9:
            return offset == len(data)
        if code == 0xD8 or code == 0x00:
            return False
        if code == 0x01 or 0xD0 <= code <= 0xD7:
            continue
        if len(data) - offset < 2:
            return False
        length = int.from_bytes(data[offset:offset + 2], "big")
        if length < 2 or offset + length > len(data):
            return False
        offset += length
        if code == 0xDA:
            in_scan = True
    return False


def _has_exact_container(data: bytes, image_format: str) -> bool:
    if image_format == "PNG":
        return _png_has_exact_end(data)
    if image_format == "JPEG":
        return _jpeg_has_exact_end(data)
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


def _inode_identity(file_stat: os.stat_result) -> tuple[int, int]:
    return file_stat.st_dev, file_stat.st_ino


def _remove_owned_entry(
    directory_fd: int,
    name: str,
    identity: tuple[int, int] | None,
) -> None:
    if identity is None:
        return
    try:
        current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if _inode_identity(current) != identity:
            return
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
    directory_fd: int | None = None
    media_id: str | None = None
    file_name: str | None = None
    final_identity: tuple[int, int] | None = None
    temporary_name: str | None = None
    temporary_identity: tuple[int, int] | None = None
    row: models.AvatarMedia | None = None
    try:
        directory_fd = _open_media_root_fd(Path(media_root), create=True)
        for _attempt in range(128):
            candidate_id = str(uuid4())
            candidate_name = f"{candidate_id}.webp"
            try:
                reservation_fd = os.open(
                    candidate_name,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_CLOEXEC", 0),
                    0o600,
                    dir_fd=directory_fd,
                )
            except FileExistsError:
                continue
            try:
                reservation_stat = os.fstat(reservation_fd)
                if not stat.S_ISREG(reservation_stat.st_mode):
                    raise _storage_unavailable()
                reserved_identity = _inode_identity(reservation_stat)
            finally:
                os.close(reservation_fd)
            file_name = candidate_name
            final_identity = reserved_identity

            candidate_row = models.AvatarMedia(
                id=candidate_id,
                file_name=candidate_name,
                mime_type="image/webp",
                width=width,
                height=height,
                size_bytes=len(encoded),
                sha256=sha256(encoded).hexdigest(),
                created_at=now.astimezone(UTC).replace(tzinfo=None),
            )
            db.add(candidate_row)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                _remove_owned_entry(directory_fd, candidate_name, reserved_identity)
                file_name = None
                final_identity = None
                continue
            media_id = candidate_id
            row = candidate_row
            break
        if media_id is None or file_name is None or row is None:
            raise _storage_unavailable()

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
        temporary_identity = _inode_identity(os.fstat(file_descriptor))
        with os.fdopen(file_descriptor, "wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        reservation_stat = os.stat(
            file_name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if _inode_identity(reservation_stat) != final_identity:
            raise _storage_unavailable()
        os.replace(
            temporary_name,
            file_name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temporary_name = None
        final_identity = temporary_identity
        installed_stat = os.stat(
            file_name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(installed_stat.st_mode)
            or installed_stat.st_nlink != 1
            or _inode_identity(installed_stat) != final_identity
        ):
            raise _storage_unavailable()
        os.fsync(directory_fd)
        db.commit()
        return row
    except APIError:
        db.rollback()
        if directory_fd is not None and file_name is not None:
            _remove_owned_entry(directory_fd, file_name, final_identity)
        if directory_fd is not None and temporary_name is not None:
            _remove_owned_entry(directory_fd, temporary_name, temporary_identity)
        raise
    except Exception:
        db.rollback()
        if directory_fd is not None and file_name is not None:
            _remove_owned_entry(directory_fd, file_name, final_identity)
        if directory_fd is not None and temporary_name is not None:
            _remove_owned_entry(directory_fd, temporary_name, temporary_identity)
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


def _validate_stored_webp(content: bytes, row: models.AvatarMedia) -> None:
    try:
        if not _has_exact_container(content, "WEBP"):
            raise _not_found()
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as probe:
                if (
                    probe.format != "WEBP"
                    or getattr(probe, "is_animated", False)
                    or getattr(probe, "n_frames", 1) != 1
                ):
                    raise _not_found()
                probe.verify()
            with Image.open(BytesIO(content)) as decoded:
                if (
                    decoded.format != "WEBP"
                    or getattr(decoded, "is_animated", False)
                    or getattr(decoded, "n_frames", 1) != 1
                ):
                    raise _not_found()
                decoded.load()
                width, height = decoded.size
                if (
                    width <= 0
                    or height <= 0
                    or width > OUTPUT_MAX_EDGE
                    or height > OUTPUT_MAX_EDGE
                    or (width, height) != (row.width, row.height)
                ):
                    raise _not_found()
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
        raise _not_found() from None


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
        or row.width <= 0
        or row.height <= 0
        or row.width > OUTPUT_MAX_EDGE
        or row.height > OUTPUT_MAX_EDGE
        or len(row.sha256) != 64
        or any(character not in "0123456789abcdef" for character in row.sha256)
    ):
        raise _not_found()

    try:
        directory_fd = _open_media_root_fd(Path(media_root), create=False)
    except APIError:
        raise _not_found() from None
    try:
        path_stat = os.stat(
            row.file_name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if not stat.S_ISREG(path_stat.st_mode) or path_stat.st_nlink != 1:
            raise _not_found()
        flags = (
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        descriptor = os.open(row.file_name, flags, dir_fd=directory_fd)
        try:
            opened_stat = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or opened_stat.st_nlink != 1
                or (opened_stat.st_dev, opened_stat.st_ino)
                != (path_stat.st_dev, path_stat.st_ino)
            ):
                raise _not_found()
            with os.fdopen(descriptor, "rb", closefd=False) as source:
                content = source.read(row.size_bytes + 1)
            finished_stat = os.fstat(descriptor)
            if (
                finished_stat.st_nlink != 1
                or _inode_identity(finished_stat) != _inode_identity(opened_stat)
            ):
                raise _not_found()
        finally:
            os.close(descriptor)
    except APIError:
        raise _not_found() from None
    except (FileNotFoundError, OSError, ValueError):
        raise _not_found() from None
    finally:
        os.close(directory_fd)
    if len(content) != row.size_bytes or sha256(content).hexdigest() != row.sha256:
        raise _not_found()
    _validate_stored_webp(content, row)
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
