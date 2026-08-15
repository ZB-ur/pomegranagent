"""DeepSeek V4 Pro 的集中 LLM 配置。

所有 Agent / Crew 统一从这里获取 LLM 实例，便于一处修改、全局生效。
模型名、base_url、key 均从 .env 读取，避免硬编码密钥。
"""
import os

from dotenv import load_dotenv

from crewai import LLM

# 加载项目根目录的 .env（可被调用方重复调用，幂等）
load_dotenv()


def get_deepseek_llm() -> LLM:
    """返回配置好的 DeepSeek V4 Pro LLM 实例。

    说明：
    - 模型走 OpenAI 兼容接口，因此用 "openai/" 前缀 + 自定义 base_url。
    - deepseek-v4-pro 于 2026-08-13 正式 GA；旧的 deepseek-chat /
      deepseek-reasoner 别名已于 2026-07-24 停用。
    """
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")

    kwargs = {
        "model": f"openai/{model}",
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        "api_key": os.getenv("DEEPSEEK_API_KEY"),
        "max_tokens": int(os.getenv("DEEPSEEK_MAX_TOKENS", "8192")),
        "timeout": float(os.getenv("DEEPSEEK_TIMEOUT", "120")),
    }

    # 可选：推理强度 low / high / max（V4 Pro 支持，未设置则不传）
    effort = os.getenv("DEEPSEEK_REASONING_EFFORT")
    if effort:
        kwargs["reasoning_effort"] = effort

    # 可选：采样温度（推理模型可能忽略该参数）
    temperature = os.getenv("DEEPSEEK_TEMPERATURE")
    if temperature:
        kwargs["temperature"] = float(temperature)

    return LLM(**kwargs)
