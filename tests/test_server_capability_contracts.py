"""Frozen P6 request and response contracts for server capabilities."""
from datetime import date
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.backend import schemas


REQUEST_ID = UUID("11111111-1111-4111-8111-111111111111")
MEDIA_ID = UUID("6d8b0000-0000-4000-8000-000000000001")
MEDIA_URL = f"/api/media/avatars/{MEDIA_ID}"
PUBLIC_AVATAR_RESPONSE_CASES = [
    pytest.param(
        schemas.ChildOut,
        {"id": 1, "name": "小明"},
        {
            "name": "小明",
            "nickname": None,
            "avatar": None,
            "active": True,
            "id": 1,
        },
        id="child-out",
    ),
    pytest.param(
        schemas.DuckOut,
        {"id": 2, "name": "小黄"},
        {
            "name": "小黄",
            "avatar": None,
            "status": None,
            "note": None,
            "id": 2,
        },
        id="duck-out",
    ),
    pytest.param(
        schemas.RosterTodayChild,
        {"id": 3, "name": "小雨"},
        {"id": 3, "name": "小雨", "nickname": None, "avatar": None},
        id="roster-today-child",
    ),
    pytest.param(
        schemas.ChildIdentity,
        {"id": 4, "name": "小北"},
        {"id": 4, "name": "小北", "nickname": None, "avatar": None},
        id="child-identity",
    ),
    pytest.param(
        schemas.TeacherChildOut,
        {
            "id": 5,
            "name": "小南",
            "active": True,
            "future_roster_entries": 0,
            "has_active_conversation": False,
        },
        {
            "id": 5,
            "name": "小南",
            "nickname": None,
            "avatar": None,
            "active": True,
            "deactivated_at": None,
            "future_roster_entries": 0,
            "has_active_conversation": False,
        },
        id="teacher-child-out",
    ),
    pytest.param(
        schemas.TeacherDuckOut,
        {
            "id": 6,
            "name": "小绿",
            "active": True,
            "historical_feeding_log_count": 0,
        },
        {
            "id": 6,
            "name": "小绿",
            "avatar": None,
            "status": None,
            "note": None,
            "active": True,
            "deactivated_at": None,
            "historical_feeding_log_count": 0,
        },
        id="teacher-duck-out",
    ),
]


def test_runtime_context_response_has_the_exact_calendar_shape():
    payload = schemas.RuntimeContextResponse(
        timezone="Asia/Shanghai",
        business_date="2026-09-02",
        week_start="2026-08-31",
        week_end_exclusive="2026-09-07",
    )

    assert payload.model_dump() == {
        "timezone": "Asia/Shanghai",
        "business_date": date(2026, 9, 2),
        "week_start": date(2026, 8, 31),
        "week_end_exclusive": date(2026, 9, 7),
    }


def test_child_mutation_normalizes_the_exact_client_owned_fields():
    payload = schemas.ChildMutationRequest(
        name="  王小明  ",
        nickname="  小明  ",
        avatar=f"  {MEDIA_URL}  ",
    )

    assert payload.model_dump() == {
        "name": "王小明",
        "nickname": "小明",
        "avatar": MEDIA_URL,
    }


@pytest.mark.parametrize("forbidden", ["active", "deactivated_at", "unknown"])
def test_child_mutation_rejects_server_owned_and_unknown_fields(forbidden):
    with pytest.raises(ValidationError):
        schemas.ChildMutationRequest.model_validate({"name": "小明", forbidden: False})


@pytest.mark.parametrize("name", ["", " 　\t "])
def test_child_mutation_rejects_a_blank_normalized_name(name):
    with pytest.raises(ValidationError):
        schemas.ChildMutationRequest(name=name)


def test_child_mutation_rejects_blank_optional_text_and_noncanonical_avatar():
    with pytest.raises(ValidationError):
        schemas.ChildMutationRequest(name="小明", nickname="  ")
    with pytest.raises(ValidationError):
        schemas.ChildMutationRequest(name="小明", avatar="https://example.invalid/avatar.png")


