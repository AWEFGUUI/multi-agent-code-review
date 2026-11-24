def read_config(path):
    with open(path) as f:
        return f.read()

print(read_config("nonexistent.txt"))