# 鸭鸭日记本 🦆

面向幼儿园真实值日场景的个人教学辅助 Web 应用。幼儿和会说话的「鸭鸭日记本」完成语音对话，记录照护小鸭的经历；系统把自然表达整理成可审阅的日记与能力观察，最终由教师确认并沉淀为成长记录。

<p align="center">
  <a href="docs/manual/assets/20260905T220349410323Z-8ed37c2232ab-f24bfb9ef129/child-avatar-selected.png">
    <img src="docs/manual/assets/20260905T220349410323Z-8ed37c2232ab-f24bfb9ef129/child-avatar-selected.png" width="960" alt="幼儿端进入会话后的准备状态">
  </a>
</p>

## 核心体验

### 幼儿自然表达

当天值日幼儿进入会话后，点一下开始说话、再次点击结束。鸭鸭日记本的 IP 形象贯穿流程，界面以大字号、语音引导和明确状态呈现操作与系统反馈；对话对象始终是「鸭鸭日记本」，小鸭则是幼儿照护和记录的对象。

<p align="center">
  <a href="docs/manual/assets/20260905T220349410323Z-8ed37c2232ab-f24bfb9ef129/child-conversation-complete.png">
    <img src="docs/manual/assets/20260905T220349410323Z-8ed37c2232ab-f24bfb9ef129/child-conversation-complete.png" width="960" alt="幼儿端三轮对话完成状态">
  </a>
</p>

### 教师审阅确认

系统异步提炼饲养流水、情绪和心得，并生成带理由的能力观察。教师可以对完整结构化结果进行修改、保存草稿和最终确认；原始会话、当前分析版本与确认状态可以相互核对。

<p align="center">
  <a href="docs/manual/assets/20260905T220349410323Z-8ed37c2232ab-f24bfb9ef129/teacher-review-confirmed.png">
    <img src="docs/manual/assets/20260905T220349410323Z-8ed37c2232ab-f24bfb9ef129/teacher-review-confirmed.png" width="1000" alt="教师端日记审阅与确认">
  </a>
</p>

### 成长沉淀

教师端提供周度概览、能力成长曲线和历史明细检索，让已确认的日记从单次记录转化为可持续观察的成长线索。

<p align="center">
  <a href="docs/manual/assets/20260905T220349410323Z-8ed37c2232ab-f24bfb9ef129/teacher-weekly-growth.png">
    <img src="docs/manual/assets/20260905T220349410323Z-8ed37c2232ab-f24bfb9ef129/teacher-weekly-growth.png" width="880" alt="教师端幼儿能力成长曲线">
  </a>
</p>

## 已实现能力

- **幼儿端**：值日幼儿选择、点击式录音、浏览器语音识别、三轮上下文对话、语音播放、断网/刷新恢复和明确的完成状态。
- **教师端**：今日任务、幼儿与小鸭资料管理、头像上传、月度搭档排班、单日临时调班、分析队列、日记审阅确认、周报、成长曲线和组合条件检索。
- **服务端**：FastAPI API、SQLite 持久化、Schema 迁移、幂等写入、并发租约、后台分析任务、版本化审阅、头像媒体存储和安全的演示数据重建。
- **AI 与语音**：DeepSeek OpenAI 兼容接口；Edge-TTS 优先，失败时降级为浏览器 TTS。

## 快速开始

### 1. 安装

macOS / Linux：

```bash
cd pomegranagent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Windows：

```bat
cd pomegranagent
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

在 `.env` 中配置 `DEEPSEEK_API_KEY`。

### 2. 初始化数据（可选）

需要空白环境时直接跳到第 3 步；普通启动只幂等创建参考评估维度，不会自动创建幼儿、小鸭或演示记录。需要完整演示环境时，必须在首次启动服务前执行下面的初始化。

<details>
<summary><strong>创建完整演示数据</strong></summary>

首次创建会离线生成合成幼儿、小鸭、排班、历史会话、分析/审阅投影和本地头像，不会调用 AI/TTS，也不会设置教师 PIN。

```bash
python scripts/seed_demo_database.py full-demo \
  --anchor-date 2026-09-02 \
  --database data/duck_diary.db \
  --media-root data/media \
  --log-path logs/app.log
```

