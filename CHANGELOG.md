# 变更记录：v2.1（可靠性 + 评测语义 + 安全边界）

> 基线：2026-11-13 的版本（`eval_results.json` 里 15/15 全红的那次）。
> 本次共改动 **24 个文件（含本文件），+2204 / −682 行**，新增 30 条离线测试（全部通过）。

## 0. 升级到 v2.1 时的注意事项

1. **轮换 `LLM_API_KEY`**。`.env.example` 此前写入过真实 key（与 `.env` 内容一致），现已改为占位符。曾以明文出现在工作区文件里的 key 应按“已泄露”处理，建议在控制台重新生成。
   ```bash
   # .env 里换上新 key；仓库里不要再出现 sk- 开头的真值
   ```
2. **重跑评测**，把表格填进 README 的「当前结果」：
   ```bash
   python eval/run_eval.py
   # 产物：eval/runs/<时间戳>/summary.md（可直接贴）
   ```
   旧版 `eval_results.json`（15/15 全失败）由已被替换的评测逻辑产生，不建议沿用。

## 1. 安全

| 文件 | 改动 |
| --- | --- |
| `.env.example` | 真实 key → `sk-your-key-here` 占位符 + 说明注释 |
| `.gitignore` | 新增 `runs/`、`.venv/`、`*.log`、`.pytest_cache/`、`.env.local` |
| `config.py` | 识别占位符（`sk-xxxx` / `sk-your-...`），避免把示例值当真 key 发请求；`.env` 改为从**项目根目录**读取（原来按 CWD，换目录就“缺少配置”）；新增 `masked_key()` |
| `utils/code_runner.py` | 子进程环境变量改为**白名单**（`PATH/TEMP/SYSTEMROOT...`），不再 `os.environ.copy()` |

**验证（实测）**：之前子进程里 `"LLM_API_KEY" in os.environ` 为 `True`；现在为 `False`。

```python
# 旧
env = os.environ.copy()
env["PYTHONIOENCODING"] = "utf-8"
# 新
def _safe_env() -> dict:
    env = {key: os.environ[key] for key in _ENV_KEEP if key in os.environ}
    env.update({"PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"})
    return env
```

## 2. 执行器（`utils/code_runner.py`）

| 改动 | 原因 |
| --- | --- |
| `-I -X utf8` 启动 | `-I` 忽略 `PYTHON*` 环境变量、不把脚本目录塞进 `sys.path`；`-X utf8` 让子进程固定 UTF-8（原来靠 `PYTHONIOENCODING`，会被 `-I` 抵消） |
| 临时工作目录 + `cwd=` | 相对路径写入不落到项目里 |
| `taskkill /F /T` / `killpg` 杀**进程树** | 原来 `subprocess.run(timeout=)` 只杀直接子进程，孙进程会活下来 |
| 字符串黑名单 → **AST 检测** | 原来看 `"input(" in code`：`def get_input()`、`user_input()` 被误判为交互程序直接跳过；`__import__("tkinter")` 又能绕过 |
| 返回字段新增 `skip_reason` / `warnings` / `duration_seconds` | 让“为什么跳过”“有哪些危险调用”可被观测 |

**验证（实测）**：

| 输入 | 旧行为 | 新行为 |
| --- | --- | --- |
| `def get_input(p): ...` | 跳过（误判） | 正常运行 |
| `name = input("x")` | 跳过 | 跳过 |
| `import tkinter` | 跳过 | 跳过 |
| `os.system("calc")` | 放行且无记录 | 放行，但 `warnings=["os.system"]` |

## 3. LLM 客户端（`utils/llm_client.py`）

- 新增 `chat_with_tools()`：主 Agent 的 tool_calls 循环走这里。**原来主循环直接 `client.client.chat.completions.create`，把封装的超时和重试全绕过了**。
- 只重试可重试错误：`429/408/5xx`、超时、连接错误；`401/400/404` 立即失败（原来 `except Exception` 连鉴权错误也重试两次还 sleep）。
- 重试加随机抖动、上限 8s。
- 新增 token 计量：`usage = {calls, prompt_tokens, completion_tokens, total_tokens}`，`reset_usage()` 每次运行清零。
- 单次超时：主循环 45s（可配）、子审查 20–60s。

## 4. 解析层（新增 `utils/llm_parse.py` + `utils/issue_tags.py`）

**修掉 v1 继承下来的三个坑**（agent1/2/3 现在共用同一实现，不再各自复制一份）：

