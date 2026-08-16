"""插入 demo 评估数据，让审阅/成长曲线/明细页面有可演示内容。

直接操作 SQLite 写入真实数据（含 conversations/messages/feeding_logs/
emotion_logs/assessments/assessment_scores），不调用 LLM。
"""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.backend import models
from app.backend.database import SessionLocal, engine
from app.backend.main import _seed_demo_data

# 先确保种子数据存在
_seed_demo_data()

db = SessionLocal()
try:
    child = db.scalar(select(models.Child).where(models.Child.nickname == "小明"))
    if not child:
        print("未找到小明，请先初始化种子")
        sys.exit(1)
    dims = {
        d.key: d
        for d in db.scalars(select(models.AssessmentDimension)).all()
    }

    # 已有则跳过
    existing = db.scalar(select(models.Conversation).where(models.Conversation.child_id == child.id))
    if existing:
        print("已存在 demo 评估数据，跳过插入")
        sys.exit(0)

    today = date.today()

    demo_data = [
        {
            "date": (today - timedelta(days=6)).isoformat(),
            "messages": [
                ("child", "今天我喂小鸭吃了青菜和米糠。"),
                ("diary", "小黄是不是很喜欢吃呀？"),
                ("child", "它吃得很香，还嘎嘎叫。"),
                ("diary", "听到小鸭开心叫，你心里怎样也呀？"),
                ("child", "我觉得很开心，因为我照顾它了。"),
            ],
            "feeding": [
                ("喂食", "喂小鸭吃青菜和米糠"),
                ("观察", "小鸭吃得很开心，还嘎嘎叫"),
            ],
            "emotion": ("开心", 5, "幼儿明确说照顾小鸭让他很开心"),
            "scores": [("language", 4, "幼儿清晰描述喂食过程和米糠种类"), ("empathy", 4, "关注小鸭的反应并表达自己的开心"), ("diligence", 5, "主动完成喂食任务")],
        },
        {
            "date": (today - timedelta(days=3)).isoformat(),
            "messages": [
                ("child", "今天我给小鸭换了干净的水。"),
                ("diary", "换水的时候小鸭有过来吗？"),
                ("child", "有！小黄过来看了我一下。"),
                ("diary", "你觉得它在看你吗？"),
                ("child", "嗯，我觉得它在谢谢我。"),
                ("diary", "你是个贴心的小朋友呢～"),
            ],
            "feeding": [
                ("清洁", "给小鸭换干净的水"),
                ("观察", "小黄好奇地凑过来看"),
            ],
            "emotion": ("满足", 4, "幼儿感受到小鸭的亲近"),
            "scores": [("language", 4, "能完整描述换水和小鸭互动"), ("empathy", 5, "主动揣摩小鸭在感谢自己"), ("diligence", 4, "主动换水，承担劳动")],
        },
        {
            "date": today.isoformat(),
            "messages": [
                ("child", "今天我给小鸭的窝清理了，还加了新稻草。"),
                ("diary", "小鸭住得舒服吗？"),
                ("child", "我觉得它睡得比昨天更香了。"),
            ],
            "feeding": [
                ("清洁", "清理小鸭的窝并加新稻草"),
                ("观察", "小鸭睡觉比昨天更安稳"),
            ],
            "emotion": ("自豪", 5, "幼儿对自己劳动成果很自豪"),
            "scores": [("language", 5, "表达连贯且使用'睡得更香'等生动描述"), ("empathy", 4, "关注小鸭的舒适度"), ("diligence", 5, "主动清洁并加新稻草")],
        },
    ]

    for day in demo_data:
        conv = models.Conversation(
            child_id=child.id, date=day["date"], status="ended",
            end_reason="complete", started_at=datetime.utcnow() - timedelta(days=2),
            ended_at=datetime.utcnow() - timedelta(days=2),
        )
        db.add(conv)
        db.flush()
        for role, text in day["messages"]:
            db.add(models.Message(conversation_id=conv.id, role=role, text=text))
        for cat, content in day["feeding"]:
            db.add(models.FeedingLog(
                conversation_id=conv.id, child_id=child.id,
                category=cat, content=content,
            ))
        emo, intensity, note = day["emotion"]
        db.add(models.EmotionLog(
            conversation_id=conv.id, child_id=child.id,
            emotion=emo, intensity=intensity, note=note,
        ))
        avg = sum(s[1] for s in day["scores"]) / len(day["scores"])
        assess = models.Assessment(
            conversation_id=conv.id, child_id=child.id,
            status="confirmed", overall=round(avg, 2),
        )
        db.add(assess)
        db.flush()
        for key, score, reason in day["scores"]:
            db.add(models.AssessmentScore(
                assessment_id=assess.id, dimension_id=dims[key].id,
                score=score, reason=reason,
            ))

    db.commit()
    print(f"✅ 已插入 {len(demo_data)} 个会话的 demo 评估数据（已确认状态）")
finally:
    db.close()