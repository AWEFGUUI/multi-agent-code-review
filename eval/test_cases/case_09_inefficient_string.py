def build_string(n):
    result = ""
    for i in range(n):
        result += str(i)
    return result

print(len(build_string(10000)))