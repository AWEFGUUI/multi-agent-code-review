"""离线测试：不调真实 LLM，不花额度。

    python -m unittest discover -s tests -v

覆盖这次改动的关键点：解析门禁、执行器隔离/超时/跳过、trace 追加、
主 Agent 状态机、评测的标签检出。
"""

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 本机 conda 环境里 openai 与 aiohttp 版本不匹配，import openai 会直接抛异常。
# 测试不需要真的联网，缺依赖时打桩即可，让测试在任何环境下都能跑。
for _name in ("openai", "dotenv"):
    try:
        __import__(_name)
    except Exception:  # noqa: BLE001
        module = types.ModuleType(_name)
        module.OpenAI = object
        module.load_dotenv = lambda *a, **k: None
        sys.modules[_name] = module

from utils.code_runner import check_risky, run_python_code, scan_code  # noqa: E402
from utils.issue_tags import normalize_tag  # noqa: E402
from utils.llm_parse import LLMOutputError, extract_code_blocks, parse_issues, parse_llm_output  # noqa: E402
from utils.tracer import Tracer  # noqa: E402


class LLMParseTest(unittest.TestCase):
    def test_capitalized_fence(self):
        result = parse_llm_output("说明\n```Python\nx = 1\n```\n")
        self.assertEqual(result["code"], "x = 1")

    def test_picks_last_block_not_example(self):
        text = "示例：\n```python\nprint('demo')\n```\n最终代码：\n```python\nx = 2\n```\n"
        self.assertEqual(parse_llm_output(text)["code"], "x = 2")

    def test_missing_block_raises(self):
        with self.assertRaises(LLMOutputError):
            parse_llm_output("我检查了一下，没问题。")

    def test_invalid_code_raises(self):
        with self.assertRaises(LLMOutputError):
            parse_llm_output("```python\ndef f(:\n    pass\n```")

    def test_crlf(self):
        blocks = extract_code_blocks("```python\r\nx = 1\r\n```")
        self.assertEqual(blocks, ["x = 1"])

    def test_issues_line(self):
        text = "说明\n```python\nx = 1\n```\nISSUES: syntax_error, Naming\n"
        self.assertEqual(parse_issues(text), ["syntax_error", "naming"])

    def test_issues_none(self):
        self.assertEqual(parse_issues("ISSUES: none"), [])

    def test_explanation_has_no_code(self):
        text = "改了命名\n```python\nx = 1\n```\nISSUES: naming\n"
        explanation = parse_llm_output(text)["explanation"]
        self.assertIn("改了命名", explanation)
        self.assertNotIn("```", explanation)
        self.assertNotIn("ISSUES", explanation)

    def test_normalize_alias(self):
        self.assertEqual(normalize_tag("语法错误"), "syntax_error")
        self.assertEqual(normalize_tag("Nested Loop"), "perf_nested_loop")
        self.assertEqual(normalize_tag("完全不认识的标签"), "other")


class CodeRunnerTest(unittest.TestCase):
    def test_chinese_output_roundtrip(self):
        result = run_python_code('print("计算失败：除数不能为零")')
        self.assertEqual(result["returncode"], 0)
        self.assertIn("计算失败", result["stdout"])

    def test_env_is_scrubbed(self):
        os.environ["LLM_API_KEY"] = "sk-test-should-not-leak"
        try:
            result = run_python_code(
                'import os\nprint("seen=" + str("LLM_API_KEY" in os.environ))'
            )
        finally:
            os.environ.pop("LLM_API_KEY", None)
        self.assertEqual(result["returncode"], 0)
        self.assertIn("seen=False", result["stdout"])

    def test_gui_is_skipped(self):
        result = run_python_code("import tkinter\nprint('x')")
        self.assertTrue(result["skipped"])
        self.assertIn("tkinter", result["skip_reason"])

    def test_input_helper_not_false_positive(self):
        self.assertEqual(check_risky("def get_input(p):\n    return p"), "")
        self.assertEqual(check_risky("x = user_input('hi')"), "")

    def test_real_input_is_skipped(self):
        self.assertTrue(check_risky("name = input('x')"))

    def test_syntax_error_reported_without_running(self):
        result = run_python_code("def f(:\n    pass")
        self.assertEqual(result["returncode"], -1)
        self.assertIn("语法错误", result["stderr"])

    def test_timeout_kills_process(self):
        result = run_python_code("while True:\n    pass\n", timeout=1)
        self.assertTrue(result["timeout"])
        self.assertLess(result["duration_seconds"], 15)

    def test_dangerous_call_warns_but_runs(self):
        result = run_python_code("import os\nprint('done')")
        self.assertEqual(result["returncode"], 0)
        scan = scan_code("import os; os.system('echo hi')")
        self.assertIn("os.system", scan["warnings"])


