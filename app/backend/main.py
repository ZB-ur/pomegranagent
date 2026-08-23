"""鸭鸭日记本 FastAPI 后端应用入口。"""
from contextlib import asynccontextmanager
import hashlib
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import ai_engine, auth, models, schemas
from .api_errors import install_api_error_handling
from .auth import require_teacher_session
from .database import Base, DATABASE_PATH, DB_MODE, SessionLocal, engine, get_db
from .http_boundary import install_same_origin_boundary
from .routes.conversations import router as conversations_router
from .versioning import VERSION_FILE, load_runtime_version

RUNTIME_VERSION = load_runtime_version()

# 日志：同时输出到 logs/app.log 与控制台，便于排查
LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("duck_diary")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("runtime database: db_mode=%s path=%s", DB_MODE, DATABASE_PATH)
    Base.metadata.create_all(bind=engine)
    _seed_dimensions()
    if DB_MODE == "app":
        _seed_demo_data()
    yield


app = FastAPI(title="鸭鸭日记本", version="1.0.0", lifespan=lifespan)
app.state.analysis_worker_status_provider = lambda: "not_started"

install_api_error_handling(app)
install_same_origin_boundary(app)
app.include_router(auth.router)
app.include_router(conversations_router)


@app.get("/api/health", response_model=schemas.HealthResponse)
def health(request: Request):
    return {
        "release_id": RUNTIME_VERSION.release_id,
        "api_version": RUNTIME_VERSION.api_version,
        "schema_version": RUNTIME_VERSION.schema_version,
        "db_mode": DB_MODE,
        "analysis_worker_status": request.app.state.analysis_worker_status_provider(),
    }


@app.get("/version.json", response_model=schemas.VersionResponse)
def version_manifest():
    current = load_runtime_version(VERSION_FILE)
    return JSONResponse(current.__dict__, headers={"Cache-Control": "no-store"})


def _seed_dimensions(session_factory=SessionLocal) -> None:
    defaults = [
        ("language", "语言表达能力", "能清晰、连贯地表达自己的观察与感受"),
        ("empathy", "同理心", "能体会并关心小鸭与同伴的感受"),
        ("diligence", "勤劳启蒙", "积极参与饲养劳动并承担责任"),
    ]
    db = session_factory()
    try:
        for key, name, description in defaults:
            if not db.scalar(select(models.AssessmentDimension).where(models.AssessmentDimension.key == key)):
                db.add(models.AssessmentDimension(key=key, name=name, description=description))
        db.commit()
    finally:
        db.close()


def _seed_demo_data(session_factory=SessionLocal, seed_date: date | None = None) -> None:
    """首次启动且数据库空时，插入示例幼儿/小鸭/排班，便于开箱演示。"""
    db = session_factory()
    try:
        if db.scalar(select(models.Child)) or db.scalar(select(models.Duck)):
            return  # 已有数据则不重复插入
        children = [
            ("王小明", "小明"),
            ("李小红", "小红"),
            ("张小华", "小华"),
            ("赵小乐", "小乐"),
            ("陈小宝", "小宝"),
        ]
        ducks = [
            ("小黄", "活泼健康，喜欢在水中嬉戏"),
            ("小白", "性格温和，喜欢吃菜叶"),
            ("小橙", "好奇心强，喜欢探索"),
        ]
        for name, nickname in children:
            db.add(models.Child(name=name, nickname=nickname, active=True))
        for name, status in ducks:
            db.add(models.Duck(name=name, status=status))
        db.commit()

        today = seed_date or date.today()
        child_ids = [
            child.id
            for child in db.scalars(select(models.Child).order_by(models.Child.id)).all()
        ]
        cycle = f"示例-{today.isocalendar().week}周"
        roster_date = today
        index = 0
        for _day in range(7):
            while roster_date.weekday() >= 5:
                roster_date += timedelta(days=1)
            for offset in range(2):
                db.add(models.DutyRoster(
                    cycle=cycle,
                    date=roster_date.isoformat(),
                    child_id=child_ids[(index + offset) % len(child_ids)],
                ))
            index += 2
            roster_date += timedelta(days=1)
        db.commit()
    finally:
        db.close()


