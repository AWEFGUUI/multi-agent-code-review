"""LLM 调用封装。

改动点：
- 只重试“可重试”的错误（429/5xx/超时/连接），鉴权错误、参数错误立即失败；
  原来 `except Exception` 会对 401 也重试两次并 sleep。
- 统一 timeout（主循环 45s，子审查 20~60s）。
- 记录 token 用量，供评测汇总成本。
- 新增 chat_with_tools：主 Agent 的 tool_calls 循环走这里，
  不再绕过封装直接 client.client.chat.completions.create（那样会把重试全丢掉）。
"""

import random
import time

from openai import OpenAI

from config import Config

_NON_RETRYABLE = {
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "BadRequestError",
    "UnprocessableEntityError",
    "InvalidRequestError",
    "ConflictError",
}
_TRANSIENT_NAMES = {
    "APITimeoutError",
    "APIConnectionError",
    "RateLimitError",
    "InternalServerError",
    "APIStatusError",
    "TimeoutError",
    "ReadTimeout",
    "ConnectTimeout",
    "ConnectionError",
    "RemoteProtocolError",
    "ServiceUnavailableError",
    "OverloadedError",
}
_RETRYABLE_STATUS = {408, 409, 429}


def is_retryable(exc: Exception) -> bool:
    """按异常类型/状态码判断是否值得重试。"""
    name = type(exc).__name__
    if name in _NON_RETRYABLE:
        return False
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status in _RETRYABLE_STATUS or status >= 500
    return name in _TRANSIENT_NAMES


def is_timeout_error(exc: Exception) -> bool:
    name = type(exc).__name__
    if name in {"APITimeoutError", "TimeoutError", "ReadTimeout", "ConnectTimeout"}:
        return True
    return "timeout" in str(exc).lower() or "timed out" in str(exc).lower()


class LLMClient:
    def __init__(self):
        Config.check()
        self.client = OpenAI(
            api_key=Config.LLM_API_KEY,
            base_url=Config.LLM_BASE_URL,
        )
        self.model = Config.LLM_MODEL_ID
        self.reset_usage()

    # ------------------------------------------------------------------ usage
    def reset_usage(self) -> None:
        self.usage = {
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    def _record_usage(self, response) -> None:
        self.usage["calls"] += 1
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        self.usage["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
        self.usage["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0
        self.usage["total_tokens"] += getattr(usage, "total_tokens", 0) or 0

    # ------------------------------------------------------------------ 底层
    def _create(
        self,
        messages: list,
        temperature: float,
        timeout: float,
        max_retries: int,
        tools: list | None = None,
    ):
        attempts = max(1, int(max_retries))
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                kwargs = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "timeout": timeout,
                }
                if tools:
                    kwargs["tools"] = tools
                response = self.client.chat.completions.create(**kwargs)
                self._record_usage(response)
                return response
            except Exception as exc:  # noqa: BLE001 - 需要按类型分流
                last_error = exc
                if not is_retryable(exc) or attempt == attempts - 1:
                    raise
                delay = min(2 ** attempt, 8) * (0.5 + random.random())
                print(
                    f"⚠️ 第 {attempt + 1}/{attempts} 次调用失败（{type(exc).__name__}），"
                    f"{delay:.1f}s 后重试"
                )
                time.sleep(delay)

        raise RuntimeError(f"LLM 调用失败：{last_error}")

    # ------------------------------------------------------------------ 接口
    def chat(
        self,
        messages: list,
        temperature: float = 0.3,
        max_retries: int = 2,
        timeout: float = 20,
    ) -> str:
        """调 LLM，返回纯文本（子 Agent 用）。"""
        response = self._create(messages, temperature, timeout, max_retries)
        content = response.choices[0].message.content
        if not content or not content.strip():
            raise RuntimeError("LLM 返回空内容")
        return content.strip()

    def chat_with_tools(
        self,
        messages: list,
        tools: list,
        temperature: float = 0.2,
        max_retries: int = 2,
        timeout: float = 45,
    ):
        """调 LLM，返回 message 对象（可能带 tool_calls）。"""
        response = self._create(
            messages,
            temperature,
            timeout,
            max_retries,
            tools=tools,
        )
        return response.choices[0].message


# ---------------------------------------------------------------- 全局单例
_client: LLMClient | None = None


def get_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client


def reset_client() -> None:
    """测试用：丢掉单例，下次重新读配置。"""
    global _client
    _client = None
