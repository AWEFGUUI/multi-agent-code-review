from agents import agent1_checker, agent2_optimizer, agent3_stylist
from utils.code_runner import run_python_code


# =============================================================================
# 工具定义
# =============================================================================
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
            "description": "检查代码性能瓶颈，结合背景判断是否需要优化。返回修改后的代码和说明。",
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
            "description": "运行 Python 代码，返回 stdout、stderr、返回码。用于验证代码能否真的跑通。",
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


# =============================================================================
# 工具执行
# =============================================================================
def execute_review_runnability(code: str, context: str = "") -> str:
    import json
    result = agent1_checker.run(code, context)
    return json.dumps({
        "code": result["code"],
        "explanation": result["explanation"],
        "syntax_ok": result["static"]["syntax_ok"],
        "missing_deps": result["static"]["missing"],
    }, ensure_ascii=False)


def execute_review_efficiency(code: str, context: str = "") -> str:
    """效率审查：超时 40 秒，重试 2 次。"""
    import json
    from utils.llm_client import get_client

    client = get_client()
    result = agent2_optimizer.run(code, context, timeout=40, max_retries=2)
    return json.dumps({
        "code": result["code"],
        "explanation": result["explanation"],
    }, ensure_ascii=False)


def execute_review_style(code: str, context: str = "") -> str:
    import json
    result = agent3_stylist.run(code, context)
    return json.dumps({
        "code": result["code"],
        "explanation": result["explanation"],
    }, ensure_ascii=False)


def execute_run_python(code: str) -> str:
    import json
    result = run_python_code(code)
    return json.dumps(result, ensure_ascii=False)


def execute_tool(name: str, arguments: dict) -> str:
    code = arguments.get("code", "")
    context = arguments.get("context", "")

    if name == "review_runnability":
        return execute_review_runnability(code, context)
    elif name == "review_efficiency":
        return execute_review_efficiency(code, context)
    elif name == "review_style":
        return execute_review_style(code, context)
    elif name == "run_python":
        return execute_run_python(code)
    else:
        return f"未知工具：{name}"