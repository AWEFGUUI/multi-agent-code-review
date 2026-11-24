def parse_int(s):
    try:
        return int(s)
    except:
        return None

print(parse_int("abc"))