def test_duck_mutation_normalizes_the_exact_client_owned_fields():
    payload = schemas.DuckMutationRequest(
        name="  小黄  ",
        avatar=f"  {MEDIA_URL}  ",
        status="  活泼健康  ",
        note="  喜欢在水里玩  ",
    )

    assert payload.model_dump() == {
        "name": "小黄",
        "avatar": MEDIA_URL,
        "status": "活泼健康",
        "note": "喜欢在水里玩",
    }


def test_duck_mutation_rejects_blank_name_optional_text_and_unknown_fields():
    for payload in (
        {"name": "  "},
        {"name": "小黄", "status": "  "},
        {"name": "小黄", "note": "\t"},
        {"name": "小黄", "active": False},
    ):
        with pytest.raises(ValidationError):
            schemas.DuckMutationRequest.model_validate(payload)


def test_avatar_media_response_has_the_exact_processed_image_shape():
    payload = schemas.AvatarMediaResponse(
        id=MEDIA_ID,
        url=MEDIA_URL,
        mime_type="image/webp",
        width=768,
        height=512,
        size_bytes=84231,
        sha256="a" * 64,
    )

    assert payload.model_dump() == {
        "id": MEDIA_ID,
        "url": MEDIA_URL,
        "mime_type": "image/webp",
        "width": 768,
        "height": 512,
        "size_bytes": 84231,
        "sha256": "a" * 64,
    }


@pytest.mark.parametrize(
    ("response_model", "base_payload", "expected_null_payload"),
    PUBLIC_AVATAR_RESPONSE_CASES,
)
def test_public_avatar_responses_preserve_shape_for_null_and_canonical_urls(
    response_model,
    base_payload,
    expected_null_payload,
):
    null_payload = response_model.model_validate({**base_payload, "avatar": None})
    canonical_payload = response_model.model_validate({
        **base_payload,
        "avatar": MEDIA_URL,
    })

    assert null_payload.model_dump() == expected_null_payload
    assert canonical_payload.model_dump() == {
        **expected_null_payload,
        "avatar": MEDIA_URL,
    }


@pytest.mark.parametrize(
    ("response_model", "base_payload", "_expected_null_payload"),
    PUBLIC_AVATAR_RESPONSE_CASES,
)
def test_public_avatar_responses_reject_noncanonical_legacy_values(
    response_model,
    base_payload,
    _expected_null_payload,
):
    with pytest.raises(ValidationError):
        response_model.model_validate({**base_payload, "avatar": "legacy-avatar.png"})


def test_monthly_roster_entry_requires_two_distinct_positive_children():
    payload = schemas.MonthlyRosterEntryRequest(
        date="2026-09-03",
        child_ids=[1, 4],
    )
    assert payload.model_dump() == {
        "date": date(2026, 9, 3),
        "child_ids": [1, 4],
    }

    for child_ids in ([1], [1, 1], [1, 2, 3], [0, 2]):
        with pytest.raises(ValidationError):
            schemas.MonthlyRosterEntryRequest(
                date="2026-09-03",
                child_ids=child_ids,
            )


def test_monthly_roster_request_normalizes_and_dumps_the_exact_shape():
    payload = schemas.MonthlyRosterRequest(
        request_id=REQUEST_ID,
        month="2026-09",
        cycle="  2026-09月值日  ",
        entries=[
            {"date": "2026-09-03", "child_ids": [1, 4]},
            {"date": "2026-09-08", "child_ids": [2, 5]},
        ],
        replace_existing=False,
    )

    assert payload.model_dump() == {
        "request_id": REQUEST_ID,
        "month": "2026-09",
        "cycle": "2026-09月值日",
        "entries": [
            {"date": date(2026, 9, 3), "child_ids": [1, 4]},
            {"date": date(2026, 9, 8), "child_ids": [2, 5]},
        ],
        "replace_existing": False,
    }


