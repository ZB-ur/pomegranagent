"""鸭鸭日记本 FastAPI 后端应用入口。"""
from contextlib import asynccontextmanager
import hashlib
import logging
import time
from datetime import date, timedelta

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import ai_engine, auth, models, schemas
from .analysis_worker import AnalysisWorker
from .api_errors import APIError, install_api_error_handling
from .auth import require_teacher_session
from .business_time import BusinessClock
from .database import Base, DATABASE_PATH, DB_MODE, SETTINGS, SessionLocal, engine, get_db
from .http_boundary import install_same_origin_boundary
from .routes.conversations import router as conversations_router
from .routes.media import router as media_router
from .routes.reports import router as reports_router
from .routes.resources import router as resources_router
from .routes.roster import router as roster_router
from .routes.runtime import router as runtime_router
from .schema_migrations import ensure_database_schema
from .versioning import VERSION_FILE, load_runtime_version

RUNTIME_VERSION = load_runtime_version()
BUSINESS_CLOCK = BusinessClock(SETTINGS.business_timezone)
MEDIA_ROOT = SETTINGS.media_root
TTS_CACHE_DIR = SETTINGS.tts_cache_path

# 日志：同时输出到 logs/app.log 与控制台，便于排查
LOG_DIR = SETTINGS.log_path.parent
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(SETTINGS.log_path, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("duck_diary")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("runtime database: db_mode=%s path=%s", DB_MODE, DATABASE_PATH)
    if DB_MODE == "app":
        ensure_database_schema(engine, DB_MODE)
    else:
        Base.metadata.create_all(bind=engine)
    _seed_dimensions()
    if DB_MODE == "app":
        _seed_demo_data()
    factory = getattr(app.state, "analysis_worker_factory", None)
    worker = (
        factory()
        if callable(factory)
        else AnalysisWorker(session_factory=SessionLocal, analyzer=ai_engine)
    )
    worker.start()
    app.state.analysis_worker_status_provider = worker.status
    try:
        yield
    finally:
        worker.stop(timeout_seconds=5.0)
        app.state.analysis_worker_status_provider = lambda: "not_started"


app = FastAPI(title="鸭鸭日记本", version="1.0.0", lifespan=lifespan)
app.state.analysis_worker_status_provider = lambda: "not_started"

install_api_error_handling(app)
install_same_origin_boundary(app)
app.include_router(auth.router)
app.include_router(conversations_router)
app.include_router(media_router)
app.include_router(reports_router)
app.include_router(resources_router)
app.include_router(roster_router)
app.include_router(runtime_router)


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

        today = seed_date or BUSINESS_CLOCK.business_today()
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


# ---------------- 提炼与评估 ----------------
@app.post("/api/conversations/{conversation_id}/finalize")
def finalize(conversation_id: int) -> None:
    """Public compatibility tombstone for the retired mutating child finalizer."""
    del conversation_id
    raise APIError(410, "LEGACY_ENDPOINT_REMOVED", "旧会话结束接口已下线")


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
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    raise APIError(410, "LEGACY_ENDPOINT_REMOVED", "旧审阅接口已下线")


# ---------------- 流水/情绪修正 ----------------
@app.patch("/api/conversations/{conv_id}/logs")
def patch_logs(
    conv_id: int,
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    raise APIError(410, "LEGACY_ENDPOINT_REMOVED", "旧审阅接口已下线")


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
