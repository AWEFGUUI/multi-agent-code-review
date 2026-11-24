import argparse
from pathlib import Path

from config import Config
from utils.file_io import read_file, write_file, ensure_output_dir
from agents import agent1_checker, agent2_optimizer, agent3_stylist, agent4_evaluator


def main():
    # 1. 解析命令行参数
    parser = argparse.ArgumentParser(description="多智能体代码审查系统")
    parser.add_argument("--code", required=True, help="要审查的 .py 文件路径")
    parser.add_argument("--context", default="", help="工作背景说明")
    parser.add_argument("--output", default="output", help="输出目录")
    args = parser.parse_args()

    # 2. 检查配置
    Config.check()

    # 3. 读代码
    code_path = args.code
    original_code = read_file(code_path)
    print(f"📖 已读取：{code_path}（{len(original_code)} 字符）")

    # 4. 确保输出目录存在
    ensure_output_dir(args.output)

    explanations = {}
    current_code = original_code

    # 5. Agent 1：可运行性
    print("\n" + "=" * 50)
    print("🔍 Agent 1：可运行性审查")
    print("=" * 50)
    result1 = agent1_checker.run(current_code, args.context)
    current_code = result1["code"]
    explanations["Agent 1（可运行性）"] = result1["explanation"]
    print("✅ Agent 1 完成")

    # 6. Agent 2：效率
    print("\n" + "=" * 50)
    print("⚡ Agent 2：效率审查")
    print("=" * 50)
    result2 = agent2_optimizer.run(current_code, args.context)
    current_code = result2["code"]
    explanations["Agent 2（效率）"] = result2["explanation"]
    print("✅ Agent 2 完成")

    # 7. Agent 3：规范
    print("\n" + "=" * 50)
    print("📐 Agent 3：规范审查")
    print("=" * 50)
    result3 = agent3_stylist.run(current_code, args.context)
    current_code = result3["code"]
    explanations["Agent 3（规范）"] = result3["explanation"]
    print("✅ Agent 3 完成")

    # 8. Agent 4：评估 + 汇总
    print("\n" + "=" * 50)
    print("📊 Agent 4：评估与汇总")
    print("=" * 50)
    result4 = agent4_evaluator.run(
        original_code, current_code, explanations, args.context
    )
    final_code = result4["final_code"]
    report = result4["report"]
    print("✅ Agent 4 完成")

    # 9. 写输出
    output_code_path = Path(args.output) / "reviewed.py"
    output_report_path = Path(args.output) / "summary.md"

    write_file(str(output_code_path), final_code)
    write_file(str(output_report_path), report)

    print("\n" + "=" * 50)
    print("🎉 审查完成")
    print("=" * 50)
    print(f"📄 修改后代码：{output_code_path}")
    print(f"📄 汇总报告：{output_report_path}")


if __name__ == "__main__":
    main()