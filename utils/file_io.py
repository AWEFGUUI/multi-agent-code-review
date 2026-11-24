import os
from pathlib import Path


def read_file(path: str) -> str:
    """读取文本文件，返回字符串。文件不存在则报错。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在：{path}")
    return p.read_text(encoding="utf-8")


def write_file(path: str, content: str):
    """写入文本文件，自动创建父目录。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def ensure_output_dir(output_dir: str = "output"):
    """确保输出目录存在。"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    return output_dir