如果任一目标数据库、WAL/SHM、媒体或日志已经存在，不要继续运行首次初始化，也不要在服务运行时直接追加 `--force`；请停止服务并使用下面的安全重建流程。

</details>

<details>
<summary><strong>安全地重建现有演示数据</strong></summary>

先停止服务并确认健康检查连接失败。重建工具会先在 staging 中生成和校验新 bundle，再归档旧数据库及 sidecar、媒体和日志；安装失败时恢复旧 bundle。以下命令使用 macOS/Linux 续行语法；Windows 可在命令提示符中以相同参数单行执行。

```bash
# 1. Stop run.sh/run.bat first. This must fail to connect.
curl --fail http://127.0.0.1:8000/api/health

# 2. Archive the old bundle and install a deterministic schema-3 demo.
python scripts/rebuild_demo_database.py \
  --confirm-rebuild \
  --anchor-date 2026-09-02 \
  --database data/duck_diary.db \
  --media-root data/media \
  --log-path logs/app.log \
  --archive-dir data/archive
```

</details>

### 3. 启动

```bash
# macOS / Linux
./run.sh
# 或直接运行：
uvicorn app.backend.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

```bat
:: Windows
run.bat
:: 或直接运行：
uvicorn app.backend.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

服务默认只监听本机回环地址 `127.0.0.1`。启动后访问：

- 幼儿端：<http://127.0.0.1:8000/>
- 教师端：<http://127.0.0.1:8000/teacher.html>

## 技术栈

| 层 | 选型 |
|---|---|
| 前端 | 原生 HTML/CSS/JavaScript，无构建步骤、无 CDN 依赖 |
| 后端 | FastAPI + SQLAlchemy |
| 数据 | SQLite + Alembic/应用启动迁移 |
| LLM | DeepSeek，通过 `DEEPSEEK_MODEL` 和官方 OpenAI 兼容接口配置 |
| TTS | Edge-TTS，失败时降级浏览器 TTS |
| ASR | 浏览器 Web Speech API |

## 测试与验收

测试命令需要 Node.js 20.10 或更高版本。测试会保护应用数据库、日志和 TTS 缓存，资源缺失、类型异常或测试期间发生变化都会令测试主动失败：

- 首次克隆：先在服务启动前执行第 2 步的完整演示数据初始化，再执行一次 `mkdir data/tts_cache`（Windows 使用 `mkdir data\tts_cache`）。
- 既有环境：不要 seed 或重建；确认 `data/duck_diary.db`、`logs/app.log` 是普通文件，`data/tts_cache` 是真实目录。
- 两种情况都必须先停止应用服务，再串行运行以下套件，避免多个测试进程共享 SQLite 资源。

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium

node --test --test-concurrency=1 \
  tests/frontend/shared/*.test.mjs \
  tests/frontend/child/*.test.mjs \
  tests/frontend/teacher/*.test.mjs

python -m pytest tests --ignore=tests/browser -q
python -m pytest tests/browser -q
```

当前版本已经过完整自动化验收与真实浏览器场景验收。真实模型、TTS 下载/解码/播放和主要教师工作流已有留存证据；真实麦克风采集与声学识别仍需在人工设备环境中验收。仓库内提交的是经策展的截图和验收摘要，包含数据库、请求与播放记录的原始机器证据保留在本地验收目录，不随 Git 提交。

查看 [使用说明书截图与真实场景验收记录](docs/manual/README.md)。

## 目录结构

```text
app/backend/     FastAPI API、业务服务、数据模型与迁移
app/frontend/    幼儿端、教师端及鸭鸭日记本 IP 素材
scripts/         演示数据、自动验收和真实场景验收工具
tests/           后端、前端与浏览器测试
docs/            产品设计、实施记录与验收材料
crews/ + flows/  CrewAI 研发编排
```

## 设计与安全约束

- AI 角色是会说话的「鸭鸭日记本」，不是任何一只真实小鸭。
- 一问一答为一轮，默认最多三轮；信息充分时可以提前结束。
- AI 结果必须经过教师审阅确认后，才进入正式成长记录。
- `DEEPSEEK_API_KEY` 只保存在已被 Git 忽略的 `.env` 中，禁止提交到仓库。
- 应用默认面向单机本地使用；如需局域网或公网部署，必须另行补充身份认证、传输加密和运维边界。
