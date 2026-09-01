"""Safe avatar upload, storage, retrieval, and resource-reference contracts."""
from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import shutil
from uuid import UUID

import pytest
from PIL import Image, PngImagePlugin
from sqlalchemy import func, select
from starlette.datastructures import Headers, UploadFile

from app.backend import models
from app.backend.api_errors import APIError
from app.backend.database import SETTINGS


MEDIA_ROOT = SETTINGS.media_root
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
CAPTURED_NOW = datetime(2026, 9, 2, 3, 4, 5, tzinfo=UTC)


def _remove_media_root() -> None:
    try:
        if MEDIA_ROOT.is_symlink():
            MEDIA_ROOT.unlink()
        elif MEDIA_ROOT.exists():
            shutil.rmtree(MEDIA_ROOT)
    except FileNotFoundError:
        pass


@pytest.fixture(autouse=True)
def isolated_media_root():
    _remove_media_root()
    yield
    _remove_media_root()


def _unlock(client) -> None:
    assert client.post("/api/auth/setup", json={"pin": "1234"}).status_code == 200


def _image_bytes(
    image_format: str,
    *,
    size: tuple[int, int] = (80, 48),
    color=(220, 40, 80),
    exif_orientation: int | None = None,
    png_text: bool = False,
) -> bytes:
    image = Image.new("RGB", size, color)
    output = BytesIO()
    kwargs: dict[str, object] = {}
    if exif_orientation is not None:
        exif = Image.Exif()
        exif[274] = exif_orientation
        kwargs["exif"] = exif
    if png_text:
        info = PngImagePlugin.PngInfo()
        info.add_text("private-note", "must be stripped")
        kwargs["pnginfo"] = info
    image.save(output, format=image_format, **kwargs)
    return output.getvalue()


def _animated_webp() -> bytes:
    first = Image.new("RGB", (32, 24), (255, 0, 0))
    second = Image.new("RGB", (32, 24), (0, 0, 255))
    output = BytesIO()
    first.save(
        output,
        format="WEBP",
        save_all=True,
        append_images=[second],
        duration=[50, 50],
        loop=0,
    )
    return output.getvalue()


def _upload(client, data: bytes, content_type: str, filename: str = "avatar.png"):
    return client.post(
        "/api/media/avatars",
        files={"file": (filename, data, content_type)},
    )


def _assert_error(response, *, status: int, code: str) -> None:
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


def _stored_rows(db_session) -> list[models.AvatarMedia]:
    db_session.expire_all()
    return list(db_session.scalars(select(models.AvatarMedia).order_by(models.AvatarMedia.id)))


def _stored_files() -> list[Path]:
    if not MEDIA_ROOT.exists() or MEDIA_ROOT.is_symlink():
        return []
    return sorted(item for item in MEDIA_ROOT.iterdir())


