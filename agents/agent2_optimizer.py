from utils.issue_tags import ISSUES_INSTRUCTION
from utils.llm_client import get_client
from utils.llm_parse import parse_llm_output as _parse


SYSTEM_PROMPT = """你是一个代码性能优化专家。

你的任务：
1. 分析代码中的性能瓶颈（如嵌套循环、重复计算、低效的数据结构）
2. 结合用户提供的工作背景（数据规模、环境限制），判断哪些优化真正有意义
3. 如果有优化空间，直接修改代码
4. 输出修改后的完整代码

重要原则：
- 不要为了优化而优化。如果数据规模很小（比如几十条），微小的优化没有意义。
- 优先优化高风险的地方（如 O(n²) 的嵌套循环）。
- 修改后必须保持功能不变。

输出格式：
- 先输出一段 Markdown 说明（优化点列表 + 理由）
- 然后用 python 代码块输出修改后的完整代码
""" + ISSUES_INSTRUCTION


def parse_llm_output(text: str) -> dict:
    """向后兼容入口，实现见 utils.llm_parse。"""
    return _parse(text, require_code=False)


def run(code: str, context: str = "", timeout: float = 20, max_retries: int = 2) -> dict:
    """
    执行 Agent 2。
    返回：{"code": 优化后代码, "explanation": 说明, "issues": 标签}
    """
    user_prompt = f"""请优化以下 Python 代码的性能。

用户背景（数据规模、环境限制）：
{context or '未提供'}

代码：
{code}

请分析性能瓶颈，结合背景判断哪些优化有意义，然后输出优化后的完整代码。"""

    client = get_client()
    response = client.chat([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ], temperature=0.3, timeout=timeout, max_retries=max_retries)

    parsed = _parse(response)
    return {
        "code": parsed["code"],
        "explanation": parsed["explanation"],
        "issues": parsed["issues"],
    }
