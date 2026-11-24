import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    LLM_API_KEY = os.getenv("LLM_API_KEY")
    LLM_MODEL_ID = os.getenv("LLM_MODEL_ID", "deepseek-flash")
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")

    @classmethod
    def check(cls):
        missing = []
        if not cls.LLM_API_KEY:
            missing.append("LLM_API_KEY")
        if not cls.LLM_MODEL_ID:
            missing.append("LLM_MODEL_ID")
        if not cls.LLM_BASE_URL:
            missing.append("LLM_BASE_URL")
        if missing:
            raise ValueError(f"缺少配置：{', '.join(missing)}，请检查 .env")
        return True