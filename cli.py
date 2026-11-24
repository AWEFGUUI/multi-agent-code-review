"""统一入口：审查一个 .py 文件，把结果落到 runs/<时间戳>/。

产物：
    input.py      原文件副本
    reviewed.py   修改后的代码
    summary.md    人读的报告（含 diff）
    diff.patch    unified diff
    trace.jsonl   工具调用轨迹
    result.json   结构化结果（status/token/步骤）

用法：
    python cli.py --code demo.py
    python cli.py --code demo.py --context "数据规模只有几十条" --max-steps 8
"""

import argparse
import difflib
import sys
import time
from pathlib import Path

from main_agent import run_main_agent
from utils.code_runner import run_python_code
from utils.console import setup_console
from utils.file_io import read_file, write_file, write_json


def _new_run_dir(base: str) -> Path:
    root = Path(base)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = root / stamp
    index = 1
    while run_dir.exists():
        index += 1
        run_dir = root / f"{stamp}-{index}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _diff(original: str, final: str) -> str:
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            final.splitlines(keepends=True),
            fromfile="input.py",
            tofile="reviewed.py",
        )
    )


def _build_summary(result: dict, diff_text: str, original_run: dict, fixed_run: dict) -> str:
    usage = result.get("usage", {})
    steps = " → ".join(result.get("steps", [])) or "（无）"
    lines = [
        "# 代码审查报告",
        "",
        f"- 状态：**{result['status']}**（completed={result['completed']}）",
        f"- 最终代码可解析：{'是' if result.get('code_valid') else '否'}",
        f"- 步数：{len(result.get('steps', []))}（{steps}）",
        f"- 耗时：{result.get('elapsed_seconds', 0)}s",
        f"- token：{usage.get('total_tokens', 0)}"
        f"（prompt {usage.get('prompt_tokens', 0)} / completion {usage.get('completion_tokens', 0)}）",
        f"- 被拒绝的修改：{len(result.get('rejected', []))}",
    ]
    if result.get("rejected"):
        for reason in result["rejected"]:
            lines.append(f"  - {reason}")
    lines += ["", "## 变更", "", "```diff", diff_text.strip() or "（无改动）", "```", ""]

    lines += ["## 运行结果", ""]
    for title, run in (("原代码", original_run), ("修改后", fixed_run)):
        if run is None:
            continue
        if run.get("skipped"):
            lines.append(f"- {title}：跳过运行（{run.get('skip_reason')}）")
        else:
            lines.append(
                f"- {title}：returncode={run.get('returncode')}，"
                f"timeout={run.get('timeout')}，{run.get('duration_seconds')}s"
            )
            out = (run.get("stdout") or "").strip()
            err = (run.get("stderr") or "").strip()
            if out:
                lines.append(f"  - stdout：`{out[:200]}`")
            if err:
                lines.append(f"  - stderr：`{err[:300]}`")
    lines.append("")

    lines += ["## 各工具意见", ""]
    for item in result.get("explanations", []):
        issues = item.get("issues") or []
        tag = f"（issues: {', '.join(issues)}）" if issues else ""
        lines.append(f"### {item['agent']}{tag}")
        lines.append("")
        body = item.get("explanation") or ""
        lines.append(body.strip() or "（无说明）")
        if item.get("error"):
            lines.append(f"\n> 错误：{item['error']}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    setup_console()

    parser = argparse.ArgumentParser(description="多智能体代码审查（v2 主 Agent + 工具）")
    parser.add_argument("--code", required=True, help="要审查的 .py 文件")
    parser.add_argument("--context", default="", help="工作背景说明")
    parser.add_argument("--max-steps", type=int, default=10, help="主 Agent 最大步数")
    parser.add_argument("--timeout", type=float, default=45, help="主 Agent 单次 LLM 调用超时（秒）")
    parser.add_argument("--out", default="runs", help="输出根目录，默认 runs/")
    parser.add_argument("--no-run", action="store_true", help="不实际执行原代码/结果代码")
    args = parser.parse_args(argv)

    source = Path(args.code)
    if not source.is_file():
        print(f"❌ 文件不存在：{source}")
        return 2
    if source.suffix != ".py":
        print(f"⚠️ 只支持 .py 文件，收到：{source.suffix or '（无后缀）'}")

    run_dir = _new_run_dir(args.out)
    original_code = read_file(str(source))
    write_file(str(run_dir / "input.py"), original_code)

    print(f"📖 已读取：{source}（{len(original_code)} 字符）")
    print(f"📂 本次产物目录：{run_dir}")

    result = run_main_agent(
        original_code,
        context=args.context,
        max_steps=args.max_steps,
        timeout=args.timeout,
        trace_path=str(run_dir / "trace.jsonl"),
    )

    final_code = result["final_code"]
    write_file(str(run_dir / "reviewed.py"), final_code)

    diff_text = _diff(original_code, final_code)
    write_file(str(run_dir / "diff.patch"), diff_text or "")

    original_run = None if args.no_run else run_python_code(original_code)
    fixed_run = None if args.no_run else run_python_code(final_code)

    write_file(
        str(run_dir / "summary.md"),
        _build_summary(result, diff_text, original_run, fixed_run),
    )

    payload = dict(result)
    payload["source"] = str(source)
    payload["diff_lines"] = len(diff_text.splitlines())
    write_json(str(run_dir / "result.json"), payload)

    print("\n" + "=" * 50)
    print(f"状态：{result['status']}（completed={result['completed']}）")
    print(f"步数：{len(result['steps'])} → {' → '.join(result['steps']) or '无'}")
    print(f"token：{result['usage'].get('total_tokens', 0)}，耗时：{result['elapsed_seconds']}s")
    print(f"📄 修改后代码：{run_dir / 'reviewed.py'}")
    print(f"📄 报告：{run_dir / 'summary.md'}")
    print(f"📄 diff：{run_dir / 'diff.patch'}")
    print("=" * 50)

    ok = result["status"] == "ok" and result["code_valid"]
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
