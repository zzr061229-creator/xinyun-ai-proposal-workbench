#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Read-only profiling of the inventory + coverage snapshots (research aid)."""
import csv
import json
import re
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DATA = BASE / "data"


def rows(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def f(v):
    try:
        return float(str(v).replace("=", "").strip())
    except Exception:
        return 0.0


bus = rows(DATA / "bus_inventory_2027Q2.csv")
metro = rows(DATA / "metro_inventory_2027Q2.csv")

# --- coverage: two sections separated by blank line + section title ---
cov_path = DATA / "coverage" / "覆盖分析_人民广场_1000米.csv"
raw = cov_path.read_text(encoding="utf-8-sig").splitlines()
summary_hdr = raw.index("汇总分析") + 1
summary_end = raw.index("明细分析") - 2
detail_hdr = raw.index("明细分析") + 1
summary = list(csv.DictReader(raw[summary_hdr:summary_end], fieldnames=None))
detail = list(csv.DictReader(raw[detail_hdr:]))


def num(v):
    return float(re.sub(r"[^0-9.]", "", v or "0") or 0)


def strip_eq(v):
    return (v or "").lstrip("=").strip('"')


print("== BUS ==")
print("rows", len(bus), "total vehicles", sum(f(r["总车辆数（可售）"]) for r in bus),
      "avail", sum(f(r["空位数"]) for r in bus))
print("available rate %.1f%%" % (100 * sum(f(r["空位数"]) for r in bus) / sum(f(r["总车辆数（可售）"]) for r in bus)))
print("zero-avail routes", sum(1 for r in bus if f(r["空位数"]) <= 0), "/", len(bus))
print("maintenance loss", sum(f(r["保养影响容量"]) for r in bus))
for g in ("S", "A++", "A+", "AA"):
    sub = [r for r in bus if r["线路等级"] == g]
    print(g, "routes", len(sub), "vehicles", sum(f(r["总车辆数（可售）"]) for r in sub),
          "avail", sum(f(r["空位数"]) for r in sub),
          "avail%% %.1f" % (100 * sum(f(r["空位数"]) for r in sub) / max(1, sum(f(r["总车辆数（可售）"]) for r in sub))))
print("companies", Counter(r["运营公司"] for r in bus).most_common())
print("media types", Counter(r["媒体类型"] for r in bus).most_common())
print("suffix 路 routes", sum(1 for r in bus if r["线路"].endswith("路")))
print("routes with chars", [r["线路"] for r in bus if not r["线路"].isdigit()][:25])
print("dup 955", [r for r in bus if r["线路"] == "955"])

print("\n== METRO ==")
print("rows", len(metro), "avail", sum(f(r["空位数"]) for r in metro))
print("zero-avail exits", sum(1 for r in metro if f(r["空位数"]) <= 0), "/", len(metro))
print("districts", Counter(r["所属辖区"] for r in metro).most_common())
print("grades", Counter(r["媒体等级"] for r in metro).most_common())
print("blank 媒体等级", [r for r in metro if not r["媒体等级"].strip()])
print("line tags", Counter(r["站点属性"] for r in metro).most_common(6))
print("'人民广场' area rows", [r for r in metro if "人民广场" in r["商业区域"]][:4])
print("area 0 rows", sum(1 for r in metro if r["商业区域"].strip() == "0"))

print("\n== COVERAGE ==")
print("summary rows", len(summary), "detail rows", len(detail))
print("summary keys", list(summary[0].keys()))
print("types", Counter(r["媒体类型"] for r in summary).most_common())
print("detail keys", list(detail[0].keys()))
print("detail types", Counter(r["媒体类型"] for r in detail).most_common())
print("radius", Counter(r["覆盖半径"] for r in summary).most_common())
print("sum-sheet media", [r["媒体名称"] for r in summary])
print("detail metro names", [r["媒体名称"] for r in detail if r["媒体类型"] == "地铁出入口"])

print("\n== JOIN: coverage -> inventory ==")
bus_names = {r["线路"].strip() for r in bus}
summary_bus = [r["媒体名称"].strip() for r in summary if r["媒体类型"] == "公交线路"]
direct = [n for n in summary_bus if n in bus_names]
stripped = [n for n in summary_bus if n.endswith("路") and n[:-1] in bus_names]
print("bus coverage", len(summary_bus), "direct", len(direct), "after strip 路", len(stripped), direct[:5])
print("unmatched bus", [n for n in summary_bus if n not in bus_names and n[:-1] not in bus_names])
print("metro coverage names", [r["媒体名称"] for r in summary if r["媒体类型"] != "公交线路"])
print("metro inventory station-name field exists?", any("站" in k for k in metro[0].keys()))

print("\n== BUDGET FEASIBILITY (list price midpoints) ==")
bus_price = {"S": 58000, "A++": 48000, "A+": 38000, "AA": 48000}
metro_price = {"A++": 300000, "A+": 200000}
for budget in (1000000, 2000000, 5000000):
    for months in (1, 2, 3):
        b_cars = budget / (bus_price["A++"] * months)
        m_pts = budget / (metro_price["A++"] * months)
        print(f"budget {budget//10000}万 / {months}mo -> bus A++ {b_cars:.1f} cars, metro A++ {m_pts:.1f} exits")

summ = json.loads((DATA / "inventory_summary.json").read_text(encoding="utf-8"))
print("\nsummary matches:", summ["bus"]["available"] == sum(f(r["空位数"]) for r in bus),
      summ["metro"]["available"] == sum(f(r["空位数"]) for r in metro))
