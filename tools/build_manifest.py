#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build data/manifest.json from inventory_live.json + coverage CSVs."""
import csv
import glob
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def read_coverage(path):
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    if lines and lines[0].strip().strip('"') == "汇总分析":
        lines = lines[1:]
    return list(csv.DictReader(lines))


def main():
    inv = json.loads((DATA / "inventory_live.json").read_text(encoding="utf-8"))
    entries = []
    for path in sorted((DATA / "coverage").glob("*.csv")):
        rows = read_coverage(path)
        parts = path.stem.split("_")
        anchor = parts[1] if len(parts) > 1 else path.stem
        radius = None
        if len(parts) > 2 and parts[2].endswith("米") and parts[2][:-1].isdigit():
            radius = int(parts[2][:-1])
        entries.append({
            "id": f"{anchor}-{radius}" if radius else anchor,
            "anchor": anchor,
            "radius": radius,
            "file": path.relative_to(DATA).as_posix(),
            "count": len(rows),
            "bus": sum(1 for r in rows if r.get("mediaType") == "bus"),
            "metro": sum(1 for r in rows if r.get("mediaType") == "metro"),
        })

    manifest = {
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "inventory": {
            "file": "inventory_live.json",
            "fetchedAt": inv.get("fetchedAt"),
            "range": inv.get("range"),
            "bus": {
                "rows": len(inv["bus"]["rows"]),
                "free": sum(float(r.get("freeCount") or 0) for r in inv["bus"]["rows"]),
            },
            "metro": {
                "rows": len(inv["metro"]["rows"]),
                "free": sum(float(r.get("freeCount") or 0) for r in inv["metro"]["rows"]),
            },
        },
        "coverage": entries,
    }
    out = DATA / "manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
