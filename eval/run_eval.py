"""评测：15 条用例 → 修复率 / 改坏率 / 输出回归 / 检出率 / 步数 / token。

相比上一版：
- 读 run_main_agent 的 status：超时、达到步数上限不再算“执行成功”
- 检出率按 ISSUES 标签求交，关键词匹配只作为回退
- 每条用例一个 trace 文件，不再互相覆盖
- 结果增量落盘：中途崩了，前 N 条结果还在
- 记录 model / token / 耗时，结果可归因
"""

import argparse
import json
import sys
import time
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.expected import EXPECTED  # noqa: E402
from main_agent import run_main_agent  # noqa: E402
from utils.code_runner import run_python_code  # noqa: E402
from utils.file_io import write_json  # noqa: E402
from utils.issue_tags import normalize_tag  # noqa: E402
from utils.llm_parse import parse_issues  # noqa: E402

CASES_DIR = Path(__file__).resolve().parent / "test_cases"


def _tags_from(result: dict) -> list[str]:
    tags: list[str] = []
    for item in result.get("explanations", []):
        for raw in item.get("issues") or []:
            tag = normalize_tag(raw)
            if tag and tag not in tags:
                tags.append(tag)
    for tag in parse_issues(result.get("final_message") or ""):
        if tag not in tags:
            tags.append(tag)
    return tags


def _detect(result: dict, expected: dict) -> tuple[list[str], list[str], float, str]:
    expected_tags = expected.get("tags", [])
    detected = _tags_from(result)
    hit = [tag for tag in expected_tags if tag in detected]

    if detected and expected_tags:
        return detected, hit, len(hit) / len(expected_tags), "tags"

    keywords = expected.get("should_detect", [])
    if keywords:
        text = (result.get("final_message") or "") + " ".join(
            (item.get("explanation") or "") for item in result.get("explanations", [])
        )
        kw_hit = [kw for kw in keywords if kw.lower() in text.lower()]
        return detected, kw_hit, len(kw_hit) / len(keywords), "keywords"

    return detected, hit, 1.0, "none"


def run_one_case(case_name: str, code: str, args, run_dir: Path) -> dict:
    expected = EXPECTED.get(case_name, {})
    trace_path = run_dir / "traces" / f"{case_name}.jsonl"

    original_run = run_python_code(code, timeout=args.run_timeout)
    original_can_run = original_run["returncode"] == 0 and not original_run["timeout"]
    original_stdout = (original_run.get("stdout") or "").strip()

    started = time.time()
    try:
        result = run_main_agent(
            code,
            context="",
            max_steps=args.max_steps,
            timeout=args.timeout,
            trace_path=str(trace_path),
        )
        harness_error = ""
    except Exception as exc:  # noqa: BLE001 - 单条用例失败不能拖垮整轮评测
        result = {
            "status": "harness_error",
            "completed": False,
            "final_code": code,
            "code_valid": False,
            "steps": [],
            "explanations": [],
            "rejected": [],
            "usage": {},
            "final_message": "",
            "elapsed_seconds": 0,
        }
        harness_error = f"{type(exc).__name__}: {exc}"

    fixed_run = run_python_code(result["final_code"], timeout=args.run_timeout)
    fixed_can_run = fixed_run["returncode"] == 0 and not fixed_run["timeout"]
    fixed_stdout = (fixed_run.get("stdout") or "").strip()

    status = result.get("status", "unknown")
    ok = status == "ok" and bool(result["code_valid"])

    # 有些用例本来就不该被"修好"（例如缺依赖：不改依赖就修不了，正确行为是
    # 拒绝 review_runnability 给的 try/except 空测补丁）。这类用例只算检出。
    expect_repair = expected.get("expect_repair", True)

    repaired = expect_repair and (not original_can_run) and fixed_can_run and ok
    broken = original_can_run and not fixed_can_run
    output_changed = (
        original_can_run and fixed_can_run and original_stdout != fixed_stdout
    )
    output_regression = output_changed and not expected.get("expect_output_changed", False)

    detected, hit, detect_rate, detect_source = _detect(result, expected)
    usage = result.get("usage", {}) or {}

    return {
        "case": case_name,
        "status": status,
        "ok": ok,
        "harness_error": harness_error,
        "original_can_run": original_can_run,
        "fixed_can_run": fixed_can_run,
        "expect_repair": expect_repair,
        "detect_only": (not original_can_run) and not expect_repair,
        "repaired": repaired,
        "broken": broken,
        "output_changed": output_changed,
        "output_regression": output_regression,
        "detect_rate": round(detect_rate, 3),
        "detect_source": detect_source,
        "detected": detected,
        "expected_tags": expected.get("tags", []),
        "expected_hit": hit,
        "original_stdout": original_stdout,
        "fixed_stdout": fixed_stdout,
        "steps": len(result.get("steps", [])),
        "steps_detail": result.get("steps", []),
        "final_message": (result.get("final_message") or "")[:500],
        "rejected": result.get("rejected", []),
        "tokens": usage.get("total_tokens", 0),
        "llm_calls": usage.get("calls", 0),
        "elapsed_seconds": round(time.time() - started, 1),
        "trace": str(trace_path),
        "final_code": result.get("final_code", ""),
    }


