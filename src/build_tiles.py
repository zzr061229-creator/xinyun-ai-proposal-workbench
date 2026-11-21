#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Download an offline OSM tile pyramid for the five demo anchors.

Outputs:
  src/assets/tiles/<z>/<x>/<y>.png     z13–z16, union of anchor extents
  src/tile-assets.js                  window.TILE_ASSETS metadata

Run once while online:
  python src/build_tiles.py
"""
from __future__ import annotations

import concurrent.futures
import glob
import json
import math
import sys
import time
import urllib.request
from io import BytesIO
from pathlib import Path

from PIL import Image

SRC = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
from build_data import bd09_to_wgs84  # noqa: E402

ROOT = SRC.parent
DATA = ROOT / "data"
TILES = SRC / "assets" / "tiles"
OUT_JS = SRC / "tile-assets.js"

TILE = 256
ZOOMS = [13, 14, 15, 16]
CITY_ZOOMS = [12, 13, 14]
TILE_ROOT = "assets/tiles"
USER_AGENT = "Xinyun-Media-Flight-Deck/1.0 (hackathon demo; one-time offline map build)"
ATTR = "© OpenStreetMap contributors (ODbL)"

# 只有五个行业默认锚点需要离线缩放；和睦家/嘉会保留静态 z14 图即可。
ANCHORS = {
    "陆家嘴金融城": "lujiazui",
    "浦发银行上海分行": "spdb-shanghai-hq",
    "浦发银行九江路支行": "spdb-jiujiang",
    "浦发银行徐家汇支行": "spdb-xujiahui",
    "上海美华妇儿医院": "meihua",
    "上海嘉会国际医院": "jiahui",
    "上海和睦家医院": "hemujia",
    "人民广场": "renmin",
    "徐家汇": "xujiahui",
    "徐家汇商圈": "xujiahui",
    "上海迪士尼度假区": "disney",
}


def lon_to_px(lon: float, z: int) -> float:
    return (lon + 180.0) / 360.0 * (2 ** z) * TILE


def lat_to_py(lat: float, z: int) -> float:
    s = math.sin(math.radians(lat))
    y = 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)
    return y * (2 ** z) * TILE


def tile_bbox(lng: float, lat: float, radius: int) -> tuple[float, float, float, float]:
    extent = radius * 1.25
    dlat = extent / 111000.0
    dlng = extent / (111000.0 * max(0.2, math.cos(math.radians(lat))))
    return lng - dlng, lat - dlat, lng + dlng, lat + dlat


def fetch(z: int, x: int, y: int) -> tuple[int, int, int, int]:
    path = TILES / str(z) / str(x) / f"{y}.png"
    if path.exists() and path.stat().st_size > 1000:
        return z, x, y, 0
    path.parent.mkdir(parents=True, exist_ok=True)
    hosts = [
        "https://tile.openstreetmap.de",
        "https://a.tile.openstreetmap.fr/hot",
        "https://b.tile.openstreetmap.fr/hot",
    ]
    last = None
    for attempt in range(6):
        base = hosts[attempt % len(hosts)]
        url = f"{base}/{z}/{x}/{y}.png"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/png,*/*"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            Image.open(BytesIO(data)).verify()
            path.write_bytes(data)
            return z, x, y, 1
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.6 + attempt * 0.8)
    raise RuntimeError(f"tile failed {z}/{x}/{y}: {last}")


def main() -> int:
    combos = {}
    for path in sorted(glob.glob(str(DATA / "coverage" / "*.json"))):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        anchor = (raw.get("anchor") or "").strip()
        radius = int(raw.get("radius") or 0)
        center = raw.get("center") or {}
        if anchor not in ANCHORS or radius not in (3000, 5000):
            continue
        if not center.get("lat") or not center.get("lng"):
            continue
        wlng, wlat = bd09_to_wgs84(float(center["lng"]), float(center["lat"]))
        combos[(anchor, radius)] = (wlng, wlat)

    # 中心三网点（银行支行 / 食品门店）共用一张网络底图：
    # 把三个锚点的并集外扩 1.2km 全部下载，避免多点总览时出现灰块。
    net_bounds = None
    city_bounds = None
    try:
        anchors_cfg = json.loads((DATA / "config" / "anchors.json").read_text(encoding="utf-8")).get("anchors") or []
        bundles_cfg = json.loads((DATA / "config" / "anchor_bundles.json").read_text(encoding="utf-8")).get("bundles") or []
        by_aid = {a["anchorId"]: a for a in anchors_cfg}
        net_members = []
        for b in bundles_cfg:
            mb = b.get("mapBounds") or {}
            if b.get("citywide") and mb.get("minLng") is not None:
                city_bounds = (float(mb["minLng"]), float(mb["minLat"]), float(mb["maxLng"]), float(mb["maxLat"]))
            if b.get("mapAssetKey") != "network-central":
                continue
            for m in b.get("members") or []:
                a = by_aid.get(m.get("anchorId"))
                if a and a.get("lng") and a.get("lat"):
                    wlng, wlat = bd09_to_wgs84(float(a["lng"]), float(a["lat"]))
                    net_members.append((wlng, wlat))
        if net_members:
            lngs = [p[0] for p in net_members]
            lats = [p[1] for p in net_members]
            coslat = math.cos(math.radians(sum(lats) / len(lats)))
            pad_lng = 1200.0 / (111000.0 * max(0.2, coslat))
            pad_lat = 1200.0 / 111000.0
            net_bounds = (min(lngs) - pad_lng, min(lats) - pad_lat, max(lngs) + pad_lng, max(lats) + pad_lat)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] network bbox skipped: {exc}")

    tiles = set()
    bounds = [999.0, 999.0, -999.0, -999.0]  # minLng,minLat,maxLng,maxLat
    boxes = []
    for (anchor, radius), (lng, lat) in combos.items():
        boxes.append(tile_bbox(lng, lat, radius))
    if net_bounds:
        boxes.append(net_bounds)
    for min_lng, min_lat, max_lng, max_lat in boxes:
        bounds[0] = min(bounds[0], min_lng)
        bounds[1] = min(bounds[1], min_lat)
        bounds[2] = max(bounds[2], max_lng)
        bounds[3] = max(bounds[3], max_lat)
        for z in ZOOMS:
            x0 = int(math.floor(lon_to_px(min_lng, z) / TILE))
            x1 = int(math.floor(lon_to_px(max_lng, z) / TILE))
            y0 = int(math.floor(lat_to_py(max_lat, z) / TILE))
            y1 = int(math.floor(lat_to_py(min_lat, z) / TILE))
            for x in range(x0, x1 + 1):
                for y in range(y0, y1 + 1):
                    tiles.add((z, x, y))

    # 全城铺送：只补 z12–z14 概览层，保证 4 枢纽 + 24 站在离线底图上没有灰块；
    # z15/z16 细节仍只保 4 枢纽周边，避免把整座城市按高倍下载。
    if city_bounds:
        min_lng, min_lat, max_lng, max_lat = city_bounds
        bounds[0] = min(bounds[0], min_lng)
        bounds[1] = min(bounds[1], min_lat)
        bounds[2] = max(bounds[2], max_lng)
        bounds[3] = max(bounds[3], max_lat)
        for z in CITY_ZOOMS:
            x0 = int(math.floor(lon_to_px(min_lng, z) / TILE))
            x1 = int(math.floor(lon_to_px(max_lng, z) / TILE))
            y0 = int(math.floor(lat_to_py(max_lat, z) / TILE))
            y1 = int(math.floor(lat_to_py(min_lat, z) / TILE))
            for x in range(x0, x1 + 1):
                for y in range(y0, y1 + 1):
                    tiles.add((z, x, y))

    print(f"[tiles] combos={len(combos)} tiles={len(tiles)} zooms={ZOOMS}+{CITY_ZOOMS if city_bounds else []} network={bool(net_bounds)} citywide={bool(city_bounds)}")
    done = 0
    downloaded = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch, z, x, y) for z, x, y in sorted(tiles)]
        for fut in concurrent.futures.as_completed(futures):
            _, _, _, new = fut.result()
            done += 1
            downloaded += new
            if done % 100 == 0:
                print(f"  {done}/{len(tiles)} (new {downloaded})")
            time.sleep(0.01)

    meta = {
        "tileRoot": TILE_ROOT,
        "minZoom": 12 if city_bounds else min(ZOOMS),
        "maxZoom": max(ZOOMS),
        "bounds": [[round(bounds[1], 6), round(bounds[0], 6)], [round(bounds[3], 6), round(bounds[2], 6)]],
        "count": len(tiles),
        "attribution": ATTR,
        "note": "z12–z14 全城概览 + 4 枢纽 z15–z16 细节；在线地图仍走 OSM。",
    }
    OUT_JS.write_text(
        "/* generated by src/build_tiles.py — offline OSM tiles, © OpenStreetMap contributors (ODbL) */\n"
        "window.TILE_ASSETS = " + json.dumps(meta, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )
    print(f"[ok] wrote {OUT_JS}")
    print(f"[ok] downloaded {downloaded} new tiles, total {len(tiles)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())