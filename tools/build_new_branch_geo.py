#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build geometry for the real SPDB branch anchors from existing line geometry.

Route geometry is line-level (same platform source); the branch centers are
within the central area already covered by lujiazui / renmin / xujiahui geo
files. For each new 1km coverage we copy the same line path and the same
metro-exit coordinates, keeping GCJ-02 so build_data.py can convert once.

Output: data/geo/spdb-*_media_geo.json
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
COV = DATA / "coverage"
GEO = DATA / "geo"

BRANCHES = {
    "浦发银行上海分行": "spdb-shanghai-hq",
    "浦发银行九江路支行": "spdb-jiujiang",
    "浦发银行徐家汇支行": "spdb-xujiahui",
}


def load(p: Path, default=None):
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def dump(p: Path, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def norm_exit(name: str) -> str:
    s = str(name or "").strip()
    m = re.search(r"原([0-9A-Za-z]+)号口", s)
    if m:
        return m.group(1).upper()
    s = re.sub(r"\([^)]*\)", "", s)
    s = s.replace("出入口", "").replace("出口", "").replace("号口", "").replace("号", "")
    if s.endswith("口"):
        s = s[:-1]
    return s.strip().upper()


def main():
    aliases = load(DATA / "bus_aliases.json", {}).get("aliases") or {}
    stations_raw = load(DATA / "metro_station_map.json", {}).get("stations") or {}

    gbus, gexit = {}, {}
    for p in sorted(GEO.glob("*.json")):
        raw = load(p, {})
        for b in raw.get("bus") or []:
            name = (b.get("name") or "").strip()
            a = aliases.get(name) or {}
            inv = a.get("inventoryName") if a.get("matched") else None
            if inv and b.get("path"):
                gbus.setdefault(inv, b)
        for e in raw.get("metro") or []:
            if e.get("lng") is None or e.get("lat") is None:
                continue
            key = ((e.get("station") or "").strip(), norm_exit(e.get("exit")))
            gexit.setdefault(key, e)

    for full_name, aid in BRANCHES.items():
        cov = load(COV / f"覆盖分析_{full_name}_1000米.json")
        if not cov:
            raise SystemExit("missing coverage " + full_name)

        bus_out, seen_bus, missing_bus = [], set(), []
        station_names, seen_st = [], set()
        for row in cov.get("list") or []:
            if row.get("mediaType") == "bus":
                name = (row.get("lineName") or "").strip()
                if not name or name in seen_bus:
                    continue
                seen_bus.add(name)
                a = aliases.get(name) or {}
                inv = a.get("inventoryName") if a.get("matched") else None
                rec = gbus.get(inv) if inv else None
                if not rec:
                    missing_bus.append(name)
                    continue
                bus_out.append({
                    "name": name,
                    "labelId": rec.get("labelId"),
                    "path": rec.get("path") or [],
                    "stops": rec.get("stops") or [],
                    "rawPointCount": rec.get("rawPointCount") or len(rec.get("path") or []),
                    "simplifiedPointCount": rec.get("simplifiedPointCount") or len(rec.get("path") or []),
                })
            elif row.get("mediaType") == "metro":
                st = (row.get("nearestStaName") or "").strip()
                if st and st not in seen_st:
                    seen_st.add(st)
                    station_names.append(st)

        metro_out, missing_metro = [], []
        for st in station_names:
            inv_st = stations_raw.get(st) or {}
            exits = inv_st.get("exits") or []
            if not exits:
                missing_metro.append(st)
                continue
            for e in exits:
                rec = gexit.get((st, norm_exit(e.get("exit"))))
                if not rec:
                    continue
                metro_out.append({
                    "station": st,
                    "exit": e.get("exit"),
                    "labelId": rec.get("labelId"),
                    "grade": e.get("grade") or rec.get("grade"),
                    "lng": rec.get("lng"),
                    "lat": rec.get("lat"),
                    "grid500": rec.get("grid500") or "",
                })

        out = {
            "version": "1.0.0",
            "anchorId": aid,
            "anchorName": full_name,
            "radius": 1000,
            "coverageFile": f"覆盖分析_{full_name}_1000米.json",
            "fetchedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
            "sourceFetchedAt": "2026-11-21",
            "source": "新云大数据平台线路/站点几何（GCJ-02），按同线路复用",
            "method": "公交按线路名复用同一条平台几何；地铁口按站点+出口名复用已有 POI 坐标；未改坐标，build_data 统一 GCJ-02→WGS84。",
            "coordinateSystem": "GCJ-02 (source)",
            "summary": {
                "busCoverage": len(seen_bus),
                "busWithGeometry": len(bus_out),
                "metroExitsWithGeometry": len(metro_out),
                "metroStations": len(station_names),
            },
            "notes": [
                "网点为真实浦发支行：上海分行/九江路支行/徐家汇支行。",
                "线路几何是线路级数据，与网点无关；新网点复用同线路几何。",
                "没有几何的选中线路会在页面明示，不用假直线替代。",
            ],
            "unmatchedBus": missing_bus,
            "unmatchedMetro": missing_metro,
            "bus": bus_out,
            "metro": metro_out,
        }
        dump(GEO / f"{aid}_media_geo.json", out)
        print(f"[ok] {full_name}: bus {len(bus_out)}/{len(seen_bus)}, metro exits {len(metro_out)}, missingBus={missing_bus}, missingMetro={missing_metro}")


if __name__ == "__main__":
    main()
