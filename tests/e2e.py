"""端到端验证：进程内启动应用 + 真实 LLM，跑通核心链路。"""
import os
import sys
import tempfile
from pathlib import Path

if os.environ.get("RUN_REAL_INTEGRATION") != "1":
    raise SystemExit("set RUN_REAL_INTEGRATION=1 to run real LLM/TTS integration")

E2E_RUNTIME_DIR = tempfile.TemporaryDirectory(prefix="duck-diary-e2e-")
os.environ["APP_DB_MODE"] = "test"
os.environ["APP_DB_PATH"] = str(Path(E2E_RUNTIME_DIR.name) / "e2e.db")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.backend.database import Base, engine  # noqa: E402
from app.backend.main import _seed_dimensions, app  # noqa: E402


def step(name, ok):
    print(("✅" if ok else "❌") + " " + name)


try:
    # 清库重建，保证 e2e 从干净状态开始
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    _seed_dimensions()

    with TestClient(app) as client:
        print("=== 端到端验证（真实 LLM）===")

        # 1. 幼儿与小鸭
        child = client.post("/api/children", json={"name": "测试幼儿", "nickname": "小测"}).json()
        step("创建幼儿", bool(child.get("id")))
        duck = client.post("/api/ducks", json={"name": "小黄", "status": "活泼健康"}).json()
        step("创建小鸭", bool(duck.get("id")))

        # 2. 排班
        for i in range(3):
            client.post("/api/children", json={"name": f"幼儿{i}", "nickname": f"娃{i}"})
        roster = client.post("/api/roster/auto", json={"start_date": "2026-08-17", "days": 5, "cycle": "第1周"}).json()
        step("自动排班（5 个工作日）", len(roster.get("schedule", [])) == 5)

        # 3. 真实多轮对话（3 轮 → 触发 max_rounds 结束）
        conv_id = None
        ended = False
        talks = ["我今天喂了小鸭，给它们吃了青菜", "我还给它们换了干净的水", "我看到小鸭在水里游来游去很开心"]
        for i, t in enumerate(talks, 1):
            r = client.post("/api/chat", json={"child_id": child["id"], "text": t, "conversation_id": conv_id})
            d = r.json()
            conv_id = d["conversation_id"]
            ended = d["ended"]
            print(f"    第{i}轮 日记本：{d['reply'][:48]}...")
            step(f"对话第 {i} 轮", bool(d["reply"]))
        step("第 3 轮触发 max_rounds 结束", ended)

        # 4. 提炼 + 评估（真实 LLM）
        fin = client.post(f"/api/conversations/{conv_id}/finalize").json()
        step("提炼流水/情绪 + 评估初评", bool(fin.get("assessment_id")))

        detail = client.get(f"/api/conversations/{conv_id}").json()
        step("提炼出饲养流水", len(detail.get("feeding_logs", [])) >= 1)
        step("提炼出情绪", detail.get("emotion") is not None)
        print("    情绪：", detail.get("emotion"))
        print("    流水：", [f["category"] + "·" + f["content"] for f in detail.get("feeding_logs", [])])
        for s in detail["assessment"]["scores"]:
            print(f"    维度[{s['dimension_name']}]={s['score']}分：{s['reason'][:40]}...")

        # 5. 确认评估
        aid = detail["assessment"]["id"]
        scores = {s["dimension_id"]: {"score": s["score"]} for s in detail["assessment"]["scores"]}
        conf = client.post(f"/api/assessments/{aid}/confirm", json={"scores": scores}).json()
        step("确认评估", conf.get("ok"))

        # 6. 成长曲线
        g = client.get(f"/api/analysis/growth?child_id={child['id']}").json()
        step("成长曲线数据（3 维度）", len(g.get("dimensions", [])) == 3)

        # 7. 前端页面可访问
        r1 = client.get("/")
        r2 = client.get("/teacher.html")
        step("幼儿端页面可访问", r1.status_code == 200 and "鸭鸭日记本" in r1.text)
        step("教师端页面可访问", r2.status_code == 200 and "教师端" in r2.text)

        print("\n===== e2e 全链路通过 =====")
finally:
    E2E_RUNTIME_DIR.cleanup()
