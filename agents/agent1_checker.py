import ast
import importlib.util
import sys

from utils.issue_tags import ISSUES_INSTRUCTION
from utils.llm_client import get_client
from utils.llm_parse import parse_llm_output as _parse  # noqa: F401  （对外仍导出 parse_llm_output）


SYSTEM_PROMPT = """你是一个代码审查专家，负责检查 Python 代码的可运行性。

你的任务：
1. 分析代码是否有严重逻辑错误（如未定义变量、错误的函数调用、死循环）
2. 如果有问题，直接修改代码
3. 输出修改后的完整代码

重要原则：
- 修改后必须保持功能不变。
- 不要在没有必要时新增 print、删掉调用或吞掉异常，那会改变程序行为。
- 如果代码只有语法错误，修好语法即可；不要顺手补类型注解、改名等规范性改动。

输出格式：
- 先输出一段 Markdown 说明（修改点列表 + 理由）
- 然后用 python 代码块输出修改后的完整代码
""" + ISSUES_INSTRUCTION


def parse_llm_output(text: str) -> dict:
    """向后兼容的入口，真正实现已统一到 utils.llm_parse。"""
    return _parse(text, require_code=False)


def _stdlib_names() -> set[str]:
    """3.10+ 自带全集；低版本退回一个常见集合。"""
    names = getattr(sys, "stdlib_module_names", None)
    if names:
        return set(names)
    return {
        "os", "sys", "re", "json", "time", "datetime", "math", "random",
        "ast", "importlib", "argparse", "pathlib", "typing", "collections",
        "itertools", "functools", "subprocess", "logging", "io", "copy",
        "unittest", "csv", "sqlite3", "hashlib", "dataclasses", "asyncio",
        "textwrap", "shutil", "tempfile", "traceback", "statistics",
    }


def static_check(code: str) -> dict:
    """
    静态检查：语法 + 依赖。
    返回：{"syntax_ok": bool, "syntax_error": str, "imports": list, "missing": list}
    """
    result = {
        "syntax_ok": True,
        "syntax_error": "",
        "imports": [],
        "missing": [],
    }

    # 1. 语法检查
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        result["syntax_ok"] = False
        result["syntax_error"] = f"第 {e.lineno} 行：{e.msg}"
        return result

    # 2. 提取 import
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                imports.add(node.module.split(".")[0])

    result["imports"] = sorted(imports)

    # 3. 检查依赖是否安装
    #    原来手写了一份 stdlib 白名单，漏了 unittest/csv/sqlite3 等，
    #    会把标准库误报成“缺依赖”；现在用 sys.stdlib_module_names。
    stdlib = _stdlib_names()
    for pkg in imports:
        if pkg in stdlib or pkg == "__future__":
            continue
        try:
            spec = importlib.util.find_spec(pkg)
        except (ImportError, ModuleNotFoundError, ValueError):
            spec = None
        if spec is None:
            result["missing"].append(pkg)

    return result


def run(code: str, context: str = "") -> dict:
    """
    执行 Agent 1。
    返回：{"code": 修改后代码, "explanation": 说明, "issues": 标签, "static": 静态检查结果}
    """
    static = static_check(code)

    if not static["syntax_ok"]:
        return {
            "code": code,
            "explanation": f"## 语法错误\n\n{static['syntax_error']}\n\n代码无法解析，请先修复语法。",
            "issues": ["syntax_error"],
            "static": static,
        }

    static_info = f"""
静态检查结果：
- 语法：通过
- 导入的包：{', '.join(static['imports']) or '无'}
- 缺失的依赖：{', '.join(static['missing']) or '无'}
"""

    user_prompt = f"""请审查以下 Python 代码。

{static_info}

用户背景：
{context or '未提供'}

代码：
{code}

请检查严重逻辑错误，并输出修改后的完整代码。"""

    client = get_client()
    response = client.chat([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ], temperature=0.2, timeout=30)

    parsed = _parse(response)
    return {
        "code": parsed["code"],
        "explanation": parsed["explanation"],
        "issues": parsed["issues"],
        "static": static,
    }