# ---------------- 幼儿 ----------------
@app.get("/api/children", response_model=list[schemas.ChildOut])
def list_children(
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    return db.scalars(select(models.Child).order_by(models.Child.id)).all()


@app.post("/api/children", response_model=schemas.ChildOut)
def create_child(
    payload: schemas.ChildCreate,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    child = models.Child(**payload.model_dump())
    db.add(child)
    db.commit()
    db.refresh(child)
    return child


@app.put("/api/children/{child_id}", response_model=schemas.ChildOut)
def update_child(
    child_id: int,
    payload: schemas.ChildCreate,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    child = db.get(models.Child, child_id)
    if not child:
        raise HTTPException(404, "幼儿不存在")
    for k, v in payload.model_dump().items():
        setattr(child, k, v)
    db.commit()
    db.refresh(child)
    return child


@app.delete("/api/children/{child_id}")
def delete_child(
    child_id: int,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    child = db.get(models.Child, child_id)
    if not child:
        raise HTTPException(404, "幼儿不存在")
    db.delete(child)
    db.commit()
    return {"ok": True}


# ---------------- 小鸭 ----------------
@app.get("/api/ducks", response_model=list[schemas.DuckOut])
def list_ducks(
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    return db.scalars(select(models.Duck).order_by(models.Duck.id)).all()


@app.post("/api/ducks", response_model=schemas.DuckOut)
def create_duck(
    payload: schemas.DuckCreate,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    duck = models.Duck(**payload.model_dump())
    db.add(duck)
    db.commit()
    db.refresh(duck)
    return duck


@app.put("/api/ducks/{duck_id}", response_model=schemas.DuckOut)
def update_duck(
    duck_id: int,
    payload: schemas.DuckCreate,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    duck = db.get(models.Duck, duck_id)
    if not duck:
        raise HTTPException(404, "小鸭不存在")
    for k, v in payload.model_dump().items():
        setattr(duck, k, v)
    db.commit()
    db.refresh(duck)
    return duck


@app.delete("/api/ducks/{duck_id}")
def delete_duck(
    duck_id: int,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    duck = db.get(models.Duck, duck_id)
    if not duck:
        raise HTTPException(404, "小鸭不存在")
    db.delete(duck)
    db.commit()
    return {"ok": True}


# ---------------- 排班 ----------------
@app.get("/api/roster")
def list_roster(
    cycle: str | None = None,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    q = select(models.DutyRoster).order_by(models.DutyRoster.date)
    if cycle:
        q = q.where(models.DutyRoster.cycle == cycle)
    rows = db.scalars(q).all()
    return [
        {"id": r.id, "cycle": r.cycle, "date": r.date, "child_id": r.child_id}
        for r in rows
    ]


@app.get("/api/roster/today")
def today_roster(db: Session = Depends(get_db)):
    """今日值日生（含幼儿信息）。无排班返回空列表，前端降级展示全部幼儿。"""
    today = date.today().isoformat()
    rows = db.scalars(
        select(models.DutyRoster).where(models.DutyRoster.date == today).order_by(models.DutyRoster.id)
    ).all()
    children = []
    for r in rows:
        c = db.get(models.Child, r.child_id)
        if c:
            children.append({"id": c.id, "name": c.name, "nickname": c.nickname, "avatar": c.avatar})
    return children


@app.post("/api/roster")
def set_roster(
    payload: schemas.RosterIn,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    # 删除该日期旧排班，写入新排班
    for old in db.scalars(select(models.DutyRoster).where(models.DutyRoster.date == payload.date)).all():
        db.delete(old)
    for cid in payload.child_ids:
        db.add(models.DutyRoster(cycle=payload.cycle, date=payload.date, child_id=cid))
    db.commit()
    return {"ok": True, "date": payload.date, "child_ids": payload.child_ids}


@app.post("/api/roster/auto")
def auto_roster(
    payload: dict,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    """自动轮值：从 start_date 起，每个工作日 2 名幼儿按名单顺序轮转。"""
    child_ids = [c.id for c in db.scalars(select(models.Child).where(models.Child.active == True).order_by(models.Child.id)).all()]
    start = date.fromisoformat(payload["start_date"])
    days = int(payload.get("days", 10))
    cycle = payload.get("cycle", "auto")
    created = []
    idx = 0
    d = start
    for _ in range(days):
        while d.weekday() >= 5:  # 跳过周末
            d += timedelta(days=1)
        pair = [child_ids[(idx + j) % len(child_ids)] for j in range(2)]
        for cid in pair:
            db.add(models.DutyRoster(cycle=cycle, date=d.isoformat(), child_id=cid))
        created.append({"date": d.isoformat(), "child_ids": pair})
        idx += 2
        d += timedelta(days=1)
    db.commit()
    return {"ok": True, "schedule": created}


# ---------------- 能力维度 ----------------
@app.get("/api/dimensions")
def list_dimensions(
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    rows = db.scalars(select(models.AssessmentDimension).order_by(models.AssessmentDimension.id)).all()
    return [
        {"id": r.id, "key": r.key, "name": r.name, "enabled": r.enabled, "weight": r.weight, "description": r.description}
        for r in rows
    ]


@app.post("/api/dimensions")
def create_dimension(
    payload: dict,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    dim = models.AssessmentDimension(
        key=payload["key"], name=payload["name"],
        description=payload.get("description"), enabled=payload.get("enabled", True),
    )
    db.add(dim)
    db.commit()
    db.refresh(dim)
    return {"id": dim.id, "key": dim.key, "name": dim.name}


@app.put("/api/dimensions/{dim_id}")
def update_dimension(
    dim_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    dim = db.get(models.AssessmentDimension, dim_id)
    if not dim:
        raise HTTPException(404, "维度不存在")
    for k in ("name", "enabled", "weight", "description"):
        if k in payload:
            setattr(dim, k, payload[k])
    db.commit()
    return {"ok": True}


# ---------------- 会话 ---------------- 
@app.get("/api/conversations")
def list_conversations(
    child_id: int | None = None,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    q = select(models.Conversation).order_by(models.Conversation.id.desc())
    if child_id:
        q = q.where(models.Conversation.child_id == child_id)
    rows = db.scalars(q).all()
    return [
        {
            "id": c.id, "child_id": c.child_id, "date": c.date,
            "status": c.status, "end_reason": c.end_reason,
            "started_at": c.started_at.isoformat() if c.started_at else None,
        }
        for c in rows
    ]


@app.get("/api/conversations/{conv_id}")
def get_conversation(
    conv_id: int,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    conv = db.get(models.Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "会话不存在")
    messages = [
        {"id": m.id, "role": m.role, "text": m.text}
        for m in sorted(conv.messages, key=lambda x: x.id)
    ]
    feeding = [
        {"id": f.id, "category": f.category, "content": f.content, "duck_id": f.duck_id}
        for f in db.scalars(select(models.FeedingLog).where(models.FeedingLog.conversation_id == conv_id)).all()
    ]
    emotion = db.scalar(select(models.EmotionLog).where(models.EmotionLog.conversation_id == conv_id))
    insight = db.scalar(select(models.InsightNote).where(models.InsightNote.conversation_id == conv_id))
    assessment = db.scalar(select(models.Assessment).where(models.Assessment.conversation_id == conv_id))
    scores = []
    if assessment:
        for s in db.scalars(select(models.AssessmentScore).where(models.AssessmentScore.assessment_id == assessment.id)).all():
            dim = db.get(models.AssessmentDimension, s.dimension_id)
            scores.append({"dimension_id": s.dimension_id, "dimension_name": dim.name if dim else "", "score": s.score, "reason": s.reason})

    return {
        "id": conv.id, "child_id": conv.child_id, "date": conv.date,
        "status": conv.status, "end_reason": conv.end_reason,
        "messages": messages, "feeding_logs": feeding,
        "emotion": {"emotion": emotion.emotion, "intensity": emotion.intensity, "note": emotion.note} if emotion else None,
        "insight": insight.content if insight else None,
        "assessment": {
            "id": assessment.id, "status": assessment.status, "overall": assessment.overall, "scores": scores,
        } if assessment else None,
    }


# ---------------- 提炼与评估 ----------------
@app.post("/api/conversations/{conv_id}/finalize")
def finalize(conv_id: int, db: Session = Depends(get_db)):
    """会话结束后：提炼流水/情绪 + 生成能力评估初评。"""
    conv = db.get(models.Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "会话不存在")

    transcript = "\n".join(f"{'幼儿' if m.role == 'child' else '日记本'}：{m.text}" for m in sorted(conv.messages, key=lambda x: x.id))
    conv.status = "ended"
    if not conv.end_reason:
        conv.end_reason = "manual"
    conv.ended_at = datetime.utcnow()

    # 提炼
    try:
        info = ai_engine.extract_info(transcript)
    except Exception:
        info = {"feeding_logs": [], "emotion": {"emotion": "平静", "intensity": 3, "note": ""}, "insight": ""}

    for log in info.get("feeding_logs", []):
        duck_id = None
        if log.get("duck_name"):
            d = db.scalar(select(models.Duck).where(models.Duck.name == log["duck_name"]))
            duck_id = d.id if d else None
        db.add(models.FeedingLog(
            conversation_id=conv_id, child_id=conv.child_id, duck_id=duck_id,
            category=log.get("category", "其它"), content=log.get("content", ""),
        ))
    emo = info.get("emotion", {})
    db.add(models.EmotionLog(
        conversation_id=conv_id, child_id=conv.child_id,
        emotion=emo.get("emotion", "平静"), intensity=emo.get("intensity", 3), note=emo.get("note"),
    ))

    # 心得/亮点落库（若提炼出非空 insight）
    insight_text = (info.get("insight") or "").strip()
    if insight_text:
        db.add(models.InsightNote(conversation_id=conv_id, child_id=conv.child_id, content=insight_text))

    # 评估初评
    dims = [
        {"key": d.key, "name": d.name, "description": d.description}
        for d in db.scalars(select(models.AssessmentDimension).where(models.AssessmentDimension.enabled == True)).all()
    ]
    try:
        assess = ai_engine.assess_conversation(transcript, dims)
    except Exception:
        assess = {"scores": [], "overall": 3.0}

    assessment = models.Assessment(conversation_id=conv_id, child_id=conv.child_id, status="pending", overall=assess.get("overall", 3.0))
    db.add(assessment)
    db.commit()
    db.refresh(assessment)

    key_to_id = {d["key"]: d_id for d_id, d in ((d.id, {"key": d.key}) for d in db.scalars(select(models.AssessmentDimension)).all())}
    for s in assess.get("scores", []):
        dim_id = key_to_id.get(s.get("dimension_key"))
        if dim_id:
            db.add(models.AssessmentScore(assessment_id=assessment.id, dimension_id=dim_id, score=s.get("score", 3), reason=s.get("reason")))

    db.commit()
    return {"ok": True, "assessment_id": assessment.id, "insight": info.get("insight", "")}


# ---------------- 评估审阅 ----------------
@app.get("/api/assessments")
def list_assessments(
    status: str | None = None,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    q = select(models.Assessment).order_by(models.Assessment.id.desc())
    if status:
        q = q.where(models.Assessment.status == status)
    return [{"id": a.id, "conversation_id": a.conversation_id, "child_id": a.child_id, "status": a.status, "overall": a.overall} for a in db.scalars(q).all()]


@app.post("/api/assessments/{assessment_id}/confirm")
def confirm_assessment(
    assessment_id: int,
    payload: schemas.AssessmentConfirm,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    assessment = db.get(models.Assessment, assessment_id)
    if not assessment:
        raise HTTPException(404, "评估不存在")
    if payload.scores:
        for dim_id, patch in payload.scores.items():
            row = db.scalar(select(models.AssessmentScore).where(
                models.AssessmentScore.assessment_id == assessment_id,
                models.AssessmentScore.dimension_id == dim_id,
            ))
            if row:
                if patch.score is not None:
                    row.score = patch.score
                if patch.reason is not None:
                    row.reason = patch.reason
    assessment.status = "confirmed"
    # 重算 overall
    scores = db.scalars(select(models.AssessmentScore).where(models.AssessmentScore.assessment_id == assessment_id)).all()
    if scores:
        assessment.overall = round(sum(s.score for s in scores) / len(scores), 2)
    db.commit()
    return {"ok": True, "overall": assessment.overall}


# ---------------- 流水/情绪修正 ----------------
@app.patch("/api/conversations/{conv_id}/logs")
def patch_logs(
    conv_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    if "feeding_logs" in payload:
        for item in payload["feeding_logs"]:
            row = db.get(models.FeedingLog, item.get("id"))
            if row:
                if "category" in item:
                    row.category = item["category"]
                if "content" in item:
                    row.content = item["content"]
    if "emotion" in payload:
        emo = payload["emotion"]
        row = db.scalar(select(models.EmotionLog).where(models.EmotionLog.conversation_id == conv_id))
        if row:
            if "emotion" in emo:
                row.emotion = emo["emotion"]
            if "intensity" in emo:
                row.intensity = emo["intensity"]
    db.commit()
    return {"ok": True}


# ---------------- 小鸭档案 ----------------
@app.get("/api/ducks/{duck_id}/archive")
def get_archive(
    duck_id: int,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    row = db.scalar(select(models.DuckArchive).where(models.DuckArchive.duck_id == duck_id))
    return {"duck_id": duck_id, "summary": row.summary if row else None}


@app.post("/api/ducks/{duck_id}/summarize")
def summarize(
    duck_id: int,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    duck = db.get(models.Duck, duck_id)
    if not duck:
        raise HTTPException(404, "小鸭不存在")
    texts = [
        f.content
        for f in db.scalars(select(models.FeedingLog).where(models.FeedingLog.duck_id == duck_id)).all()
    ]
    summary = ai_engine.summarize_duck(duck.name, texts)
    row = db.scalar(select(models.DuckArchive).where(models.DuckArchive.duck_id == duck_id))
    if row:
        row.summary = summary
    else:
        db.add(models.DuckArchive(duck_id=duck_id, summary=summary))
    db.commit()
    return {"duck_id": duck_id, "summary": summary}


@app.put("/api/ducks/{duck_id}/archive")
def update_archive(
    duck_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    row = db.scalar(select(models.DuckArchive).where(models.DuckArchive.duck_id == duck_id))
    if row:
        row.summary = payload.get("summary")
    else:
        db.add(models.DuckArchive(duck_id=duck_id, summary=payload.get("summary")))
    db.commit()
    return {"ok": True}


# ---------------- 语音合成（Edge-TTS） ----------------
TTS_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "tts_cache"


@app.get("/api/tts")
async def tts(text: str):
    """Edge-TTS 神经语音合成，返回 mp3 音频流。按文本哈希缓存，失败降级由前端处理。"""
    t0 = time.time()
    text = (text or "").strip()
    if not text:
        raise HTTPException(400, "text 不能为空")
    if len(text) > 500:
        text = text[:500]

    # 缓存：相同文本直接返回已合成 mp3（秒回，避免重复合成）
    cache_key = hashlib.md5(text.encode("utf-8")).hexdigest()
    cache_file = TTS_CACHE_DIR / f"{cache_key}.mp3"
    if cache_file.exists():
        logger.info("tts 缓存命中: text=%r", text[:50])
        return Response(content=cache_file.read_bytes(), media_type="audio/mpeg")

    try:
        import edge_tts
        communicate = edge_tts.Communicate(
            text, "zh-CN-XiaoxiaoNeural", rate="+0%", pitch="+5Hz"
        )
        audio = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
        if not audio:
            logger.error("tts 合成结果为空: text=%r", text[:50])
            raise HTTPException(502, "TTS 合成结果为空")
        logger.info("tts 完成: 耗时=%.2fs 字节=%d text=%r", time.time() - t0, len(audio), text[:50])
        TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(bytes(audio))
        return Response(content=bytes(audio), media_type="audio/mpeg")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error("tts 失败: %s text=%r", e, text[:50])
        raise HTTPException(502, f"TTS 合成失败：{e}")


# ---------------- 成长曲线分析 ----------------
@app.get("/api/analysis/growth")
def growth_analysis(
    child_id: int,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    """按时间返回该幼儿各维度的评估分数序列（成长曲线）。"""
    assessments = db.scalars(
        select(models.Assessment).where(
            models.Assessment.child_id == child_id,
            models.Assessment.status == "confirmed",
        ).order_by(models.Assessment.id)
    ).all()

    dims = db.scalars(select(models.AssessmentDimension).where(models.AssessmentDimension.enabled == True)).all()
    series = {d.id: {"key": d.key, "name": d.name, "points": []} for d in dims}

    for a in assessments:
        conv = db.get(models.Conversation, a.conversation_id)
        label = conv.date if conv else str(a.id)
        for s in db.scalars(select(models.AssessmentScore).where(models.AssessmentScore.assessment_id == a.id)).all():
            if s.dimension_id in series:
                series[s.dimension_id]["points"].append({"date": label, "score": s.score})

    return {"child_id": child_id, "dimensions": list(series.values())}


@app.get("/api/analysis/overview")
def overview(
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    children = db.scalars(select(models.Child).order_by(models.Child.id)).all()
    result = []
    for c in children:
        convs = db.scalars(select(models.Conversation).where(models.Conversation.child_id == c.id)).all()
        assessments = db.scalars(select(models.Assessment).where(models.Assessment.child_id == c.id, models.Assessment.status == "confirmed")).all()
        latest = assessments[-1].overall if assessments else None
        result.append({"child_id": c.id, "name": c.name, "nickname": c.nickname, "conversations": len(convs), "latest_overall": latest})
    return result


# 前端静态托管（生产：由 uvicorn 直接托管 app/frontend）
FRONTEND_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
