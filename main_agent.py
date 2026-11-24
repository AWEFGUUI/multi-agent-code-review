import json
import time
from utils.llm_client import get_client
from utils.tracer import Tracer
from tools import TOOLS, execute_tool


SYSTEM_PROMPT = """你是一个代码审查调度器。

你有以下工具：
- review_runnability：检查代码能否运行
- review_efficiency：检查性能瓶颈（超时 40 秒，重试 2 次）
- review_style：检查代码规范
- run_python：运行代码，看能否真的跑通

你的工作流程：
1. 先调 review_runnability，确保代码能跑
2. 如果有修改，调 run_python 验证修改后的代码能跑
3. 再调 review_efficiency 和 review_style
4. 每次修改后，调 run_python 验证
5. 当你有足够信息时，返回最终结果

重要：
- 工具返回的 code 字段是修改后的代码
- 你可以多次调同一个工具
- 最多 10 步，达到上限必须返回结果
- 如果某个工具超时失败，不要重试，直接继续下一步

关于 run_python 的使用限制：
- 只对纯计算、纯逻辑的代码有效
- 不要跑 GUI 程序（tkinter、pyqt、wx）
- 不要跑需要模型文件、数据集、外部资源的程序
- 不要跑需要用户输入的程序（input、sys.stdin）
- 不要跑依赖缺失的程序（先看 import 语句，判断依赖是否齐全）
- 如果 run_python 返回 skipped=True，说明工具主动跳过了，不要重试
"""


def run_main_agent(user_code: str, context: str = "", max_steps: int = 10) -> dict:
    client = get_client()
    tracer = Tracer()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"""请审查以下代码。

工作背景：{context or '未提供'}

代码：
{user_code}

请按流程审查，最后返回最终代码。"""},
    ]

    current_code = user_code
    explanations = []
    steps = []

    for step in range(1, max_steps + 1):
        print(f"\n--- 主 Agent 第 {step} 步 ---")

        try:
            response = client.client.chat.completions.create(
                model=client.model,
                messages=messages,
                tools=TOOLS,
                temperature=0.2,
                timeout=20,   # 主 Agent 单次调用 20 秒超时
            )
        except Exception as e:
            print(f"❌ 主 Agent 调用失败（20秒超时）：{e}")
            return {
                "final_code": current_code,
                "explanations": explanations,
                "steps": steps,
                "final_message": f"主 Agent 调用超时：{e}",
            }

        msg = response.choices[0].message

        if msg.tool_calls:
            messages.append(msg)

            for tool_call in msg.tool_calls:
                name = tool_call.function.name

                # 保护：解析 tool_call 参数
                try:
                    args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError as e:
                    print(f"⚠️ 解析工具参数失败：{e}")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": f"参数解析失败：{e}，请重新输出合法的 JSON",
                    })
                    continue

                print(f"🔧 主 Agent 决定调用：{name}")

                start = time.time()
                try:
                    result_str = execute_tool(name, args)
                except Exception as e:
                    print(f"⚠️ 工具执行失败：{e}")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": f"工具执行失败：{e}",
                    })
                    continue
                duration = time.time() - start

                tracer.log(step, name, args, result_str, duration)

                # 保护：解析工具返回
                try:
                    result = json.loads(result_str)
                except json.JSONDecodeError:
                    result = {"code": current_code, "explanation": result_str}

                if result.get("code"):
                    current_code = result["code"]

                explanations.append({
                    "agent": name,
                    "explanation": result.get("explanation", ""),
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_str,
                })

                steps.append(name)
                print(f"✅ {name} 完成（{duration:.1f}秒）")

            continue

        else:
            print("✅ 主 Agent 认为任务完成")
            return {
                "final_code": current_code,
                "explanations": explanations,
                "steps": steps,
                "final_message": msg.content,
            }

    return {
        "final_code": current_code,
        "explanations": explanations,
        "steps": steps,
        "final_message": f"达到最大步数（{max_steps}）",
    }


if __name__ == "__main__":
    code = '''
def f(a, b):
    r = a / b
    return r

print(f(10, 0))
'''

    result = run_main_agent(code, context="简单的除法函数")

    print("\n" + "=" * 50)
    print("最终代码：")
    print(result["final_code"])
    print("\n" + "=" * 50)
    print("调用轨迹：", result["steps"])