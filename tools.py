"""工具定义与调度。

改动点：
- 每个 reviewer 的**返回代码**都要能 ast.parse，否则丢弃并返回错误 JSON，
  让模型重试 —— 挡住“模型偷懒回 `# 其余代码不变`”把代码截断。
- 未知工具、参数缺失、超时都返回结构化 JSON（不再返回纯文本，
  避免主循环 json.loads 直接炸）。
- 每个工具独立超时/重试，review_efficiency 最慢（60s / 2 次）。
"""

import ast
import json

from agents import agent1_checker, agent2_optimizer, agent3_stylist
from utils.code_runner import run_python_code
from utils.llm_parse import LLMOutputError

TOOL_NAMES = (
    "review_runnability",
    "review_efficiency",
    "review_style",
    "run_python",
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "review_runnability",
            "description": "检查代码能否运行：语法错误、依赖缺失、严重逻辑错误。返回修改后的代码和说明。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "要审查的 Python 代码"},
                    "context": {"type": "string", "description": "工作背景说明，可为空"},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "review_efficiency",
            "description": "检查代码性能瓶颈，结合背景判断是否需要优化。返回修改后的代码和说明。较慢，约 10-60 秒。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "要审查的 Python 代码"},
                    "context": {"type": "string", "description": "数据规模、环境限制等背景"},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "review_style",
            "description": "检查命名、模块化、可读性、鲁棒性。返回修改后的代码和说明。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "要审查的 Python 代码"},
                    "context": {"type": "string", "description": "工作背景说明，可为空"},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": "在隔离子进程里运行 Python 代码，返回 stdout、stderr、返回码。用于验证代码能否真的跑通。GUI/交互/模型类代码会被跳过。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "要运行的 Python 代码"},
                },
                "required": ["code"],
            },
        },
    },
]


def _error(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


def _validate_output_code(code: str) -> str:
    """返回错误信息；空串表示代码可用。"""
    if not code:
        return ""
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return f"返回的代码无法解析（第 {exc.lineno} 行：{exc.msg}），本次修改已丢弃，请重试"
    return ""


def _review(tool_name: str, func, code: str, context: str, extra: dict | None = None) -> str:
    if not code or not code.strip():
        return _error(f"{tool_name} 缺少 code 参数")

    try:
        result = func(code, context)
    except LLMOutputError as exc:
        return _error(f"{tool_name} 输出不合规：{exc}")
    except Exception as exc:  # noqa: BLE001 - 工具层必须把异常转成可读结果
        return _error(f"{tool_name} 执行失败：{type(exc).__name__}: {exc}")

    new_code = result.get("code", "") or ""
    problem = _validate_output_code(new_code)
    if problem:
        return _error(problem)

    payload = {
        "code": new_code,
        "explanation": result.get("explanation", ""),
        "issues": result.get("issues", []),
    }
    if extra:
        payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


def execute_review_runnability(code: str, context: str = "") -> str:
    if not code or not code.strip():
        return _error("review_runnability 缺少 code 参数")
    try:
        result = agent1_checker.run(code, context)
    except LLMOutputError as exc:
        return _error(f"review_runnability 输出不合规：{exc}")
    except Exception as exc:  # noqa: BLE001
        return _error(f"review_runnability 执行失败：{type(exc).__name__}: {exc}")

    static = result.get("static", {}) or {}

    # 语法错误时 Agent 1 只做诊断、不改代码（返回原代码 + issues=["syntax_error"]）。
    # 这里不能因为"返回的代码仍然不合法"就当成失败：那会把 syntax_error 标签丢掉，
    # 评测里 case_01 的检出率就变成了 0。
    if not static.get("syntax_ok", True):
        return json.dumps({
            "code": "",
            "explanation": result.get("explanation", ""),
            "issues": result.get("issues", []) or ["syntax_error"],
            "syntax_ok": False,
            "missing_deps": static.get("missing", []),
        }, ensure_ascii=False)

    payload = {
        "code": result.get("code", ""),
        "explanation": result.get("explanation", ""),
        "issues": list(result.get("issues", []) or []),
        "syntax_ok": True,
        "missing_deps": static.get("missing", []),
    }

    # 缺依赖是静态检查能确定的事实，不该依赖模型“记得打标签”：
    # 第一轮评测里 case_02 就跑成了 0%（模型说了缺依赖，但 ISSUES 行给的是 other）。
    if static.get("missing") and "missing_dep" not in payload["issues"]:
        payload["issues"].append("missing_dep")

    problem = _validate_output_code(payload["code"])
    if problem:
        return _error(problem)
    return json.dumps(payload, ensure_ascii=False)


def execute_review_efficiency(code: str, context: str = "") -> str:
    return _review(
        "review_efficiency",
        lambda c, ctx: agent2_optimizer.run(c, ctx, timeout=60, max_retries=2),
        code,
        context,
    )


def execute_review_style(code: str, context: str = "") -> str:
    return _review(
        "review_style",
        lambda c, ctx: agent3_stylist.run(c, ctx, timeout=30),
        code,
        context,
    )


def execute_run_python(code: str) -> str:
    if not code or not code.strip():
        return _error("run_python 缺少 code 参数")
    try:
        result = run_python_code(code)
    except Exception as exc:  # noqa: BLE001
        return _error(f"run_python 执行失败：{type(exc).__name__}: {exc}")
    return json.dumps(result, ensure_ascii=False)


def execute_tool(name: str, arguments: dict) -> str:
    arguments = arguments or {}
    code = arguments.get("code", "")
    context = arguments.get("context", "")

    if name == "review_runnability":
        return execute_review_runnability(code, context)
    if name == "review_efficiency":
        return execute_review_efficiency(code, context)
    if name == "review_style":
        return execute_review_style(code, context)
    if name == "run_python":
        return execute_run_python(code)
    return _error(f"未知工具：{name}（可用：{', '.join(TOOL_NAMES)}）")
