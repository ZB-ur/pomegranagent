# CrewAI + DeepSeek V4 Pro 配置模板

一个开箱即用的 CrewAI 多智能体项目模板，已接入 **DeepSeek V4 Pro**（`deepseek-v4-pro`）模型。

## 环境信息

| 项 | 值 |
| --- | --- |
| CrewAI | 1.15.x（`crewai[litellm]`） |
| 模型 | DeepSeek V4 Pro（2026-08-13 正式 GA） |
| 模型名 | `deepseek-v4-pro` |
| 接口 | OpenAI 兼容，base_url `https://api.deepseek.com/v1` |
| Python | 3.13 |

> 注意：DeepSeek 旧的 `deepseek-chat` / `deepseek-reasoner` 别名已于 **2026-07-24 停用**，请使用 `deepseek-v4-pro` 或 `deepseek-v4-flash`。

## ⚠️ Python 版本要求（重要）

CrewAI 1.15.x 要求 Python **3.10 ~ 3.13**（`>=3.10,<3.14`），**不支持 3.14**，也低于 3.10 的版本不可用。

你机器上的情况：

| Python | 版本 | 是否可用 |
| --- | --- | --- |
| Homebrew `python3` | 3.14.x | ❌ 太新 |
| macOS 自带 `/usr/bin/python3` | 3.9.6 | ❌ 太老 |
| WorkBuddy 内置 Python | 3.13.12 | ✅ 可用 |

**彻底脱离 WorkBuddy 独立运行（推荐）**：用 Homebrew 装一个标准 Python 3.13：

```bash
brew install python@3.13

# 然后用它重建项目内虚拟环境
cd pomegranagent
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

之后 `python3.13` 就是系统级命令，完全不依赖 WorkBuddy。

> 当前项目 `.venv` 是用 WorkBuddy 内置的 3.13.12 创建的，只要 `~/.workbuddy` 目录保留即可正常使用；若你要彻底卸载 WorkBuddy，请按上面步骤用 `python@3.13` 重建。

## 目录结构

```
pomegranagent/
├── .env                  # 密钥与模型配置（已 gitignore，勿提交）
├── .env.example          # 配置模板
├── .gitignore
├── requirements.txt      # 依赖清单
├── README.md
├── config/
│   ├── __init__.py
│   └── llm.py            # DeepSeek LLM 集中配置（单点修改、全局生效）
├── crews/
│   ├── __init__.py
│   └── research_crew.py  # 示例 crew：研究员 -> 撰稿人
├── main.py               # 入口
└── scripts/
    └── test_connection.py  # 快速验证连接与 key 有效性
```

## 快速开始

项目使用**项目内虚拟环境 `.venv`**，完全独立于 WorkBuddy——脱离 WorkBuddy 后，只要有系统 Python（≥3.10，推荐 3.11+）即可照常运行。

```bash
# 1. 进入项目
cd pomegranagent

# 2. 创建虚拟环境（首次）
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置密钥：复制 .env.example 为 .env 并填入真实 key
cp .env.example .env

# 5. 验证连接
python scripts/test_connection.py

# 6. 运行示例 crew
python main.py
```

> `.venv` 已加入 `.gitignore`，不会随 Git 提交。以后每次使用前先 `source .venv/bin/activate` 激活环境即可。

## DeepSeek 配置说明

所有模型相关配置集中在 `config/llm.py`，通过 `.env` 控制：

```bash
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_REASONING_EFFORT=     # 可选：low / high / max
DEEPSEEK_MAX_TOKENS=8192       # 最大输出 token
DEEPSEEK_TIMEOUT=120           # 请求超时（秒）
```

关键实现（`config/llm.py`）：

```python
from crewai import LLM

llm = LLM(
    model="openai/deepseek-v4-pro",          # openai 前缀走 OpenAI 兼容接口
    base_url="https://api.deepseek.com/v1",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    max_tokens=8192,
    timeout=120,
)
```

要点：

- **模型前缀**：CrewAI 的 `LLM` 底层是 LiteLLM，模型名必须带 provider 前缀。接入 DeepSeek 用 `openai/` 前缀 + 自定义 `base_url` 最稳妥。
- **思考模式**：V4 Pro 默认开启 thinking（返回 `reasoning_content`）。若只想拿最终答案，可设置 `DEEPSEEK_REASONING_EFFORT` 或在 `LLM` 传 `reasoning_effort` 调整强度。
- **温度参数**：推理模型可能忽略 `temperature`，若设置了却不生效属正常现象。

## 如何扩展

在 `crews/research_crew.py` 的 `build_crew()` 中新增 Agent / Task 即可：

```python
new_agent = Agent(
    role="...", goal="...", backstory="...",
    llm=llm, verbose=True,
)
new_task = Task(description="...", expected_output="...", agent=new_agent)
```

所有 Agent 共享同一个 `llm` 实例；如需给某个 Agent 单独换模型，可在该 Agent 的 `llm=` 传入新的 `LLM(...)` 实例。

## 成本与安全提示

- **轮换密钥**：本 key 曾明文出现在对话中，建议尽快到 DeepSeek 控制台 reset。
- **密钥管理**：key 只放在 `.env`（已加入 `.gitignore`），切勿硬编码进源码或提交到 Git。
- **成本**：多智能体单次运行会触发多次 LLM 调用，V4 Pro 价格约为 Flash 的 3 倍；DeepSeek 官方预告近期将整体上调 API 定价，重度使用请提前评估。
- **中文输出**：若在 Windows 遇到 GBK 编码报错，运行前设置 `PYTHONIOENCODING=utf-8`。

## 常见问题

| 问题 | 处理 |
| --- | --- |
| `deepseek-chat` 报 400 / 模型不存在 | 旧别名已停用，改用 `deepseek-v4-pro` |
| `content` 为空、只有思考过程 | 默认 thinking 模式，调整 `DEEPSEEK_REASONING_EFFORT` |
| 温度不生效 | 推理模型忽略 temperature，属正常 |
| 超时 | 调大 `DEEPSEEK_TIMEOUT` |
