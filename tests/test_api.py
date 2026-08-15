"""后端集成测试（mock LLM，确定性验证 API 逻辑与数据流）。"""
import os
import sys
from pathlib import Path

# 确保项目根在 sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.backend import ai_engine  # noqa: E402
from app.backend.database import Base, engine  # noqa: E402
from app.backend.main import app  # noqa: E402


def _mock_chat_reply(**kwargs):
    return {"reply": "真棒！还有呢？", "ended": False, "end_reason": None}


def _mock_extract(transcript):
    return {
        "feeding_logs": [{"category": "喂食", "content": "给鸭子喂了菜叶", "duck_name": None}],
        "emotion": {"emotion": "开心", "intensity": 4, "note": "语气积极"},
        "insight": "主动描述喂食过程",
    }


def _mock_assess(transcript, dimensions):
    return {
        "scores": [
            {"dimension_key": d["key"], "score": 4, "reason": "幼儿说" + d["key"]}
            for d in dimensions
        ],
        "overall": 4.0,
    }


def setup_function():
    # 每次测试重建表，隔离数据
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    from app.backend.main import _seed_dimensions
    _seed_dimensions()


client = TestClient(app)


def test_dimensions_seeded():
    r = client.get("/api/dimensions")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 3
    assert {d["key"] for d in data} == {"language", "empathy", "diligence"}


def test_child_crud():
    r = client.post("/api/children", json={"name": "王小明", "nickname": "小明"})
    assert r.status_code == 200
    cid = r.json()["id"]
    assert r.json()["nickname"] == "小明"

    r = client.get("/api/children")
    assert len(r.json()) == 1

    r = client.put(f"/api/children/{cid}", json={"name": "王小明", "nickname": "明明", "active": True})
    assert r.json()["nickname"] == "明明"

    r = client.delete(f"/api/children/{cid}")
    assert r.json()["ok"] is True


def test_duck_crud():
    r = client.post("/api/ducks", json={"name": "小黄", "status": "活泼健康"})
    assert r.status_code == 200
    did = r.json()["id"]
    assert client.get("/api/ducks").json()[0]["name"] == "小黄"
    client.delete(f"/api/ducks/{did}")


def test_roster_auto(monkeypatch):
    for i in range(6):
        client.post("/api/children", json={"name": f"幼儿{i}"})
    r = client.post("/api/roster/auto", json={"start_date": "2026-08-17", "days": 5, "cycle": "第1周"})
    assert r.status_code == 200
    schedule = r.json()["schedule"]
    assert len(schedule) == 5  # 5 个工作日
    for s in schedule:
        assert len(s["child_ids"]) == 2


def test_chat_flow(monkeypatch):
    monkeypatch.setattr(ai_engine, "chat_reply", _mock_chat_reply)
    cid = client.post("/api/children", json={"name": "王小明", "nickname": "小明"}).json()["id"]

    # 第一轮
    r = client.post("/api/chat", json={"child_id": cid, "text": "我今天喂了小鸭"})
    assert r.status_code == 200
    data = r.json()
    assert data["reply"] == "真棒！还有呢？"
    assert data["ended"] is False
    conv_id = data["conversation_id"]

    # 继续会话
    r = client.post("/api/chat", json={"child_id": cid, "text": "还给它们换了水", "conversation_id": conv_id})
    assert r.json()["conversation_id"] == conv_id
    assert r.json()["round"] == 2

    # 会话明细
    detail = client.get(f"/api/conversations/{conv_id}").json()
    assert len(detail["messages"]) == 4  # 2 问 2 答


def test_chat_max_rounds(monkeypatch):
    monkeypatch.setattr(ai_engine, "chat_reply", _mock_chat_reply)
    cid = client.post("/api/children", json={"name": "李小红"}).json()["id"]
    conv_id = None
    # 打满 3 轮
    for i in range(3):
        r = client.post("/api/chat", json={"child_id": cid, "text": f"话{i}", "conversation_id": conv_id})
        conv_id = r.json()["conversation_id"]
        if i == 2:
            # 第 3 轮已触发强制结束
            assert r.json()["ended"] is True
            assert r.json()["end_reason"] == "max_rounds"


def test_finalize_and_assessment(monkeypatch):
    monkeypatch.setattr(ai_engine, "chat_reply", _mock_chat_reply)
    monkeypatch.setattr(ai_engine, "extract_info", _mock_extract)
    monkeypatch.setattr(ai_engine, "assess_conversation", _mock_assess)

    cid = client.post("/api/children", json={"name": "王小明", "nickname": "小明"}).json()["id"]
    r = client.post("/api/chat", json={"child_id": cid, "text": "我喂了小鸭"})
    conv_id = r.json()["conversation_id"]

    # 手动结束并提炼评估
    fr = client.post(f"/api/conversations/{conv_id}/finalize")
    assert fr.status_code == 200
    assert fr.json()["assessment_id"] > 0

    detail = client.get(f"/api/conversations/{conv_id}").json()
    assert len(detail["feeding_logs"]) == 1
    assert detail["emotion"]["emotion"] == "开心"
    assert detail["assessment"]["status"] == "pending"
    assert len(detail["assessment"]["scores"]) == 3

    # 确认评估
    aid = detail["assessment"]["id"]
    dims = client.get("/api/dimensions").json()
    scores = {d["id"]: {"score": 5} for d in dims}
    cr = client.post(f"/api/assessments/{aid}/confirm", json={"scores": scores})
    assert cr.json()["ok"] is True

    # 成长曲线
    g = client.get(f"/api/analysis/growth?child_id={cid}").json()
    assert len(g["dimensions"]) == 3
    for dim in g["dimensions"]:
        assert dim["points"][0]["score"] == 5


def test_frontend_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "鸭鸭日记本" in r.text


def test_teacher_served():
    r = client.get("/teacher.html")
    assert r.status_code == 200
