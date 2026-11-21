#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Cross-source consistency checks: ledger 01, Hongdou snapshot, coverage, sample proposal."""
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DATA = BASE / "data"


def rows(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


bus = rows(DATA / "bus_inventory_2027Q2.csv")
metro = rows(DATA / "metro_inventory_2027Q2.csv")

# --- 01 ledger via openpyxl ---
import openpyxl
wb = openpyxl.load_workbook(BASE / "materials" / "01-公交媒体台账.xlsx", data_only=True)
print("ledger sheets", wb.sheetnames)
ws = wb[wb.sheetnames[0]]
hdr = [c.value for c in ws[1]]
print("ledger header", hdr)
ledger = []
for r in ws.iter_rows(min_row=2, values_only=True):
    if r[0] is None and all(v is None for v in r):
        continue
    ledger.append(dict(zip(hdr, r)))
print("ledger rows", len(ledger), "sample", ledger[0])
grade_col = next(k for k in hdr if "等级" in str(k))
name_col = next(k for k in hdr if "线路" in str(k))
print("ledger grades", Counter(str(r[grade_col]) for r in ledger).most_common())
print("ledger route count", len({str(r[name_col]).strip() for r in ledger}))

# route-set overlap ledger vs Hongdou
def norm(n):
    n = str(n).strip()
    n = re.sub(r"\s+", "", n)
    return n

ledger_names = {norm(r[name_col]) for r in ledger}
bus_names = {norm(r["线路"]) for r in bus}
print("ledger routes not in Hongdou:", len(ledger_names - bus_names), sorted(ledger_names - bus_names)[:15])
print("Hongdou routes not in ledger:", len(bus_names - ledger_names), sorted(bus_names - ledger_names)[:15])

# grade mismatches on shared names
ledger_grade = {}
for r in ledger:
    ledger_grade.setdefault(norm(r[name_col]), set()).add(str(r[grade_col]).strip())
bus_grade = defaultdict(set)
for r in bus:
    bus_grade[norm(r["线路"])].add(r["线路等级"].strip())
mismatch = [(n, sorted(ledger_grade[n]), sorted(bus_grade[n])) for n in ledger_names & bus_names
            if ledger_grade[n] != bus_grade[n]]
print("grade mismatches:", len(mismatch), mismatch[:10])

# --- 05 sample route names & grades ---
t = (BASE / "extracted" / "05-历史销售提案样本" / "饮用水客户-销售提案样本.pdf.txt").read_text(encoding="utf-8")
lines = [l.strip() for l in t.splitlines()]
sample = []
for i, l in enumerate(lines):
    if l in ("S", "A++", "A+") and i >= 1 and i + 1 < len(lines) and lines[i + 1] == "3":
        sample.append((lines[i - 1], l))
print("sample route count", len(sample), "grades", Counter(g for _, g in sample))
sample_names = {norm(n) for n, _ in sample}
print("sample routes missing from Hongdou:", sorted(sample_names - bus_names))
print("sample route names not in ledger:", sorted(sample_names - ledger_names))
sg = {}
for n, g in sample:
    sg.setdefault(norm(n), set()).add(g)
smm = [(n, sorted(sg[n]), sorted(bus_grade[n])) for n in sample_names & bus_names if sg[n] != bus_grade[n]]
print("sample vs Hongdou grade mismatches:", len(smm), smm)

# --- coverage to metro mapping ---
raw = (DATA / "coverage" / "覆盖分析_人民广场_1000米.csv").read_text(encoding="utf-8-sig").splitlines()
h = raw.index("汇总分析") + 1
end = raw.index("明细分析") - 2
cov = list(csv.DictReader(raw[h:end]))
metro_cov = [r["媒体名称"] for r in cov if r["媒体类型"] == "地铁出入口"]
print("coverage metro entries", metro_cov)
for name in metro_cov:
    line = re.match(r"地铁(\d+)号线", name)
    station = name.split(" - ")[-1] if " - " in name else ""
    code = "L%02d" % int(line.group(1)) if line else "?"
    hits = [r for r in metro if code in r["站点属性"] and station and station in r["商业区域"]]
    print(f"  {name} -> line {code}, station {station}, exits matched {len(hits)}:",
          [(r["地铁编号"], r["出入口名称"], r["媒体等级"], r["空位数"]) for r in hits][:6])

print("人民广场 exits total", sum(1 for r in metro if "人民广场" in r["商业区域"]))
print("人民广场 area values", Counter(r["商业区域"] for r in metro if "人民广场" in r["商业区域"]))

# --- inventory value ---
val_bus = sum(float(r["总车辆数（可售）"]) for r in bus) * 48000
val_metro = sum(float(r["数量"]) for r in metro) * 300000
print("monthly inventory capacity: bus %.2f亿 metro %.2f亿 total %.2f亿" % (val_bus/1e8, val_metro/1e8, (val_bus+val_metro)/1e8))
for b in (100, 200, 500):
    print(f"{b}万 = {b*1e4/ (val_bus+val_metro)*100:.3f}% of monthly capacity")
