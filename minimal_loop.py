import json
import subprocess
import tempfile
import os

from utils.llm_client import get_client


# =============================================================================
# 工具定义（给 LLM 看的 schema）
# =============================================================================
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取文件内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": "运行 Python 代码，返回 stdout、stderr 和返回码",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "要运行的 Python 代码"}
                },
                "required": ["code"],
            },
        },
    },
]


# =============================================================================
# 工具的真实执行逻辑
# =============================================================================
def execute_read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"读取失败：{e}"


def execute_run_python(code: str) -> str:
    """把代码写到临时文件，跑一遍，返回结果。"""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name

        result = subprocess.run(
            ["python", tmp_path],
            capture_output=True,
            text=True,
            timeout=10,
        )

        os.unlink(tmp_path)

        output = []
        if result.stdout:
            output.append(f"stdout:\n{result.stdout}")
        if result.stderr:
            output.append(f"stderr:\n{result.stderr}")
        output.append(f"返回码：{result.returncode}")

        return "\n".join(output)

    except subprocess.TimeoutExpired:
        return "运行超时（10秒）"
    except Exception as e:
        return f"运行失败：{e}"


# =============================================================================
# 工具调度器
# =============================================================================
def execute_tool(name: str, arguments: dict) -> str:
    if name == "read_file":
        return execute_read_file(arguments.get("path", ""))
    elif name == "run_python":
        return execute_run_python(arguments.get("code", ""))
    else:
        return f"未知工具：{name}"


# =============================================================================
# 最小 agent loop
# =============================================================================
def run_agent(user_query: str, max_steps: int = 5) -> str:
    """
    最小 agent loop：
        1. 把用户问题和工具列表发给 LLM
        2. LLM 返回 tool_calls → 执行工具 → 结果喂回
        3. LLM 返回文本 → 任务完成
        4. 达到 max_steps → 强制停止
    """
    client = get_client()

    messages = [
        {
            "role": "system",
            "content": "你是一个代码审查助手。你可以用 read_file 读文件，用 run_python 跑代码。",
        },
        {"role": "user", "content": user_query},
    ]

    for step in range(1, max_steps + 1):
        print(f"\n--- 第 {step} 步 ---")

        # 调 LLM
        response = client.client.chat.completions.create(
            model=client.model,
            messages=messages,
            tools=TOOLS,
            temperature=0.2,
        )

        msg = response.choices[0].message

        # 情况 1：LLM 想调工具
        if msg.tool_calls:
            # 把 LLM 的决策追加到 messages（必须做，否则 LLM 不知道上一步）
            messages.append(msg)

            for tool_call in msg.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)

                print(f"🔧 LLM 请求调用：{name}({args})")

                result = execute_tool(name, args)
                print(f"📤 工具返回：{result[:200]}...")

                # 把工具结果追加到 messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

            continue  # 进入下一轮

        # 情况 2：LLM 返回文本，任务完成
        else:
            print("✅ LLM 认为任务完成")
            return msg.content

    return f"⚠️ 达到最大步数（{max_steps}），未完成"


if __name__ == "__main__":
    result = run_agent("请读取 demo.py，然后用 run_python 跑一下，告诉我有没有语法错误。")
    print("\n" + "=" * 50)
    print("最终结果：")
    print(result)