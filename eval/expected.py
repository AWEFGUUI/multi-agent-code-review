"""每个用例的期望结果。

tags：reviewer 应该报出的问题标签（与 utils/issue_tags.ISSUE_TAGS 对齐）。
      评测按标签求交，不再靠中文关键词碰运气。
should_detect：中文描述，保留给人看（报告里展示用）。
expect_output_changed：原代码本就能跑时，修复是否允许改变 stdout。
      False 表示“只允许无损修改”，stdout 变了就算输出回归。
"""

EXPECTED = {
    "case_01_syntax_error": {
        "tags": ["syntax_error"],
        "should_detect": ["语法错误"],
        "should_run": False,
        "expect_output_changed": False,
    },
    "case_02_missing_dep": {
        "tags": ["missing_dep"],
        "should_detect": ["依赖缺失"],
        "should_run": False,
        "expect_output_changed": False,
        # 缺依赖不改依赖就修不好；正确行为是识别出来并拒绝"吞掉 ImportError"的假修复，
        # 因此只算检出，不计入修复率。
        "expect_repair": False,
    },
    "case_03_division_by_zero": {
        "tags": ["zero_division"],
        "should_detect": ["除零错误"],
        "should_run": False,
        "expect_output_changed": False,
    },
    "case_04_index_out_of_range": {
        "tags": ["index_error"],
        "should_detect": ["索引越界"],
        "should_run": False,
        "expect_output_changed": False,
    },
    "case_05_nested_loop": {
        "tags": ["perf_nested_loop"],
        "should_detect": ["性能问题"],
        "should_run": True,
        "expect_output_changed": False,
    },
    "case_06_bad_naming": {
        "tags": ["naming"],
        "should_detect": ["命名不规范"],
        "should_run": True,
        # 原代码没有 print，修复不应该凭空加 print
        "expect_output_changed": False,
    },
    "case_07_no_error_handling": {
        "tags": ["no_error_handling"],
        "should_detect": ["异常处理缺失"],
        "should_run": False,
        "expect_output_changed": False,
    },
    "case_08_mutable_default": {
        "tags": ["mutable_default"],
        "should_detect": ["可变默认参数"],
        "should_run": True,
        # 修 mutable default 必然改变输出（[1, 2] → [2]）
        "expect_output_changed": True,
    },
    "case_09_inefficient_string": {
        "tags": ["perf_string_concat"],
        "should_detect": ["性能问题"],
        "should_run": True,
        "expect_output_changed": False,
    },
    "case_10_bare_except": {
        "tags": ["bare_except"],
        "should_detect": ["裸except"],
        "should_run": True,
        "expect_output_changed": False,
    },
    "case_11_global_variable": {
        "tags": ["global_var"],
        "should_detect": ["全局变量"],
        "should_run": True,
        "expect_output_changed": False,
    },
    "case_12_recursive_no_base": {
        "tags": ["recursion_no_base"],
        "should_detect": ["递归无基线"],
        "should_run": False,
        "expect_output_changed": False,
    },
    "case_13_duplicate_code": {
        "tags": ["duplicate_code"],
        "should_detect": ["重复代码"],
        "should_run": True,
        "expect_output_changed": False,
    },
    "case_14_no_type_hint": {
        "tags": ["no_type_hint"],
        "should_detect": ["无类型注解"],
        "should_run": True,
        "expect_output_changed": False,
    },
    "case_15_mixed": {
        "tags": ["perf_nested_loop", "naming"],
        "should_detect": ["性能问题", "命名不规范"],
        "should_run": True,
        # 去重会把 [2, 2] 变成 [2]，属于预期内的行为改变
        "expect_output_changed": True,
    },
}
