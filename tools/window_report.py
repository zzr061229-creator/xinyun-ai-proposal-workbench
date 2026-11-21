#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""汇总 2027 四个档期的可售库存（整体 + 五个锚点覆盖内）。

输出 data/reports/window_inventory_report.json，供 docs/档期库存对比.md 引用。
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
REPORTS = DATA / "reports"

WINDOWS = [
    {"id": "q2", "name": "春季 Q2", "file": "inventory_live.json", "start": "2027-04-01", "end": "2027-05-15"},
    {"id": "kaimenhong", "name": "开门红", "file": "inventory_kaimenhong.json", "start": "2027-01-04", "end": "2027-02-14"},
    {"id": "summer", "name": "暑期", "file": "inventory_summer.json", "start": "2027-07-01", "end": "2027-08-11"},
    {"id": "midautumn", "name": "中秋国庆", "file": "inventory_midautumn.json", "start": "2027-08-30", "end": "2027-10-10"},
]

ANCHORS = [
    {"id": "lujiazui", "name": "陆家嘴金融城", "coverage": "覆盖分析_陆家嘴_3000米.json"},
    {"id": "meihua", "name": "美华", "coverage": "覆盖分析_上海美华妇儿医院_3000米.json"},
    {"id": "renmin-guangchang", "name": "人民广场", "coverage": "覆盖分析_人民广场_3000米.json"},
    {"id": "xujiahui", "name": "徐家汇商圈", "coverage": "覆盖分析_徐家汇_3000米.json"},
    {"id": "disney", "name": "迪士尼", "coverage": "覆盖分析_上海迪士尼度假区_5000米.json"},
]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def grade_of(row):
    return (row.get("grade") or "").strip() or "空"


def summarize(inv):
    bus_rows = inv["bus"]["rows"]
    metro_rows = inv["metro"]["rows"]
    bus_grade = defaultdict(int)
    metro_grade = defaultdict(int)
    for r in bus_rows:
        bus_grade[grade_of(r)] += float(r.get("freeCount") or 0)
    for r in metro_rows:
        metro_grade[grade_of(r)] += float(r.get("freeCount") or 0)
    return {
        "fetchedAt": inv.get("fetchedAt"),
        "range": inv.get("range"),
        "bus": {
            "rows": len(bus_rows),
            "free": int(sum(float(r.get("freeCount") or 0) for r in bus_rows)),
            "byGrade": {k: int(v) for k, v in sorted(bus_grade.items())},
        },
        "metro": {
            "rows": len(metro_rows),
            "free": int(sum(float(r.get("freeCount") or 0) for r in metro_rows)),
            "byGrade": {k: int(v) for k, v in sorted(metro_grade.items())},
        },
    }


def coverage_names(anchor):
    cov = load(DATA / "coverage" / anchor["coverage"])
    bus = {r["lineName"] for r in cov.get("list", []) if r.get("mediaType") == "bus" and r.get("lineName")}
    metro = {r["nearestStaName"] for r in cov.get("list", []) if r.get("mediaType") == "metro" and r.get("nearestStaName")}
    return bus, metro


def anchor_stats(inv, anchor, aliases, cov_cache):
    bus_names, stations = cov_cache[anchor["id"]]
    inv_bus = defaultdict(int)
    inv_bus_lines = defaultdict(set)
    for r in inv["bus"]["rows"]:
        inv_bus[r.get("lineName")] += float(r.get("freeCount") or 0)
        inv_bus_lines[r.get("lineName")].add(grade_of(r))
    targets = set()
    for name in bus_names:
        a = aliases.get(name) or {}
        if a.get("matched") and a.get("inventoryName"):
            targets.add(a["inventoryName"])
    bus_free = int(sum(inv_bus.get(t, 0) for t in targets))
    bus_lines = sum(1 for t in targets if inv_bus.get(t, 0) > 0)

    metro_rows = [r for r in inv["metro"]["rows"] if r.get("lineName") in stations]
    seen = set()
    metro_free = 0
    metro_available = 0
    metro_grade_unknown_free = 0
    for r in metro_rows:
        key = r.get("metroNumber") or (r.get("lineName"), r.get("exitName"))
        if key in seen:
            continue
        seen.add(key)
        free = float(r.get("freeCount") or 0)
        metro_free += free
        if free > 0:
            if grade_of(r) == "空":
                metro_grade_unknown_free += 1
            else:
                metro_available += 1
    return {
        "busFree": bus_free,
        "busLinesFree": bus_lines,
        "busCoverageNames": len(bus_names),
        "busMatchedNames": len(targets),
        "metroFree": int(metro_free),
        "metroExitsFree": sum(
            1
            for r in metro_rows
            if r.get("freeCount") and float(r.get("freeCount")) > 0
        ),
        "metroAvailableExits": metro_available,
        "metroGradeUnknownFree": metro_grade_unknown_free,
        "metroStations": len(stations),
    }


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    aliases = (load(DATA / "bus_aliases.json").get("aliases") or {})
    cov_cache = {a["id"]: coverage_names(a) for a in ANCHORS}

    report = {"generatedAt": None, "windows": {}, "anchors": [a["id"] for a in ANCHORS]}
    for w in WINDOWS:
        inv = load(DATA / w["file"])
        summary = summarize(inv)
        summary.update({"id": w["id"], "name": w["name"], "start": w["start"], "end": w["end"], "file": w["file"]})
        summary["anchors"] = {
            a["id"]: anchor_stats(inv, a, aliases, cov_cache) for a in ANCHORS
        }
        report["windows"][w["id"]] = summary
    report["generatedAt"] = __import__("time").strftime("%Y-%m-%d %H:%M:%S")

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / "window_inventory_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"output: {out}")
    for wid, w in report["windows"].items():
        print(f"{wid}: bus {w['bus']['free']} metro {w['metro']['free']}")
        for aid, a in w["anchors"].items():
            print(f"  {aid}: bus {a['busFree']} ({a['busLinesFree']}线) metro {a['metroAvailableExits']}口 free{a['metroExitsFree']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())