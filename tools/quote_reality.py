#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Quote-model reality check: what 100/200/500万 actually buys for 4/6/12 weeks."""
WPM = 52 / 12  # weeks per month = 4.333
BUS = {"S": 58000, "A++": 48000, "A+": 38000}
METRO = {"A++": 300000, "A+": 200000}
BUS_PROD = 5000
METRO_PROD = 2000  # 100元/㎡ × assumed 20㎡


def cost(bus_n, bus_grade, metro_n, metro_grade, weeks, discount=1.0):
    months = weeks / WPM
    media = bus_n * BUS[bus_grade] * months + metro_n * METRO[metro_grade] * months
    prod = bus_n * BUS_PROD + metro_n * METRO_PROD
    total = (media + prod) * discount
    return media, prod, total


def show(label, bus_n, bg, metro_n, mg, weeks, disc=1.0):
    media, prod, total = cost(bus_n, bg, metro_n, mg, weeks, disc)
    print(f"{label:<38} {bus_n:>2}辆{pg(bg):<4}+{metro_n:>2}口{pg(mg):<4} {weeks:>2}周 | "
          f"媒体 {media/1e4:>7.1f}万 制作 {prod/1e4:>5.1f}万 合计 {total/1e4:>7.1f}万")


def pg(g):
    return {"S": "S", "A++": "A++", "A+": "A+"}[g]


print("== 页面/文档里的方案，按刊例中值重算 ==")
show("介绍页 100万档（单点打透）", 10, "A++", 2, "A++", 4)
show("介绍页 200万档（双线协同）", 12, "A++", 3, "A++", 6)
show("介绍页 500万档（多点饱和）", 39, "A++", 6, "A++", 6)
show("旧版错误示例 200万（45辆+6口）", 45, "A++", 6, "A++", 6)
show("旧版错误示例 500万（90辆+15口）", 90, "A++", 15, "A++", 12)
show("走查页 200万（3口+12辆）", 12, "A++", 3, "A++", 6)
show("【同 3口+12辆】92折", 12, "A++", 3, "A++", 6, 0.92)
print("\n== 200万预算，6周，92折（净价200万≈刊例217.4万）能买什么 ==")
for m in (1, 2, 3, 4, 5, 6):
    # solve bus count at A++ with remaining budget
    media_budget = 217.4e4
    fixed = m * (METRO["A++"] * 6 / WPM + METRO_PROD)
    per_bus = BUS["A++"] * 6 / WPM + BUS_PROD
    b = int((media_budget - fixed) / per_bus)
    print(f"  {m} 个地铁口 A++ + {max(0,b)} 辆公交 A++")
print("\n== 500万预算，12周，92折 ==")
media_budget = 500e4 / 0.92
for m in (3, 4, 5, 6):
    fixed = m * (METRO["A++"] * 12 / WPM + METRO_PROD)
    per_bus = BUS["A++"] * 12 / WPM + BUS_PROD
    b = int((media_budget - fixed) / per_bus)
    print(f"  {m} 个地铁口 A++ + {max(0,b)} 辆公交 A++ (刊例 {media_budget/1e4:.1f}万)")
