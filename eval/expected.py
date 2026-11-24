EXPECTED = {
    "case_01_syntax_error": {
        "should_detect": ["语法错误"],
        "should_run": False,
    },
    "case_02_missing_dep": {
        "should_detect": ["依赖缺失"],
        "should_run": False,
    },
    "case_03_division_by_zero": {
        "should_detect": ["除零错误"],
        "should_run": False,
    },
    "case_04_index_out_of_range": {
        "should_detect": ["索引越界"],
        "should_run": False,
    },
    "case_05_nested_loop": {
        "should_detect": ["性能问题"],
        "should_run": True,
    },
    "case_06_bad_naming": {
        "should_detect": ["命名不规范"],
        "should_run": True,
    },
    "case_07_no_error_handling": {
        "should_detect": ["异常处理缺失"],
        "should_run": False,
    },
    "case_08_mutable_default": {
        "should_detect": ["可变默认参数"],
        "should_run": True,
    },
    "case_09_inefficient_string": {
        "should_detect": ["性能问题"],
        "should_run": True,
    },
    "case_10_bare_except": {
        "should_detect": ["裸except"],
        "should_run": True,
    },
    "case_11_global_variable": {
        "should_detect": ["全局变量"],
        "should_run": True,
    },
    "case_12_recursive_no_base": {
        "should_detect": ["递归无基线"],
        "should_run": False,
    },
    "case_13_duplicate_code": {
        "should_detect": ["重复代码"],
        "should_run": True,
    },
    "case_14_no_type_hint": {
        "should_detect": ["无类型注解"],
        "should_run": True,
    },
    "case_15_mixed": {
        "should_detect": ["性能问题", "命名不规范"],
        "should_run": True,
    },
}