from utils.llm_client import get_client
from agents import agent1_checker
import re


EVAL_SYSTEM_PROMPT = """你是一个代码评估专家。

你的任务：对比原代码和修改后的代码，从三个维度打分（1-5分）。

三个维度：
1. 准确性：修改是否引入新 bug，逻辑是否正确
2. 效率：修改是否提升了性能
3. 可读性：修改是否让代码更易读

输出格式：
1. 先输出分析理由（对比两个代码的差异）
2. 然后输出分数，格式严格如下：
准确性：X
效率：X
可读性：X

只输出一次，不要重复。
"""


BUG_CHECK_PROMPT = """你是一个代码审查专家。

请检查以下代码是否有明显 bug（如未定义变量、错误调用、死循环）。

如果有明显 bug，只输出：有bug
如果没有明显 bug，只输出：无bug

不要输出其他任何内容。
"""


_SCORE_RE = re.compile(
    r"^[ \t]*(准确性|效率|可读性)[ \t]*[:：=][ \t]*([0-5](?:\.[0-9])?)[ \t]*(?:/[ \t]*5)?[ \t]*$",
    re.M,
)


def parse_scores(text: str) -> dict:
    """从 LLM 输出里提取三个维度的分数。

    修掉两个坑：原来是 re.findall(r"\\d") 逐位取数，
    "4.5" 会变成 4、"10" 会变成 1，而且同一行出现多个维度时会串味。
    """
    scores = {"准确性": 0, "效率": 0, "可读性": 0}
    for key, value in _SCORE_RE.findall(text or ""):
        scores[key] = float(value)
    return scores


def evaluate(original_code: str, final_code: str, context: str = "") -> dict:
    """
    评估：对比原代码和最终代码，三次打分取平均。
    返回：{"scores": {...}, "reasons": [...], "stable": bool}
    """
    client = get_client()
    all_scores = []
    reasons = []

    for i in range(3):
        user_prompt = f"""请对比以下两段代码。

原代码：
{original_code}

修改后代码：
{final_code}

用户背景：
{context or '未提供'}

请先分析差异，然后打分。"""

        response = client.chat([
            {"role": "system", "content": EVAL_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ], temperature=0.2)

        scores = parse_scores(response)
        all_scores.append(scores)
        reasons.append(response)

    # 取平均
    avg_scores = {}
    for key in ["准确性", "效率", "可读性"]:
        values = [s[key] for s in all_scores]
        avg_scores[key] = round(sum(values) / len(values), 1)
        # 检查稳定性
        if max(values) - min(values) > 2:
            avg_scores[f"{key}_不稳定"] = True

    return {
        "scores": avg_scores,
        "reasons": reasons,
        "raw": all_scores,
    }


def check_bugs(code: str) -> bool:
    """检查代码是否有明显 bug。返回 True 表示有 bug。

    原来直接 `return "有bug" in response`，而 "没有bug" 里也含 "有bug"，
    会把“没问题”判成“有 bug”，白触发一次回退重写。
    """
    client = get_client()
    response = client.chat([
        {"role": "system", "content": BUG_CHECK_PROMPT},
        {"role": "user", "content": code},
    ], temperature=0.1)

    text = (response or "").strip().lower()
    if any(word in text for word in ("没有bug", "无bug", "no bug", "no-bug", "没问题")):
        return False
    return "有bug" in text


def run(
    original_code: str,
    final_code: str,
    explanations: dict,
    context: str = "",
) -> dict:
    """
    执行 Agent 4。
    返回：{"final_code": ..., "report": ..., "scores": ...}
    """
    # 1. 检查 bug
    has_bug = check_bugs(final_code)

    if has_bug:
        print("⚠️ Agent 4 发现明显 bug，回退到 Agent 1 修改一次")
        retry_result = agent1_checker.run(final_code, context)
        final_code = retry_result["code"]
        explanations["agent4_retry"] = retry_result["explanation"]

    # 2. 评估
    eval_result = evaluate(original_code, final_code, context)

    # 3. 汇总报告
    report_parts = ["# 代码审查报告\n"]

    for agent_name, explanation in explanations.items():
        report_parts.append(f"## {agent_name}\n\n{explanation}\n")

    report_parts.append("## 评估结果\n")
    scores = eval_result["scores"]
    report_parts.append(f"- 准确性：{scores['准确性']}/5")
    report_parts.append(f"- 效率：{scores['效率']}/5")
    report_parts.append(f"- 可读性：{scores['可读性']}/5")

    # 不稳定标记
    for key in ["准确性", "效率", "可读性"]:
        if scores.get(f"{key}_不稳定"):
            report_parts.append(f"- ⚠️ {key}评估不稳定（三次分差 > 2）")

    report = "\n".join(report_parts)

    return {
        "final_code": final_code,
        "report": report,
        "scores": scores,
        "has_bug": has_bug,
    }