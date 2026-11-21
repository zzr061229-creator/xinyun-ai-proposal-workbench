#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Parse the Hongdou inventory exports into clean CSV + a summary."""
import csv
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

SRC = Path(r"C:\Users\zzr\Desktop\新云AI提案工作台\data\raw")
OUT = Path(r"C:\Users\zzr\Desktop\新云AI提案工作台\data")
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def read_sheet(path: Path):
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(f"{S}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{S}t")))
        root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        rows = []
        for row in root.iter(f"{S}row"):
            cells = {}
            for c in row.findall(f"{S}c"):
                ref = c.get("r") or ""
                col = re.match(r"([A-Z]+)", ref)
                if not col:
                    continue
                t = c.get("t")
                v = c.find(f"{S}v")
                is_ = c.find(f"{S}is")
                if t == "inlineStr" and is_ is not None:
                    val = "".join(x.text or "" for x in is_.iter(f"{S}t"))
                elif t == "s" and v is not None:
                    try:
                        val = shared[int(v.text)]
                    except Exception:
                        val = v.text or ""
                elif v is not None:
                    val = v.text or ""
                else:
                    val = ""
                cells[col.group(1)] = val
            if cells:
                rows.append(cells)
        return rows


def to_records(rows):
    if not rows:
        return [], []
    header = rows[0]
    cols = sorted(header.keys(), key=lambda x: (len(x), x))
    names = [header.get(c, c) for c in cols]
    records = []
    for r in rows[1:]:
        rec = {names[i]: r.get(c, "") for i, c in enumerate(cols)}
        if any(str(v).strip() for v in rec.values()):
            records.append(rec)
    return names, records


def num(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def summarize(records, grade_key, total_key, avail_key, contract_key, reserved_key):
    grades = {}
    for r in records:
        g = r.get(grade_key, "") or "(空)"
        x = grades.setdefault(g, {"rows": 0, "total": 0, "available": 0, "contract": 0, "reserved": 0})
        x["rows"] += 1
        x["total"] += num(r.get(total_key))
        x["available"] += num(r.get(avail_key))
        x["contract"] += num(r.get(contract_key))
        x["reserved"] += num(r.get(reserved_key))
    return {
        "rows": len(records),
        "total": sum(num(r.get(total_key)) for r in records),
        "available": sum(num(r.get(avail_key)) for r in records),
        "contract": sum(num(r.get(contract_key)) for r in records),
        "reserved": sum(num(r.get(reserved_key)) for r in records),
        "grades": grades,
    }


def write_csv(path: Path, names, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=names)
        w.writeheader()
        w.writerows(records)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}

    bus_path = SRC / "公交媒体库_2027-04-01_2027-05-15.xlsx"
    bus_names, bus = to_records(read_sheet(bus_path))
    write_csv(OUT / "bus_inventory_2027Q2.csv", bus_names, bus)
    summary["bus"] = summarize(bus, "线路等级", "总车辆数（可售）", "空位数", "合同车数", "预定车数")

    metro_path = SRC / "地铁媒体库_2027-04-01_2027-05-15.xlsx"
    metro_names, metro = to_records(read_sheet(metro_path))
    write_csv(OUT / "metro_inventory_2027Q2.csv", metro_names, metro)
    summary["metro"] = summarize(metro, "媒体等级", "数量", "空位数", "合同数", "预定数")

    summary["bus_columns"] = bus_names
    summary["metro_columns"] = metro_names
    (OUT / "inventory_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("BUS", summary["bus"])
    print("BUS columns", bus_names)
    print("METRO", summary["metro"])
    print("METRO columns", metro_names)


if __name__ == "__main__":
    main()
