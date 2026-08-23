"""Deterministic release-gate end-to-end flow over Foundation fixtures."""
from uuid import uuid4

from sqlalchemy import select

from app.backend import ai_engine, models
from app.backend.analysis_worker import AnalysisWorker
from app.backend.database import SessionLocal


class _FakeAnalyzer:
    def extract_info(self, _transcript: str) -> dict:
        return {
            "feeding_logs": [{"category": "喂食", "content": "给小黄添了菜叶", "duck_name": "小黄"}],
            "emotion": {"emotion": "开心", "intensity": 4, "note": "完整分享"},
            "insight": "能完整说出照顾小鸭的过程。",
        }

    def assess_conversation(self, _transcript: str, dimensions: list[dict]) -> dict:
        return {
            "scores": [
                {"dimension_key": item["key"], "score": 4, "reason": f"提到了{item['name']}"}
                for item in dimensions
            ],
            "overall": 4.0,
        }


def _chat(client, *, child_id: int, text: str, conversation_id: int | None) -> dict:
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


def test_reliable_end_to_end_flow(monkeypatch, client, db_session):
    """Use only disposable SQLite, fake providers, and one manually driven worker."""
    def fake_chat_reply(**_kwargs):
        return {"reply": "我记下来了，还有什么发现？", "ended": False, "end_reason": None}

    monkeypatch.setattr(ai_engine, "chat_reply", fake_chat_reply)
    setup = client.post("/api/auth/setup", json={"pin": "1234"})
    assert setup.status_code == 200
    assert setup.json() == {"configured": True, "authenticated": True}

    child_response = client.post("/api/children", json={"name": "测试幼儿", "nickname": "小测"})
    duck_response = client.post("/api/ducks", json={"name": "小黄", "status": "活泼健康"})
    assert child_response.status_code == 200
    assert duck_response.status_code == 200
    child_id = child_response.json()["id"]
    duck_id = duck_response.json()["id"]
    for index in range(3):
        assert client.post("/api/children", json={"name": f"排班幼儿{index}"}).status_code == 200

    roster_request_id = str(uuid4())
    roster_body = {
        "request_id": roster_request_id,
        "start_date": "2026-08-17",
        "days": 5,
        "cycle": "第1周",
    }
    roster = client.post("/api/roster/auto", json=roster_body)
    roster_replay = client.post("/api/roster/auto", json=roster_body)
    assert roster.status_code == 200
    assert roster.json()["request_id"] == roster_request_id
    assert len(roster.json()["schedule"]) == 5
    assert roster_replay.status_code == 200
    assert roster_replay.json()["replayed"] is True
    assert roster_replay.json()["schedule"] == roster.json()["schedule"]

    first = _chat(client, child_id=child_id, text="我今天喂了小鸭，给它们吃了青菜", conversation_id=None)
    second = _chat(
        client,
        child_id=child_id,
        text="我还给它们换了干净的水",
        conversation_id=first["conversation_id"],
    )
    third = _chat(
        client,
        child_id=child_id,
        text="我看到小鸭在水里游来游去很开心",
        conversation_id=first["conversation_id"],
    )
    assert first["conversation_id"] == second["conversation_id"] == third["conversation_id"]
    assert third["ended"] is True
    assert third["end_reason"] == "max_rounds"

    completed = client.post(
        f"/api/conversations/{third['conversation_id']}/complete",
        json={"expected_last_message_id": third["diary_message_id"]},
    )
    assert completed.status_code == 200
    assert completed.json()["conversation_id"] == third["conversation_id"]
    assert completed.json()["analysis_status"] == "pending"
    db_session.expire_all()
    assert db_session.scalar(
        select(models.AnalysisJob.status).where(models.AnalysisJob.id == completed.json()["analysis_job_id"])
    ) == "pending"

    worker = AnalysisWorker(session_factory=SessionLocal, analyzer=_FakeAnalyzer())
    assert worker.run_once() is True
    detail_response = client.get(f"/api/conversations/{third['conversation_id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["analysis"]["status"] == "succeeded"
    review = detail["review"]
    assert review is not None
    assert review["feeding_logs"] == [
        {
            "id": review["feeding_logs"][0]["id"],
            "category": "喂食",
            "content": "给小黄添了菜叶",
            "duck_id": duck_id,
        }
    ]

    confirmed = client.put(
        f"/api/conversations/{third['conversation_id']}/review",
        json={
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
        },
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["review_status"] == "confirmed"

    growth = client.get("/api/analysis/growth", params={"child_id": child_id})
    assert growth.status_code == 200
    assert all(series["points"] == [{"date": detail["date"], "score": 5}] for series in growth.json()["dimensions"])

    child_page = client.get("/")
    teacher_page = client.get("/teacher.html")
    assert child_page.status_code == 200 and "鸭鸭日记本" in child_page.text
    assert teacher_page.status_code == 200 and "教师端" in teacher_page.text
