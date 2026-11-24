"""问题标签：让“检出率”可评测，而不是靠中文关键词碰运气。

reviewer 必须在回答最后输出一行 `ISSUES: tag1, tag2`，评测按标签求交。
这样“说法换了”不会影响指标（原来的关键词匹配会把英文描述判成没检出）。
"""

ISSUE_TAGS = (
    "syntax_error",
    "missing_dep",
    "zero_division",
    "index_error",
    "no_error_handling",
    "mutable_default",
    "recursion_no_base",
    "global_var",
    "bare_except",
    "perf_nested_loop",
    "perf_string_concat",
    "naming",
    "no_type_hint",
    "duplicate_code",
    "logic_error",
    "other",
)

# 中英文别名 → 标准标签
_ALIASES = {
    "syntax": "syntax_error",
    "syntaxerror": "syntax_error",
    "语法错误": "syntax_error",
    "missing_dependency": "missing_dep",
    "missing_dependencies": "missing_dep",
    "依赖缺失": "missing_dep",
    "divide_by_zero": "zero_division",
    "division_by_zero": "zero_division",
    "除零": "zero_division",
    "除零错误": "zero_division",
    "indexerror": "index_error",
    "index_out_of_range": "index_error",
    "索引越界": "index_error",
    "error_handling": "no_error_handling",
    "异常处理缺失": "no_error_handling",
    "mutable_default_argument": "mutable_default",
    "可变默认参数": "mutable_default",
    "recursion": "recursion_no_base",
    "递归无基线": "recursion_no_base",
    "global": "global_var",
    "全局变量": "global_var",
    "bare_except_clause": "bare_except",
    "裸except": "bare_except",
    "nested_loop": "perf_nested_loop",
    "o(n^2)": "perf_nested_loop",
    "性能问题": "perf_nested_loop",
    "string_concat": "perf_string_concat",
    "string_concatenation": "perf_string_concat",
    "命名不规范": "naming",
    "naming_convention": "naming",
    "type_hint": "no_type_hint",
    "type_annotation": "no_type_hint",
    "无类型注解": "no_type_hint",
    "duplication": "duplicate_code",
    "重复代码": "duplicate_code",
    "bug": "logic_error",
}

_NONE_WORDS = {"none", "no", "n/a", "-", "无", "没有", "空"}


def normalize_tag(raw: str) -> str:
    """把模型输出的任意标签归一化到 ISSUE_TAGS；无法识别返回 "other"。"""
    t = (raw or "").strip().strip("`.,;，。；、 ").lower()
    if not t:
        return ""
    t = t.replace(" ", "_").replace("-", "_")
    t = _ALIASES.get(t, t)
    return t if t in ISSUE_TAGS else "other"


def is_none_word(raw: str) -> bool:
    return (raw or "").strip().strip("`.,;，。； ").lower() in _NONE_WORDS


ISSUES_INSTRUCTION = f"""
问题标签（必须输出，用于自动评测）：
在回答的最后单独一行输出
ISSUES: tag1, tag2
可用标签：{', '.join(ISSUE_TAGS)}
只列你确认存在的问题；没有发现任何问题就输出 ISSUES: none
"""