def test_monthly_roster_rejects_date_outside_month_and_duplicate_dates():
    with pytest.raises(ValidationError):
        schemas.MonthlyRosterRequest(
            request_id=REQUEST_ID,
            month="2026-09",
            cycle="九月值日",
            entries=[{"date": "2026-10-01", "child_ids": [1, 2]}],
            replace_existing=False,
        )

    with pytest.raises(ValidationError):
        schemas.MonthlyRosterRequest(
            request_id=REQUEST_ID,
            month="2026-09",
            cycle="九月值日",
            entries=[
                {"date": "2026-09-03", "child_ids": [1, 2]},
                {"date": "2026-09-03", "child_ids": [3, 4]},
            ],
            replace_existing=False,
        )


def test_monthly_roster_rejects_invalid_month_blank_cycle_and_unknown_fields():
    base = {
        "request_id": REQUEST_ID,
        "month": "2026-09",
        "cycle": "九月值日",
        "entries": [{"date": "2026-09-03", "child_ids": [1, 2]}],
        "replace_existing": False,
    }
    for patch in (
        {"month": "2026-13"},
        {"cycle": "  "},
        {"unexpected": True},
    ):
        with pytest.raises(ValidationError):
            schemas.MonthlyRosterRequest.model_validate({**base, **patch})


def test_monthly_roster_response_has_the_exact_sorted_snapshot_shape():
    payload = schemas.MonthlyRosterResponse(
        request_id=REQUEST_ID,
        month="2026-09",
        schedule=[
            {
                "date": "2026-09-03",
                "cycle": "2026-09月值日",
                "child_ids": [1, 4],
            },
            {
                "date": "2026-09-08",
                "cycle": "2026-09月值日",
                "child_ids": [2, 5],
            },
        ],
        replayed=False,
    )

    assert payload.model_dump() == {
        "request_id": REQUEST_ID,
        "month": "2026-09",
        "schedule": [
            {
                "date": date(2026, 9, 3),
                "cycle": "2026-09月值日",
                "child_ids": [1, 4],
            },
            {
                "date": date(2026, 9, 8),
                "cycle": "2026-09月值日",
                "child_ids": [2, 5],
            },
        ],
        "replayed": False,
    }


@pytest.mark.parametrize(
    "schedule",
    [
        [],
        [
            {
                "date": "2026-09-01",
                "cycle": "九月值日",
                "child_ids": [1, 2],
            }
        ]
        * 32,
    ],
)
def test_monthly_roster_response_requires_one_to_thirty_one_items(schedule):
    with pytest.raises(ValidationError):
        schemas.MonthlyRosterResponse(
            request_id=REQUEST_ID,
            month="2026-09",
            schedule=schedule,
            replayed=False,
        )


def test_monthly_roster_response_rejects_duplicate_schedule_dates():
    with pytest.raises(ValidationError):
        schemas.MonthlyRosterResponse(
            request_id=REQUEST_ID,
            month="2026-09",
            schedule=[
                {"date": "2026-09-03", "cycle": "九月值日", "child_ids": [1, 2]},
                {"date": "2026-09-03", "cycle": "九月值日", "child_ids": [3, 4]},
            ],
            replayed=False,
        )


def test_monthly_roster_response_rejects_dates_outside_response_month():
    with pytest.raises(ValidationError):
        schemas.MonthlyRosterResponse(
            request_id=REQUEST_ID,
            month="2026-09",
            schedule=[
                {"date": "2026-10-01", "cycle": "九月值日", "child_ids": [1, 2]},
            ],
            replayed=False,
        )


def test_monthly_roster_response_requires_ascending_schedule_dates():
    with pytest.raises(ValidationError):
        schemas.MonthlyRosterResponse(
            request_id=REQUEST_ID,
            month="2026-09",
            schedule=[
                {"date": "2026-09-08", "cycle": "九月值日", "child_ids": [1, 2]},
                {"date": "2026-09-03", "cycle": "九月值日", "child_ids": [3, 4]},
            ],
            replayed=False,
        )


