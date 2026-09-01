"""Foundation-fixture integration coverage for the frozen backend API."""
from uuid import uuid4
from sqlalchemy import select

from app.backend import ai_engine, models
from app.backend.analysis_worker import AnalysisWorker
from app.backend.database import SessionLocal


CHILD_AVATAR = "/api/media/avatars/00000000-0000-4000-8000-000000000011"
DUCK_AVATAR = "/api/media/avatars/00000000-0000-4000-8000-000000000012"


def unlock_teacher(client) -> None:
    response = client.post("/api/auth/setup", json={"pin": "1234"})
    assert response.status_code == 200


def _mock_chat_reply(**_kwargs):
    return {"reply": "真棒！还有呢？", "ended": False, "end_reason": None}


class _FakeAnalyzer:
    """In-process analysis provider used only by the release-gate flows."""

    def extract_info(self, _transcript: str) -> dict:
        return {
            "feeding_logs": [{"category": "喂食", "content": "给鸭子喂了菜叶", "duck_name": None}],
            "emotion": {"emotion": "开心", "intensity": 4, "note": "语气积极"},
            "insight": "主动描述喂食过程",
        }

    def assess_conversation(self, _transcript: str, dimensions: list[dict]) -> dict:
        return {
            "scores": [
                {"dimension_key": dimension["key"], "score": 4, "reason": f"幼儿说了{dimension['key']}"}
                for dimension in dimensions
            ],
            "overall": 4.0,
        }


def _chat(client, *, child_id: int, text: str, conversation_id: int | None = None) -> dict:
    response = client.post(
        "/api/chat",
        json={
            "request_id": str(uuid4()),
            "child_id": child_id,
            "text": text,
            "conversation_id": conversation_id,
        },
    )
    assert response.status_code == 200
    return response.json()


def _confirmed_review_payload(detail: dict) -> dict:
    review = detail["review"]
    assert review is not None
    return {
        "revision": detail["revision"],
        "feeding_logs": review["feeding_logs"],
        "emotion": review["emotion"],
        "insight": review["insight"],
        "scores": [
            {
                "dimension_id": score["dimension_id"],
                "score": 5,
                "reason": f"教师确认：{score['dimension_name']}",
            }
            for score in review["scores"]
        ],
        "action": "confirm",
    }


def _finalize_snapshot(db_session, conversation_id: int) -> dict:
    """Capture every row the retired finalizer used to mutate."""
    db_session.expire_all()
    return {
        "conversation": [
            (row.id, row.status, row.end_reason, row.ended_at, row.revision, row.frozen_last_message_id)
            for row in db_session.scalars(
                select(models.Conversation).where(models.Conversation.id == conversation_id)
            )
        ],
        "messages": [
            (row.id, row.role, row.text, row.created_at)
            for row in db_session.scalars(
                select(models.Message)
                .where(models.Message.conversation_id == conversation_id)
                .order_by(models.Message.id)
            )
        ],
        "jobs": [
            (row.id, row.status, row.attempt_count, row.frozen_last_message_id)
            for row in db_session.scalars(
                select(models.AnalysisJob)
                .where(models.AnalysisJob.conversation_id == conversation_id)
                .order_by(models.AnalysisJob.id)
            )
        ],
        "feeding": list(db_session.scalars(
            select(models.FeedingLog.id).where(models.FeedingLog.conversation_id == conversation_id)
        )),
        "emotions": list(db_session.scalars(
            select(models.EmotionLog.id).where(models.EmotionLog.conversation_id == conversation_id)
        )),
        "insights": list(db_session.scalars(
            select(models.InsightNote.id).where(models.InsightNote.conversation_id == conversation_id)
        )),
        "assessments": list(db_session.scalars(
            select(models.Assessment.id).where(models.Assessment.conversation_id == conversation_id)
        )),
    }


def test_dimensions_seeded(client):
    unlock_teacher(client)
    response = client.get("/api/dimensions")
    assert response.status_code == 200
    assert {item["key"] for item in response.json()} == {"language", "empathy", "diligence"}


def test_child_crud_list_smoke(client):
    unlock_teacher(client)
    created = client.post("/api/children", json={
        "name": "  王小明  ",
        "nickname": "  小明  ",
        "avatar": f"  {CHILD_AVATAR}  ",
    })
    assert created.status_code == 200
    child_id = created.json()["id"]
    assert created.json() == {
        "name": "王小明",
        "nickname": "小明",
        "avatar": CHILD_AVATAR,
        "active": True,
        "id": child_id,
    }
    assert client.get("/api/children").json()[0]["id"] == child_id

    updated = client.put(f"/api/children/{child_id}", json={
        "name": "  王小明  ",
        "nickname": None,
        "avatar": None,
    })
    assert updated.status_code == 200
    assert updated.json() == {
        "name": "王小明",
        "nickname": None,
        "avatar": None,
        "active": True,
        "id": child_id,
    }


def test_duck_crud_list_smoke(client):
    unlock_teacher(client)
    created = client.post("/api/ducks", json={
        "name": "  小黄  ",
        "avatar": f"  {DUCK_AVATAR}  ",
        "status": "  活泼健康  ",
        "note": None,
    })
    assert created.status_code == 200
    duck_id = created.json()["id"]
    assert created.json() == {
        "name": "小黄",
        "avatar": DUCK_AVATAR,
        "status": "活泼健康",
        "note": None,
        "id": duck_id,
    }
    assert client.get("/api/ducks").json()[0]["id"] == duck_id

    updated = client.put(f"/api/ducks/{duck_id}", json={
        "name": "  小黄  ",
        "avatar": None,
        "status": None,
        "note": "  喜欢菜叶  ",
    })
    assert updated.status_code == 200
    assert updated.json() == {
        "name": "小黄",
        "avatar": None,
        "status": None,
        "note": "喜欢菜叶",
        "id": duck_id,
    }


