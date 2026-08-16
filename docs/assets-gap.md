# 鸭鸭日记本 — 素材补充说明

> 本应用已可完整运行，以下素材为**后续待补充项**。每项均标注了位置、用途、当前占位方案与替换方式。素材到位后按「替换方式」操作即可，无需改动业务逻辑。

---

## 0. 已集成素材（基于用户提供的三视图 + ImageGen 生成）

> 已基于用户上传的柯尔鸭卡通 IP 三视图（正/侧/背），裁剪水印并多尺寸输出，再用 ImageGen（图生图）生成 3 个表情变体，已集成到项目代码。

**资产文件清单**（`app/frontend/assets/`）：

| 文件 | 来源 | 用途 | 集成位置 |
|---|---|---|---|
| `duck-front-512.png` | 三视图（正面）裁剪 | 主形象 / 开场 | 预留可用 |
| `duck-side-512.png` | 三视图（侧面）裁剪 | 备用（侧面展示） | 预留可用 |
| `duck-back-512.png` | 三视图（背面）裁剪 | 备用 | 预留可用 |
| `duck-front-128.png` | 正面缩放 | 对话页 header 头像 | ✅ `index.html` header |
| `duck-front-logo.png` | 正面缩放（96px） | 教师端 Logo | ✅ `teacher.html` 侧边栏 |
| `duck-front-favicon.png` | 正面缩放（64px） | 浏览器标签 favicon | ✅ `<head>` |
| `duck-happy.png` | ImageGen（开心表情） | 幼儿端开场动画 | ✅ `index.html` showOpening |
| `duck-listening.png` | ImageGen（倾听表情） | 录音中 header 头像切换 | ✅ 录音时动态切换 |
| `duck-encouraging.png` | ImageGen（鼓励表情） | 幼儿端结束动画 | ✅ `index.html` showEnding |

**ImageGen 消耗**：约 15-30 credits（3 张变体 × 5-10 credits）。

**生成/复用脚本**：
- 处理三视图：`tests/process_ip_images.py`（裁水印 + 多尺寸）
- 表情变体 ImageGen 调用：见本轮提交历史
- 命名规范：`duck-{view/expression}-{size}.png`，引用路径 `/assets/duck-front-128.png`

---

## 1. 幼儿端动画素材（部分已集成）

| 位置 | 用途 | 当前占位 | 建议规格 |
|---|---|---|---|
| 开场 | 鸭鸭日记本登场欢迎 | ✅ **duck-happy.png**（柯尔鸭 IP 抱笔记本） | 如需更丰富动画：MP4/APNG/Lottie，时长 3-5 秒 |
| 录音中 | header 头像切换 | ✅ **duck-listening.png**（倾听变体） | 可选：叠加声波动画或麦克风呼吸灯 |
| 对话过程 | "思考/眨眼"循环 | 静态 front 头像（可选增强） | 循环动画（点头/眨眼），1-2 秒 |
| 结束 | 会话结束庆祝 | ✅ **duck-encouraging.png**（竖大拇指） | 可选：庆祝动画（烟花/礼花） |

**替换方式**：将更丰富的动画素材放入 `app/frontend/assets/`，在 `index.html` 替换 `<img>` 为 `<video>` 或 Lottie 播放器，触发时机已预留。

## 2. 角色形象素材（已集成）

| 素材 | 状态 | 说明 |
|---|---|---|
| 「鸭鸭日记本」主形象 | ✅ **已集成**（基于三视图） | 柯尔鸭 + 圆框眼镜 + 黄色笔记本 + 3 个表情变体 |
| 幼儿头像 | ⏳ emoji 占位（🐤） | 每名幼儿可选头像，在教师端幼儿管理上传（后端 `children.avatar` 字段已支持） |
| 小鸭头像 | ⏳ 文字名（无头像） | 每只小鸭一张照片/插画，教师端小鸭管理上传（后端 `ducks.avatar` 字段已支持） |

## 3. 语音相关（当前已可用，可选增强）

| 项 | 当前方案 | 可选增强 |
|---|---|---|
| 语音识别 ASR | 浏览器 Web Speech API（Chrome/Edge） | 腾讯云/讯飞 ASR（儿童中文更佳） |
| 语音合成 TTS | 浏览器 SpeechSynthesis | Edge-TTS（音色统一） |

> 后端 ASR/TTS 抽象层已预留，详见 `docs/superpowers/specs/2026-08-16-duck-diary-design.md`。

## 4. 界面视觉素材（可选）

| 素材 | 状态 | 说明 |
|---|---|---|
| 教师端 Logo | ✅ **已用 IP 形象** | `duck-front-logo.png` 已替换原 emoji |
| 幼儿端背景装饰 | ⏳ 浅蓝纯色 | 可加草地/池塘/云朵等童趣背景插画 |

## 5. 使用数据（部署时录入，非素材）

由教师在应用内录入：
- 幼儿名单（全名 + 小名）与人数（约 20+ 人）
- 小鸭名单与数量、各自状态
- 值日周期与排班安排

---

**当前状态**：柯尔鸭 IP 形象 + 3 表情变体已完整集成并通过 Playwright e2e 截图验证。语音增强与背景装饰为可选优化项，可在使用中观察后再补充。