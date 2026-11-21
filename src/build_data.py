#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build src/data.js (window.APP_DATA) from the read-only snapshots in ../data/.

Only reads ../data/; only writes src/data.js. Run:
    python src/build_data.py

Reads:
  inventory_live.json / metro_inventory_2027Q2.csv   红豆库存
  coverage/*.json + manifest.json                     大数据平台覆盖（BD-09）
  bus_aliases.json / metro_station_map.json           覆盖 → 库存 join
  config/industries.json / anchors.json / pricing.json / footfall.json
  footfall/<anchor>_<yyyymm>.json                     平台人流（所有文件，通用逻辑）
  geo/<anchor>_media_geo.json                         平台几何（GCJ-02）

Coordinate systems (do NOT mix the two converters):
  coverage  → BD-09 (Baidu)  → bd09_to_wgs84()
  geo       → GCJ-02 (Amap)  → gcj02_to_wgs84()
"""
from __future__ import annotations

import csv
import glob
import json
import math
import re
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
DATA = ROOT / "data"
CONFIG = DATA / "config"
OUT = SRC / "data.js"
MAX_BYTES = 2 * 1024 * 1024

# ---------------------------------------------------------------------------
# DEMO_LINEUP — 已拍板的五行业 × 一品牌 × 一锚点。
# industries.json 是单一来源；只有当它还没按本表更新（品牌/锚点不一致或 stub）
# 时才用这里兜底，并打印 [warn]。待 ZCode 同步 industries.json 后删除兜底。
# ---------------------------------------------------------------------------
DEMO_LINEUP = [
    {
        "industryId": "bank-insurance", "key": "bank", "label": "银行保险",
        "brand": "浦发银行", "brandFull": "上海浦东发展银行",
        "anchorId": "spdb-shanghai-hq", "radii": [1000],
        "insight": "上海分行 / 浦发支行网络 / 财富管理：上海分行、九江路支行、徐家汇支行三个网点周边 1km 的商务通勤与高净值客群；核心信息「稳健 / 专业 / 可信」。",
        "compliance": ["不承诺收益，不用“保本/稳赚/无风险”", "须有风险提示“投资有风险”", "不写具体产品/收益率/费率"],
        "extraCompliance": ["对外只说“浦发上海分行在陆家嘴”，不说总部"],
        "note": "锚点：上海分行 + 九江路支行 + 徐家汇支行（每个网点 1km）",
    },
    {
        "industryId": "private-hospital", "key": "hospital", "label": "私立医院",
        "brand": "上海美华妇儿医院", "brandFull": "上海美华妇儿医院",
        "anchorId": "meihua", "radii": [1000, 3000],
        "insight": "高端妇儿 / 家庭健康：院区 3km 内新中产家庭（孕产、儿科、家庭健康管理）；核心信息「近 / 专 / 安心」。",
        "compliance": ["投放前须取得《医疗广告审查证明》", "不得保证治愈或疗效", "不得利用患者/医生形象作证明"],
        "extraCompliance": [],
        "note": "锚点：上海美华妇儿医院院区",
    },
    {
        "industryId": "food-beverage", "key": "food", "label": "食品饮料",
        "brand": "农夫山泉", "brandFull": "农夫山泉（饮用水）",
        "anchorId": "renmin-guangchang", "radii": [1000, 3000],
        "insight": "饮用水 / 高频即饮：人民广场枢纽通勤与游客人流；公交车身做频次，枢纽地铁口做到达；报价口径对标新云历史提案的同品类样本。",
        "compliance": ["食品广告不得涉及疾病预防/治疗功能", "不得使用医疗用语或与药品混淆", "成分、产地、销量宣称须真实可验证"],
        "extraCompliance": [],
        "note": "锚点：人民广场（城市枢纽）",
    },
    {
        "industryId": "health-supplement", "key": "health", "label": "保健品",
        "brand": "汤臣倍健", "brandFull": "汤臣倍健",
        "anchorId": "xujiahui", "radii": [1000, 3000],
        "insight": "家庭健康营养：徐家汇商圈与周边社区的健康关注人群；公交做社区覆盖，地铁枢纽补品牌信任；核心信息「科学 / 安心 / 日常」。",
        "compliance": ["不得宣称疗效或治疗作用", "须标保健食品标志（蓝帽子）及批准文号", "须注明“保健食品不是药物，不能代替药物治疗疾病”"],
        "extraCompliance": [],
        "note": "锚点：徐家汇商圈",
    },
    {
        "industryId": "theme-park", "key": "park", "label": "乐园",
        "brand": "上海迪士尼", "brandFull": "上海迪士尼度假区",
        "anchorId": "disney", "radii": [3000, 5000],
        "insight": "家庭亲子目的地：度假区周边到达线路与跨区公交做家庭覆盖；红豆库存无迪士尼站地铁口，以公交为主；核心信息「欢乐 / 安全 / 家庭」。",
        "compliance": ["涉及游乐设施须标注安全须知、身高年龄限制", "未成年人形象使用须符合未成年人保护规定", "活动/票价/开放时间以官方公告为准"],
        "extraCompliance": [],
        "note": "锚点：上海迪士尼度假区（3/5km）",
    },
]
DEFAULT_INDUSTRY = "bank-insurance"

# OSM 已知点抽查（2026-11-21 Overpass railway=subway_entrance，WGS84）。
# 只用于打印误差，不参与计算。
OSM_CHECKPOINTS = [
    ("陆家嘴", "1", 121.4971344, 31.2407209), ("陆家嘴", "2", 121.4976354, 31.2405112),
    ("陆家嘴", "3", 121.4984289, 31.2402422), ("陆家嘴", "4", 121.4984304, 31.2398322),
    ("陆家嘴", "5", 121.4988172, 31.2396810), ("陆家嘴", "6", 121.4983920, 31.2392297),
    ("陆家嘴", "7", 121.4988593, 31.2383774),
    ("浦东大道", "1", 121.5149721, 31.2428717), ("浦东大道", "3", 121.5153497, 31.2416150),
    ("浦东大道", "4", 121.5147236, 31.2420432), ("浦东大道", "5", 121.5137190, 31.2424152),
    ("浦东大道", "6", 121.5138692, 31.2418293), ("浦东大道", "7A", 121.5161853, 31.2427707),
    ("浦东大道", "7B", 121.5164924, 31.2428142), ("浦东大道", "8", 121.5160196, 31.2418924),
]

PI = math.pi
AXIS = 6378245.0
EE = 0.00669342162296594323


def _transform_lat(x, y):
    r = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    r += (20 * math.sin(6 * x * PI) + 20 * math.sin(2 * x * PI)) * 2 / 3
    r += (20 * math.sin(y * PI) + 40 * math.sin(y / 3 * PI)) * 2 / 3
    r += (160 * math.sin(y / 12 * PI) + 320 * math.sin(y * PI / 30)) * 2 / 3
    return r


def _transform_lng(x, y):
    r = 300 + 2 * x + 3 * y + 0.1 * x * y + 0.1 * x * x + 0.1 * math.sqrt(abs(x))
    r += (20 * math.sin(6 * x * PI) + 20 * math.sin(2 * x * PI)) * 2 / 3
    r += (20 * math.sin(x * PI) + 40 * math.sin(x / 3 * PI)) * 2 / 3
    r += (150 * math.sin(x / 12 * PI) + 300 * math.sin(x / 30 * PI)) * 2 / 3
    return r


def gcj02_to_wgs84(lng, lat):
    """GCJ-02 (Amap) -> WGS84 (GPS/OSM). Used for data/geo/*."""
    dlat = _transform_lat(lng - 105, lat - 35)
    dlng = _transform_lng(lng - 105, lat - 35)
    rad = lat / 180 * PI
    magic = math.sin(rad)
    magic = 1 - EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    dlat = (dlat * 180) / ((AXIS * (1 - EE)) / (magic * sqrt_magic) * PI)
    dlng = (dlng * 180) / (AXIS / sqrt_magic * math.cos(rad) * PI)
    return lng - dlng, lat - dlat


def bd09_to_wgs84(lng, lat):
    """BD-09 (Baidu) -> WGS84. Used for data/coverage/* only."""
    x = lng - 0.0065
    y = lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * PI * 3000 / 180)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * PI * 3000 / 180)
    glng = z * math.cos(theta)
    glat = z * math.sin(theta)
    return gcj02_to_wgs84(glng, glat)


def meters(lng1, lat1, lng2, lat2):
    dy = (lat1 - lat2) * 111320
    dx = (lng1 - lng2) * 111320 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def num(v, default=0):
    try:
        x = float(v)
    except Exception:
        return default
    return int(x) if x.is_integer() else round(x, 2)


def opt_int(v):
    """Platform metric: keep None as None (无数据), never coerce to 0."""
    if v is None or v == "":
        return None
    try:
        return int(round(float(v)))
    except Exception:
        return None


def nz(v):
    return "" if v is None else v


def norm_exit(name):
    """'3A号口' / '3A口' / '3号口' / '3号出入口' -> '3A' / '3'."""
    s = str(name or "").strip().replace("出入口", "").replace("出口", "")
    s = re.sub(r"号?口$", "", s)
    s = s.replace("号", "")
    return s.upper()


def load_json(path: Path, default=None):
    if not path.exists():
        print(f"[warn] missing {path}")
        return default
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# inventory
# ---------------------------------------------------------------------------
def build_metro_district():
    path = DATA / "metro_inventory_2027Q2.csv"
    out = {}
    if not path.exists():
        print(f"[warn] missing {path}, districts will be empty")
        return out
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            key = (row.get("地铁编号") or "").strip()
            if key:
                out[key] = (row.get("所属辖区") or "").strip()
    return out


def build_windows(windows_cfg, base_inv):
    """四档期窗口 + 各窗口相对 Q2 的库存覆盖值。

    只存 free/contract/reserved 三个数，避免在 data.js 里重复 4 份 431/861 行。
    键：公交 = resourceId|mediaName；地铁 = metroNumber。
    """
    windows = (windows_cfg or {}).get("windows") or []
    base_bus = {
        str(r.get("resourceId")) + "|" + (r.get("mediaName") or ""): r
        for r in base_inv.get("bus", {}).get("rows", [])
    }
    base_metro = {
        (r.get("metroNumber") or ""): r
        for r in base_inv.get("metro", {}).get("rows", [])
    }
    overrides = {}
    out = []
    for w in windows:
        item = {
            "id": w.get("id"),
            "name": w.get("name"),
            "start": w.get("start"),
            "end": w.get("end"),
            "weeks": int(w.get("weeks") or 6),
            "industries": w.get("industries") or [],
            "anchorIds": w.get("anchorIds") or [],
            "reason": w.get("reason") or "",
            "snapshotAt": w.get("snapshotAt") or "",
            "status": w.get("status") or "verified",
        }
        out.append(item)
        if item["id"] == "q2":
            continue
        path = ROOT / (w.get("inventoryFile") or "")
        inv = load_json(path)
        if not inv:
            print(f"[warn] window {item['id']}: missing {path}, skip overrides")
            continue
        bus_ov = {}
        for r in inv.get("bus", {}).get("rows", []):
            key = str(r.get("resourceId")) + "|" + (r.get("mediaName") or "")
            if key in base_bus:
                bus_ov[key] = [num(r.get("freeCount")), num(r.get("contractCount")), num(r.get("reservationCount"))]
        metro_ov = {}
        for r in inv.get("metro", {}).get("rows", []):
            key = (r.get("metroNumber") or "")
            if key in base_metro:
                metro_ov[key] = [num(r.get("freeCount")), num(r.get("contractCount")), num(r.get("reservationCount"))]
        overrides[item["id"]] = {"bus": bus_ov, "metro": metro_ov}
    return out, overrides


def build_inventory(inv, districts):
    bus = []
    for r in inv.get("bus", {}).get("rows", []):
        bus.append({
            "id": nz(r.get("resourceId")),
            "line": (r.get("lineName") or "").strip(),
            "company": (r.get("companyName") or "").strip(),
            "media": (r.get("mediaName") or "").strip(),
            "grade": (r.get("grade") or "").strip(),
            "total": num(r.get("totalCount")),
            "contract": num(r.get("contractCount")),
            "reserved": num(r.get("reservationCount")),
            "free": num(r.get("freeCount")),
            "maintenance": num(r.get("maintenanceForbiddenCount")),
        })
    metro = []
    for r in inv.get("metro", {}).get("rows", []):
        mid = (r.get("metroNumber") or "").strip()
        metro.append({
            "id": mid or nz(r.get("resourceId")),
            "station": (r.get("lineName") or "").strip(),
            "exit": (r.get("exitName") or "").strip(),
            "stationAttr": (r.get("stationAttr") or "").strip(),
            "area": (r.get("businessAreaName") or "").strip(),
            "district": districts.get(mid, ""),
            "grade": (r.get("grade") or "").strip(),
            "total": num(r.get("totalCount")),
            "contract": num(r.get("contractCount")),
            "reserved": num(r.get("reservationCount")),
            "free": num(r.get("freeCount")),
        })
    return bus, metro


# ---------------------------------------------------------------------------
# coverage (BD-09)
# ---------------------------------------------------------------------------
def to_wgs_bd(lng, lat):
    try:
        wlng, wlat = bd09_to_wgs84(float(lng), float(lat))
        return round(wlng, 8), round(wlat, 8)
    except Exception:
        return None, None


def normalize_coverage(raw, anchor, radius):
    center = raw.get("center") or {}
    clng, clat = center.get("lng"), center.get("lat")
    cwlng, cwlat = to_wgs_bd(clng, clat) if clng is not None and clat is not None else (None, None)
    items = []
    for r in raw.get("list") or []:
        media = (r.get("mediaType") or "").strip()
        if media not in ("bus", "metro"):
            continue
        if media == "bus":
            lng, lat = r.get("nearestLng"), r.get("nearestLat")
        else:
            lng, lat = r.get("nearestStaLng"), r.get("nearestStaLat")
        try:
            lng, lat = float(lng), float(lat)
        except Exception:
            lng, lat = clng, clat
        wlng, wlat = to_wgs_bd(lng, lat) if lng is not None and lat is not None else (None, None)
        item = {
            "mediaType": media,
            "lineName": (r.get("lineName") or "").strip(),
            "minDistance": num(r.get("minDistance")),
            "pointLng": round(float(wlng), 6) if wlng is not None else None,
            "pointLat": round(float(wlat), 6) if wlat is not None else None,
            "sourceLng": round(float(lng), 6) if lng is not None else None,
            "sourceLat": round(float(lat), 6) if lat is not None else None,
            "pointName": (r.get("nearestStaName") or "").strip(),
            "pointDistance": num(r.get("nearestStaDistance")),
        }
        if media == "metro":
            item["stationLines"] = [item["lineName"]] if item["lineName"] else []
        items.append(item)
    return {
        "anchor": anchor,
        "rawAnchor": (raw.get("anchor") or "").strip(),
        "center": {
            "name": (center.get("name") or anchor).strip(),
            "address": (center.get("address") or "").strip(),
            "lng": round(float(cwlng), 8) if cwlng is not None else None,
            "lat": round(float(cwlat), 8) if cwlat is not None else None,
            "sourceLng": round(float(clng), 8) if clng is not None else None,
            "sourceLat": round(float(clat), 8) if clat is not None else None,
        },
        "radius": radius,
        "list": items,
    }


def build_coverage(anchors_cfg, manifest):
    """Key coverage by the anchors.json fullName via coverageIds -> manifest -> file."""
    by_mid = {c["id"]: c for c in (manifest.get("coverage") or [])}
    id_to_name = {}
    file_to_anchor = {}
    for a in anchors_cfg:
        name = a.get("fullName") or a.get("name")
        id_to_name[a["anchorId"]] = name
        for radius, mid in (a.get("coverageIds") or {}).items():
            m = by_mid.get(mid)
            if not m:
                continue
            stem = Path(m["file"]).stem
            file_to_anchor[stem] = (name, int(radius))
    coverage, used = {}, []
    for path in sorted(glob.glob(str(DATA / "coverage" / "*.json"))):
        p = Path(path)
        raw = load_json(p)
        if not raw:
            continue
        if p.stem in file_to_anchor:
            anchor, radius = file_to_anchor[p.stem]
        else:
            anchor = (raw.get("anchor") or "").strip()
            radius = int(raw.get("radius") or 0)
            print(f"[warn] {p.name} not referenced by anchors.json coverageIds; keyed by raw anchor {anchor}")
        if not anchor or not radius:
            continue
        cov = normalize_coverage(raw, anchor, radius)
        bucket = coverage.setdefault(anchor, {})
        if str(radius) in bucket:
            print(f"[warn] duplicate coverage {anchor} {radius}, keeping latest")
        bucket[str(radius)] = cov
        used.append({
            "file": p.name, "anchor": anchor, "radius": radius,
            "count": len(cov["list"]),
            "bus": sum(1 for x in cov["list"] if x["mediaType"] == "bus"),
            "metro": sum(1 for x in cov["list"] if x["mediaType"] == "metro"),
        })
    return coverage, used, id_to_name


def build_anchors(anchors_cfg, coverage, manifest):
    out = []
    seen = set()
    manifest_names = {}
    for c in manifest.get("coverage") or []:
        manifest_names.setdefault(c["id"], c.get("anchor"))
    for a in anchors_cfg:
        name = a.get("fullName") or a.get("name")
        if name not in coverage:
            continue
        seen.add(name)
        radii = sorted(int(k) for k in coverage[name].keys())
        center = None
        for r in radii:
            c = coverage[name][str(r)].get("center") or {}
            if c.get("lng") and c.get("lat"):
                center = c
                break
        aliases = {name, a.get("name") or name}
        for r in radii:
            aliases.add(coverage[name][str(r)].get("rawAnchor") or name)
        for mid in (a.get("coverageIds") or {}).values():
            if manifest_names.get(mid):
                aliases.add(manifest_names[mid])
        out.append({
            "id": a["anchorId"], "name": name, "short": a.get("name") or name,
            "type": a.get("type") or "", "typeLabel": a.get("typeLabel") or "",
            "address": a.get("address") or "",
            "center": center or {}, "radii": radii,
            "aliases": sorted(aliases),
        })
    for name in sorted(n for n in coverage if n not in seen):
        radii = sorted(int(k) for k in coverage[name].keys())
        c = coverage[name][str(radii[0])]["center"]
        out.append({"id": name, "name": name, "short": name, "type": "", "typeLabel": "", "address": "",
                    "center": c, "radii": radii, "aliases": [name]})
    return out


# ---------------------------------------------------------------------------
# footfall (platform 2023-05) — generic over data/footfall/*.json
# ---------------------------------------------------------------------------
def exit_index(stations):
    """station -> normExit -> inventory exit id."""
    idx = {}
    for st, s in stations.items():
        for e in s.get("exits") or []:
            idx.setdefault(st, {})[norm_exit(e.get("exit"))] = e.get("id")
    return idx


def alias_of(aliases, name):
    a = aliases.get(name)
    if a and a.get("matched") and a.get("inventoryName"):
        return a["inventoryName"]
    return None


def build_footfall(id_to_name, aliases, stations_idx):
    out = {}
    report = []
    for path in sorted(glob.glob(str(DATA / "footfall" / "*.json"))):
        p = Path(path)
        raw = load_json(p)
        if not raw:
            continue
        aid = raw.get("anchorId") or p.stem.split("_")[0]
        anchor = id_to_name.get(aid)
        if not anchor:
            print(f"[warn] footfall {p.name}: anchorId {aid} not in anchors.json, skipped")
            continue
        month = raw.get("month") or raw.get("dataMonth") or ""
        bus = {}
        bus_unmatched = []
        for l in (raw.get("bus") or {}).get("lines") or []:
            name = (l.get("name") or "").strip()
            inv = alias_of(aliases, name)
            if not inv:
                bus_unmatched.append(name)
                continue
            bus[inv] = {
                "name": name,
                "dailyReach": opt_int(l.get("dailyReach")),
                "dailyTrips": opt_int(l.get("dailyTrips")),
                "dailyPeople": opt_int(l.get("dailyPeople")),
            }
        stations = {}
        exits = {}
        exit_unmatched = []
        for s in (raw.get("metro") or {}).get("stations") or []:
            st = (s.get("station") or "").strip()
            ex_list = []
            for e in s.get("exits") or []:
                k = norm_exit(e.get("exit"))
                eid = (stations_idx.get(st) or {}).get(k)
                rec = {
                    "exit": (e.get("exit") or "").strip(),
                    "key": k,
                    "id": eid,
                    "dailyReach": opt_int(e.get("dailyReach")),
                    "dailyTrips": opt_int(e.get("dailyTrips")),
                    "dailyPeople": opt_int(e.get("dailyPeople")),
                }
                ex_list.append(rec)
                if eid:
                    exits[eid] = {"station": st, "exit": rec["exit"], "dailyReach": rec["dailyReach"]}
                else:
                    exit_unmatched.append(st + " " + rec["exit"])
            stations[st] = {
                "aggregateReach": opt_int(s.get("aggregateReach")),
                "dailyTrips": opt_int(s.get("dailyTrips")),
                "dailyPeople": opt_int(s.get("dailyPeople")),
                "exitCount": len(ex_list),
            }
        missing = list((raw.get("summary") or {}).get("metroMissingStations") or [])
        out[anchor] = {
            "anchorId": aid,
            "file": "data/footfall/" + p.name,
            "month": month,
            "label": "平台 " + month,
            "bus": bus,
            "stations": stations,
            "exits": exits,
            "missingStations": missing,
            "profile": slim_profile(raw.get("areaProfile")),
        }
        report.append((p.name, anchor, len(bus), len((raw.get("bus") or {}).get("lines") or []),
                       len(exits), sum(v["exitCount"] for v in stations.values()), bus_unmatched, missing))
    return out, report


def slim_profile(ap):
    if not ap:
        return None
    return {k: ap.get(k) for k in ("basis", "age", "gender", "consumption", "house") if ap.get(k) is not None}


# ---------------------------------------------------------------------------
# geo (platform GCJ-02) — generic over data/geo/*_media_geo.json
# ---------------------------------------------------------------------------
def gcj_pt(lng, lat):
    w = gcj02_to_wgs84(float(lng), float(lat))
    return [round(w[0], 6), round(w[1], 6)]


def build_geo(id_to_name, aliases, stations_idx, coverage):
    out = {}
    report = []
    for path in sorted(glob.glob(str(DATA / "geo" / "*.json"))):
        p = Path(path)
        raw = load_json(p)
        if not raw:
            continue
        aid = raw.get("anchorId") or p.stem.split("_")[0]
        anchor = id_to_name.get(aid)
        if not anchor:
            print(f"[warn] geo {p.name}: anchorId {aid} not in anchors.json, skipped")
            continue
        bus = {}
        for b in raw.get("bus") or []:
            inv = alias_of(aliases, (b.get("name") or "").strip())
            if not inv or not b.get("path"):
                continue
            bus[inv] = {"name": b.get("name"), "path": [gcj_pt(x[0], x[1]) for x in b["path"]]}
        exits = {}
        station_pts = {}
        for e in raw.get("metro") or []:
            st = (e.get("station") or "").strip()
            if e.get("lng") is None or e.get("lat") is None:
                continue
            pt = gcj_pt(e["lng"], e["lat"])
            station_pts.setdefault(st, []).append(pt)
            eid = (stations_idx.get(st) or {}).get(norm_exit(e.get("exit")))
            if eid:
                exits[eid] = {"station": st, "exit": e.get("exit"), "lng": pt[0], "lat": pt[1]}
        # station centroid for stations whose inventory exits have no POI point
        stations = {st: [round(sum(x[0] for x in v) / len(v), 6), round(sum(x[1] for x in v) / len(v), 6)]
                    for st, v in station_pts.items()}
        out[anchor] = {"anchorId": aid, "file": "data/geo/" + p.name, "coords": "WGS84 (from GCJ-02)",
                       "bus": bus, "exits": exits, "stations": stations}
        report.append((p.name, anchor, len(bus), len(raw.get("bus") or []), len(exits), len(raw.get("metro") or [])))
    return out, report


def trim_geo(geo, coverage):
    """Keep only path points within ~1.6×max radius of the anchor (plus one neighbour)."""
    for anchor, g in geo.items():
        cov = coverage.get(anchor) or {}
        radii = sorted(int(k) for k in cov.keys())
        if not radii:
            continue
        c = cov[str(radii[-1])]["center"]
        lim = radii[-1] * 1.6
        for line in g["bus"].values():
            path = line["path"]
            keep = [meters(x[0], x[1], c["lng"], c["lat"]) <= lim for x in path]
            new = [pt for i, pt in enumerate(path)
                   if keep[i] or (i > 0 and keep[i - 1]) or (i + 1 < len(path) and keep[i + 1])]
            line["path"] = new
            line["trimmed"] = True


def osm_check(geo):
    rows = []
    for anchor, g in geo.items():
        by = {}
        for e in g["exits"].values():
            by[(e["station"], norm_exit(e["exit"]))] = e
        for st, k, lng, lat in OSM_CHECKPOINTS:
            e = by.get((st, k))
            if e:
                rows.append((st, k, meters(e["lng"], e["lat"], lng, lat)))
    return rows


# ---------------------------------------------------------------------------
# 多锚点/网点组合 — anchor_bundles.json
# ---------------------------------------------------------------------------
def build_bundles(bundle_cfg, anchors_cfg, coverage):
    by_aid = {a["anchorId"]: a for a in anchors_cfg}
    out = {}
    for b in (bundle_cfg or {}).get("bundles") or []:
        members = []
        for m in b.get("members") or []:
            a = by_aid.get(m.get("anchorId"))
            if not a:
                print(f"[warn] bundle {b.get('bundleId')}: anchor {m.get('anchorId')} not found, skipped")
                continue
            name = a.get("fullName") or a.get("name")
            radius = int(m.get("radius") or a.get("radiusDefault") or 1000)
            if str(radius) not in (coverage.get(name) or {}):
                print(f"[warn] bundle {b.get('bundleId')}: {name} has no {radius}m coverage, skipped")
                continue
            members.append({
                "anchorId": a["anchorId"],
                "anchor": name,
                "label": m.get("label") or a.get("name") or name,
                "radius": radius,
                "weight": float(m.get("weight") or 1.0),
            })
        if len(members) < 2:
            print(f"[warn] bundle {b.get('bundleId')}: fewer than 2 valid members, dropped")
            continue
        out[b["bundleId"]] = {
            "bundleId": b["bundleId"],
            "industryId": b.get("industryId") or "",
            "brandId": b.get("brandId") or "",
            "status": b.get("status") or "sample",
            "mode": b.get("mode") or "network",
            "label": b.get("label") or b["bundleId"],
            "shortLabel": b.get("shortLabel") or b.get("label") or b["bundleId"],
            "mapAssetKey": b.get("mapAssetKey") or "",
            "weightLabel": b.get("weightLabel") or "",
            "unitLabel": b.get("unitLabel") or "网点",
            "allocateBusByWeight": bool(b.get("allocateBusByWeight")),
            "note": b.get("note") or "",
            "members": members,
        }
    return out


# industries — industries.json first, DEMO_LINEUP fallback
# ---------------------------------------------------------------------------
def build_industries(ind_cfg, anchors_cfg, bundles=None):
    cfg = (ind_cfg or {}).get("industries") or {}
    bundles = bundles or {}
    by_aid = {a["anchorId"]: a for a in anchors_cfg}
    out = []
    fallbacks = []
    for lu in DEMO_LINEUP:
        c = cfg.get(lu["industryId"]) or {}
        brands = c.get("brands") or []
        default_brand = next((b for b in brands if b.get("brandId") == c.get("defaultBrandId")), None) or \
            next((b for b in brands if b.get("isDefault")), None)
        brand_ok = bool(default_brand) and lu["brand"] in (default_brand.get("name"), default_brand.get("fullName"))
        anchor_ok = bool(default_brand) and lu["anchorId"] in (default_brand.get("anchorIds") or [])
        ready = c.get("status") == "ready"
        use_cfg = brand_ok and anchor_ok and ready
        if not use_cfg:
            fallbacks.append(lu["industryId"])
        anchor_cfg = by_aid.get(lu["anchorId"]) or {}
        anchor_name = anchor_cfg.get("fullName") or anchor_cfg.get("name") or lu["anchorId"]
        nar = c.get("narrative") or {}
        if use_cfg and nar:
            insight = " · ".join(x for x in [nar.get("positioning"), nar.get("audience")] if x)
            if nar.get("coreMessage"):
                insight += "；核心信息「" + nar["coreMessage"] + "」。"
        else:
            insight = lu["insight"]
        comp_cfg = [x.get("requirement") for x in (c.get("compliance") or []) if x.get("requirement")]
        compliance = (comp_cfg or lu["compliance"]) + lu["extraCompliance"]
        branch = (default_brand or {}).get("branchPoint") if use_cfg else None
        bundle = None
        for bid in c.get("anchorBundleIds") or []:
            if bid in bundles:
                bundle = bundles[bid]
                break
        out.append({
            "id": lu["industryId"],
            "key": lu["key"],
            "label": c.get("name") or lu["label"],
            "brand": lu["brand"],
            "brandFull": lu["brandFull"],
            "anchorId": lu["anchorId"],
            "anchor": anchor_name,
            "anchorMode": c.get("anchorMode") or ("network" if bundle else "single"),
            "anchorBundle": bundle,
            "radii": lu["radii"],
            "radiusDefault": int(c.get("radiusDefault") or (5000 if lu["industryId"] == "theme-park" else 3000)),
            "insight": insight,
            "compliance": compliance,
            "complianceShort": lu["compliance"] + lu["extraCompliance"],
            "complianceNotice": c.get("complianceNotice") or "合规条目为行业通用清单，未逐条经法务复核。",
            "note": c.get("note") or lu["note"],
            "source": "industries.json" if use_cfg else "DEMO_LINEUP 兜底（待 ZCode 同步 industries.json）",
            "branchPoint": branch,
            "defaultWindowId": c.get("defaultWindowId") or "",
            "seasonalWindows": c.get("seasonalWindows") or [],
            "scoringWeights": c.get("scoringWeights") or {},
            "weightsStatus": c.get("weightsStatus") or "",
            "logic": c.get("logic") or "",
        })
    default = (ind_cfg or {}).get("defaultIndustryId") or DEFAULT_INDUSTRY
    if default not in [x["id"] for x in out]:
        default = DEFAULT_INDUSTRY
    return out, default, fallbacks


def build_pricing(pr):
    pr = pr or {}
    disc = pr.get("discount") or {}
    return {
        "bus": pr.get("bus") or {},
        "metro": pr.get("metro") or {},
        "production": pr.get("production") or {},
        "discount": {
            "default": disc.get("default", 1.0),
            "options": disc.get("options") or [0.92],
            "floor": disc.get("floor", 0.88),
            "note": disc.get("note") or "",
        },
        "tax": pr.get("tax") or {"mode": "excluded", "rate": 0.06},
        "monitoringRate": (pr.get("monitoring") or {}).get("rate", 0),
        "weeksPerMonth": pr.get("weeksPerMonth") or 52 / 12,
    }


def build_sample_reach(ff_cfg):
    g = (ff_cfg or {}).get("busByGrade") or {}
    out = {}
    for k, v in g.items():
        if isinstance(v, dict) and v.get("dailyWan") is not None:
            out[k] = int(round(float(v["dailyWan"]) * 10000))
    if "all" not in out:
        out["all"] = 98000
    return {"busPerVehicleByGrade": out, "source": "05 历史提案样本（按级别均值）",
            "disclaimer": (ff_cfg or {}).get("disclaimer") or "2023 数据仅作相对权重，不代表 2027 绝对值。"}


def main():
    inv = load_json(DATA / "inventory_live.json")
    if not inv:
        raise SystemExit("inventory_live.json missing; cannot build data.js")
    aliases_raw = load_json(DATA / "bus_aliases.json", {}) or {}
    stations_raw = load_json(DATA / "metro_station_map.json", {}) or {}
    manifest = load_json(DATA / "manifest.json", {}) or {}
    anchors_cfg = (load_json(CONFIG / "anchors.json", {}) or {}).get("anchors") or []
    ind_cfg = load_json(CONFIG / "industries.json", {}) or {}
    pricing_cfg = load_json(CONFIG / "pricing.json", {}) or {}
    ff_cfg = load_json(CONFIG / "footfall.json", {}) or {}
    windows_cfg = load_json(CONFIG / "windows.json", {}) or {}
    briefs_cfg = load_json(CONFIG / "briefs.json", {}) or {}

    districts = build_metro_district()
    bus, metro = build_inventory(inv, districts)

    aliases = {}
    for name, a in (aliases_raw.get("aliases") or {}).items():
        aliases[name] = {"inventoryName": a.get("inventoryName"), "matched": bool(a.get("matched")),
                         "method": a.get("method") or ""}

    stations = {}
    for name, s in (stations_raw.get("stations") or {}).items():
        exits = []
        for e in s.get("exits") or []:
            eid = (e.get("id") or "").strip()
            exits.append({
                "id": eid, "exit": (e.get("exit") or "").strip(), "grade": (e.get("grade") or "").strip(),
                "free": num(e.get("free")), "total": num(e.get("total")),
                "contract": num(e.get("contract")), "reserved": num(e.get("reserved")),
                "area": (e.get("area") or "").strip(), "district": districts.get(eid, ""),
            })
        stations[name] = {"inInventory": bool(s.get("inInventory")), "exits": exits}
    st_idx = exit_index(stations)

    coverage, used, id_to_name = build_coverage(anchors_cfg, manifest)
    anchors = build_anchors(anchors_cfg, coverage, manifest)
    footfall, ff_report = build_footfall(id_to_name, aliases, st_idx)
    geo, geo_report = build_geo(id_to_name, aliases, st_idx, coverage)
    windows, window_inventory = build_windows(windows_cfg, inv)
    bundle_cfg = load_json(CONFIG / "anchor_bundles.json", {}) or {}
    bundles = build_bundles(bundle_cfg, anchors_cfg, coverage)
    industries, default_ind, fallbacks = build_industries(ind_cfg, anchors_cfg, bundles)

    bus_free = sum(r["free"] for r in bus)
    metro_free = sum(r["free"] for r in metro)
    meta = {
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "inventoryFetchedAt": inv.get("fetchedAt") or "",
        "range": inv.get("range") or {},
        "coords": {
            "rendered": "WGS84 (OSM/Leaflet)",
            "coverage": "BD-09 → WGS84 (bd09_to_wgs84)",
            "geo": "GCJ-02 → WGS84 (gcj02_to_wgs84)",
        },
        "counts": {
            "busRows": len(bus), "busTotal": sum(r["total"] for r in bus), "busFree": bus_free,
            "busInterfaceTotal": inv.get("bus", {}).get("total"),
            "metroRows": len(metro), "metroFree": metro_free,
        },
        "join": {
            "busMatched": sum(1 for a in aliases.values() if a["matched"]), "busNames": len(aliases),
            "stationsInInventory": sum(1 for s in stations.values() if s["inInventory"]), "stations": len(stations),
        },
        "coverageFiles": used,
        "footfallDisclaimer": ff_cfg.get("disclaimer") or "2023 数据仅作相对权重，不代表 2027 绝对值。",
        "lineupFallback": fallbacks,
        "windowSnapshots": {w["id"]: {"snapshotAt": w.get("snapshotAt"), "start": w.get("start"), "end": w.get("end")} for w in windows},
    }

    payload = {
        "meta": meta, "bus": bus, "metro": metro, "aliases": aliases, "stations": stations,
        "coverage": coverage, "anchors": anchors,
        "industries": industries, "defaultIndustryId": default_ind,
        "pricing": build_pricing(pricing_cfg), "sampleReach": build_sample_reach(ff_cfg),
        "footfall": footfall, "geo": geo,
        "windows": windows, "windowInventory": window_inventory,
        "briefs": briefs_cfg,
    }

    def dump(obj):
        return ("/* generated by src/build_data.py from ../data; do not edit by hand */\n"
                "window.APP_DATA = " + json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + ";\n")

    text = dump(payload)
    if len(text.encode("utf-8")) > MAX_BYTES:
        print(f"[info] data.js {len(text.encode('utf-8'))/1024:.0f} KB > 2 MB, trimming geo to coverage area")
        trim_geo(geo, coverage)
        text = dump(payload)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")

    # ---- report ----
    j = meta["join"]
    print(f"[ok] bus rows={len(bus)} free={bus_free} total={meta['counts']['busTotal']} interfaceTotal={meta['counts']['busInterfaceTotal']}")
    print(f"[ok] metro rows={len(metro)} free={metro_free}")
    print(f"[ok] coverage files={len(used)} anchors={len(anchors)}: {[a['name'] for a in anchors]}")
    for u in used:
        print(f"      {u['anchor']} {u['radius']}m: {u['count']} ({u['bus']}/{u['metro']})")
    print(f"[ok] join: bus aliases matched={j['busMatched']}/{j['busNames']}; stations in inventory={j['stationsInInventory']}/{j['stations']}")
    for name, anchor, nb, nb_all, ne, ne_all, unmatched, missing in ff_report:
        print(f"[ok] footfall {name} -> {anchor}: bus {nb}/{nb_all} joined to inventory, metro exits {ne}/{ne_all} joined"
              + (f"; bus not joined {unmatched}" if unmatched else "") + (f"; no platform label: {missing}" if missing else ""))
    for name, anchor, nb, nb_all, ne, ne_all in geo_report:
        print(f"[ok] geo {name} -> {anchor}: bus paths {nb}/{nb_all}, metro exit points {ne}/{ne_all} joined (GCJ-02→WGS84)")
    chk = osm_check(geo)
    if chk:
        errs = sorted(e for _, _, e in chk)
        print(f"[ok] OSM spot check {len(chk)} exits: median {errs[len(errs)//2]:.0f}m, max {errs[-1]:.0f}m")
    have_ff = set(footfall)
    for ind in industries:
        tag = "platform" if ind["anchor"] in have_ff else "sample-estimate (no footfall file yet)"
        bd = ind.get("anchorBundle")
        btag = (" · network " + "/".join(m["label"] + " " + str(m["radius"]) + "m" for m in bd["members"])) if bd else ""
        print(f"[ok] industry {ind['key']:8s} {ind['label']} / {ind['brand']} / {ind['anchor']} {ind['radii']} · reach={tag}{btag} · {ind['source']}")
    if fallbacks:
        print(f"[warn] industries.json not yet aligned with DEMO_LINEUP for {fallbacks}; using DEMO_LINEUP fallback")
    lj = (coverage.get("陆家嘴金融城") or {}).get("3000")
    if lj:
        nb = sum(1 for x in lj["list"] if x["mediaType"] == "bus")
        print(f"[{'ok' if len(lj['list']) == 87 else 'warn'}] 陆家嘴金融城 3km = {len(lj['list'])} ({nb}/{len(lj['list']) - nb}); expected 87 (76/11)")
    print(f"[ok] wrote {OUT} ({OUT.stat().st_size/1024:.1f} KB)")
    if len(bus) != 431 or len(metro) != 861:
        print("[warn] row counts changed from the 431/861 snapshot; UI will display actual counts")


if __name__ == "__main__":
    main()
