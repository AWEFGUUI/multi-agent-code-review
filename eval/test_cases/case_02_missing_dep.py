# 这个包不存在，用来真正触发“依赖缺失”（原来用的 pandas 本机已安装，
# 这条用例一直是空测）。
import definitely_missing_pkg_2026

result = definitely_missing_pkg_2026.compute(1, 2)
print(result)
