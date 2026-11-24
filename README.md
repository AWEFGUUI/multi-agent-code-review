# 多智能体代码审查系统

输入一段 Python 代码，由「主 Agent + 工具」审查并改写，输出修改后的代码、diff、审查报告和完整的工具调用轨迹。

> 本文档描述的是**当前代码的真实行为**。上一版 README 里写的 `--code` 参数、`output/reviewed.py`、全自动“动态调度”当时并不存在，已经全部按实现更正。

## 快速开始

```bash
python -m venv .venv
.venv\Scripts\activate           # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

copy .env.example .env           # 然后填入你自己的 LLM_API_KEY
python cli.py --code demo.py
```

产物落在 `runs/<时间戳>/`：

```
runs/20261114-103012/
├── input.py       原文件副本
├── reviewed.py    修改后的代码
├── summary.md     报告（含 diff、状态、各工具意见）
├── diff.patch     unified diff
├── trace.jsonl    每次工具调用：参数、返回头尾、耗时、token、ok
└── result.json    结构化结果（status / usage / steps / rejected）
```

常用参数：

```bash
python cli.py --code demo.py --context "数据规模只有几十条"
python cli.py --code demo.py --max-steps 8 --timeout 45
python cli.py --code demo.py --no-run          # 只审查，不执行代码
```

退出码：`0` = 主 Agent 正常结束且最终代码可解析；`2` = 超时 / 达到步数上限 / 最终代码不合法。

## 架构

### v1（保留作 baseline）：4 Agent 串行流水线

`main.py`：Agent 1 可运行性 → Agent 2 效率 → Agent 3 规范 → Agent 4 评估汇总。

已知问题：顺序写死、不能回退、后一个 Agent 可能推翻前一个的修改、没有客观验证手段。

### v2（当前主线）：主 Agent + 工具

```
主 Agent（tool_calls 循环，最多 N 步）
  ├── review_runnability   调 Agent 1：语法 / 依赖 / 严重逻辑错误
  ├── review_efficiency    调 Agent 2：性能瓶颈（较慢）
  ├── review_style         调 Agent 3：命名 / 可读性 / 鲁棒性
  └── run_python           在隔离子进程里真的跑一遍，拿 stdout/stderr/rc
```

每次修改后用 `run_python` 验证；`run_python` 的观测（stdout/stderr/返回码）是唯一的“真相来源”。

**关于“动态调度”**：工具由主 Agent 决定调用，但 `SYSTEM_PROMPT` 里给了一条建议顺序，实测模型基本会照走。准确的说法是“顺序由模型决定、可跳过可重复”，而不是“完全自主规划”。

## 工具

| 工具 | 作用 | 超时 |
| --- | --- | --- |
| review_runnability | 语法、依赖、严重逻辑错误 | 30s |
| review_efficiency | 性能瓶颈，结合 `--context` 判断是否值得优化 | 60s × 2 次重试 |
| review_style | 命名、模块化、可读性、鲁棒性 | 30s |
| run_python | 隔离执行，返回 stdout/stderr/返回码 | 10s，超时杀进程树 |

## 执行模型与安全边界

`utils/code_runner.py` 会在子进程里跑模型给出的代码。**它不是沙箱**，只做最小防护：

- 环境变量白名单：只传 `PATH/TEMP/SYSTEMROOT` 等，**不会把 `LLM_API_KEY` 交给被审查的代码**（之前是 `os.environ.copy()`，代码 `print(os.environ)` 就能泄露 key）
- `python -I -X utf8`：隔离模式（忽略 `PYTHON*` 环境变量、不把脚本目录加进 `sys.path`），强制 UTF-8 输出
- 独立临时工作目录，相对路径写入落在临时目录里
- 超时后杀**进程树**（原先 `subprocess.run` 只杀直接子进程，孙进程会残留）
- AST 静态检测：GUI / 交互 / 模型类代码直接跳过，`os.system`、`subprocess`、`socket` 等只告警

局限（不要高估）：没有容器、没有网络隔离、没有内存/CPU 限额。要跑不受信任的代码，请放进容器或虚拟机。

## 观测

`trace.jsonl` 每条记录：

| 字段 | 说明 |
| --- | --- |
| step / tool / arguments | 第几步、调什么、参数 |
| result_preview / result_tail | 返回头 600 字 + 尾 300 字（报错通常在末尾） |
| ok | 工具是否返回 error |
| duration_seconds / tokens | 耗时与该步 token |
| timestamp | 时间 |

不再“每次运行清空 trace”：评测时每条用例一个 trace 文件。

## 评测

```bash
python eval/run_eval.py                 # 全部 15 条
python eval/run_eval.py --only case_03,case_15
python eval/run_eval.py --max-steps 8 --out eval/runs/manual
```

结果：`<out>/results.json`（含 meta + 每条明细 + 汇总）与 `<out>/summary.md`（可直接贴进 README 的表格）。

### 指标定义

| 指标 | 定义 |
| --- | --- |
| 执行完成 | `status == "ok"`，超时 / 达步数上限 / LLM 失败都不算 |
| 修复成功 | 原本跑不起来 → 改完能跑，且执行完成 |
| 改坏 | 原本能跑 → 改完跑不起来 |
| 输出回归 | 原本能跑、改完也能跑，但 stdout 变了（`expect_output_changed=false` 的用例才算） |
| 检出率 | 期望标签（`expected.py` 的 `tags`）与 reviewer 输出的 `ISSUES:` 标签求交 |
| token / 耗时 | 单条用例的用量，用于算成本 |

