# 鸭鸭日记本 🦆

一款面向幼儿园的**个人教学辅助 Web 应用**。幼儿通过「按住说话」与 AI 角色「鸭鸭日记本」语音对话，记录饲养小鸭的过程；系统自动提炼饲养流水、情绪、心得，并对幼儿进行隐性的多维能力评估，教师端做数据沉淀与成长分析。

## 功能

- **幼儿端**：IP 形象（柯尔鸭）+ 全程语音引导 + 按住说话（PTT）+ 对话流 + 开场/结束动画，投影友好大字号
- **教师端**：幼儿/小鸭/排班管理、值日审阅（提炼修正 + 星级评分 + 确认）、能力成长曲线、明细检索
- **AI 引擎**：对话（角色扮演 + 轮次控制 + 提前终止 + 历史感知）、信息提炼、多维评估（打分 + 理由）、小鸭档案汇总
- **CrewAI 研发团队**：5 Crew 11 Agent + Flow 图工程编排（用于持续研发）

## 技术栈

| 层 | 选型 |
|---|---|
| 前端 | 原生 HTML/CSS/JS（零构建零 CDN，单机开箱即用） |
| 后端 | FastAPI + SQLAlchemy + SQLite |
| LLM | DeepSeek `deepseek-v4-pro`（OpenAI 兼容接口） |
| TTS | Edge-TTS（神经语音，失败降级浏览器 TTS） |
| ASR | 浏览器 Web Speech API |
| 研发编排 | CrewAI（5 Crew + Flow 图工程） |

## 快速开始

### macOS / Linux

```bash
cd pomegranagent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # 填入真实 DEEPSEEK_API_KEY
./run.sh                  # 或 uvicorn app.backend.main:app --port 8000
```

### Windows

```bat
cd pomegranagent
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env    # 填入真实 DEEPSEEK_API_KEY
run.bat                   # 双击，或 uvicorn app.backend.main:app --port 8000
```

启动后浏览器访问：

- **幼儿端**：http://localhost:8000/
- **教师端**：http://localhost:8000/teacher.html

> 首次启动自动插入示例数据（5 幼儿 / 3 小鸭 / 排班），便于开箱演示。

## 目录结构

```
pomegranagent/
├── app/
│   ├── backend/          # FastAPI 后端
│   │   ├── main.py       # 路由（含 /api/tts 等）
│   │   ├── models.py     # SQLAlchemy 数据模型
│   │   ├── schemas.py    # Pydantic 模型
│   │   ├── ai_engine.py  # 对话/提炼/评估/小鸭档案
│   │   └── database.py   # SQLite 连接
│   └── frontend/         # 幼儿端 + 教师端 + IP 素材
│       ├── index.html    # 幼儿端
│       ├── teacher.html  # 教师端
│       └── assets/       # 柯尔鸭 IP 素材
├── crews/                # CrewAI 研发团队（5 Crew）
├── flows/                # Flow 图工程编排
├── tests/                # 集成测试 + e2e + 截图
├── docs/                 # 需求/方案/评估报告
├── config/llm.py         # DeepSeek 集中配置
├── main.py               # CrewAI 流水线入口
├── run.sh / run.bat      # 一键启动脚本
└── requirements.txt
```

## 测试

```bash
pytest tests/test_api.py -q      # 集成测试（13 个）
python tests/e2e.py              # 端到端（真实 LLM）
python tests/screenshot.py       # Playwright 全页面截图
```

## 关键设计

- **AI 角色**：「鸭鸭日记本」——会说话的日记本，**不是**任何一只真实小鸭；小鸭是幼儿照顾的对象
- **对话机制**：一问一答算 1 轮，默认最大 3 轮；信息充分可提前终止；注入幼儿档案 + 近期摘要 + 小鸭档案营造「活人感」
- **评估**：AI 初评 + 教师确认，按次打分 + 周期汇总，幼儿全程无感知
- **语音**：Edge-TTS 神经语音（温柔女声）优先，失败自动降级浏览器 TTS

## 成本与安全

- **密钥**：`DEEPSEEK_API_KEY` 只放 `.env`（已 gitignore），勿提交
- **成本**：对话/提炼/评估均调用 DeepSeek，按量计费；V4 Pro 价格约为 Flash 的 3 倍
- **中文编码**：Windows 遇 GBK 报错时，运行前设 `PYTHONIOENCODING=utf-8`