| 坑 | 旧结果 | 新结果 |
| --- | --- | --- |
| 大小写敏感 | ```` ```Python ```` 被当成无语言块，代码里混进 `Python\nx = 1` | 正则 `re.I`，正确提取 |
| 取第一个代码块 | 说明里的示例代码被当成最终代码 | 取**最后一个**代码块 |
| 解析失败静默回退 | `code or 原代码`，报告说改了、文件没改 | 抛 `LLMOutputError`，由工具层转成错误 JSON 让模型重试 |

代码块提取后会立刻 `ast.parse`，语法不合法直接判失败。

新增 `ISSUES: tag1, tag2` 标签协议（枚举见 `utils/issue_tags.py`，含中英别名归一化），三个 reviewer 的 prompt 都追加了这段要求 —— 评测不再靠中文关键词碰运气。

## 5. 主 Agent（`main_agent.py`）

```python
return {
    "status": "ok" | "max_steps" | "timeout" | "llm_error" | "empty_response",
    "completed": bool,
    "final_code": ..., "code_valid": bool,
    "steps": [...], "explanations": [...], "rejected": [...],
    "usage": {...}, "elapsed_seconds": ..., "trace_path": ...,
}
```

- **采用门禁**：reviewer 返回的代码必须 `ast.parse` 通过才更新 `current_code`；被拒绝的修改记入 `rejected`，不再静默覆盖。
- 工具参数不是合法 JSON 时，回一条 `{"error": ...}` 让模型重试，而不是整轮崩。
- token 按步统计，写入 trace。

**验证（离线）**：假客户端返回 `TimeoutError` → `status="timeout"`、`completed=False`；“一直调工具” → `status="max_steps"`。

## 6. 工具层（`tools.py`）

- 三个 reviewer 的**输出代码**统一校验，不合法则返回 `{"error": ...}` 且不携带 code。
- 未知工具、缺参数、异常全部返回结构化 JSON（原来未知工具返回纯文本，主循环 `json.loads` 直接炸）。
- 每个 reviewer 独立超时：runnability 30s、efficiency 60s×2、style 30s。

## 7. 观测（`utils/tracer.py`）

| 改动 | 原因 |
| --- | --- |
| 不再 `write_text("")` 清空 | 原来每跑一条用例就删掉上一条的现场，15 条评测后只剩最后一条 |
| 默认路径 `runs/<时间戳>/trace.jsonl` | 每次运行独立 |
| 记录 `result_preview` + `result_tail` | 原来只存前 500 字，而报错信息通常在末尾 |
| 新增 `ok` / `tokens` / 时间戳 | 能按“哪一步开始失败”定位 |

## 8. 评测（`eval/run_eval.py` + `eval/expected.py`）

| 改动 | 原因 |
| --- | --- |
| 读 `status` | 原来只判断“有没有抛异常”，**超时返回的结果也会被记成 `success: true`**（该场景已复现） |
| 检出率按标签求交 | 原来关键词匹配会惩罚正确输出：英文 `Found a syntax error` → 检出率 0 |
| 新增 `broken`（改坏）与 `output_regression`（输出回归） | 只有“能跑”一个指标时，删掉出问题那行、加一行 print 都能刷分。`case_06` 就曾被加了 print 却记为“没弄坏” |
| 每条用例独立 trace | 否则证据互相覆盖 |
| 增量落盘 | 中途崩了，前 N 条结果还在（上次 15 条全红时没有任何中间产物） |
| 新增 `meta`（时间/model/步数/超时/Python 版本） | 结果可归因 |
| 新增 `--only/--max-steps/--timeout/--run-timeout/--out` | 单条调试不必跑全量 |
| 自动生成 `summary.md` 表格 | 直接贴进 README |

用例修正：`case_02_missing_dep` 原来 `import pandas`，而本机装了 pandas，`original_can_run` 一直是 `true` —— 这条用例从来没测到“依赖缺失”。已改成 `import definitely_missing_pkg_2026`。

`expected.py` 新增 `tags`（评测用）与 `expect_output_changed`（区分“预期内的行为改变”和“输出回归”）。

## 9. 统一 CLI（新增 `cli.py`）

README 里写了但代码里不存在的 `--code` 现在真的有了：

```bash
python cli.py --code demo.py --context "..." --max-steps 8
```

产物：`runs/<ts>/{input.py, reviewed.py, summary.md, diff.patch, trace.jsonl, result.json}`；退出码 0/2 区分成功与“超时/达上限/代码不合法”。

## 10. 测试（新增 `tests/test_offline.py`）

```bash
python -m unittest discover -s tests -v
# Ran 30 tests ... OK
```

覆盖：解析门禁（4 种畸形输出）、执行器（env 隔离 / 中文 / 跳过 / 超时 / 语法错）、trace 追加、主 Agent 状态机、评测指标语义（超时不算成功、改好才算修复）、CLI 落盘与退出码。

**全部离线，不调用 LLM（不产生费用）**。测试文件里对 `openai`/`dotenv` 做了打桩，因此在 `import openai` 已经坏掉的 conda 环境里也能跑。

## 11. 顺带修掉的 v1 遗留问题

- `agents/agent4_evaluator.py`：`parse_scores` 的 `re.findall(r"\d")` → 锚定行首、支持小数、限制 0–5；`check_bugs` 的 `"有bug" in response` 会把“没有bug”判成有 bug。
- `agents/agent1_checker.py`：硬编码 stdlib 白名单（漏 `unittest/csv/sqlite3`）→ `sys.stdlib_module_names`；`find_spec` 加异常兜底。
- `utils/file_io.py`：`write_file` 改原子写（临时文件 + `os.replace`），中断不留半个文件；新增 `write_json`。
- `utils/console.py`：Windows GBK 控制台打印 emoji 会 `UnicodeEncodeError`，入口统一切成 UTF-8。
- `requirements.txt`：加上大版本区间；注明 `aiohttp` 过旧会导致 `import openai` 直接崩（本机就是这个状态）。

## 12. 兼容性影响

- `run_main_agent` / `run_python_code` / `Tracer.log` 的返回值**新增字段**（向后兼容）。
- `agent1/2/3.run()` 不再“解析失败就用原代码”，失败时抛 `LLMOutputError`；调用方需要处理（`tools.py` 已处理）。
- reviewer prompt 新增 `ISSUES:` 输出要求，因此它们的说明文本会比以前多一行。
- `config.py` 的 `.env` 路径改为项目根目录：从任何目录启动都能读到配置。
- v1 `main.py` 仍然可用（作为 baseline），但它的评测语义已被 v2 取代。

## 13. 本次没做（建议下一步）

1. 单 Agent 直接改 / v2 去掉 `run_python` 两条对照实验（回答“多智能体值不值”）
2. 长文件按顶层函数切块 + 只喂 diff（上下文管理）
3. 把执行器放进容器（现在是“降低误伤”，不是隔离）
4. 用例扩到 40+，含“无需修改”的可跑代码，量化过度修改
