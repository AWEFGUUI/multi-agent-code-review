"""LLM 输出解析：统一、严格、可测试。

修掉 v1 的三个坑：
1. 大小写敏感 —— ```Python 被当成无语言代码块，代码里混进 "Python" 字样；
2. 取第一个代码块 —— 说明里的示例代码被当成最终代码；
3. 解析失败静默返回空串 —— 调用方 `code or 原代码` 回退，报告说改了、文件没改。
"""

import ast
import re

from utils.issue_tags import is_none_word, normalize_tag

_CODE_FENCE = re.compile(
    r"```[ \t]*(?:python|py|python3)?[ \t]*\r?\n(.*?)(?:\r?\n)?[ \t]*```",
    re.S | re.I,
)
_ISSUES_LINE = re.compile(r"^[ \t]*ISSUES?[ \t]*[:：][ \t]*(.+?)[ \t]*$", re.I | re.M)


class LLMOutputError(ValueError):
    """LLM 输出不符合约定：缺代码块 / 代码语法错。"""


def extract_code_blocks(text: str) -> list[str]:
    return [m.group(1).strip("\n") for m in _CODE_FENCE.finditer(text or "")]


def parse_issues(text: str) -> list[str]:
    """从 `ISSUES: a, b` 行解析标签，去重保序。"""
    tags: list[str] = []
    for raw in _ISSUES_LINE.findall(text or ""):
        for part in re.split(r"[,，、;；/]+", raw):
            if is_none_word(part):
                continue
            tag = normalize_tag(part)
            if tag and tag not in tags:
                tags.append(tag)
    return tags


def strip_code_and_tags(text: str) -> str:
    """去掉代码块和 ISSUES 行，剩下的就是给人看的说明。"""
    cleaned = _CODE_FENCE.sub("", text or "")
    cleaned = _ISSUES_LINE.sub("", cleaned)
    return cleaned.strip()


def ensure_valid_python(code: str) -> None:
    try:
        ast.parse(code)
    except SyntaxError as exc:
        raise LLMOutputError(f"代码无法解析：第 {exc.lineno} 行 {exc.msg}") from exc


def parse_llm_output(text: str, require_code: bool = True) -> dict:
    """返回 {"explanation", "code", "issues"}。

    require_code=True 时，没有代码块或代码语法错都会抛 LLMOutputError，
    由上层决定“重试 / 报错”，绝不再静默回退。
    """
    blocks = extract_code_blocks(text)
    code = blocks[-1] if blocks else ""

    if not code:
        if require_code:
            raise LLMOutputError("LLM 输出里没有找到 python 代码块")
        return {
            "explanation": strip_code_and_tags(text),
            "code": "",
            "issues": parse_issues(text),
        }

    ensure_valid_python(code)
    return {
        "explanation": strip_code_and_tags(text),
        "code": code,
        "issues": parse_issues(text),
    }
