"""工具调用轨迹：每次运行一个文件，追加写，不再清空。

原来 __init__ 里 `write_text("")` 会把上一次的轨迹删掉：
跑 15 条评测后只剩最后一条的现场，出问题根本没法复盘。
"""

import json
import time
from pathlib import Path


def default_trace_path() -> Path:
    return Path("runs") / time.strftime("%Y%m%d-%H%M%S") / "trace.jsonl"


class Tracer:
    """记录每次工具调用：工具名、参数、返回预览、耗时、token。"""

    def __init__(self, trace_path: str | Path | None = None):
        self.output_path = Path(trace_path) if trace_path else default_trace_path()
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        # 注意：不再 write_text("")，保持追加语义

    def log(
        self,
        step: int,
        tool_name: str,
        arguments: dict,
        result: str,
        duration: float,
        tokens: dict | None = None,
        ok: bool = True,
    ) -> None:
        result = result or ""
        record = {
            "step": step,
            "tool": tool_name,
            "arguments": arguments,
            "ok": ok,
            "result_length": len(result),
            # 头尾各留一段：原来只存前 500 字，报错信息通常在末尾，全丢了
            "result_preview": result[:600],
            "result_tail": result[-300:] if len(result) > 900 else "",
            "duration_seconds": round(duration, 2),
            "tokens": tokens or {},
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(self.output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