def test_roster_auto_uses_an_idempotency_request_id(client):
    unlock_teacher(client)
    for index in range(6):
        assert client.post("/api/children", json={"name": f"幼儿{index}"}).status_code == 200

    response = client.post(
        "/api/roster/auto",
        json={
            "request_id": str(uuid4()),
            "start_date": "2026-08-17",
            "days": 5,
            "cycle": "第1周",
        },
    )
    assert response.status_code == 200
    assert len(response.json()["schedule"]) == 5
    assert all(len(item["child_ids"]) == 2 for item in response.json()["schedule"])


def test_chat_flow_reads_the_public_active_transcript(monkeypatch, client):
    unlock_teacher(client)
    monkeypatch.setattr(ai_engine, "chat_reply", _mock_chat_reply)
    child_id = client.post("/api/children", json={"name": "王小明", "nickname": "小明"}).json()["id"]

    first = _chat(client, child_id=child_id, text="我今天喂了小鸭")
    second = _chat(
        client,
        child_id=child_id,
        text="还给它们换了水",
        conversation_id=first["conversation_id"],
    )
    assert second["conversation_id"] == first["conversation_id"]
    assert second["round"] == 2

    active = client.get(f"/api/children/{child_id}/active-conversation")
    assert active.status_code == 200
    assert active.json()["conversation"]["id"] == first["conversation_id"]
    assert len(active.json()["conversation"]["messages"]) == 4


def test_chat_max_rounds_uses_distinct_request_ids(monkeypatch, client):
    unlock_teacher(client)
    monkeypatch.setattr(ai_engine, "chat_reply", _mock_chat_reply)
    child_id = client.post("/api/children", json={"name": "李小红"}).json()["id"]

    conversation_id = None
    for index in range(3):
        result = _chat(client, child_id=child_id, text=f"话{index}", conversation_id=conversation_id)
        conversation_id = result["conversation_id"]
    assert result["ended"] is True
    assert result["end_reason"] == "max_rounds"


def test_complete_runs_one_local_fake_worker_then_confirms_growth(monkeypatch, client, db_session):
    unlock_teacher(client)
    monkeypatch.setattr(ai_engine, "chat_reply", _mock_chat_reply)
    child_id = client.post("/api/children", json={"name": "王小明", "nickname": "小明"}).json()["id"]
    chat = _chat(client, child_id=child_id, text="我喂了小鸭")
    conversation_id = chat["conversation_id"]

    completed = client.post(
        f"/api/conversations/{conversation_id}/complete",
        json={"expected_last_message_id": chat["diary_message_id"]},
    )
    assert completed.status_code == 200
    assert completed.json()["analysis_status"] == "pending"
    assert completed.json()["last_message_id"] == chat["diary_message_id"]

    worker = AnalysisWorker(session_factory=SessionLocal, analyzer=_FakeAnalyzer())
    assert worker.run_once() is True
    db_session.expire_all()
    assert db_session.scalar(
        select(models.AnalysisJob.status).where(models.AnalysisJob.id == completed.json()["analysis_job_id"])
    ) == "succeeded"

    detail_response = client.get(f"/api/conversations/{conversation_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["analysis"]["status"] == "succeeded"
    assert detail["review"] is not None
    assert detail["review"]["insight"] == "主动描述喂食过程"

    confirmed = client.put(
        f"/api/conversations/{conversation_id}/review",
        json=_confirmed_review_payload(detail),
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["review_status"] == "confirmed"

    growth = client.get(f"/api/analysis/growth?child_id={child_id}")
    assert growth.status_code == 200
    assert len(growth.json()["dimensions"]) == 3
    assert all(item["points"][0]["score"] == 5 for item in growth.json()["dimensions"])


def test_frontend_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "鸭鸭日记本" in response.text


def test_teacher_served(client):
    assert client.get("/teacher.html").status_code == 200


def test_missing_resources_and_tombstones_use_frozen_contracts(monkeypatch, client, db_session):
    unlock_teacher(client)
    monkeypatch.setattr(ai_engine, "chat_reply", _mock_chat_reply)
    analyzer = _FakeAnalyzer()
    monkeypatch.setattr(ai_engine, "extract_info", analyzer.extract_info)
    monkeypatch.setattr(ai_engine, "assess_conversation", analyzer.assess_conversation)
    assert client.get("/api/children/99999").status_code == 404
    assert client.get("/api/ducks/99999").status_code == 404
    missing_detail = client.get("/api/conversations/99999")
    assert missing_detail.status_code == 404
    assert missing_detail.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"

    empty = client.post("/api/chat", json={"request_id": str(uuid4()), "child_id": 1, "text": ""})
    assert empty.status_code == 422
    assert empty.json()["error"]["code"] == "VALIDATION_ERROR"
    unknown = client.post("/api/chat", json={"request_id": str(uuid4()), "child_id": 99999, "text": "你好"})
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "CHILD_NOT_FOUND"

    child = models.Child(name="终结墓碑", active=True)
    db_session.add(child)
    db_session.commit()
    active = _chat(client, child_id=child.id, text="我喂了小鸭")
    before = _finalize_snapshot(db_session, active["conversation_id"])
    tombstone = client.post(
        f"/api/conversations/{active['conversation_id']}/finalize",
        content=b"{not-json",
        headers={"content-type": "application/json"},
    )
    assert tombstone.status_code == 410
    assert tombstone.json()["error"]["code"] == "LEGACY_ENDPOINT_REMOVED"
    assert _finalize_snapshot(db_session, active["conversation_id"]) == before


def test_tts_rejects_empty_text_without_a_provider_call(client):
    assert client.get("/api/tts", params={"text": ""}).status_code == 400
