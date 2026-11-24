import time
from openai import OpenAI
from config import Config


class LLMClient:
    def __init__(self):
        Config.check()
        self.client = OpenAI(
            api_key=Config.LLM_API_KEY,
            base_url=Config.LLM_BASE_URL,
        )
        self.model = Config.LLM_MODEL_ID

    def chat(self, messages: list, temperature: float = 0.3, max_retries: int = 2, timeout: int = 20) -> str:
        """
        调 LLM，返回文本。
        timeout: 单次调用超时（秒），默认 20 秒
        max_retries: 重试次数，默认 2 次
        """
        last_error = None
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    timeout=timeout,
                )
                content = response.choices[0].message.content
                if content:
                    return content.strip()
                else:
                    last_error = "LLM 返回空内容"
            except Exception as e:
                last_error = str(e)
                print(f"⚠️ 第 {attempt + 1} 次调用失败（{timeout}秒超时）：{e}")
                time.sleep(1.5 ** attempt)

        raise RuntimeError(f"LLM 调用失败（重试 {max_retries} 次）：{last_error}")


# 全局单例
_client = None

def get_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client