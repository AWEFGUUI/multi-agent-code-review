from utils.llm_client import get_client


SYSTEM_PROMPT = """你是一个代码规范专家。

你的任务：
1. 检查命名规范（变量、函数、类名是否清晰、符合 PEP 8）
2. 检查模块化和可复用性（是否有重复代码、是否可以提取函数）
3. 检查可读性（注释、文档字符串、代码结构）
4. 检查鲁棒性（异常处理、边界条件）

如果有改进空间，直接修改代码。修改后必须保持功能不变。

输出格式：
- 先输出一段 Markdown 说明（修改点列表 + 理由）
- 然后用 python 代码块输出修改后的完整代码
"""


def parse_llm_output(text: str) -> dict:
    """从 LLM 输出里提取说明和代码。"""
    if "```python" in text:
        parts = text.split("```python")
        explanation = parts[0].strip()
        code = parts[1].split("```")[0].strip() if len(parts) > 1 else ""
    elif "```" in text:
        parts = text.split("```")
        explanation = parts[0].strip()
        code = parts[1].strip() if len(parts) > 1 else ""
    else:
        explanation = text.strip()
        code = ""
    return {"explanation": explanation, "code": code}


def run(code: str, context: str = "") -> dict:
    """
    执行 Agent 3。
    返回：{"code": 规范后代码, "explanation": 说明}
    """
    user_prompt = f"""请检查以下 Python 代码的规范性。

用户背景：
{context or '未提供'}

代码：
{code}

请检查命名、模块化、可读性、鲁棒性，然后输出修改后的完整代码。"""

    client = get_client()
    response = client.chat([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ], temperature=0.3)

    parsed = parse_llm_output(response)

    return {
        "code": parsed["code"] or code,
        "explanation": parsed["explanation"],
    }