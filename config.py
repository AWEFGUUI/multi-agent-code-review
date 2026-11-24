"""集中读取 .env 配置。

改动点：
- 无论从哪个目录启动，都从项目根目录读 .env（原来按当前工作目录找，
  换个目录执行就成了“缺少配置”）。
- 占位符（sk-xxxx / your-key）视为未配置，避免把 .env.example 的占位符
  当成真 key 发请求。
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
load_dotenv(ENV_FILE)

_PLACEHOLDER_PREFIXES = ("sk-xxxx", "your-", "changeme", "<", "todo", "replace")


def _is_placeholder(value: str) -> bool:
    """判断是否是 .env.example 里的占位符而不是真 key。"""
    v = (value or "").strip().lower()
    if not v:
        return True
    candidates = {v}
    if v.startswith("sk-"):
        candidates.add(v[3:])
    if any(c.startswith(p) for c in candidates for p in _PLACEHOLDER_PREFIXES):
        return True
    tail = v[3:] if v.startswith("sk-") else v
    return bool(tail) and set(tail) <= {"x", "-"}


class Config:
    LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
    LLM_MODEL_ID = os.getenv("LLM_MODEL_ID", "deepseek-flash").strip()
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").strip()

    @classmethod
    def refresh(cls) -> None:
        """重新读取环境变量（测试、或运行时切换配置用）。"""
        cls.LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
        cls.LLM_MODEL_ID = os.getenv("LLM_MODEL_ID", "deepseek-flash").strip()
        cls.LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").strip()

    @classmethod
    def check(cls) -> bool:
        missing = []
        if not cls.LLM_API_KEY or _is_placeholder(cls.LLM_API_KEY):
            missing.append("LLM_API_KEY")
        if not cls.LLM_MODEL_ID:
            missing.append("LLM_MODEL_ID")
        if not cls.LLM_BASE_URL:
            missing.append("LLM_BASE_URL")
        if missing:
            raise ValueError(
                f"缺少配置：{', '.join(missing)}，请检查 {ENV_FILE}（可参考 .env.example）"
            )
        return True

    @classmethod
    def masked_key(cls) -> str:
        key = cls.LLM_API_KEY or ""
        if len(key) <= 8:
            return "***"
        return f"{key[:5]}...{key[-4:]}"
