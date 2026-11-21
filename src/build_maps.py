#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Download a real OpenStreetMap basemap per anchor and write src/map-assets.js.

Only reads ../data/coverage/*.json; only writes src/assets/ and src/map-assets.js.
Requires Pillow and network access to tile.openstreetmap.org (one-time build step).
Attribution: © OpenStreetMap contributors, ODbL.
"""
from __future__ import annotations

import glob
import json
import math
import time
import urllib.request
import sys
from pathlib import Path

from PIL import Image

SRC = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
from build_data import bd09_to_wgs84  # noqa: E402
ROOT = SRC.parent
DATA = ROOT / "data"
ASSETS = SRC / "assets"
OUT_JS = SRC / "map-assets.js"

ANCHOR_META = {
    "上海美华妇儿医院": "meihua",
    "上海和睦家医院": "hemujia",
    "上海嘉会国际医院": "jiahui",
    "人民广场": "renmin",
    "徐家汇": "xujiahui",
    "陆家嘴": "lujiazui",
    "陆家嘴金融城": "lujiazui",
    "上海迪士尼度假区": "disney",
}
TILE = 256
ZOOM = 14
USER_AGENT = "Xinyun-Media-Flight-Deck/1.0 (hackathon demo; local one-time map build)"
ATTR = "© OpenStreetMap contributors (ODbL)"


def lon_to_px(lon: float, z: int) -> float:
    return (lon + 180.0) / 360.0 * (2 ** z) * TILE


def lat_to_py(lat: float, z: int) -> float:
    s = math.sin(math.radians(lat))
    y = 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)
    return y * (2 ** z) * TILE


def px_to_lon(px: float, z: int) -> float:
    return px / ((2 ** z) * TILE) * 360.0 - 180.0


def py_to_lat(py: float, z: int) -> float:
    n = math.pi - 2.0 * math.pi * py / ((2 ** z) * TILE)
    return math.degrees(math.atan(math.sinh(n)))


def download_tile(z: int, x: int, y: int) -> Image.Image:
    hosts = ["https://tile.openstreetmap.org", "https://a.tile.openstreetmap.org", "https://b.tile.openstreetmap.org", "https://c.tile.openstreetmap.org"]
    last = None
    for attempt in range(6):
        url = f"{hosts[attempt % len(hosts)]}/{z}/{x}/{y}.png"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/png,*/*"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            from io import BytesIO
            return Image.open(BytesIO(data)).convert("RGB")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.8 + attempt * 0.9)
    raise RuntimeError(f"tile failed {z}/{x}/{y}: {last}")


def build_one(anchor: str, radius: int, center: dict, anchor_id: str) -> dict:
    lat, lng = float(center["lat"]), float(center["lng"])
    extent = radius * 1.25
    dlat = extent / 111000.0
    dlng = extent / (111000.0 * max(0.2, math.cos(math.radians(lat))))
    min_lng, max_lng = lng - dlng, lng + dlng
    min_lat, max_lat = lat - dlat, lat + dlat

    x0 = int(math.floor(lon_to_px(min_lng, ZOOM) / TILE))
    x1 = int(math.floor(lon_to_px(max_lng, ZOOM) / TILE))
    y0 = int(math.floor(lat_to_py(max_lat, ZOOM) / TILE))
    y1 = int(math.floor(lat_to_py(min_lat, ZOOM) / TILE))
    w = (x1 - x0 + 1) * TILE
    h = (y1 - y0 + 1) * TILE
    if w * h > 4096 * 4096:
        raise RuntimeError(f"map too large {anchor} {radius}: {w}x{h}")

    ASSETS.mkdir(parents=True, exist_ok=True)
    name = f"map-{anchor_id}-{radius}.png"
    path = ASSETS / name
    count = 0
    if path.exists():
        canvas = Image.open(path).convert("RGB")
        print(f"      reuse existing {name} ({canvas.size[0]}x{canvas.size[1]})")
    else:
        canvas = Image.new("RGB", (w, h), (250, 248, 242))
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                tile = download_tile(ZOOM, x, y)
                canvas.paste(tile, ((x - x0) * TILE, (y - y0) * TILE))
                count += 1
                time.sleep(0.12)

    # Crop tile-aligned images to a landscape plate (target 1.2) so the map card
    # doesn't letterbox a portrait image. Keep the center; update the bbox.
    # w0/h0 are the full tile-aligned canvas; a reused image may already be
    # cropped, so recover its offset from w0/h0 before any further crop.
    w0 = (x1 - x0 + 1) * TILE
    h0 = (y1 - y0 + 1) * TILE
    cw, ch = canvas.size
    left = max(0, (w0 - cw) // 2)
    top = max(0, (h0 - ch) // 2)
    target = 1.2
    if cw / ch > target + 0.02:
        nw = int(ch * target)
        extra = (cw - nw) // 2
        canvas = canvas.crop((extra, 0, extra + nw, ch))
        left += extra
        cw = nw
    elif cw / ch < target - 0.02:
        nh = int(cw / target)
        extra = (ch - nh) // 2
        canvas = canvas.crop((0, extra, cw, extra + nh))
        top += extra
        ch = nh
    canvas.save(path, "PNG", optimize=True)

    bbox = {
        "minLng": round(px_to_lon(x0 * TILE + left, ZOOM), 8),
        "maxLng": round(px_to_lon(x0 * TILE + left + cw, ZOOM), 8),
        "minLat": round(py_to_lat(y0 * TILE + top + ch, ZOOM), 8),
        "maxLat": round(py_to_lat(y0 * TILE + top, ZOOM), 8),
    }
    return {
        "file": "assets/" + name,
        "width": cw,
        "height": ch,
        "zoom": ZOOM,
        "tiles": count,
        "anchor": anchor,
        "radius": radius,
        "attribution": ATTR,
        **bbox,
    }


def main():
    combos = {}
    for path in sorted(glob.glob(str(DATA / "coverage" / "*.json"))):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        anchor = (raw.get("anchor") or "").strip()
        radius = int(raw.get("radius") or 0)
        center = raw.get("center") or {}
        if not anchor or not radius or not center.get("lat") or not center.get("lng"):
            continue
        if radius not in (3000, 5000):
            continue
        wlng, wlat = bd09_to_wgs84(float(center["lng"]), float(center["lat"]))
        combos[(anchor, radius)] = {"lng": wlng, "lat": wlat, "address": center.get("address", "")}

    assets = {}
    total_tiles = 0
    for (anchor, radius), center in sorted(combos.items()):
        anchor_id = ANCHOR_META.get(anchor, anchor)
        print(f"[map] {anchor} {radius}m ...")
        meta = build_one(anchor, radius, center, anchor_id)
        assets.setdefault(anchor, {})[str(radius)] = meta
        total_tiles += meta["tiles"]
        print(f"      {meta['width']}x{meta['height']}  tiles={meta['tiles']}  bbox={meta['minLng']},{meta['minLat']} -> {meta['maxLng']},{meta['maxLat']}")

    OUT_JS.write_text(
        "/* generated by src/build_maps.py — real OSM basemaps, © OpenStreetMap contributors (ODbL) */\n"
        "window.MAP_ASSETS = " + json.dumps(assets, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )
    print(f"[ok] wrote {OUT_JS} ({OUT_JS.stat().st_size/1024:.1f} KB), {total_tiles} tiles")


if __name__ == "__main__":
    main()