def _direct_upload(data: bytes, content_type: str, filename: str = "avatar.png") -> UploadFile:
    return UploadFile(
        BytesIO(data),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


def _insert_media(
    db_session,
    *,
    media_id: str,
    file_name: str,
    data: bytes,
) -> models.AvatarMedia:
    row = models.AvatarMedia(
        id=media_id,
        file_name=file_name,
        mime_type="image/webp",
        width=12,
        height=8,
        size_bytes=len(data),
        sha256=sha256(data).hexdigest(),
        created_at=CAPTURED_NOW,
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_upload_authentication_precedes_multipart_parsing_content_length_and_writes(
    client,
    db_session,
) -> None:
    response = client.post(
        "/api/media/avatars",
        content=b"this is deliberately not a multipart body",
        headers={
            "Content-Type": "multipart/form-data; boundary=broken",
            "Content-Length": str(MAX_UPLOAD_BYTES + 999_999),
            "X-Request-ID": "avatar-auth-before-body",
        },
    )

    _assert_error(response, status=401, code="TEACHER_AUTH_REQUIRED")
    assert response.headers["x-request-id"] == "avatar-auth-before-body"
    assert _stored_rows(db_session) == []
    assert not MEDIA_ROOT.exists()


@pytest.mark.parametrize(
    ("image_format", "content_type", "filename"),
    [
        pytest.param("PNG", "image/png", "avatar.png", id="png"),
        pytest.param("JPEG", "image/jpeg", "avatar.jpg", id="jpeg"),
        pytest.param("WEBP", "image/webp", "avatar.webp", id="webp"),
    ],
)
def test_valid_uploads_have_exact_dto_uuid_metadata_and_static_webp(
    client,
    db_session,
    image_format,
    content_type,
    filename,
) -> None:
    _unlock(client)
    response = _upload(client, _image_bytes(image_format), content_type, filename)

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"id", "url", "mime_type", "width", "height", "size_bytes", "sha256"}
    media_id = UUID(payload["id"])
    assert str(media_id) == payload["id"]
    assert payload["url"] == f"/api/media/avatars/{media_id}"
    assert payload["mime_type"] == "image/webp"
    assert (payload["width"], payload["height"]) == (80, 48)

    rows = _stored_rows(db_session)
    assert len(rows) == 1
    row = rows[0]
    assert row.id == str(media_id)
    assert row.file_name == f"{media_id}.webp"
    stored = MEDIA_ROOT / row.file_name
    assert _stored_files() == [stored]
    data = stored.read_bytes()
    assert payload["size_bytes"] == row.size_bytes == len(data)
    assert payload["sha256"] == row.sha256 == sha256(data).hexdigest()
    with Image.open(BytesIO(data)) as decoded:
        assert decoded.format == "WEBP"
        assert decoded.n_frames == 1
        assert decoded.size == (80, 48)


def test_processing_applies_exif_orientation_resizes_and_strips_metadata(client, db_session) -> None:
    _unlock(client)
    oriented = _upload(
        client,
        _image_bytes("JPEG", size=(120, 60), exif_orientation=6),
        "image/jpeg",
        "oriented.jpg",
    )
    large = _upload(
        client,
        _image_bytes("PNG", size=(2048, 1024), png_text=True),
        "image/png",
        "large.png",
    )

    assert oriented.status_code == 200
    assert (oriented.json()["width"], oriented.json()["height"]) == (60, 120)
    assert large.status_code == 200
    assert (large.json()["width"], large.json()["height"]) == (1024, 512)
    for row in _stored_rows(db_session):
        with Image.open(MEDIA_ROOT / row.file_name) as decoded:
            decoded.load()
            assert decoded.format == "WEBP"
            assert decoded.n_frames == 1
            assert "exif" not in decoded.info
            assert "icc_profile" not in decoded.info
            assert "xmp" not in decoded.info
            assert decoded.getexif() == {}


@pytest.mark.parametrize(
    ("data", "content_type", "filename", "status", "code"),
    [
        pytest.param(b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml", "x.svg", 415, "AVATAR_TYPE_UNSUPPORTED", id="svg"),
        pytest.param(_image_bytes("GIF"), "image/gif", "x.gif", 415, "AVATAR_TYPE_UNSUPPORTED", id="gif"),
        pytest.param(_animated_webp(), "image/webp", "animated.webp", 422, "AVATAR_INVALID", id="animated-webp"),
        pytest.param(b"not an image", "image/png", "broken.png", 422, "AVATAR_INVALID", id="malformed"),
        pytest.param(_image_bytes("PNG"), "image/jpeg", "mismatch.jpg", 422, "AVATAR_INVALID", id="declared-mismatch"),
        pytest.param(_image_bytes("PNG") + b"<script>alert(1)</script>", "image/png", "polyglot.png", 422, "AVATAR_INVALID", id="polyglot"),
    ],
)
def test_unsafe_or_malformed_uploads_are_rejected_without_rows_or_files(
    client,
    db_session,
    data,
    content_type,
    filename,
    status,
    code,
) -> None:
    _unlock(client)

    response = _upload(client, data, content_type, filename)

    _assert_error(response, status=status, code=code)
    assert _stored_rows(db_session) == []
    assert _stored_files() == []


def test_dimension_and_stream_size_limits_fail_before_storage(client, db_session) -> None:
    _unlock(client)
    too_wide = _upload(
        client,
        _image_bytes("PNG", size=(4097, 1)),
        "image/png",
        "wide.png",
    )
    stream_oversize = _upload(
        client,
        b"x" * (MAX_UPLOAD_BYTES + 1),
        "image/png",
        "oversize.png",
    )

    _assert_error(too_wide, status=422, code="AVATAR_INVALID")
    _assert_error(stream_oversize, status=413, code="AVATAR_TOO_LARGE")
    assert _stored_rows(db_session) == []
    assert _stored_files() == []


def test_authenticated_oversize_content_length_is_rejected_before_multipart_parsing(
    client,
    db_session,
) -> None:
    _unlock(client)
    response = client.post(
        "/api/media/avatars",
        content=b"not multipart",
        headers={
            "Content-Type": "multipart/form-data; boundary=broken",
            "Content-Length": str(MAX_UPLOAD_BYTES + 999_999),
        },
    )

    _assert_error(response, status=413, code="AVATAR_TOO_LARGE")
    assert _stored_rows(db_session) == []
    assert not MEDIA_ROOT.exists()


def test_store_fsyncs_file_and_directory_and_cleans_up_atomic_replace_failure(
    db_session,
    monkeypatch,
) -> None:
    from app.backend.services import avatar_media

    calls: list[int] = []
    original_fsync = avatar_media.os.fsync

    def recording_fsync(fd: int) -> None:
        calls.append(fd)
        original_fsync(fd)

    monkeypatch.setattr(avatar_media.os, "fsync", recording_fsync)
    stored = avatar_media.store_avatar(
        db_session,
        _direct_upload(_image_bytes("PNG"), "image/png"),
        media_root=MEDIA_ROOT,
        now=CAPTURED_NOW,
    )
    assert stored.mime_type == "image/webp"
    assert len(calls) >= 2
    assert len(_stored_rows(db_session)) == 1
    assert len(_stored_files()) == 1

    db_session.query(models.AvatarMedia).delete()
    db_session.commit()
    _remove_media_root()

    def fail_replace(_source, _destination) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(avatar_media.os, "replace", fail_replace)
    with pytest.raises(APIError) as error:
        avatar_media.store_avatar(
            db_session,
            _direct_upload(_image_bytes("PNG"), "image/png"),
            media_root=MEDIA_ROOT,
            now=CAPTURED_NOW,
        )
    assert error.value.code == "AVATAR_STORAGE_UNAVAILABLE"
    assert _stored_rows(db_session) == []
    assert _stored_files() == []


def test_store_compensates_the_final_file_when_database_commit_fails(db_session, monkeypatch) -> None:
    from app.backend.services import avatar_media

    def fail_commit() -> None:
        raise OSError("synthetic database failure")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(APIError) as error:
        avatar_media.store_avatar(
            db_session,
            _direct_upload(_image_bytes("PNG"), "image/png"),
            media_root=MEDIA_ROOT,
            now=CAPTURED_NOW,
        )
    assert error.value.code == "AVATAR_STORAGE_UNAVAILABLE"
    assert list(db_session.new) == []
    assert _stored_files() == []


def test_public_get_is_exact_webp_with_cache_nosniff_etag_and_no_auth(client) -> None:
    _unlock(client)
    uploaded = _upload(client, _image_bytes("PNG"), "image/png")
    assert uploaded.status_code == 200
    payload = uploaded.json()
    assert client.post("/api/auth/lock").status_code == 200

    response = client.get(payload["url"])

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["etag"] == f'"{payload["sha256"]}"'
    assert int(response.headers["content-length"]) == payload["size_bytes"] == len(response.content)
    with Image.open(BytesIO(response.content)) as decoded:
        assert decoded.format == "WEBP"
        assert decoded.n_frames == 1


def test_missing_row_missing_file_symlink_and_path_escape_fail_closed(
    client,
    db_session,
    tmp_path,
) -> None:
    missing_id = "11111111-1111-4111-8111-111111111111"
    _assert_error(
        client.get(f"/api/media/avatars/{missing_id}"),
        status=404,
        code="AVATAR_NOT_FOUND",
    )

    data = _image_bytes("WEBP")
    MEDIA_ROOT.mkdir(parents=True)
    missing_file_id = "22222222-2222-4222-8222-222222222222"
    _insert_media(
        db_session,
        media_id=missing_file_id,
        file_name=f"{missing_file_id}.webp",
        data=data,
    )
    _assert_error(
        client.get(f"/api/media/avatars/{missing_file_id}"),
        status=404,
        code="AVATAR_NOT_FOUND",
    )

    symlink_id = "33333333-3333-4333-8333-333333333333"
    outside = tmp_path / "outside.webp"
    outside.write_bytes(data)
    (MEDIA_ROOT / f"{symlink_id}.webp").symlink_to(outside)
    _insert_media(
        db_session,
        media_id=symlink_id,
        file_name=f"{symlink_id}.webp",
        data=data,
    )
    symlink_response = client.get(f"/api/media/avatars/{symlink_id}")
    _assert_error(symlink_response, status=404, code="AVATAR_NOT_FOUND")
    assert symlink_response.content != data

    escape_id = "44444444-4444-4444-8444-444444444444"
    escaped = MEDIA_ROOT.parent / "escape.webp"
    escaped.write_bytes(data)
    _insert_media(
        db_session,
        media_id=escape_id,
        file_name="../escape.webp",
        data=data,
    )
    escape_response = client.get(f"/api/media/avatars/{escape_id}")
    _assert_error(escape_response, status=404, code="AVATAR_NOT_FOUND")
    assert escape_response.content != data


def test_symlink_media_root_is_rejected_for_reads_and_writes(
    client,
    db_session,
    tmp_path,
) -> None:
    target = tmp_path / "media-target"
    target.mkdir()
    MEDIA_ROOT.parent.mkdir(parents=True, exist_ok=True)
    MEDIA_ROOT.symlink_to(target, target_is_directory=True)
    _unlock(client)

    upload = _upload(client, _image_bytes("PNG"), "image/png")

    _assert_error(upload, status=500, code="AVATAR_STORAGE_UNAVAILABLE")
    assert _stored_rows(db_session) == []
    assert list(target.iterdir()) == []


def test_resource_avatar_reference_requires_safe_row_and_file_before_any_write(
    client,
    db_session,
) -> None:
    _unlock(client)
    missing_url = "/api/media/avatars/55555555-5555-4555-8555-555555555555"

    response = client.post(
        "/api/children",
        json={"name": "不应保存", "nickname": None, "avatar": missing_url},
    )

    _assert_error(response, status=422, code="VALIDATION_ERROR")
    assert response.json()["error"]["field_errors"] == {
        "body.avatar": ["头像文件不存在或不可用"]
    }
    assert db_session.scalar(select(func.count(models.Child.id))) == 0

    missing_file_id = "77777777-7777-4777-8777-777777777777"
    _insert_media(
        db_session,
        media_id=missing_file_id,
        file_name=f"{missing_file_id}.webp",
        data=_image_bytes("WEBP"),
    )
    missing_file = client.post(
        "/api/ducks",
        json={
            "name": "也不应保存",
            "avatar": f"/api/media/avatars/{missing_file_id}",
            "status": "不应保存",
            "note": None,
        },
    )
    _assert_error(missing_file, status=422, code="VALIDATION_ERROR")
    assert missing_file.json()["error"]["field_errors"] == {
        "body.avatar": ["头像文件不存在或不可用"]
    }
    assert db_session.scalar(select(func.count(models.Duck.id))) == 0


def test_valid_reference_replacement_and_null_removal_never_delete_old_media(
    client,
    db_session,
) -> None:
    _unlock(client)
    first = _upload(client, _image_bytes("PNG", color=(200, 10, 10)), "image/png").json()
    second = _upload(client, _image_bytes("JPEG", color=(10, 10, 200)), "image/jpeg").json()

    created = client.post(
        "/api/children",
        json={"name": "小雨", "nickname": "雨雨", "avatar": first["url"]},
    )
    assert created.status_code == 200
    child_id = created.json()["id"]
    replaced = client.put(
        f"/api/children/{child_id}",
        json={"name": "小雨", "nickname": "雨雨", "avatar": second["url"]},
    )
    assert replaced.status_code == 200
    assert replaced.json()["avatar"] == second["url"]
    removed = client.put(
        f"/api/children/{child_id}",
        json={"name": "小雨", "nickname": "雨雨", "avatar": None},
    )
    assert removed.status_code == 200
    assert removed.json()["avatar"] is None

    assert client.get(first["url"]).status_code == 200
    assert client.get(second["url"]).status_code == 200
    assert len(_stored_rows(db_session)) == 2
    assert len(_stored_files()) == 2


def test_invalid_replacement_preserves_every_existing_resource_field(client, db_session) -> None:
    _unlock(client)
    uploaded = _upload(client, _image_bytes("PNG"), "image/png").json()
    created = client.post(
        "/api/ducks",
        json={
            "name": "小黄",
            "avatar": uploaded["url"],
            "status": "健康",
            "note": "原笔记",
        },
    )
    duck_id = created.json()["id"]
    db_session.expire_all()
    before = db_session.get(models.Duck, duck_id)
    before_values = (before.name, before.avatar, before.status, before.note, before.active)
    db_session.rollback()

    invalid = client.put(
        f"/api/ducks/{duck_id}",
        json={
            "name": "不应写入",
            "avatar": "/api/media/avatars/66666666-6666-4666-8666-666666666666",
            "status": None,
            "note": None,
        },
    )

    _assert_error(invalid, status=422, code="VALIDATION_ERROR")
    db_session.expire_all()
    after = db_session.get(models.Duck, duck_id)
    assert (after.name, after.avatar, after.status, after.note, after.active) == before_values