### 用例格式

`eval/test_cases/case_XX_*.py` + `eval/expected.py`：

```python
"case_03_division_by_zero": {
    "tags": ["zero_division"],          # 评测按标签求交
    "should_detect": ["除零错误"],       # 仅用于展示
    "should_run": False,
    "expect_output_changed": False,      # 修复是否允许改变 stdout
},
```

reviewer 被要求在回答最后输出 `ISSUES: tag1, tag2`（标签枚举见 `utils/issue_tags.py`）。这样“模型换个说法”不会被判成没检出；标签缺失时才回退到中文关键词匹配。

### 当前结果

同一套 15 条用例、每例跑 1 次（`deepseek-flash`，`max_steps=8`）。三轮结果都保留，因为数字会波动，而且中间两轮各暴露了一个真问题：

| 轮次 | 执行完成 | 修复 | 改坏 | 输出回归 | 检出率 | 平均步数 | token/例 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 11-23 | 15/15 | 5/6 | 0 | 1 | 93.3% | 4.9 | 19.7k | 暴露：语法用例检出 0%（门禁吞掉 issues）、style 擅自加 print |
| 11-24 ① | 15/15 | 4/5 | 0 | 0 | 93.3% | 4.6 | 17.8k | 修掉上两处；暴露：缺依赖标签靠模型“记得打”、case_07 口径不清 |
| 11-24 ②（最终） | 15/15 | 5/5 | 0 | 0 | 100% | 4.7 | 18.2k | 缺依赖标签改由静态检查注入；case_07 写清期望行为 |

原始结果见 `eval/RESULTS.md`（含每例明细与 token）。三条结论：

- **稳定性**：三轮都没有超时、没有改坏、没有输出回归 —— 循环上限、超时、`ast` 门禁是有效的；
- **100% 不代表能力强**：只有 15 条用例、每类问题都很典型，且每例只跑一次。真实水平请按“两轮之间有 1–2 例波动”来读；
- **成本**：单次约 1.8 万 token、40–60 秒，主要来自每步重发全部上下文（见「已知局限」）。

### 三次被评测抓到的真实问题（已修）

1. **语法错误用例检出率 0%**：Agent 1 对语法错误只诊断、不改代码，返回原代码 + `issues=["syntax_error"]`，但工具层「输出必须能 `ast.parse`」的校验把它判成失败，标签被吞。→ 语法分支改为返回「无代码 + issues + 说明」。
2. **模型擅自加 `print("all checks passed")`**：`case_13` 被判输出回归。→ 三个 reviewer 的 prompt 都补了「不要新增 print / 删调用 / 吞异常」。
3. **缺依赖标签靠模型自觉**：模型说了缺依赖，但 `ISSUES:` 行给的是 `other`。→ 缺依赖是静态检查的确定事实，直接由工具注入 `missing_dep`，不再指望模型记得打标签。

### 评测口径的一个坑

`case_02`（缺依赖）现在标记为 `expect_repair: false`，只算检出、不进修复率分母。原因是：它没法在不改依赖的前提下修好，而模型给的“修复”（`try/except ImportError` + 本地 fallback）会让原本应抛 `ModuleNotFoundError` 的用例变成 `returncode 0` —— 那就是**空测**。正确行为是识别出来并拒绝这种假修复，而不是把分数做漂亮。

## 测试

```bash
python -m unittest discover -s tests -v
```

30 条离线测试，**不调用 LLM、不花钱**，覆盖：解析门禁（大小写代码块、取错块、缺块报错）、执行器（env 隔离、中文输出、跳过 GUI、超时杀进程）、trace 追加、主 Agent 状态机（ok/timeout/max_steps/坏 JSON）、评测指标语义（超时不算成功、改好才算修复）。

## 已知局限

- 只支持单个 `.py` 文件；没有目录/仓库模式、没有按函数切块，超长文件会顶到上下文上限
- `run_python` 对“需要外部资源”的代码只能跳过，不能模拟
- 依赖缺失只报告，不会自动 `pip install`（安全考虑）
- 多智能体的收益还没有量化：缺“单 Agent 直接改”“v2 去掉 `run_python`”两条对照实验
- 评测只有 15 条用例、每例跑 1 次，LLM 有随机性：同一份代码三轮之间出现过 1–2 例差异
- 每步都把完整上下文重发一遍（工具返回含整段改写后的代码 + 长解释），单次审查约 1.8 万 token；把解释截断后再回填，预计可降一半

## 项目结构

```
.
├── cli.py                 统一入口：python cli.py --code x.py
├── main_agent.py          主 Agent 循环（tool_calls + 状态机 + 采用门禁）
├── tools.py               4 个工具的定义与调度
├── main.py                v1 串行流水线（baseline，仅作对照）
├── agents/                三个 reviewer（可运行性 / 效率 / 规范）+ v1 评估器
├── utils/                 解析、LLM 客户端、执行器、trace、issue 标签
├── eval/                  expected.py + 15 条用例 + run_eval.py + RESULTS.md
├── tests/                 30 条离线单测（不打 API）
└── .github/workflows/     CI：3 个 Python 版本跑单测 + compileall
```

## 贡献与复现

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v     # 离线，不需要 key
python eval/run_eval.py                    # 需要 key，约 15 分钟 / 27 万 token
```

