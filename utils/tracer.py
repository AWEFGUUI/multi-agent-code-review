import json
import time
from pathlib import Path


class Tracer:
    """
    记录每次工具调用：工具名、参数、返回、耗时。
    写到 trace.jsonl，每行一条记录。
    """

    def __init__(self, output_path: str = "output/trace.jsonl"):
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        # 清空旧文件
        self.output_path.write_text("", encoding="utf-8")

    def log(self, step: int, tool_name: str, arguments: dict, result: str, duration: float):
        record = {
            "step": step,
            "tool": tool_name,
            "arguments": arguments,
            "result_preview": result[:500],  # 只存前500字，防止文件太大
            "result_length": len(result),
            "duration_seconds": round(duration, 2),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(self.output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")