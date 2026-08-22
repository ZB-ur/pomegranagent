"""AI 引擎：对话、提炼、评估、小鸭档案汇总。

统一通过 DeepSeek（OpenAI 兼容接口）以结构化 JSON 输出。
"""
import json
import logging
import os
import re

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("duck_diary.ai_engine")

BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
TIMEOUT = float(os.getenv("DEEPSEEK_TIMEOUT", "120"))


def _llm(messages: list[dict], json_mode: bool = False, retries: int = 1) -> str:
    """调用 DeepSeek chat completions，返回文本内容（失败自动重试 1 次）。"""
    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": int(os.getenv("DEEPSEEK_MAX_TOKENS", "8192")),
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = httpx.post(
                f"{BASE_URL}/chat/completions", json=payload, headers=headers, timeout=TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"] or ""
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning("LLM 调用失败（第 %d 次）：%s", attempt + 1, e)
            if attempt < retries:
                continue
    logger.error("LLM 调用最终失败：%s", last_err)
    raise last_err


def _parse_json(text: str) -> dict:
    """健壮地解析 LLM 返回的 JSON（容忍 markdown 代码块包裹）。"""
    text = text.strip()
    # 去掉 ```json ... ``` 包裹
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    # 截取第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return json.loads(text)


SYSTEM_PROMPT = """你是「鸭鸭日记本」，一本会说话的日记本，是值日小朋友的陪伴与记录小助手。

重要身份边界：
- 你不是任何一只小鸭。小鸭们是幼儿园饲养的一群真实小鸭，它们是小朋友照顾的对象。
- 你负责：温柔地倾听、把小朋友的饲养经历记进日记、用提问引导小朋友多说，并回答关于小鸭们的情况。

对话要求：
- 用小朋友的小名亲切称呼他/她（若小名未知则用全名）。
- 语气温柔、简短、鼓励，像会说话的朋友，句子不要太长。
- 结合「小朋友档案、最近对话、小鸭档案」来回应，体现出你记得他/她（活人感）。
- 引导小朋友反馈：今天做了什么（喂食/清洁/观察）、心里感受、对小鸭的观察。
- 当小朋友已经说得比较全面时，可以自然地收尾并鼓励他/她。

输出必须是 JSON，格式：
{"reply": "你的回复", "ended": false, "end_reason": null}
- ended=true 表示你认为信息已足够、本轮会话可以结束，end_reason 填 "complete"。
- 正常继续时 ended=false、end_reason=null。
"""


def chat_reply(
    *,
    child: dict,
    recent_summary: str,
    ducks_info: str,
    history: list[dict],
    round_num: int,
    max_rounds: int,
) -> dict:
    """生成「鸭鸭日记本」的下一句回复，并判断是否可提前结束。"""
    context = (
        f"小朋友档案：{json.dumps(child, ensure_ascii=False)}\n"
        f"最近对话摘要：{recent_summary or '（暂无历史）'}\n"
        f"小鸭档案：{ducks_info or '（暂无）'}\n"
        f"当前是第 {round_num} 轮（最多 {max_rounds} 轮）。"
    )
    messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n" + context}]
    for h in history:
        messages.append({"role": h["role"], "content": h["text"]})

    raw = _llm(messages, json_mode=True)
    try:
        return _parse_json(raw)
    except Exception:
        # 解析失败降级：返回一个中性回复，不结束
        return {"reply": "嗯嗯，我在认真听呢，然后呢？", "ended": False, "end_reason": None}


def extract_info(transcript: str) -> dict:
    """会话结束后提炼：饲养流水、情绪、心得。"""
    prompt = f"""请从下面这段幼儿与「鸭鸭日记本」的对话中提炼结构化信息。
对话原文：
{transcript}

输出 JSON：
{{
  "feeding_logs": [{{"category": "喂食/清洁/观察/其它", "content": "一句话描述", "duck_name": "小鸭名或null"}}],
  "emotion": {{"emotion": "开心/平静/疲惫/期待/其它", "intensity": 1-5, "note": "依据"}},
  "insight": "幼儿今日的心得或亮点，一句概括，无则空字符串"
}}
只输出 JSON。"""
    raw = _llm(
        [{"role": "user", "content": prompt}],
        json_mode=True,
    )
    try:
        return _parse_json(raw)
    except Exception:
        return {"feeding_logs": [], "emotion": {"emotion": "平静", "intensity": 3, "note": ""}, "insight": ""}


def assess_conversation(transcript: str, dimensions: list[dict]) -> dict:
    """多维能力评估：每维度 1-5 分 + 评分理由（引用对话原句）。"""
    dim_desc = "\n".join(f"- {d['name']}（{d['key']}）: {d['description'] or ''}" for d in dimensions)
    prompt = f"""你是幼儿园能力发展评估助手。请基于下面这段值日对话，对幼儿的多维能力打分。
评估维度：
{dim_desc}

对话原文：
{transcript}

要求：
- 每个维度给 1-5 分（5 最高），并给一句评分理由，理由必须引用对话中的关键语句作为依据。
- 这是面向教师的事后分析，幼儿不会看到分数。

输出 JSON：
{{"scores": [{{"dimension_key": "维度key", "score": 1-5, "reason": "引用原句的依据"}}], "overall": 平均分}}
只输出 JSON。"""
    raw = _llm([{"role": "user", "content": prompt}], json_mode=True)
    try:
        return _parse_json(raw)
    except Exception:
        return {"scores": [], "overall": 3.0}


def summarize_duck(duck_name: str, related_texts: list[str]) -> str:
    """小鸭档案汇总：基于历史对话生成小鸭当前/历史情况。"""
    joined = "\n".join(related_texts[-40:]) or "（暂无相关记录）"
    prompt = f"""请为幼儿园饲养的小鸭「{duck_name}」汇总一份简短档案（当前情况 + 历史情况），
基于以下历史对话片段：

{joined}

输出 3-5 句话的中文档案，便于幼儿询问时「鸭鸭日记本」引用。"""
    return _llm([{"role": "user", "content": prompt}]).strip()
