#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build alias / station maps between coverage CSVs and Hongdou inventory."""
import csv
import glob
import json
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
    bus_names = {str(r["lineName"]) for r in inv["bus"]["rows"]}
    metro_rows = inv["metro"]["rows"]

    coverage_bus, coverage_metro = set(), set()
    for path in (DATA / "coverage").glob("*.csv"):
        for r in read_coverage(path):
            if r.get("mediaType") == "bus":
                coverage_bus.add(str(r.get("媒体名称") or "").strip())
            elif r.get("mediaType") == "metro":
                coverage_metro.add(str(r.get("最近站点") or "").strip())

    MANUAL_BUS_ALIASES = {
        # 覆盖名 → 红豆库存名（人工核对过）
        "866路": "866-高峰线",
        "986路区间": "986(区间)",
        "南龙专线": "南龙线",
        "840路": "840",
    }

    def match_bus(name):
        if name in bus_names:
            return name, "exact"
        manual = MANUAL_BUS_ALIASES.get(name)
        if manual in bus_names:
            return manual, "manual"
        for suffix in ("路双层", "路单层", "路"):
            if name.endswith(suffix):
                candidate = name[: -len(suffix)]
                if candidate in bus_names:
                    return candidate, f"strip_{suffix}"
        return None, "not_in_inventory"

    aliases = {}
    for name in sorted(coverage_bus):
        target, method = match_bus(name)
        aliases[name] = {"inventoryName": target, "matched": target is not None, "method": method}

    metro_map = {}
    for station in sorted(coverage_metro):
        rows = [r for r in metro_rows if str(r.get("lineName")) == station]
        exits = [
            {
                "id": r.get("metroNumber"),
                "exit": r.get("exitName"),
                "grade": r.get("grade"),
                "free": r.get("freeCount"),
                "total": r.get("totalCount"),
                "contract": r.get("contractCount"),
                "reserved": r.get("reservationCount"),
                "area": r.get("businessAreaName"),
            }
            for r in rows
        ]
        metro_map[station] = {"inInventory": bool(rows), "exitCount": len(rows), "exits": exits}

    (DATA / "bus_aliases.json").write_text(
        json.dumps({"generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"), "aliases": aliases}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DATA / "metro_station_map.json").write_text(
        json.dumps({"generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"), "stations": metro_map}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(json.dumps({
        "busAliases": len(aliases),
        "busMatched": sum(1 for v in aliases.values() if v["matched"]),
        "busUnmatched": [k for k, v in aliases.items() if not v["matched"]],
        "metroStations": len(metro_map),
        "metroInInventory": sum(1 for v in metro_map.values() if v["inInventory"]),
        "metroUnmatched": [k for k, v in metro_map.items() if not v["inInventory"]],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