def _build_markdown(meta: dict, results: list[dict], summary: dict) -> str:
    lines = [
        "# 评测结果",
        "",
        f"- 时间：{meta['run_at']}",
        f"- 模型：`{meta['model']}`",
        f"- 用例数：{meta['cases']}（每例 max_steps={meta['max_steps']}）",
        "",
        "## 汇总",
        "",
        "| 指标 | 数值 |",
        "| --- | --- |",
        f"| 执行完成（status=ok） | {summary['ok']}/{summary['total']} |",
        f"| 超时 / 达步数上限 / LLM 失败 | {summary['not_ok']} |",
        f"| 修复成功（原本跑不了 → 跑得起来） | {summary['repaired']}/{summary['needs_fix']} |",
        f"| 只算检出（缺依赖这类改不了的用例） | {summary['detect_only']} |",
        f"| 改坏（原本能跑 → 跑不了） | {summary['broken']} |",
        f"| 输出回归（能跑但 stdout 变了） | {summary['regressions']} |",
        f"| 平均检出率 | {summary['detect_rate']:.1%} |",
        f"| 平均步数 | {summary['avg_steps']:.1f} |",
        f"| 总 token / 平均每条 | {summary['tokens']} / {summary['avg_tokens']:.0f} |",
        f"| 平均耗时 | {summary['avg_elapsed']:.1f}s |",
        "",
        "## 明细",
        "",
        "| 用例 | 状态 | 原本能跑 | 修复 | 改坏 | 输出回归 | 检出率 | 步数 | token |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in results:
        if item.get("detect_only"):
            mark = "只测检出"
        elif item["repaired"]:
            mark = "✅"
        else:
            mark = "—"
        lines.append(
            "| {case} | {status} | {orig} | {rep} | {brk} | {reg} | {det:.0%} | {steps} | {tok} |".format(
                case=item["case"],
                status=item["status"],
                orig="是" if item["original_can_run"] else "否",
                rep=mark,
                brk="❌" if item["broken"] else "—",
                reg="⚠️" if item["output_regression"] else "—",
                det=item["detect_rate"],
                steps=item["steps"],
                tok=item["tokens"],
            )
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    parser = argparse.ArgumentParser(description="跑评测集")
    parser.add_argument("--only", default="", help="只跑指定用例，逗号分隔（例：case_03,case_15）")
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=45, help="主 Agent 单次调用超时（秒）")
    parser.add_argument("--run-timeout", type=float, default=10, help="执行被测代码的超时（秒）")
    parser.add_argument("--out", default="", help="输出目录，默认 eval/runs/<时间戳>")
    parser.add_argument("--result-file", default="", help="结果 json 路径，默认 <out>/results.json")
    args = parser.parse_args(argv)

    from config import Config
    from utils.llm_client import get_client

    client = get_client()

    only = {name.strip() for name in args.only.split(",") if name.strip()}
    case_files = sorted(CASES_DIR.glob("case_*.py"))
    if only:
        case_files = [path for path in case_files if path.stem in only]
    if not case_files:
        print("❌ 没有匹配的用例")
        return 2

    run_dir = Path(args.out) if args.out else Path(__file__).resolve().parent / "runs" / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "run_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": Config.LLM_MODEL_ID,
        "cases": len(case_files),
        "max_steps": args.max_steps,
        "timeout": args.timeout,
        "python": sys.version.split()[0],
    }

    results: list[dict] = []
    result_path = Path(args.result_file) if args.result_file else run_dir / "results.json"
    payload = {"meta": meta, "results": results}

    for index, case_file in enumerate(case_files, start=1):
        case_name = case_file.stem
        code = case_file.read_text(encoding="utf-8")
        print(f"\n{'=' * 60}\n[{index}/{len(case_files)}] {case_name}\n{'=' * 60}")

        item = run_one_case(case_name, code, args, run_dir)
        results.append(item)

        # 增量落盘：单条失败不会丢掉整轮结果
        write_json(str(result_path), payload)

        print(
            f"status={item['status']} ok={item['ok']} 修复={item['repaired']} "
            f"改坏={item['broken']} 输出回归={item['output_regression']} "
            f"检出={item['detect_rate']:.0%}({item['detect_source']}) "
            f"步数={item['steps']} token={item['tokens']}"
        )

    total = len(results)
    ok_count = sum(1 for item in results if item["ok"])
    needs_fix = sum(
        1 for item in results if not item["original_can_run"] and item.get("expect_repair", True)
    )
    summary = {
        "total": total,
        "ok": ok_count,
        "not_ok": total - ok_count,
        "needs_fix": needs_fix,
        "detect_only": sum(1 for item in results if item.get("detect_only")),
        "repaired": sum(1 for item in results if item["repaired"]),
        "broken": sum(1 for item in results if item["broken"]),
        "regressions": sum(1 for item in results if item["output_regression"]),
        "detect_rate": mean(item["detect_rate"] for item in results),
        "avg_steps": mean(item["steps"] for item in results),
        "tokens": sum(item["tokens"] for item in results),
        "avg_tokens": mean(item["tokens"] for item in results),
        "avg_elapsed": mean(item["elapsed_seconds"] for item in results),
    }
    payload["summary"] = summary

    markdown = _build_markdown(meta, results, summary)
    write_json(str(result_path), payload)
    markdown_path = run_dir / "summary.md"
    markdown_path.write_text(markdown, encoding="utf-8")

    print("\n" + "=" * 60)
    print("评测汇总")
    print("=" * 60)
    print(markdown)
    print(f"详细结果：{result_path}")
    print(f"Markdown：{markdown_path}")
    print(f"调用次数：{sum(item['llm_calls'] for item in results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
