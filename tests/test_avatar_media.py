"""Safe avatar upload, storage, retrieval, and resource-reference contracts."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import stat
from threading import Event, Lock, Thread, current_thread, get_ident, local
import time
from types import SimpleNamespace
from uuid import UUID
import zlib

import pytest
from PIL import Image, PngImagePlugin
from sqlalchemy import event, func, select
from starlette.datastructures import Headers, UploadFile

from app.backend import models
from app.backend.api_errors import APIError
from app.backend.auth import COOKIE_NAME
from app.backend.database import SETTINGS, SessionLocal, engine
from app.backend.main import app


MEDIA_ROOT = SETTINGS.media_root
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
CAPTURED_NOW = datetime(2026, 9, 2, 3, 4, 5, tzinfo=UTC)
MAX_MULTIPART_BYTES = MAX_UPLOAD_BYTES + 64 * 1024


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
    from app.backend.services import avatar_media

    close_roots = getattr(avatar_media, "close_pinned_media_roots", lambda: None)
    close_roots()
    _remove_media_root()
    yield
    close_roots()
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
    progressive: bool = False,
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
        info.add_text("private-note", "IEND bytes in metadata must be stripped")
        kwargs["pnginfo"] = info
    if progressive:
        kwargs["progressive"] = True
    image.save(output, format=image_format, **kwargs)
    return output.getvalue()


def _jpeg_with_false_eoi_comment() -> bytes:
    image = Image.new("RGB", (80, 48))
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            pixels[x, y] = (
                (x * 37 + y * 17) % 256,
                (x * 19 + y * 43) % 256,
                (x * 71 + y * 11) % 256,
            )
    output = BytesIO()
    image.save(
        output,
        format="JPEG",
        quality=88,
        progressive=True,
        restart_marker_rows=1,
    )
    source = output.getvalue()
    comment = b"metadata-before-\xff\xd9-metadata-after"
    segment = b"\xff\xfe" + (len(comment) + 2).to_bytes(2, "big") + comment
    return source[:2] + segment + source[2:]


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        len(payload).to_bytes(4, "big")
        + kind
        + payload
        + zlib.crc32(kind + payload).to_bytes(4, "big")
    )


def _png_polyglot_with_second_iend() -> bytes:
    script = b"Comment\x00<script>alert(1)</script>"
    return _image_bytes("PNG") + _png_chunk(b"tEXt", script) + _png_chunk(b"IEND", b"")


def _jpeg_polyglot_with_second_eoi() -> bytes:
    script = b"<script>alert(1)</script>"
    comment = b"\xff\xfe" + (len(script) + 2).to_bytes(2, "big") + script
    return _image_bytes("JPEG") + comment + b"\xff\xd9"


def _jpeg_with_tem_in_scan() -> bytes:
    """Pillow-compatible JPEG carrying the legal stand-alone TEM scan marker."""

    source = _image_bytes("JPEG")
    assert source.endswith(b"\xff\xd9")
    return source[:-2] + b"\xff\x01\xff\xd9"


def _jpeg_marker_fixture_with_dnl_in_scan() -> bytes:
    """Minimal marker grammar fixture exercising legal DNL scan continuity."""

    return (
        b"\xff\xd8"
        b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
        b"scan-data"
        b"\xff\xdc\x00\x04\x00\x30"
        b"more-scan-data"
        b"\xff\xd9"
    )


def _jpeg_marker_fixture_with_tem_in_scan() -> bytes:
    return (
        b"\xff\xd8"
        b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
        b"scan-before-tem"
        b"\xff\x01"
        b"scan-after-tem"
        b"\xff\xd9"
    )


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
    width: int = 12,
    height: int = 8,
) -> models.AvatarMedia:
    row = models.AvatarMedia(
        id=media_id,
        file_name=file_name,
        mime_type="image/webp",
        width=width,
        height=height,
        size_bytes=len(data),
        sha256=sha256(data).hexdigest(),
        created_at=CAPTURED_NOW,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _multipart_body(*, boundary: str, file_data: bytes, epilogue: bytes = b"") -> bytes:
    return (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="avatar.png"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode("ascii") + file_data + f"\r\n--{boundary}--\r\n".encode("ascii") + epilogue


async def _asgi_post(
    *,
    chunks: list[bytes],
    headers: list[tuple[bytes, bytes]],
) -> tuple[int, dict[str, str], bytes, int, int]:
    messages: list[dict] = []
    chunk_index = 0
    receive_calls = 0
    received_bytes = 0

    async def receive() -> dict:
        nonlocal chunk_index, receive_calls, received_bytes
        receive_calls += 1
        if chunk_index >= len(chunks):
            return {"type": "http.disconnect"}
        body = chunks[chunk_index]
        chunk_index += 1
        received_bytes += len(body)
        return {
            "type": "http.request",
            "body": body,
            "more_body": chunk_index < len(chunks),
        }

    async def send(message: dict) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/media/avatars",
        "raw_path": b"/api/media/avatars",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "state": {},
    }
    await app(scope, receive, send)
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    response_headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in start["headers"]
    }
    return start["status"], response_headers, body, receive_calls, received_bytes


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


def test_unauthenticated_asgi_request_reads_zero_body_bytes(client, db_session) -> None:
    boundary = "avatar-auth-receive-spy"
    body = _multipart_body(
        boundary=boundary,
        file_data=b"x",
        epilogue=b"z" * (MAX_MULTIPART_BYTES + 1),
    )

    status, response_headers, response_body, receive_calls, received_bytes = asyncio.run(
        _asgi_post(
            chunks=[body[:1024], body[1024:]],
            headers=[
                (b"content-type", f"multipart/form-data; boundary={boundary}".encode("ascii")),
                (b"x-request-id", b"avatar-auth-receive-spy"),
            ],
        )
    )

    assert status == 401
    assert response_headers["x-request-id"] == "avatar-auth-receive-spy"
    assert json.loads(response_body)["error"]["code"] == "TEACHER_AUTH_REQUIRED"
    assert (receive_calls, received_bytes) == (0, 0)
    assert _stored_rows(db_session) == []
    assert not MEDIA_ROOT.exists()


def test_authenticated_chunked_multipart_total_budget_stops_before_oversize_epilogue(
    client,
    db_session,
) -> None:
    _unlock(client)
    boundary = "avatar-total-stream-budget"
    repeated_part_epilogue = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="second.png"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode("ascii") + b"q" * (MAX_MULTIPART_BYTES + 256 * 1024)
    body = _multipart_body(
        boundary=boundary,
        file_data=b"x",
        epilogue=repeated_part_epilogue,
    )
    chunks = [body[index:index + 16 * 1024] for index in range(0, len(body), 16 * 1024)]
    cookie = f"{COOKIE_NAME}={client.cookies.get(COOKIE_NAME)}".encode("ascii")

    status, _headers, response_body, receive_calls, received_bytes = asyncio.run(
        _asgi_post(
            chunks=chunks,
            headers=[
                (b"content-type", f"multipart/form-data; boundary={boundary}".encode("ascii")),
                (b"cookie", cookie),
                (b"x-request-id", b"avatar-total-stream-budget"),
            ],
        )
    )

    assert status == 413
    assert json.loads(response_body)["error"]["code"] == "AVATAR_TOO_LARGE"
    assert receive_calls < len(chunks)
    assert MAX_MULTIPART_BYTES < received_bytes < len(body)
    assert _stored_rows(db_session) == []
    assert not MEDIA_ROOT.exists()


def test_authenticated_chunked_oversize_preamble_hits_total_budget_and_stops_receive(
    client,
    db_session,
) -> None:
    _unlock(client)
    boundary = "avatar-total-preamble-budget"
    body = (b"\r\n" * ((MAX_MULTIPART_BYTES // 2) + 128 * 1024)) + _multipart_body(
        boundary=boundary,
        file_data=b"x",
    )
    chunks = [body[index:index + 16 * 1024] for index in range(0, len(body), 16 * 1024)]
    cookie = f"{COOKIE_NAME}={client.cookies.get(COOKIE_NAME)}".encode("ascii")

    status, _headers, response_body, receive_calls, received_bytes = asyncio.run(
        _asgi_post(
            chunks=chunks,
            headers=[
                (b"content-type", f"multipart/form-data; boundary={boundary}".encode("ascii")),
                (b"cookie", cookie),
                (b"x-request-id", b"avatar-total-preamble-budget"),
            ],
        )
    )

    assert status == 413
    assert json.loads(response_body)["error"]["code"] == "AVATAR_TOO_LARGE"
    assert receive_calls < len(chunks)
    assert MAX_MULTIPART_BYTES < received_bytes < len(body)
    assert _stored_rows(db_session) == []
    assert not MEDIA_ROOT.exists()


def test_authenticated_repeated_file_parts_stop_before_receiving_second_payload(
    client,
    db_session,
) -> None:
    _unlock(client)
    boundary = "avatar-repeated-parts"
    part_header = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="avatar.png"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode("ascii")
    body = (
        part_header
        + b"x"
        + f"\r\n--{boundary}\r\n".encode("ascii")
        + part_header.split(b"\r\n", 1)[1]
        + (b"q" * MAX_MULTIPART_BYTES)
        + f"\r\n--{boundary}--\r\n".encode("ascii")
    )
    chunks = [body[index:index + 256] for index in range(0, len(body), 256)]
    cookie = f"{COOKIE_NAME}={client.cookies.get(COOKIE_NAME)}".encode("ascii")

    status, _headers, response_body, receive_calls, received_bytes = asyncio.run(
        _asgi_post(
            chunks=chunks,
            headers=[
                (b"content-type", f"multipart/form-data; boundary={boundary}".encode("ascii")),
                (b"cookie", cookie),
                (b"x-request-id", b"avatar-repeated-parts"),
            ],
        )
    )

    assert status == 422
    assert json.loads(response_body)["error"]["code"] == "AVATAR_INVALID"
    assert receive_calls < len(chunks)
    assert received_bytes < MAX_MULTIPART_BYTES
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
        pytest.param(
            _png_polyglot_with_second_iend(),
            "image/png",
            "polyglot-second-iend.png",
            422,
            "AVATAR_INVALID",
            id="png-polyglot-second-terminator",
        ),
        pytest.param(
            _jpeg_polyglot_with_second_eoi(),
            "image/jpeg",
            "polyglot-second-eoi.jpg",
            422,
            "AVATAR_INVALID",
            id="jpeg-polyglot-second-terminator",
        ),
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


def test_valid_progressive_jpeg_with_false_eoi_inside_comment_is_accepted(client) -> None:
    _unlock(client)
    data = _jpeg_with_false_eoi_comment()
    assert data.count(b"\xff\xda") > 1
    assert b"\xff\x00" in data
    assert any(bytes((0xFF, marker)) in data for marker in range(0xD0, 0xD8))

    response = _upload(
        client,
        data,
        "image/jpeg",
        "commented-progressive.jpg",
    )

    assert response.status_code == 200
    assert response.json()["mime_type"] == "image/webp"


def test_legal_tem_and_dnl_markers_keep_jpeg_scan_state(client) -> None:
    from app.backend.services import avatar_media

    _unlock(client)
    tem = _jpeg_with_tem_in_scan()
    with Image.open(BytesIO(tem)) as decoded:
        decoded.load()
        assert decoded.format == "JPEG"

    response = _upload(client, tem, "image/jpeg", "tem-in-scan.jpg")

    assert response.status_code == 200
    assert response.json()["mime_type"] == "image/webp"
    assert avatar_media._jpeg_has_exact_end(_jpeg_marker_fixture_with_tem_in_scan()) is True
    assert avatar_media._jpeg_has_exact_end(_jpeg_marker_fixture_with_dnl_in_scan()) is True


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


def test_authenticated_upload_runs_sync_image_file_and_database_work_off_event_loop(
    client,
    monkeypatch,
) -> None:
    from app.backend.routes import media as media_routes

    observed_running_loop: list[bool] = []

    def fake_store_avatar(*_args, **_kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            observed_running_loop.append(False)
        else:
            observed_running_loop.append(True)
        return SimpleNamespace(
            id="11111111-1111-4111-8111-111111111111",
            mime_type="image/webp",
            width=8,
            height=8,
            size_bytes=32,
            sha256="ab" * 32,
        )

    monkeypatch.setattr(media_routes, "store_avatar", fake_store_avatar)
    _unlock(client)

    response = _upload(client, _image_bytes("PNG"), "image/png")

    assert response.status_code == 200
    assert observed_running_loop == [False]


def test_upload_materializes_expired_orm_response_inside_worker_thread(
    client,
    monkeypatch,
) -> None:
    from app.backend.routes import media as media_routes

    worker_threads: list[int] = []
    avatar_sql_threads: list[int] = []
    original_store = media_routes.store_avatar

    def recording_store(*args, **kwargs):
        worker_threads.append(get_ident())
        return original_store(*args, **kwargs)

    def record_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "avatar_media" in statement.lower():
            avatar_sql_threads.append(get_ident())

    monkeypatch.setattr(media_routes, "store_avatar", recording_store)
    event.listen(engine, "before_cursor_execute", record_sql)
    try:
        _unlock(client)
        response = _upload(client, _image_bytes("PNG"), "image/png")
    finally:
        event.remove(engine, "before_cursor_execute", record_sql)

    assert response.status_code == 200
    assert len(worker_threads) == 1
    assert avatar_sql_threads
    assert set(avatar_sql_threads) == set(worker_threads)


def test_store_fsyncs_file_and_directory_and_cleans_up_atomic_link_failure(
    db_session,
    monkeypatch,
) -> None:
    from app.backend.services import avatar_media

    calls: list[str] = []
    original_fsync = avatar_media.os.fsync

    def recording_fsync(fd: int) -> None:
        mode = os.fstat(fd).st_mode
        calls.append("directory" if stat.S_ISDIR(mode) else "file")
        original_fsync(fd)

    monkeypatch.setattr(avatar_media.os, "fsync", recording_fsync)
    stored = avatar_media.store_avatar(
        db_session,
        _direct_upload(_image_bytes("PNG"), "image/png"),
        media_root=MEDIA_ROOT,
        now=CAPTURED_NOW,
    )
    assert stored.mime_type == "image/webp"
    assert "file" in calls
    assert "directory" in calls
    assert len(_stored_rows(db_session)) == 1
    assert len(_stored_files()) == 1

    db_session.query(models.AvatarMedia).delete()
    db_session.commit()
    avatar_media.close_pinned_media_roots()
    _remove_media_root()

    def fail_link(
        _source,
        _destination,
        *,
        src_dir_fd=None,
        dst_dir_fd=None,
        follow_symlinks=True,
    ) -> None:
        del src_dir_fd, dst_dir_fd, follow_symlinks
        raise OSError("synthetic link failure")

    monkeypatch.setattr(avatar_media.os, "link", fail_link)
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


def test_atomic_publish_never_overwrites_boundary_attacker_and_retries_uuid(
    db_session,
    monkeypatch,
) -> None:
    from app.backend.services import avatar_media

    fixed = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    queued = iter(
        [
            fixed,
            UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"),
            UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1"),
            UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2"),
        ]
    )
    original_uuid4 = avatar_media.uuid4
    original_link = avatar_media.os.link
    original_replace = avatar_media.os.replace
    original_unlink = avatar_media.os.unlink
    original_open = avatar_media.os.open
    attacker = b"boundary attacker must survive"
    attacked = False

    def controlled_uuid4():
        return next(queued, original_uuid4())

    def install_attacker(destination, directory_fd) -> None:
        nonlocal attacked
        if attacked or os.fspath(destination) != f"{fixed}.webp":
            return
        attacked = True
        try:
            original_unlink(destination, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        descriptor = original_open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=directory_fd,
        )
        try:
            os.write(descriptor, attacker)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def boundary_replace(source, destination, *, src_dir_fd=None, dst_dir_fd=None):
        install_attacker(destination, dst_dir_fd)
        return original_replace(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    def boundary_link(
        source,
        destination,
        *,
        src_dir_fd=None,
        dst_dir_fd=None,
        follow_symlinks=True,
    ):
        install_attacker(destination, dst_dir_fd)
        return original_link(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    monkeypatch.setattr(avatar_media, "uuid4", controlled_uuid4)
    monkeypatch.setattr(avatar_media.os, "replace", boundary_replace)
    monkeypatch.setattr(avatar_media.os, "link", boundary_link)

    stored = avatar_media.store_avatar(
        db_session,
        _direct_upload(_image_bytes("PNG"), "image/png"),
        media_root=MEDIA_ROOT,
        now=CAPTURED_NOW,
    )

    assert attacked is True
    assert stored.id != str(fixed)
    assert (MEDIA_ROOT / f"{fixed}.webp").read_bytes() == attacker
    loaded = avatar_media.load_avatar(db_session, stored.id, media_root=MEDIA_ROOT)
    assert loaded.media.id == stored.id
    assert [row.id for row in db_session.scalars(select(models.AvatarMedia)).all()] == [
        stored.id
    ]


def test_cleanup_boundary_exchange_never_unlinks_a_foreign_inode(
    db_session,
    monkeypatch,
) -> None:
    from app.backend.services import avatar_media

    fixed = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
    queued = iter([fixed, UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc1")])
    original_uuid4 = avatar_media.uuid4
    original_open = avatar_media.os.open
    original_unlink = avatar_media.os.unlink
    original_rename = avatar_media.os.rename
    attacker = b"foreign inode must not be deleted"
    exchanged = False

    def controlled_uuid4():
        return next(queued, original_uuid4())

    def exchange(directory_fd: int) -> None:
        nonlocal exchanged
        if exchanged:
            return
        exchanged = True
        original_rename(
            f"{fixed}.webp",
            "owned-but-unreachable.webp",
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        descriptor = original_open(
            f"{fixed}.webp",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=directory_fd,
        )
        try:
            os.write(descriptor, attacker)
        finally:
            os.close(descriptor)

    def boundary_unlink(path, *, dir_fd=None):
        if os.fspath(path) == f"{fixed}.webp" and dir_fd is not None:
            exchange(dir_fd)
        return original_unlink(path, dir_fd=dir_fd)

    def boundary_rename(source, destination, *, src_dir_fd=None, dst_dir_fd=None):
        if os.fspath(source) == f"{fixed}.webp" and src_dir_fd is not None:
            exchange(src_dir_fd)
        return original_rename(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    def fail_commit() -> None:
        raise OSError("synthetic database failure")

    monkeypatch.setattr(avatar_media, "uuid4", controlled_uuid4)
    monkeypatch.setattr(avatar_media.os, "unlink", boundary_unlink)
    monkeypatch.setattr(avatar_media.os, "rename", boundary_rename)
    monkeypatch.setattr(db_session, "commit", fail_commit)

    with pytest.raises(APIError) as error:
        avatar_media.store_avatar(
            db_session,
            _direct_upload(_image_bytes("PNG"), "image/png"),
            media_root=MEDIA_ROOT,
            now=CAPTURED_NOW,
        )

    assert error.value.code == "AVATAR_STORAGE_UNAVAILABLE"
    assert exchanged is True
    assert (MEDIA_ROOT / f"{fixed}.webp").read_bytes() == attacker
    assert (MEDIA_ROOT / "owned-but-unreachable.webp").is_file()
    assert db_session.scalar(select(func.count(models.AvatarMedia.id))) == 0


@pytest.mark.parametrize("failure_stage", ["fstat", "fdopen"])
def test_temporary_descriptor_failures_close_fd_and_leave_no_dangerous_name(
    db_session,
    monkeypatch,
    failure_stage,
) -> None:
    from app.backend.services import avatar_media

    captured_fds: list[int] = []
    original_open = avatar_media.os.open
    original_fstat = avatar_media.os.fstat
    original_fdopen = avatar_media.os.fdopen
    failed = False

    def recording_open(path, flags, mode=0o777, *, dir_fd=None):
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if os.fspath(path).startswith(".avatar-"):
            captured_fds.append(descriptor)
        return descriptor

    def failing_fstat(descriptor):
        nonlocal failed
        if failure_stage == "fstat" and descriptor in captured_fds and not failed:
            failed = True
            raise OSError("synthetic temporary fstat failure")
        return original_fstat(descriptor)

    def failing_fdopen(descriptor, *args, **kwargs):
        nonlocal failed
        if failure_stage == "fdopen" and descriptor in captured_fds and not failed:
            failed = True
            raise OSError("synthetic temporary fdopen failure")
        return original_fdopen(descriptor, *args, **kwargs)

    monkeypatch.setattr(avatar_media.os, "open", recording_open)
    monkeypatch.setattr(avatar_media.os, "fstat", failing_fstat)
    monkeypatch.setattr(avatar_media.os, "fdopen", failing_fdopen)

    with pytest.raises(APIError) as error:
        avatar_media.store_avatar(
            db_session,
            _direct_upload(_image_bytes("PNG"), "image/png"),
            media_root=MEDIA_ROOT,
            now=CAPTURED_NOW,
        )

    assert error.value.code == "AVATAR_STORAGE_UNAVAILABLE"
    assert failed is True
    assert len(captured_fds) == 1
    with pytest.raises(OSError):
        original_fstat(captured_fds[0])
    assert all(path.name.startswith(".") for path in _stored_files())
    if failure_stage == "fdopen":
        assert _stored_files() == []
    assert db_session.scalar(select(func.count(models.AvatarMedia.id))) == 0


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


def test_public_head_conditional_get_and_unsupported_range_have_explicit_contract(client) -> None:
    _unlock(client)
    uploaded = _upload(client, _image_bytes("PNG"), "image/png").json()
    assert client.post("/api/auth/lock").status_code == 200

    head = client.head(uploaded["url"])
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["content-type"] == "image/webp"
    assert head.headers["content-length"] == str(uploaded["size_bytes"])
    assert head.headers["etag"] == f'"{uploaded["sha256"]}"'
    assert head.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert head.headers["x-content-type-options"] == "nosniff"

    conditional = client.get(
        uploaded["url"],
        headers={
            "If-None-Match": head.headers["etag"],
            "Range": "bytes=0-0",
        },
    )
    assert conditional.status_code == 304
    assert conditional.content == b""
    assert conditional.headers["etag"] == head.headers["etag"]
    assert conditional.headers["cache-control"] == head.headers["cache-control"]
    assert conditional.headers["x-content-type-options"] == "nosniff"

    ranged = client.get(uploaded["url"], headers={"Range": "bytes=0-0"})
    _assert_error(ranged, status=416, code="AVATAR_RANGE_UNSUPPORTED")

    missing_with_range = client.get(
        "/api/media/avatars/11111111-1111-4111-8111-111111111111",
        headers={"Range": "bytes=0-0"},
    )
    _assert_error(missing_with_range, status=404, code="AVATAR_NOT_FOUND")


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


def test_store_holds_trusted_parent_fd_when_root_parent_is_swapped_to_symlink(
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    from app.backend.services import avatar_media

    safe_parent = tmp_path / "safe"
    media_root = safe_parent / "avatars"
    media_root.mkdir(parents=True)
    moved_parent = tmp_path / "safe-held"
    outside_parent = tmp_path / "outside"
    outside_root = outside_parent / "avatars"
    outside_root.mkdir(parents=True)
    original_open = avatar_media.os.open
    swapped = False

    def swapping_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        path_text = os.fspath(path)
        if not swapped and (path_text == os.fspath(media_root) or path_text == "avatars"):
            safe_parent.rename(moved_parent)
            safe_parent.symlink_to(outside_parent, target_is_directory=True)
            swapped = True
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(avatar_media.os, "open", swapping_open)

    stored = avatar_media.store_avatar(
        db_session,
        _direct_upload(_image_bytes("PNG"), "image/png"),
        media_root=media_root,
        now=CAPTURED_NOW,
    )

    assert swapped is True
    assert list(outside_root.iterdir()) == []
    stored_path = moved_parent / "avatars" / stored.file_name
    assert stored_path.is_file()
    expected = stored_path.read_bytes()

    loaded = avatar_media.load_avatar(db_session, stored.id, media_root=media_root)

    assert loaded.content == expected
    avatar_media.close_pinned_media_roots()
    with pytest.raises(APIError) as error:
        avatar_media.load_avatar(db_session, stored.id, media_root=media_root)
    assert error.value.code == "AVATAR_NOT_FOUND"


def test_load_holds_trusted_parent_fd_when_root_parent_is_swapped_to_symlink(
    db_session,
    tmp_path,
) -> None:
    from app.backend.services import avatar_media

    safe_parent = tmp_path / "safe"
    media_root = safe_parent / "avatars"
    media_root.mkdir(parents=True)
    stored = avatar_media.store_avatar(
        db_session,
        _direct_upload(_image_bytes("PNG"), "image/png"),
        media_root=media_root,
        now=CAPTURED_NOW,
    )
    expected = (media_root / stored.file_name).read_bytes()
    moved_parent = tmp_path / "safe-held"
    outside_parent = tmp_path / "outside"
    outside_root = outside_parent / "avatars"
    outside_root.mkdir(parents=True)
    (outside_root / stored.file_name).write_bytes(b"x" * len(expected))
    safe_parent.rename(moved_parent)
    safe_parent.symlink_to(outside_parent, target_is_directory=True)

    loaded = avatar_media.load_avatar(db_session, stored.id, media_root=media_root)

    assert loaded.content == expected
    assert (outside_root / stored.file_name).read_bytes() != loaded.content


def test_pinned_root_reset_closes_every_held_descriptor(db_session) -> None:
    from app.backend.services import avatar_media

    avatar_media.store_avatar(
        db_session,
        _direct_upload(_image_bytes("PNG"), "image/png"),
        media_root=MEDIA_ROOT,
        now=CAPTURED_NOW,
    )
    descriptors = [pinned.fd for pinned in avatar_media._PINNED_ROOTS.values()]
    assert len(descriptors) == 1

    avatar_media.close_pinned_media_roots()

    assert avatar_media._PINNED_ROOTS == {}
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_pid_guard_closes_inherited_registry_before_child_reopens_root(
    db_session,
    monkeypatch,
) -> None:
    from app.backend.services import avatar_media

    stored = avatar_media.store_avatar(
        db_session,
        _direct_upload(_image_bytes("PNG"), "image/png"),
        media_root=MEDIA_ROOT,
        now=CAPTURED_NOW,
    )
    inherited = next(iter(avatar_media._PINNED_ROOTS.values()))
    inherited_fd = inherited.fd
    parent_pid = os.getpid()
    original_secure_open = avatar_media._secure_open_media_root_fd
    inspections: list[tuple[bool, bool]] = []

    def inspecting_secure_open(media_root, *, create):
        try:
            os.fstat(inherited_fd)
        except OSError:
            inherited_closed = True
        else:
            inherited_closed = False
        inspections.append((avatar_media._PINNED_ROOTS == {}, inherited_closed))
        return original_secure_open(media_root, create=create)

    monkeypatch.setattr(avatar_media, "_secure_open_media_root_fd", inspecting_secure_open)
    monkeypatch.setattr(avatar_media.os, "getpid", lambda: parent_pid + 1)

    loaded = avatar_media.load_avatar(db_session, stored.id, media_root=MEDIA_ROOT)

    assert loaded.media.id == stored.id
    assert inspections == [(True, True)]
    assert next(iter(avatar_media._PINNED_ROOTS.values())) is not inherited


def test_invalidating_waiter_never_closes_a_root_held_by_an_active_reader(
    db_session,
    monkeypatch,
) -> None:
    """Catches validation/close occurring before the incumbent root lease ends."""

    from app.backend.services import avatar_media

    stored = avatar_media.store_avatar(
        db_session,
        _direct_upload(_image_bytes("PNG"), "image/png"),
        media_root=MEDIA_ROOT,
        now=CAPTURED_NOW,
    )
    expected = (MEDIA_ROOT / stored.file_name).read_bytes()
    original_mode = stat.S_IMODE(MEDIA_ROOT.stat().st_mode)
    original_open = avatar_media.os.open
    reader_at_fd_operation = Event()
    release_reader = Event()
    waiter_done = Event()
    reader_result: dict[str, object] = {}
    waiter_result: dict[str, object] = {}

    def blocking_open(path, flags, mode=0o777, *, dir_fd=None):
        if (
            current_thread().name == "active-avatar-reader"
            and os.fspath(path) == stored.file_name
            and dir_fd is not None
        ):
            reader_at_fd_operation.set()
            if not release_reader.wait(timeout=3):
                raise AssertionError("reader release timed out")
        return original_open(path, flags, mode, dir_fd=dir_fd)

    def read_as(target: dict[str, object], done: Event | None = None) -> None:
        session = SessionLocal()
        try:
            target["blob"] = avatar_media.load_avatar(
                session,
                stored.id,
                media_root=MEDIA_ROOT,
            )
        except BaseException as error:
            target["error"] = error
        finally:
            session.close()
            if done is not None:
                done.set()

    monkeypatch.setattr(avatar_media.os, "open", blocking_open)
    reader = Thread(
        target=read_as,
        name="active-avatar-reader",
        args=(reader_result,),
    )
    waiter = Thread(
        target=read_as,
        name="invalidating-avatar-waiter",
        args=(waiter_result, waiter_done),
    )
    try:
        reader.start()
        assert reader_at_fd_operation.wait(timeout=3)
        MEDIA_ROOT.chmod(0o777)
        waiter.start()
        waiter_finished_while_reader_held = waiter_done.wait(timeout=0.2)
    finally:
        release_reader.set()
        reader.join(timeout=3)
        waiter.join(timeout=3)
        MEDIA_ROOT.chmod(original_mode)

    assert not reader.is_alive()
    assert not waiter.is_alive()
    assert waiter_finished_while_reader_held is False
    assert "error" not in reader_result
    assert reader_result["blob"].content == expected
    assert isinstance(waiter_result.get("error"), APIError)
    assert waiter_result["error"].code == "AVATAR_NOT_FOUND"


def test_waiting_store_revalidates_root_after_permission_drift_before_any_write(
    db_session,
) -> None:
    """Catches a safe validation result being reused after waiting on root.lock."""

    from app.backend.services import avatar_media

    baseline = avatar_media.store_avatar(
        db_session,
        _direct_upload(_image_bytes("PNG"), "image/png"),
        media_root=MEDIA_ROOT,
        now=CAPTURED_NOW,
    )
    baseline_files = {path.name for path in MEDIA_ROOT.iterdir()}
    original_mode = stat.S_IMODE(MEDIA_ROOT.stat().st_mode)
    pinned = next(iter(avatar_media._PINNED_ROOTS.values()))
    result: dict[str, object] = {}

    def waiting_store() -> None:
        session = SessionLocal()
        try:
            result["stored"] = avatar_media.store_avatar(
                session,
                _direct_upload(_image_bytes("PNG", color=(20, 40, 220)), "image/png"),
                media_root=MEDIA_ROOT,
                now=CAPTURED_NOW,
            )
        except BaseException as error:
            result["error"] = error
        finally:
            session.close()

    pinned.lock.acquire()
    thread = Thread(target=waiting_store, name="permission-drift-avatar-store")
    try:
        thread.start()
        deadline = time.monotonic() + 3
        waiter_holds_registry = False
        while time.monotonic() < deadline:
            if not avatar_media._PINNED_ROOTS_LOCK.acquire(blocking=False):
                waiter_holds_registry = True
                break
            avatar_media._PINNED_ROOTS_LOCK.release()
            time.sleep(0.005)
        assert waiter_holds_registry is True
        MEDIA_ROOT.chmod(0o777)
    finally:
        pinned.lock.release()
        thread.join(timeout=3)
        MEDIA_ROOT.chmod(original_mode)

    assert not thread.is_alive()
    assert "stored" not in result
    assert isinstance(result.get("error"), APIError)
    assert result["error"].code == "AVATAR_STORAGE_UNAVAILABLE"
    db_session.expire_all()
    assert db_session.scalar(select(func.count(models.AvatarMedia.id))) == 1
    assert db_session.get(models.AvatarMedia, baseline.id) is not None
    assert {path.name for path in MEDIA_ROOT.iterdir()} == baseline_files


def test_reader_holds_root_lease_through_stored_content_validation(
    db_session,
    monkeypatch,
) -> None:
    """The validated root lease covers the complete load, not only fd reads."""

    from app.backend.services import avatar_media

    stored = avatar_media.store_avatar(
        db_session,
        _direct_upload(_image_bytes("PNG"), "image/png"),
        media_root=MEDIA_ROOT,
        now=CAPTURED_NOW,
    )
    original_validate = avatar_media._validate_stored_webp
    reader_at_validation = Event()
    release_reader = Event()
    waiter_done = Event()
    reader_result: dict[str, object] = {}
    waiter_result: dict[str, object] = {}

    def blocking_validate(content, row):
        if current_thread().name == "active-avatar-validator":
            reader_at_validation.set()
            if not release_reader.wait(timeout=3):
                raise AssertionError("validator release timed out")
        return original_validate(content, row)

    def load_as(target: dict[str, object], done: Event | None = None) -> None:
        session = SessionLocal()
        try:
            target["blob"] = avatar_media.load_avatar(
                session,
                stored.id,
                media_root=MEDIA_ROOT,
            )
        except BaseException as error:
            target["error"] = error
        finally:
            session.close()
            if done is not None:
                done.set()

    monkeypatch.setattr(avatar_media, "_validate_stored_webp", blocking_validate)
    reader = Thread(
        target=load_as,
        name="active-avatar-validator",
        args=(reader_result,),
    )
    waiter = Thread(
        target=load_as,
        name="waiting-avatar-reader",
        args=(waiter_result, waiter_done),
    )
    try:
        reader.start()
        assert reader_at_validation.wait(timeout=3)
        waiter.start()
        waiter_finished_while_reader_held = waiter_done.wait(timeout=0.2)
    finally:
        release_reader.set()
        reader.join(timeout=3)
        waiter.join(timeout=3)

    assert not reader.is_alive()
    assert not waiter.is_alive()
    assert waiter_finished_while_reader_held is False
    assert "error" not in reader_result
    assert "error" not in waiter_result
    assert reader_result["blob"].media.id == stored.id
    assert waiter_result["blob"].media.id == stored.id


@pytest.mark.parametrize(
    ("data", "row_width", "row_height"),
    [
        pytest.param(_image_bytes("PNG"), 80, 48, id="non-webp"),
        pytest.param(_image_bytes("WEBP"), 79, 48, id="row-dimension-mismatch"),
        pytest.param(_image_bytes("WEBP", size=(1200, 600)), 1200, 600, id="stored-edge-over-1024"),
        pytest.param(_animated_webp(), 32, 24, id="stored-animation"),
    ],
)
def test_public_and_reference_reject_row_backed_files_with_invalid_decoded_webp(
    client,
    db_session,
    data,
    row_width,
    row_height,
) -> None:
    media_id = "88888888-8888-4888-8888-888888888888"
    MEDIA_ROOT.mkdir(parents=True)
    (MEDIA_ROOT / f"{media_id}.webp").write_bytes(data)
    _insert_media(
        db_session,
        media_id=media_id,
        file_name=f"{media_id}.webp",
        data=data,
        width=row_width,
        height=row_height,
    )

    public = client.get(f"/api/media/avatars/{media_id}")
    _assert_error(public, status=404, code="AVATAR_NOT_FOUND")

    _unlock(client)
    reference = client.post(
        "/api/children",
        json={
            "name": "不应保存",
            "nickname": None,
            "avatar": f"/api/media/avatars/{media_id}",
        },
    )
    _assert_error(reference, status=422, code="VALIDATION_ERROR")
    assert db_session.scalar(select(func.count(models.Child.id))) == 0


def test_public_and_reference_reject_hardlinked_avatar_file(
    client,
    db_session,
    tmp_path,
) -> None:
    media_id = "99999999-9999-4999-8999-999999999999"
    data = _image_bytes("WEBP")
    source = tmp_path / "outside.webp"
    source.write_bytes(data)
    MEDIA_ROOT.mkdir(parents=True)
    os.link(source, MEDIA_ROOT / f"{media_id}.webp")
    _insert_media(
        db_session,
        media_id=media_id,
        file_name=f"{media_id}.webp",
        data=data,
        width=80,
        height=48,
    )

    public = client.get(f"/api/media/avatars/{media_id}")
    _assert_error(public, status=404, code="AVATAR_NOT_FOUND")

    _unlock(client)
    reference = client.post(
        "/api/ducks",
        json={
            "name": "不应保存",
            "avatar": f"/api/media/avatars/{media_id}",
            "status": None,
            "note": None,
        },
    )
    _assert_error(reference, status=422, code="VALIDATION_ERROR")
    assert db_session.scalar(select(func.count(models.Duck.id))) == 0


def test_concurrent_fixed_uuid_collision_never_overwrites_or_deletes_winner(
    monkeypatch,
) -> None:
    from app.backend.services import avatar_media

    MEDIA_ROOT.mkdir(parents=True)
    fixed = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    sequences = {
        "avatar-a": [
            fixed,
            UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"),
            UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2"),
            UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3"),
        ],
        "avatar-b": [
            fixed,
            UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1"),
            UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2"),
            UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb3"),
        ],
    }
    state = local()

    def controlled_uuid4():
        index = getattr(state, "uuid_index", 0)
        state.uuid_index = index + 1
        return sequences[state.thread_name][index]

    monkeypatch.setattr(avatar_media, "uuid4", controlled_uuid4)
    results: list[str] = []
    errors: list[BaseException] = []
    result_lock = Lock()

    def upload_in_thread(name: str, color: tuple[int, int, int]) -> None:
        state.thread_name = name
        session = SessionLocal()
        try:
            row = avatar_media.store_avatar(
                session,
                _direct_upload(_image_bytes("PNG", color=color), "image/png"),
                media_root=MEDIA_ROOT,
                now=CAPTURED_NOW,
            )
            with result_lock:
                results.append(row.id)
        except BaseException as error:
            with result_lock:
                errors.append(error)
        finally:
            session.close()

    threads = [
        Thread(target=upload_in_thread, name="avatar-a", args=("avatar-a", (220, 20, 20))),
        Thread(target=upload_in_thread, name="avatar-b", args=("avatar-b", (20, 20, 220))),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert len(set(results)) == 2
    with SessionLocal() as fresh:
        rows = fresh.scalars(select(models.AvatarMedia).order_by(models.AvatarMedia.id)).all()
        assert {row.id for row in rows} == set(results)
        assert {path.name for path in MEDIA_ROOT.iterdir()} == {row.file_name for row in rows}
        for row in rows:
            content = (MEDIA_ROOT / row.file_name).read_bytes()
            assert len(content) == row.size_bytes
            assert sha256(content).hexdigest() == row.sha256


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
