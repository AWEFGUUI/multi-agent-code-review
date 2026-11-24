import json
import os
import tempfile
from pathlib import Path


def read_file(path: str) -> str:
    """读取文本文件，返回字符串。文件不存在则报错。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在：{path}")
    return p.read_text(encoding="utf-8")


def write_file(path: str, content: str) -> None:
    """原子写：先写临时文件再 os.replace，进程中断不会留下半个文件。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json(path: str, data) -> None:
    write_file(str(path), json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def ensure_output_dir(output_dir: str = "output") -> str:
    """确保输出目录存在。"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    return output_dir
