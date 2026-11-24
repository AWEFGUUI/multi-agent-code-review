# 多智能体代码审查系统

## 系统目标

输入一段 Python 代码，经过多个 Agent 协作审查，输出修改后的代码和修改汇总报告。目标是提升代码的鲁棒性、效率和可读性。

## 架构演进

### v1：4 Agent 串行流水线

Agent 1（可运行性）→ Agent 2（效率）→ Agent 3（规范）→ Agent 4（评估）

问题：
- 顺序写死，不能跳过
- 不能回退
- Agent 之间建议可能冲突
- 代码没有效率问题时，Agent 2 白调一次，浪费钱

### v2：主 Agent + 工具

主 Agent（LLM 循环）
  ├── review_runnability（调 Agent 1，查可运行性）
  ├── review_efficiency（调 Agent 2，查效率）
  ├── review_style（调 Agent 3，查规范）
  └── run_python（真的跑代码，验证修改）

改进：
- 主 Agent 动态决定调哪些工具、调几次、按什么顺序
- 改完代码用 run_python 验证，从"猜"变成"实测"
- 子 Agent 职责不变，但变成了"可调用的工具"
- 主 Agent 能发现子 Agent 之间的矛盾，自己决策

## Agent 分工

### Agent 1：可运行性审查
- 用 ast 检查语法错误
- 用 ast 提取 import，用 importlib.util.find_spec 检查依赖是否安装
- 用 LLM 分析严重逻辑错误
- 输出：修改后的代码 + 说明

### Agent 2：效率审查
- 结合用户背景（数据规模、环境限制）判断哪些优化真正有意义
- 分析代码模式（嵌套循环、重复计算等）
- 输出：修改后的代码 + 说明

### Agent 3：规范审查
- 检查命名规范、模块化、可复用性、可读性、鲁棒性
- 输出：修改后的代码 + 说明

### 主 Agent
- 调度者，决定调哪些工具、调几次
- 发现问题时回退到 Agent 1 重改（最多一次，防死循环）
- 汇总所有说明，生成报告

## 工具定义

| 工具 | 作用 |
|------|------|
| review_runnability | 调 Agent 1，查可运行性 |
| review_efficiency | 调 Agent 2，查效率 |
| review_style | 调 Agent 3，查规范 |
| run_python | 真的跑代码，返回 stdout/stderr/返回码 |

## 防死循环机制

1. 主 Agent 最多 10 步，达到上限强制停止
2. run_python 超时 10 秒，强制杀进程
3. Agent 4 回退只做一次
4. 不适合自动运行的代码（GUI、模型、交互）直接跳过

## 安全机制

run_python 预检查，遇到以下特征直接跳过：
- GUI：tkinter、pyqt、wx、cv2.imshow、mainloop()
- 交互：input()、sys.stdin、sys.argv
- 模型：RTDETR、YOLO、torch.load
- Web：flask.Flask、fastapi.FastAPI

## 可观测性

每次工具调用记录到 output/trace.jsonl：
- 第几步、调什么工具、参数是什么
- 返回了什么（前 500 字）
- 耗时多少秒
- 时间戳

## 输入输出

### 输入
- 一个 .py 文件
- 可选：--context 命令行参数，说明工作背景

### 输出
- output/reviewed.py：修改后的代码
- output/summary.md：修改汇总报告
- output/trace.jsonl：工具调用轨迹

## 评测结果

### 评测集

15 个测试用例，覆盖 11 类问题：

| 类型 | 用例数 |
|------|--------|
| 语法错误 | 1 |
| 依赖缺失 | 1 |
| 除零错误 | 1 |
| 索引越界 | 1 |
| 异常处理缺失 | 1 |
| 递归无基线 | 1 |
| 可变默认参数 | 1 |
| 性能问题 | 3 |
| 命名/规范 | 3 |
| 重复代码 | 1 |
| 混合问题 | 1 |

### 结果

| 指标 | 数值 |
|------|------|
| 总用例 | 15 |
| Agent 执行成功 | 15/15 |
| 原本有问题的用例 | 6 |
| 修复成功 | 6/6 (100%) |
| 原本能跑、改完没坏 | 9/9 (100%) |
| 平均步数 | 5.7 |

### 代表性案例

case_08：可变默认参数
原代码 def append_item(item, items=[]) 默认值只在定义时求值一次，所有调用共享同一个列表。
Agent 修复后输出 [1] / [2] / [10, 20, 3]，每次调用独立。

case_15：混合问题
原代码有 O(n²) 性能问题、命名不规范、逻辑 bug（重复元素被 append 两次）。
Agent 改为 O(n) 哈希计数，输出 [2]，同时修了逻辑和性能。

### 已知局限

- GUI/模型/交互程序：run_python 会主动跳过（skipped=True），因为无法在无头环境运行
- Windows 控制台编码：中文输出可能乱码，需设 PYTHONIOENCODING=utf-8
- 依赖缺失：Agent 会报告缺失，但不会自动 pip install（安全考虑）

## 项目结构

multi-agent-code-review/
├── config.py                 配置读取
├── main.py                   4 Agent 串行版入口（v1）
├── main_agent.py             主 Agent + 工具版入口（v2）
├── minimal_loop.py           最小 agent loop 教学示例
├── demo.py                   示例输入
├── agents/
│   ├── agent1_checker.py     可运行性审查
│   ├── agent2_optimizer.py   效率审查
│   ├── agent3_stylist.py     规范审查
│   └── agent4_evaluator.py   评估与汇总（v1 使用）
├── utils/
│   ├── llm_client.py         LLM 调用封装
│   ├── file_io.py            文件读写
│   ├── code_runner.py        代码执行器（带安全预检查）
│   └── tracer.py             工具调用轨迹记录
├── tools.py                  工具定义与调度
├── eval/
│   ├── expected.py           每个用例的期望结果
│   ├── run_eval.py           评测脚本
│   └── test_cases/           15 个测试用例
└── output/
    ├── reviewed.py           修改后的代码
    ├── summary.md            汇总报告
    └── trace.jsonl           工具调用轨迹

## 技术栈

- Python 3.10+
- DeepSeek API（LLM）
- 标准库：ast、importlib、argparse、subprocess
- 第三方：openai、python-dotenv

## 使用方法

1. 安装依赖：pip install -r requirements.txt
2. 配置 .env（参考 .env.example）
3. 运行 v2（推荐）：
   python main_agent.py --code demo.py --context "工作背景说明"
4. 运行评测：
   python eval/run_eval.py
5. 查看输出：
   output/reviewed.py、output/summary.md、output/trace.jsonl

## 面试可讲的关键决策

1. 为什么从 4 Agent 串行改成主 Agent + 工具？
   串行顺序写死、不能跳过、不能回退。主 Agent 可以动态调度，同时保留子 Agent 的专业化分工。

2. 怎么防止死循环？
   主 Agent 最多 10 步，run_python 超时 10 秒，回退只做一次。

3. 怎么证明改完的代码真的能跑？
   run_python 真的执行代码，返回 stdout/stderr/返回码，不是 LLM 猜。

4. 怎么防止恶意代码？
   run_python 预检查 GUI、交互、模型、Web 特征，命中直接跳过。

5. 怎么排查线上问题？
   trace.jsonl 记录每次工具调用的参数、返回、耗时，可以定位到某次失败是第几步、哪个工具、什么参数。

6. 评测怎么做的？
   15 个用例覆盖 11 类问题，记录"原本能不能跑、改完能不能跑、修复成功率"，不只看准确率。