#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把人民广场/徐家汇/美华/迪士尼的公交线路几何写成地图 JSON。

输入：data/raw/footfall/media_geo_anchors_raw.json
输出：data/geo/<anchorId>_media_geo.json（格式对齐 lujiazui_media_geo.json）

- 只处理覆盖范围内的公交线路（mediaType=bus）
- 平台原始坐标（GCJ-02）不转换，meta 写明
- Douglas-Peucker 简化，容差与 lujiazui 一致（约 2m）
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW_PATH = DATA / "raw" / "footfall" / "media_geo_anchors_raw.json"
OUT_DIR = DATA / "geo"

TOLERANCE = 0.00002  # 约 2 米，与 build_geo.py 一致


def perp_distance(point, start, end):
    if start == end:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    x0, y0 = point
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    t = ((x0 - x1) * dx + (y0 - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    px, py = x1 + t * dx, y1 + t * dy
    return math.hypot(x0 - px, y0 - py)


def rdp(points, tolerance):
    if len(points) < 3:
        return points
    start, end = points[0], points[-1]
    index, max_dist = -1, 0.0
    for i in range(1, len(points) - 1):
        dist = perp_distance(points[i], start, end)
        if dist > max_dist:
            index, max_dist = i, dist
    if max_dist > tolerance:
        left = rdp(points[: index + 1], tolerance)
        right = rdp(points[index:], tolerance)
        return left[:-1] + right
    return [start, end]


def build_anchor(anchor_id: str, meta: dict, resolution: dict, geometry: dict, metro_raw: dict) -> dict:
    bus_out = []
    for item in meta.get("matched", []):
        label_id = str(item["labelId"])
        geo = geometry.get(label_id)
        if not geo:
            continue
        path = [[float(x), float(y)] for x, y in geo.get("path") or []]
        simplified = rdp(path, TOLERANCE) if len(path) > 2 else path
        stops = [
            {
                "name": s.get("name") or "",
                "lng": s.get("lng"),
                "lat": s.get("lat"),
                "grid500": s.get("grid500") or "",
            }
            for s in geo.get("stops") or []
        ]
        bus_out.append(
            {
                "name": item["name"],
                "labelId": item["labelId"],
                "path": [[round(x, 6), round(y, 6)] for x, y in simplified],
                "stops": stops,
                "rawPointCount": len(path),
                "simplifiedPointCount": len(simplified),
            }
        )

    station_map = metro_raw.get("stationMap") or {}
    metro_cache = metro_raw.get("cache") or {}
    anchor_meta = (metro_raw.get("anchors") or {}).get(anchor_id) or {}
    metro_out = []
    metro_missing = []
    for st in anchor_meta.get("stations") or []:
        sm = station_map.get(st) or {}
        exits_raw = sm.get("exits") or []
        if not exits_raw:
            metro_missing.append(st)
            continue
        for e in exits_raw:
            c = metro_cache.get(str(e["labelId"])) or {}
            lng, lat = c.get("lng"), c.get("lat")
            if lng is None or lat is None:
                continue
            metro_out.append(
                {
                    "station": st,
                    "exit": e["exit"],
                    "labelId": e["labelId"],
                    "grade": e.get("grade"),
                    "lng": lng,
                    "lat": lat,
                    "grid500": c.get("grid500") or "",
                }
            )

    return {
        "version": "1.0.0",
        "anchorId": anchor_id,
        "anchorName": meta["anchorName"],
        "radius": meta.get("radius"),
        "coverageFile": meta.get("coverageFile"),
        "fetchedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sourceFetchedAt": meta.get("fetchedAt"),
        "source": "新云大数据平台 /label/queryLabelData（dataMonth=202305）",
        "method": "覆盖分析中的公交线路名 → /label/queryThirdLabel 标签 ID → /label/queryLabelData 的 sopLabelLines/sopLabelPoints；折线按约 2m 容差简化。",
        "coordinateSystem": "GCJ-02（高德；平台原始值，未转 WGS84）",
        "toleranceDegrees": TOLERANCE,
        "summary": {
            "busLines": len(bus_out),
            "busRequested": len(meta.get("busNames") or []),
            "busUnmatched": len(meta.get("unmatched") or []),
            "busRawPoints": sum(x["rawPointCount"] for x in bus_out),
            "busSimplifiedPoints": sum(x["simplifiedPointCount"] for x in bus_out),
            "busStops": sum(len(x["stops"]) for x in bus_out),
            "metroExits": len(metro_out),
            "metroMissingStations": metro_missing,
        },
        "notes": [
            "公交折线与地铁出入口坐标均来自平台标签几何。",
            "坐标为平台原始值（高德/GCJ-02），未做 WGS84 转换；接 OSM/Leaflet 前需先转换。",
            "公交折线为整条线路，不裁到覆盖半径内。",
            "覆盖里有、平台无标签的线路列在 unmatchedBus 中；无标签地铁站列在 summary.metroMissingStations，不伪造几何。",
            "2023-05 仅用于取几何，几何本身不含时间含义。",
        ],
        "unmatchedBus": meta.get("unmatched") or [],
        "bus": bus_out,
        "metro": metro_out,
    }


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    raw = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    resolution = raw.get("resolution") or {}
    geometry = raw.get("geometry") or {}
    fetched_at = raw.get("fetchedAt")
    metro_path = RAW_PATH.parent / "metro_geo_footfall_anchors_raw.json"
    metro_raw = json.loads(metro_path.read_text(encoding="utf-8")) if metro_path.exists() else {}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for anchor_id, meta in raw["anchors"].items():
        meta = dict(meta)
        meta["fetchedAt"] = fetched_at
        doc = build_anchor(anchor_id, meta, resolution, geometry, metro_raw)
        out_path = OUT_DIR / f"{anchor_id}_media_geo.json"
        out_path.write_text(
            json.dumps(doc, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print(
            f"{anchor_id}: bus {doc['summary']['busLines']}/{doc['summary']['busRequested']} "
            f"points {doc['summary']['busRawPoints']}->{doc['summary']['busSimplifiedPoints']} "
            f"stops {doc['summary']['busStops']} size {out_path.stat().st_size/1024:.1f}KB"
        )
        if doc["unmatchedBus"]:
            print(f"  unmatched: {doc['unmatchedBus']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())