"""主 Agent：一个带工具的 tool_calls 循环。

改动点：
- 走 LLMClient.chat_with_tools（带 timeout + 只重试可重试错误），
  不再直接 client.client.chat.completions.create 绕过封装。
- 返回 status/completed：区分 ok / max_steps / timeout / llm_error，
  调用方（评测）不能再把“超时”记成“执行成功”。
- 采用门禁：reviewer 返回的代码必须能 ast.parse 才采用，
  被拒绝的修改单独记录（rejected），不再静默覆盖 current_code。
- 统计 token 用量与耗时。
"""

import ast
import json
import time

from tools import TOOLS, execute_tool
from utils.console import setup_console
from utils.llm_client import get_client, is_timeout_error
from utils.tracer import Tracer

setup_console()

SYSTEM_PROMPT = """你是一个代码审查调度器。

你有以下工具：
- review_runnability：检查代码能否运行（语法、依赖、严重逻辑错误）
- review_efficiency：检查性能瓶颈（较慢，约 10-60 秒）
- review_style：检查代码规范
- run_python：在隔离子进程里运行代码，验证能否真的跑通

建议流程（可以按情况调整）：
1. 先调 review_runnability，确保代码能跑
2. 有修改就调 run_python 验证
3. 再考虑 review_efficiency / review_style
4. 每次修改后都调 run_python 验证

重要：
- 工具返回的 code 字段是修改后的完整代码；error 字段表示这次调用失败，不要基于它继续
- 工具返回的 issues 是问题标签，汇总时请保留
- 你可以多次调同一个工具，但不要无意义重复
- 最多 10 步，达到上限必须返回结果
- 不要为了“看起来改了”而新增 print、删除调用或吞掉异常——那会改变程序行为
"""


def _adopt_code(code: str, rejected: list) -> bool:
    """只有语法合法的代码才允许被采用。"""
    if not code or not code.strip():
        return False
    try:
        ast.parse(code)
    except SyntaxError as exc:
        rejected.append(f"第 {exc.lineno} 行 {exc.msg}")
        return False
    return True


def run_main_agent(
    user_code: str,
    context: str = "",
    max_steps: int = 10,
    timeout: float = 45,
    trace_path: str | None = None,
    client=None,
) -> dict:
    """返回 {status, completed, final_code, code_valid, steps, explanations, ...}。"""
    client = client or get_client()
    try:
        client.reset_usage()
    except AttributeError:
        pass

    tracer = Tracer(trace_path)
    started = time.time()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"""请审查以下代码。

工作背景：{context or '未提供'}

代码：
{user_code}

请按流程审查，最后返回最终代码。""",
        },
    ]

    current_code = user_code
    explanations: list[dict] = []
    rejected: list[str] = []
    steps: list[str] = []
    status = "max_steps"
    final_message = ""

    for step in range(1, max_steps + 1):
        print(f"\n--- 主 Agent 第 {step} 步 ---")

        try:
            msg = client.chat_with_tools(
                messages, TOOLS, temperature=0.2, timeout=timeout, max_retries=2
            )
        except Exception as exc:  # noqa: BLE001 - 循环必须给出结构化失败
            status = "timeout" if is_timeout_error(exc) else "llm_error"
            final_message = f"LLM 调用失败：{type(exc).__name__}: {exc}"
            print(f"❌ {final_message}")
            break

        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            final_message = (getattr(msg, "content", "") or "").strip()
            status = "ok" if final_message else "empty_response"
            print("✅ 主 Agent 认为任务完成")
            break

        # 必须先把 assistant 的决策写回历史，否则模型不知道上一步做过什么
        messages.append(msg)

        for tool_call in tool_calls:
            name = getattr(tool_call.function, "name", "")
            raw_args = getattr(tool_call.function, "arguments", "") or "{}"

            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError as exc:
                print(f"⚠️ 工具参数不是合法 JSON：{exc}")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(
                            {"error": f"参数不是合法 JSON：{exc}，请重新输出"}, ensure_ascii=False
                        ),
                    }
                )
                continue

            print(f"🔧 主 Agent 决定调用：{name}")

            before_usage = dict(getattr(client, "usage", {}) or {})
            start = time.time()
            try:
                result_str = execute_tool(name, args)
            except Exception as exc:  # noqa: BLE001
                result_str = json.dumps(
                    {"error": f"工具执行异常：{type(exc).__name__}: {exc}"}, ensure_ascii=False
                )
            duration = time.time() - start

            try:
                result = json.loads(result_str)
                if not isinstance(result, dict):
                    result = {"explanation": result_str}
            except json.JSONDecodeError:
                result = {"explanation": result_str}

            after_usage = getattr(client, "usage", {}) or {}
            tokens = {
                key: after_usage.get(key, 0) - before_usage.get(key, 0)
                for key in after_usage
            }

            tracer.log(
                step,
                name,
                args,
                result_str,
                duration,
                tokens=tokens,
                ok="error" not in result,
            )

            if result.get("code") and _adopt_code(result["code"], rejected):
                current_code = result["code"]

            explanations.append(
                {
                    "agent": name,
                    "explanation": result.get("explanation", ""),
                    "issues": result.get("issues", []),
                    "error": result.get("error", ""),
                }
            )
            steps.append(name)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_str,
                }
            )

            if result.get("error"):
                print(f"⚠️ {name} 返回错误：{result['error']}")
            else:
                print(f"✅ {name} 完成（{duration:.1f}秒）")

    try:
        code_valid = bool(ast.parse(current_code))
    except SyntaxError:
        code_valid = False

    usage = dict(getattr(client, "usage", {}) or {})
    return {
        "status": status,
        "completed": status == "ok",
        "final_code": current_code,
        "code_valid": code_valid,
        "final_message": final_message,
        "steps": steps,
        "explanations": explanations,
        "rejected": rejected,
        "usage": usage,
        "elapsed_seconds": round(time.time() - started, 2),
        "trace_path": str(tracer.output_path),
    }


if __name__ == "__main__":
    from cli import main as cli_main

    raise SystemExit(cli_main())
