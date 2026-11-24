import subprocess
import tempfile
import os
import sys


# 不适合自动运行的代码特征
RISKY_PATTERNS = [
    "tkinter", "pyqt", "wx.",
    "cv2.imshow", "cv2.waitKey", "cv2.VideoCapture",
    "mainloop()", "input(",
    "RTDETR", "YOLO", "torch.load",
    "sys.stdin", "sys.argv",
    "flask.Flask", "fastapi.FastAPI",
]


def check_risky(code: str) -> str:
    """检查代码是否包含不适合自动运行的特征。返回命中的特征，没命中返回空字符串。"""
    for pattern in RISKY_PATTERNS:
        if pattern in code:
            return pattern
    return ""


def run_python_code(code: str, timeout: int = 10) -> dict:
    """
    在临时文件里跑 Python 代码，返回：
    {"returncode": int, "stdout": str, "stderr": str, "timeout": bool, "skipped": bool}
    """
    # 预检查：不适合自动运行的代码
    risky = check_risky(code)
    if risky:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"跳过运行：代码包含 '{risky}'，可能是 GUI/模型/交互程序，不适合自动运行",
            "timeout": False,
            "skipped": True,
        }

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name

        # 关键：用 sys.executable，强制子进程 UTF-8 输出
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timeout": False,
            "skipped": False,
        }

    except subprocess.TimeoutExpired:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"运行超时（{timeout}秒）",
            "timeout": True,
            "skipped": False,
        }
    except Exception as e:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": str(e),
            "timeout": False,
            "skipped": False,
        }
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)