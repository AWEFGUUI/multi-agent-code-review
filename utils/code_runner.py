"""在子进程里执行被审查的代码。

安全边界（别高估它）：这不是沙箱，只是“降低误伤”的最小防护：
- 干净的环境变量（不再把 LLM_API_KEY 之类的密钥交给模型生成的代码）
- 隔离模式 -I（忽略 PYTHON* 环境变量、不把脚本目录加进 sys.path）
- 独立临时工作目录（相对路径写入落在临时目录里）
- 超时 + 杀进程树（原来 subprocess.run 只杀直接子进程，孙进程会活下来）

真正的隔离要靠容器/虚拟机；这里只保证“跑一段纯计算代码”这个场景不出事。
"""

from __future__ import annotations

import ast
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

# 需要“跳过”的库：GUI / 模型推理 / 交互
SKIP_MODULES = {
    "tkinter",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "wx",
    "cv2",
    "torch",
    "tensorflow",
    "ultralytics",
    "gradio",
    "streamlit",
}

# 需要“跳过”的调用：等待用户输入 / 进事件循环
SKIP_CALLS = {"input", "mainloop"}

# 需要“跳过”的属性访问（含子属性，例如 sys.stdin.read）
SKIP_ATTR_PREFIXES = ("sys.stdin", "sys.argv")

# 只告警、不跳过的危险调用
WARN_CALLS = {
    "os.system",
    "os.popen",
    "subprocess.run",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_output",
    "socket.socket",
    "urllib.request.urlopen",
    "eval",
    "exec",
    "compile",
    "__import__",
}

_ENV_KEEP = (
    "PATH",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "HOME",
    "LANG",
    "LC_ALL",
)


def _dotted_name(node: ast.AST) -> str:
    """把 ast.Attribute 还原成 a.b.c 形式的名字。"""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def scan_code(code: str) -> dict:
    """静态扫描：是否应该跳过、有哪些危险调用。

    返回 {"skip_reason": str, "warnings": list[str], "parse_error": str}
    """
    result = {"skip_reason": "", "warnings": [], "parse_error": ""}

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        result["parse_error"] = f"第 {exc.lineno} 行：{exc.msg}"
        return result

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                modules = [node.module or ""]
            for module in modules:
                root = module.split(".")[0]
                if root in SKIP_MODULES and not result["skip_reason"]:
                    result["skip_reason"] = f"import {root}"

        elif isinstance(node, ast.Call):
            name = _dotted_name(node.func)
            if not name:
                continue
            if name in SKIP_CALLS and not result["skip_reason"]:
                result["skip_reason"] = f"调用 {name}()"
            elif name in WARN_CALLS and name not in result["warnings"]:
                result["warnings"].append(name)

        elif isinstance(node, ast.Attribute):
            name = _dotted_name(node)
            if any(name == p or name.startswith(p + ".") for p in SKIP_ATTR_PREFIXES):
                if not result["skip_reason"]:
                    result["skip_reason"] = f"使用 {name.split('.')[0]}.{name.split('.')[1]}"

    return result


def check_risky(code: str) -> str:
    """兼容旧接口：返回跳过原因（空串表示可以跑）。"""
    return scan_code(code)["skip_reason"]


def _safe_env() -> dict:
    """只传必要的环境变量，绝不把 API key 交给被审查的代码。"""
    env = {key: os.environ[key] for key in _ENV_KEEP if key in os.environ}
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return env


def _kill_process_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def run_python_code(code: str, timeout: float = 10) -> dict:
    """在临时目录里跑 Python 代码。

    返回 {"returncode", "stdout", "stderr", "timeout", "skipped",
          "skip_reason", "warnings", "duration_seconds"}
    """
    scan = scan_code(code)
    base = {
        "returncode": -1,
        "stdout": "",
        "stderr": "",
        "timeout": False,
        "skipped": False,
        "skip_reason": "",
        "warnings": scan["warnings"],
        "duration_seconds": 0.0,
    }

    if scan["parse_error"]:
        return {**base, "stderr": f"语法错误：{scan['parse_error']}"}

    if scan["skip_reason"]:
        return {
            **base,
            "skipped": True,
            "skip_reason": scan["skip_reason"],
            "stderr": f"跳过运行：代码包含 {scan['skip_reason']}，属于 GUI/交互/模型程序，不适合自动运行",
        }

    workdir = tempfile.mkdtemp(prefix="macr-run-")
    script = os.path.join(workdir, "user_code.py")
    started = time.time()

    try:
        with open(script, "w", encoding="utf-8", newline="\n") as f:
            f.write(code)

        kwargs = {}
        if os.name != "nt":
            kwargs["start_new_session"] = True

        proc = subprocess.Popen(
            [sys.executable, "-I", "-X", "utf8", script],
            cwd=workdir,
            env=_safe_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **kwargs,
        )

        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc)
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
            timed_out = True

        return {
            **base,
            "returncode": proc.returncode if not timed_out else -1,
            "stdout": stdout or "",
            "stderr": (stderr or "") if not timed_out else f"运行超时（{timeout} 秒），已终止进程树",
            "timeout": timed_out,
            "duration_seconds": round(time.time() - started, 2),
        }

    except Exception as exc:  # noqa: BLE001 - 工具层必须永远返回结构
        return {
            **base,
            "stderr": f"{type(exc).__name__}: {exc}",
            "duration_seconds": round(time.time() - started, 2),
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
