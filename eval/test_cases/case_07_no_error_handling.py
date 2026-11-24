# 期望行为（评测口径，请勿“优化”掉）：
#   配置文件不存在时不应该直接抛 FileNotFoundError 崩掉，
#   而要捕获 OSError，打印一条可读的错误信息，并正常退出（退出码 0）。
#   判定标准：修改后进程能从 1 变成 0，且仍然只读取 path 指定的文件。

def read_config(path):
    with open(path) as f:
        return f.read()

print(read_config("nonexistent.txt"))