def test_weekly_report_response_has_the_exact_mixed_week_and_backlog_shape():
    payload = schemas.WeeklyReportResponse(
        timezone="Asia/Shanghai",
        week_start="2026-08-31",
        week_end_exclusive="2026-09-07",
        completed_conversations=4,
        participating_children=3,
        confirmed_reviews=2,
        failed_analyses=1,
        pending_reviews_total=5,
    )

    assert payload.model_dump() == {
        "timezone": "Asia/Shanghai",
        "week_start": date(2026, 8, 31),
        "week_end_exclusive": date(2026, 9, 7),
        "completed_conversations": 4,
        "participating_children": 3,
        "confirmed_reviews": 2,
        "failed_analyses": 1,
        "pending_reviews_total": 5,
    }


def test_conversation_search_request_normalizes_and_dumps_the_exact_shape():
    payload = schemas.ConversationSearchRequest(
        child_id=1,
        date_from="2026-08-01",
        date_to="2026-09-02",
        analysis_status=["succeeded"],
        review_status=["confirmed"],
        end_reason=["complete", "manual"],
        keyword="  喂菜叶  ",
        sort="completed_desc",
        limit=20,
        cursor=None,
    )

    assert payload.model_dump() == {
        "child_id": 1,
        "date_from": date(2026, 8, 1),
        "date_to": date(2026, 9, 2),
        "analysis_status": ["succeeded"],
        "review_status": ["confirmed"],
        "end_reason": ["complete", "manual"],
        "keyword": "喂菜叶",
        "sort": "completed_desc",
        "limit": 20,
        "cursor": None,
    }


@pytest.mark.parametrize("field", ["analysis_status", "review_status", "end_reason"])
def test_conversation_search_rejects_duplicate_status_values(field):
    value = {
        "analysis_status": "succeeded",
        "review_status": "confirmed",
        "end_reason": "complete",
    }[field]
    with pytest.raises(ValidationError):
        schemas.ConversationSearchRequest.model_validate({field: [value, value]})


@pytest.mark.parametrize(
    ("date_from", "date_to"),
    [
        ("2026-09-03", "2026-09-02"),
        ("2025-01-01", "2026-01-02"),
    ],
)
def test_conversation_search_rejects_inverted_or_367_day_range(date_from, date_to):
    with pytest.raises(ValidationError):
        schemas.ConversationSearchRequest(date_from=date_from, date_to=date_to)


def test_conversation_search_rejects_blank_keyword_unknown_fields_and_invalid_cursor():
    for payload in (
        {"keyword": "  "},
        {"unknown": True},
        {"cursor": "not url safe="},
    ):
        with pytest.raises(ValidationError):
            schemas.ConversationSearchRequest.model_validate(payload)


def test_conversation_search_page_is_separate_from_legacy_before_id_page():
    payload = schemas.ConversationSearchPage(items=[], next_cursor="Y3Vyc29yXzE")

    assert payload.model_dump() == {
        "items": [],
        "next_cursor": "Y3Vyc29yXzE",
    }
    with pytest.raises(ValidationError):
        schemas.ConversationSearchPage.model_validate(
            {"items": [], "next_cursor": None, "next_before_id": 7}
        )


def test_conversation_search_request_cursor_accepts_the_1024_character_boundary():
    cursor = "a" * 1024

    payload = schemas.ConversationSearchRequest(cursor=cursor)

    assert payload.cursor == cursor


def test_conversation_search_request_cursor_rejects_more_than_1024_characters():
    with pytest.raises(ValidationError):
        schemas.ConversationSearchRequest(cursor="a" * 1025)


def test_conversation_search_page_cursor_accepts_the_1024_character_boundary():
    cursor = "a" * 1024

    payload = schemas.ConversationSearchPage(items=[], next_cursor=cursor)

    assert payload.next_cursor == cursor


def test_conversation_search_page_cursor_rejects_more_than_1024_characters():
    with pytest.raises(ValidationError):
        schemas.ConversationSearchPage(items=[], next_cursor="a" * 1025)
