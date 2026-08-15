"""快速验证 DeepSeek V4 Pro 连接与 API Key 是否有效。

用法：
    python scripts/test_connection.py
"""
import os

from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    import litellm

    model = f"openai/{os.getenv('DEEPSEEK_MODEL', 'deepseek-v4-pro')}"
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    api_key = os.getenv("DEEPSEEK_API_KEY")

    print(f"测试模型: {model}")
    print(f"base_url: {base_url}")
    print(f"API Key: {'已配置' if api_key else '缺失！'}")

    response = litellm.completion(
        model=model,
        api_key=api_key,
        api_base=base_url,
        messages=[{"role": "user", "content": "请用一句话介绍你自己。"}],
        max_tokens=200,
    )

    print("\n连接成功！模型回复：")
    print(response.choices[0].message.content)


if __name__ == "__main__":
    main()