class TracerTest(unittest.TestCase):
    def test_appends_and_does_not_truncate(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace = Path(tmp) / "trace.jsonl"
            Tracer(trace).log(1, "run_python", {"code": "x"}, "result-1", 0.1)
            Tracer(trace).log(2, "run_python", {"code": "x"}, "result-2", 0.2)

            lines = trace.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            record = json.loads(lines[1])
            self.assertEqual(record["step"], 2)
            self.assertTrue(record["ok"])
            self.assertIn("result_length", record)


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class FakeClient:
    """假的 LLM 客户端：只回放预设的响应序列。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.usage = {"calls": 1, "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    def reset_usage(self):
        pass

    def chat_with_tools(self, messages, tools, **kwargs):
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _tool_call(call_id, name, arguments):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


class MainAgentTest(unittest.TestCase):
    def _run(self, responses, code="print(1)\n"):
        import main_agent

        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(responses)
            return main_agent.run_main_agent(
                code,
                max_steps=5,
                trace_path=str(Path(tmp) / "trace.jsonl"),
                client=client,
            )

    def test_status_ok_after_tool_then_text(self):
        call = _tool_call("1", "run_python", json.dumps({"code": "print(2)"}))
        result = self._run([FakeMessage(tool_calls=[call]), FakeMessage("完成")])
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["completed"])
        self.assertTrue(result["code_valid"])
        self.assertEqual(result["steps"], ["run_python"])

    def test_status_timeout_not_ok(self):
        result = self._run([TimeoutError("timed out")])
        self.assertEqual(result["status"], "timeout")
        self.assertFalse(result["completed"])

    def test_max_steps_reported(self):
        call = _tool_call("1", "run_python", json.dumps({"code": "print(2)"}))
        result = self._run([FakeMessage(tool_calls=[call])] * 5)
        self.assertEqual(result["status"], "max_steps")
        self.assertFalse(result["completed"])

    def test_bad_json_arguments_do_not_crash(self):
        call = _tool_call("1", "run_python", "{not json")
        result = self._run([FakeMessage(tool_calls=[call]), FakeMessage("完成")])
        self.assertEqual(result["status"], "ok")

    def test_adopt_rejects_syntax_broken_code(self):
        import main_agent

        rejected = []
        self.assertFalse(main_agent._adopt_code("def f(:\n    pass", rejected))
        self.assertEqual(len(rejected), 1)
        self.assertTrue(main_agent._adopt_code("x = 1", rejected))


class EvalMetricTest(unittest.TestCase):
    def test_tag_detection(self):
        from eval.run_eval import _detect

        result = {
            "explanations": [
                {"agent": "review_style", "explanation": "把 f 改成 divide", "issues": ["naming"]}
            ],
            "final_message": "ISSUES: perf_nested_loop",
        }
        expected = {"tags": ["naming", "perf_nested_loop"], "should_detect": ["命名不规范"]}
        detected, hit, rate, source = _detect(result, expected)
        self.assertEqual(source, "tags")
        self.assertEqual(rate, 1.0)
        self.assertCountEqual(detected, ["naming", "perf_nested_loop"])

    def test_keyword_fallback_when_no_tags(self):
        from eval.run_eval import _detect

        result = {
            "explanations": [{"agent": "review_style", "explanation": "存在语法错误", "issues": []}],
            "final_message": "",
        }
        expected = {"tags": ["syntax_error"], "should_detect": ["语法错误"]}
        _, _, rate, source = _detect(result, expected)
        self.assertEqual(source, "keywords")
        self.assertEqual(rate, 1.0)


class ConfigTest(unittest.TestCase):
    def test_placeholder_detected(self):
        import config

        self.assertTrue(config._is_placeholder("sk-your-key-here"))
        self.assertTrue(config._is_placeholder("sk-xxxxxxxx"))
        self.assertFalse(config._is_placeholder("sk-abc123def456abc123def456abc12345"))


class CliTest(unittest.TestCase):
    """CLI 落盘行为：不调 LLM，用假结果替换 run_main_agent。"""

    def _fake(self, status="ok", final_code="print(2)\n"):
        return {
            "status": status,
            "completed": status == "ok",
            "final_code": final_code,
            "code_valid": True,
            "final_message": "done",
            "steps": ["run_python"],
            "explanations": [{"agent": "run_python", "explanation": "ok", "issues": []}],
            "rejected": [],
            "usage": {"calls": 1, "prompt_tokens": 6, "completion_tokens": 4, "total_tokens": 10},
            "elapsed_seconds": 1.0,
            "trace_path": "",
        }

    def test_artifacts_written_and_exit_zero(self):
        from unittest.mock import patch

        import cli

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "demo.py"
            source.write_text("print(1)\n", encoding="utf-8")
            out = Path(tmp) / "runs"

            with patch.object(cli, "run_main_agent", return_value=self._fake()):
                exit_code = cli.main(["--code", str(source), "--out", str(out)])

            self.assertEqual(exit_code, 0)
            run_dirs = list(out.iterdir())
            self.assertEqual(len(run_dirs), 1)
            run_dir = run_dirs[0]
            for name in ("input.py", "reviewed.py", "summary.md", "diff.patch", "result.json"):
                self.assertTrue((run_dir / name).is_file(), f"{name} 未生成")

            diff_text = (run_dir / "diff.patch").read_text(encoding="utf-8")
            self.assertIn("-print(1)", diff_text)
            self.assertIn("+print(2)", diff_text)

            summary = (run_dir / "summary.md").read_text(encoding="utf-8")
            self.assertIn("状态：**ok**", summary)

    def test_non_ok_status_exits_two(self):
        from unittest.mock import patch

        import cli

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "demo.py"
            source.write_text("print(1)\n", encoding="utf-8")
            with patch.object(
                cli, "run_main_agent", return_value=self._fake(status="max_steps")
            ):
                exit_code = cli.main(
                    ["--code", str(source), "--out", str(Path(tmp) / "runs")]
                )
            self.assertEqual(exit_code, 2)


class EvalRunCaseTest(unittest.TestCase):
    """验证“超时不再算成功”“修好才算 repaired”这两条指标语义。"""

    def _result(self, **overrides):
        base = {
            "status": "ok",
            "completed": True,
            "final_code": "",
            "code_valid": True,
            "final_message": "ISSUES: zero_division",
            "steps": ["review_runnability", "run_python"],
            "explanations": [{"agent": "review_runnability", "explanation": "加除零校验", "issues": ["zero_division"]}],
            "rejected": [],
            "usage": {"calls": 2, "prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            "elapsed_seconds": 3.0,
        }
        base.update(overrides)
        return base

    def _run(self, fake):
        import argparse
        import tempfile
        from unittest.mock import patch

        import eval.run_eval as runner

        args = argparse.Namespace(max_steps=8, timeout=45, run_timeout=10)
        case = "case_03_division_by_zero"
        code = (Path(runner.__file__).parent / "test_cases" / f"{case}.py").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            runner, "run_main_agent", return_value=fake
        ):
            return runner.run_one_case(case, code, args, Path(tmp))

    def test_timeout_is_not_success(self):
        item = self._run(self._result(status="timeout", completed=False, final_code="x = 1\n"))
        self.assertFalse(item["ok"])
        self.assertFalse(item["repaired"])

    def test_repaired_when_original_fails_and_final_runs(self):
        fixed = "def divide(a, b):\n    if b == 0:\n        raise ValueError('除数不能为零')\n    return a / b\n\nprint(divide(10, 2))\n"
        item = self._run(self._result(final_code=fixed))
        self.assertFalse(item["original_can_run"])
        self.assertTrue(item["fixed_can_run"])
        self.assertTrue(item["repaired"])
        self.assertEqual(item["detect_rate"], 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
