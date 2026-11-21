#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把大数据平台的线路/站点几何简化成地图可用 JSON。

输入：data/raw/footfall/media_geo_raw.json
输出：data/geo/lujiazui_media_geo.json

- 公交：完整折线（Douglas-Peucker 简化，约 2m 容差）+ 站点坐标
- 地铁：49 个出入口坐标
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW_PATH = DATA / "raw" / "footfall" / "media_geo_raw.json"
OUT_DIR = DATA / "geo"
OUT_PATH = OUT_DIR / "lujiazui_media_geo.json"

TOLERANCE = 0.00002  # 约 2 米


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


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    raw = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    bus_out = []
    for item in raw["bus"]:
        path = [[float(x), float(y)] for x, y in item.get("path") or []]
        simplified = rdp(path, TOLERANCE) if len(path) > 2 else path
        stops = [
            {
                "name": s.get("name") or "",
                "lng": s.get("lng"),
                "lat": s.get("lat"),
                "grid500": s.get("grid500") or "",
            }
            for s in item.get("stops") or []
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

    metro_out = [
        {
            "station": item["station"],
            "exit": item["exit"],
            "labelId": item["labelId"],
            "lng": item["lng"],
            "lat": item["lat"],
            "grid500": item.get("grid500") or "",
        }
        for item in raw["metro"]
    ]

    result = {
        "version": "1.0.0",
        "anchorId": "lujiazui",
        "anchorName": "陆家嘴金融城",
        "fetchedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "新云大数据平台 /label/queryLabelData（dataMonth=202305）",
        "method": "取公交标签的 sopLabelLines/sopLabelPoints 与地铁口标签的 sopLabelPoints；折线按约 2m 容差简化。",
        "coordinateSystem": "GCJ-02（高德；平台原始值，未转 WGS84）",
        "toleranceDegrees": TOLERANCE,
        "summary": {
            "busLines": len(bus_out),
            "busRawPoints": sum(x["rawPointCount"] for x in bus_out),
            "busSimplifiedPoints": sum(x["simplifiedPointCount"] for x in bus_out),
            "busStops": sum(len(x["stops"]) for x in bus_out),
            "metroExits": len(metro_out),
        },
        "notes": [
            "坐标为平台原始值（高德/GCJ-02；label.js 里再调 gaoDeToBaidu 显示），未做 WGS84 转换；示意地图无影响，接真实底图需先转换。",
            "公交折线为整条线路，不在 3km 圈内的点也保留，便于画完整线路。",
            "地铁坐标为出入口 POI 点；同站多口分别有点位。",
        ],
        "bus": bus_out,
        "metro": metro_out,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"output: {OUT_PATH}")
    print(f"size: {OUT_PATH.stat().st_size / 1024:.1f} KB")
    print(json.dumps(result["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())