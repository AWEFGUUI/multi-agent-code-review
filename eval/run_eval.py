import json
import sys
from pathlib import Path

# 把项目根目录加到 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main_agent import run_main_agent
from utils.code_runner import run_python_code
from eval.expected import EXPECTED


def run_one_case(case_name: str, code: str, context: str = "") -> dict:
    """跑一个用例，返回结果。"""
    print(f"\n{'='*60}")
    print(f"测试用例：{case_name}")
    print(f"{'='*60}")

    # 1. 原代码能不能跑
    original_run = run_python_code(code)
    original_can_run = (
        original_run["returncode"] == 0 and not original_run["timeout"]
    )
    original_stdout = original_run["stdout"].strip()
    print(f"原代码能否运行：{original_can_run}")

    expected = EXPECTED.get(case_name, {})
    should_detect = expected.get("should_detect", [])

    try:
        # 2. 跑 Agent
        result = run_main_agent(code, context, max_steps=8)

        # 3. 修改后能不能跑
        fixed_run = run_python_code(result["final_code"])
        fixed_can_run = (
            fixed_run["returncode"] == 0 and not fixed_run["timeout"]
        )
        fixed_stdout = fixed_run["stdout"].strip()
        print(f"修改后能否运行：{fixed_can_run}")

        # 4. 修复成功 = 原本不能跑，改完能跑
        fixed_successfully = (not original_can_run) and fixed_can_run

        # 5. 改坏 = 原本能跑，改完跑不了了
        broken = original_can_run and not fixed_can_run

        # 6. 改坏率 = 原本能跑，改完 stdout 变了
        output_changed = (
            original_can_run
            and fixed_can_run
            and original_stdout != fixed_stdout
        )

        # 7. 检出率：期望的问题，有没有在报告里提到
        report_text = result["final_message"]
        for exp in result["explanations"]:
            report_text += exp.get("explanation", "")
        detected = []
        for issue in should_detect:
            if issue in report_text:
                detected.append(issue)
        detect_rate = (
            len(detected) / len(should_detect) if should_detect else 1.0
        )

        return {
            "case": case_name,
            "success": True,
            "original_can_run": original_can_run,
            "fixed_can_run": fixed_can_run,
            "fixed_successfully": fixed_successfully,
            "broken": broken,
            "output_changed": output_changed,
            "detect_rate": detect_rate,
            "detected": detected,
            "should_detect": should_detect,
            "original_stdout": original_stdout,
            "fixed_stdout": fixed_stdout,
            "final_code": result["final_code"],
            "steps": len(result["steps"]),
            "steps_detail": result["steps"],
        }

    except Exception as e:
        return {
            "case": case_name,
            "success": False,
            "original_can_run": original_can_run,
            "should_detect": should_detect,
            "error": str(e),
        }


def main():
    cases_dir = Path(__file__).parent / "test_cases"
    results = []

    case_files = sorted(cases_dir.glob("case_*.py"))

    for case_file in case_files:
        case_name = case_file.stem
        code = case_file.read_text(encoding="utf-8")

        result = run_one_case(case_name, code)
        results.append(result)

        print(f"期望检出：{result.get('should_detect')}")
        print(f"实际检出：{result.get('detected')}")
        print(f"检出率：{result.get('detect_rate')}")
        print(f"修复成功：{result.get('fixed_successfully')}")
        print(f"改坏：{result.get('broken')}")
        print(f"输出变化：{result.get('output_changed')}")
        print(f"步数：{result.get('steps')}")

    # 汇总
    print("\n" + "=" * 60)
    print("评测汇总")
    print("=" * 60)

    total = len(results)
    success = sum(1 for r in results if r.get("success"))
    needs_fix = sum(1 for r in results if not r.get("original_can_run"))
    fixed_success = sum(1 for r in results if r.get("fixed_successfully"))
    broken = sum(1 for r in results if r.get("broken"))
    output_changed = sum(1 for r in results if r.get("output_changed"))
    avg_steps = (
        sum(r.get("steps", 0) for r in results if r.get("success"))
        / max(success, 1)
    )
    avg_detect = (
        sum(r.get("detect_rate", 0) for r in results if r.get("success"))
        / max(success, 1)
    )

    print(f"总用例：{total}")
    print(f"Agent 执行成功：{success}/{total}")
    print(f"原本有问题：{needs_fix}")
    print(f"修复成功：{fixed_success}/{needs_fix}")
    print(f"改坏：{broken}")
    print(f"输出变化：{output_changed}")
    print(f"平均检出率：{avg_detect:.1%}")
    print(f"平均步数：{avg_steps:.1f}")

    output_path = Path(__file__).parent / "eval_results.json"
    output_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n详细结果已保存：{output_path}")


if __name__ == "__main__":
    main()