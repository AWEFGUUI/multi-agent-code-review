"""Windows 控制台默认 GBK，打印中文+emoji 会 UnicodeEncodeError。

在入口处调用一次，把 stdout 切成 UTF-8（失败就算了，不影响逻辑）。
"""

import sys


def setup_console() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - 非 tty / 老版本 Python / 已被重定向
        pass
