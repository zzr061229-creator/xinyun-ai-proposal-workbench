#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build coverage join / capacity reports for the 新云 AI 提案工作台.

Standard library only. Reads data/inventory_live.json, data/coverage/*,
data/bus_aliases.json, data/metro_station_map.json, data/config/pricing.json.
Writes:
  - data/bus_aliases.json              (alias补漏 + note, additive)
  - data/metro_station_map.json        (gradeUnknown + missing stations, additive)
  - data/reports/coverage_join_report.json
  - data/reports/capacity_report.json

No data is deleted. All joins are deterministic; unmatched candidates are kept
and counted, never silently dropped.
"""

import csv
import datetime
import json
import math
import os
import sys

from collections import Counter, defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA = os.path.join(ROOT, "data")
REPORTS = os.path.join(DATA, "reports")

INVENTORY_PATH = os.path.join(DATA, "inventory_live.json")
ALIASES_PATH = os.path.join(DATA, "bus_aliases.json")
STATION_MAP_PATH = os.path.join(DATA, "metro_station_map.json")
MANIFEST_PATH = os.path.join(DATA, "manifest.json")
PRICING_PATH = os.path.join(DATA, "config", "pricing.json")
JOIN_REPORT_PATH = os.path.join(REPORTS, "coverage_join_report.json")
CAPACITY_REPORT_PATH = os.path.join(REPORTS, "capacity_report.json")

ANCHOR_ORDER = [
    "上海美华妇儿医院",
    "上海嘉会国际医院",
    "上海和睦家医院",
    "人民广场",
    "上海迪士尼度假区",
    "陆家嘴",
    "徐家汇",
]
DKEY = {1.0: "1.0", 0.92: "0.92"}

# The station map as originally generated at 2026-11-21 11:42:51 (21 stations).
# Used only to report which stations this task added, so reruns stay idempotent.
BASELINE_STATIONS = {
    "一大会址·黄陂南路",
    "上海体育馆",
    "人民广场",
    "北新泾",
    "南京西路",
    "吴中路",
    "娄山关路",
    "宋园路",
    "宜山路",
    "宝山路",
    "徐家汇",
    "桂林公园",
    "桂林路",
    "漕河泾开发区",
    "真北路",
    "虹桥路",
    "虹漕路",
    "豫园",
    "静安寺",
    "马当路",
    "龙溪路",
}


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def money(value):
    return int(round(value))


def load_inventory():
    inv = read_json(INVENTORY_PATH)
    bus_lines = {}
    for row in inv["bus"]["rows"]:
        name = (row.get("lineName") or "").strip()
        if not name:
            continue
        rec = bus_lines.setdefault(
            name,
            {
                "free": 0,
                "total": 0,
                "contract": 0,
                "reserved": 0,
                "grades": set(),
                "media": set(),
                "resourceIds": set(),
            },
        )
        rec["free"] += as_int(row.get("freeCount"))
        rec["total"] += as_int(row.get("totalCount"))
        rec["contract"] += as_int(row.get("contractCount"))
        rec["reserved"] += as_int(row.get("reservationCount"))
        rec["grades"].add((row.get("grade") or "").strip())
        rec["media"].add((row.get("mediaName") or "").strip())
        rec["resourceIds"].add(row.get("resourceId"))

    metro_by_station = defaultdict(list)
    for row in inv["metro"]["rows"]:
        station = (row.get("lineName") or "").strip()
        if not station:
            continue
        metro_by_station[station].append(row)

    return inv, bus_lines, metro_by_station


def grade_label(grades):
    return "/".join(sorted(g for g in grades if g)) or "空"


def make_exit(row):
    grade = (row.get("grade") or "").strip()
    return {
        "id": row.get("metroNumber") or "SHDT-{}".format(row.get("resourceId")),
        "exit": (row.get("exitName") or "").strip(),
        "grade": grade,
        "free": as_int(row.get("freeCount")),
        "total": as_int(row.get("totalCount")),
        "contract": as_int(row.get("contractCount")),
        "reserved": as_int(row.get("reservationCount")),
        "area": (row.get("businessAreaName") or "").strip(),
        "gradeUnknown": not bool(grade),
    }


def load_coverage_rows(entry):
    """Return (rows, meta). JSON is preferred; CSV is a GB18030/UTF-8 fallback."""
    csv_path = os.path.join(DATA, entry["file"])
    json_path = os.path.splitext(csv_path)[0] + ".json"
    if os.path.exists(json_path):
        doc = read_json(json_path)
        return doc.get("list", []), {
            "format": "json",
            "path": os.path.relpath(json_path, ROOT).replace("\\", "/"),
        }

    raw = open(csv_path, "rb").read()
    text = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise RuntimeError("Cannot decode coverage CSV: {}".format(csv_path))

    table = list(csv.reader(text.splitlines()))
    header_idx = None
    for i, row in enumerate(table):
        if row and "媒体类型" in row:
            header_idx = i
            break
    if header_idx is None:
        raise RuntimeError("No header row in coverage CSV: {}".format(csv_path))
    header = table[header_idx]
    rows = []
    for row in table[header_idx + 1 :]:
        if not row or len(row) < len(header):
            continue
        item = dict(zip(header, row))
        media_type = (item.get("mediaType") or "").strip().lower()
        if media_type not in ("bus", "metro"):
            if "公交" in (item.get("媒体类型") or ""):
                media_type = "bus"
            elif "地铁" in (item.get("媒体类型") or ""):
                media_type = "metro"
        rows.append(
            {
                "mediaType": media_type,
                "lineName": (item.get("媒体名称") or "").strip(),
                "nearestStaName": (item.get("最近站点") or "").strip(),
                "minDistance": item.get("最近距离"),
            }
        )
    return rows, {
        "format": "csv",
        "path": os.path.relpath(csv_path, ROOT).replace("\\", "/"),
    }


def resolve_new_bus_name(name, bus_lines):
    if name == "南龙专线" and "南龙线" in bus_lines:
        return "南龙线", "alias_南龙线"
    if name in bus_lines:
        return name, "exact"
    if name.endswith("路") and name[:-1] in bus_lines:
        return name[:-1], "strip_路"
    return None, None


def build_bus_aliases(bus, bus_lines, coverage_names):
    old_doc = read_json(ALIASES_PATH)
    old = old_doc.get("aliases", {})
    special = {
        "866路": (
            "866-高峰线",
            "alias_866-高峰线",
            "覆盖名 866路 → 库存 866-高峰线（A++，空位 1）；已核实库存存在。",
        ),
        "986路区间": (
            "986(区间)",
            "alias_986(区间)",
            "覆盖名 986路区间 → 库存 986(区间)（A++，空位 0）；可匹配但当前无空位。",
        ),
        "911路双层": (
            None,
            "not_in_inventory",
            "观光/双层产品不在 431 条公交库存；保留 matched:false，不伪造库存。",
        ),
        "旅游1线": (
            None,
            "not_in_inventory",
            "观光线路不在 431 条公交库存；保留 matched:false，不伪造库存。",
        ),
        "旅游2线": (
            None,
            "not_in_inventory",
            "观光线路不在 431 条公交库存；保留 matched:false，不伪造库存。",
        ),
        "旅游10线": (
            None,
            "not_in_inventory",
            "观光线路不在 431 条公交库存；保留 matched:false，不伪造库存。",
        ),
        "629路": (
            None,
            "not_in_inventory",
            "库存 431 条中无 629 路（可能停运/更名）；保留 matched:false，不伪造库存。",
        ),
    }

    def matched_note(name, target, method, prefix):
        rec = bus_lines[target]
        grade = grade_label(rec["grades"])
        free = rec["free"]
        note = "{}库存 {}（{}，空位 {}，总车 {}）".format(prefix, target, grade, free, rec["total"])
        if free == 0:
            note += "；匹配但当前无空位，不可下单。"
        return note

    aliases = {}
    data_quality = []
    names = sorted(set(old) | set(coverage_names))
    for name in names:
        if name in special:
            target, method, note = special[name]
            if target is not None and target not in bus_lines:
                data_quality.append(
                    "{}: special alias target {} not found in inventory".format(name, target)
                )
                target = None
                method = "not_in_inventory"
            aliases[name] = {
                "inventoryName": target,
                "matched": bool(target),
                "method": method,
                "note": note,
            }
            continue

        if name in old:
            old_entry = old[name]
            target = old_entry.get("inventoryName")
            method = old_entry.get("method") or "exact"
            if old_entry.get("matched") and target in bus_lines:
                aliases[name] = {
                    "inventoryName": target,
                    "matched": True,
                    "method": method,
                    "note": matched_note(name, target, method, "库存匹配："),
                }
                continue
            # Old unmatched entry: try a fresh deterministic resolution.
            target, method = resolve_new_bus_name(name, bus_lines)
            if target:
                aliases[name] = {
                    "inventoryName": target,
                    "matched": True,
                    "method": method,
                    "note": matched_note(name, target, method, "库存匹配（补漏）："),
                }
            else:
                aliases[name] = {
                    "inventoryName": None,
                    "matched": False,
                    "method": "not_in_inventory",
                    "note": "库存中未找到对应线路；保留 matched:false，不伪造库存。",
                }
            continue

        target, method = resolve_new_bus_name(name, bus_lines)
        if target:
            prefix = "别名匹配（同线简称，待运营确认）：" if method == "alias_南龙线" else "库存匹配："
            aliases[name] = {
                "inventoryName": target,
                "matched": True,
                "method": method,
                "note": matched_note(name, target, method, prefix),
            }
        else:
            aliases[name] = {
                "inventoryName": None,
                "matched": False,
                "method": "not_in_inventory",
                "note": "库存中未找到对应线路；保留 matched:false，不伪造库存。",
            }

    matched = [name for name, item in aliases.items() if item["matched"]]
    unmatched = [name for name, item in aliases.items() if not item["matched"]]
    zero_free = [
        name
        for name, item in aliases.items()
        if item["matched"] and bus_lines[item["inventoryName"]]["free"] == 0
    ]

    doc = {
        "generatedAt": old_doc.get("generatedAt") or now_str(),
        "updatedAt": now_str(),
        "inventorySnapshot": {
            "file": "data/inventory_live.json",
            "fetchedAt": bus["fetchedAt"],
            "range": bus["range"],
            "busRows": len(bus["bus"]["rows"]),
            "metroRows": len(bus["metro"]["rows"]),
        },
        "summary": {
            "coverageNames": len(coverage_names),
            "aliasEntries": len(aliases),
            "matched": len(matched),
            "unmatched": len(unmatched),
            "unmatchedNames": sorted(unmatched),
            "matchedButZeroFree": sorted(zero_free),
            "dataQuality": data_quality,
            "methodCounts": dict(Counter(item["method"] for item in aliases.values())),
        },
        "notes": [
            "覆盖名 → 库存线路名的唯一连接表；matched=false 表示覆盖有、431 条公交库存没有。",
            "866路→866-高峰线、986路区间→986(区间) 已按任务核实；后者空位为 0，匹配但不可售。",
            "911路双层、旅游1/2/10线为观光/双层产品，不在 431 条库存，保留 matched:false。",
            "629路不在库存，保留 matched:false；南龙专线按同线简称映射到南龙线，待运营确认。",
        ],
        "aliases": aliases,
    }
    write_json(ALIASES_PATH, doc)
    return doc


def build_station_map(metro_by_station, coverage_station_names):
    old_doc = read_json(STATION_MAP_PATH)
    stations = old_doc.get("stations", {})

    for station, value in stations.items():
        for exit_item in value.get("exits", []):
            exit_item["grade"] = (exit_item.get("grade") or "").strip()
            exit_item["gradeUnknown"] = not bool(exit_item["grade"])
            exit_item.setdefault("area", "")
            exit_item.setdefault("free", 0)
            exit_item.setdefault("total", 0)
            exit_item.setdefault("contract", 0)
            exit_item.setdefault("reserved", 0)
        value["exitCount"] = len(value.get("exits", []))

    # Add every coverage station plus 陆家嘴 (it holds 2 of the 5 empty-grade
    # exits and is therefore needed to mark all five).
    extension_names = sorted(
        (set(coverage_station_names) | {"陆家嘴"}) - BASELINE_STATIONS
    )
    add_names = sorted(set(extension_names) - set(stations))
    for station in add_names:
        if station in metro_by_station:
            exits = [make_exit(row) for row in metro_by_station[station]]
            stations[station] = {
                "inInventory": True,
                "exitCount": len(exits),
                "exits": exits,
            }
        else:
            stations[station] = {"inInventory": False, "exitCount": 0, "exits": []}

    total_exits = sum(len(value.get("exits", [])) for value in stations.values())
    grade_unknown_ids = sorted(
        exit_item["id"]
        for value in stations.values()
        for exit_item in value.get("exits", [])
        if exit_item.get("gradeUnknown")
    )
    doc = {
        "generatedAt": old_doc.get("generatedAt") or now_str(),
        "updatedAt": now_str(),
        "schemaVersion": "1.1",
        "notes": [
            "2026-11-21 更新：每个 exit 增加 gradeUnknown；grade 为空的口不猜级别。",
            "补入徐家汇/陆家嘴/迪士尼等新锚点覆盖到的站点，以及陆家嘴站（用于标记库存中全部 5 个 grade 空口）。",
            "原有站点/出入口数据未删除；inInventory=false 的站点保持原样。",
        ],
        "summary": {
            "stations": len(stations),
            "inInventory": sum(1 for value in stations.values() if value.get("inInventory")),
            "notInInventory": sum(1 for value in stations.values() if not value.get("inInventory")),
            "exits": total_exits,
            "gradeUnknownExits": len(grade_unknown_ids),
            "gradeUnknownExitIds": grade_unknown_ids,
            "baselineStations": len(BASELINE_STATIONS),
            "extensionStations": len(extension_names),
            "extensionStationNames": extension_names,
            "newlyAddedThisRun": add_names,
        },
        "stations": stations,
    }
    write_json(STATION_MAP_PATH, doc)
    return doc


def bus_item_for_alias(name, aliases, bus_lines):
    alias = aliases.get(name)
    item = {
        "coverageName": name,
        "inventoryName": None,
        "grade": None,
        "free": None,
        "total": None,
        "method": None,
        "status": "not_in_inventory",
        "reason": None,
    }
    if not alias:
        item["reason"] = "no_alias_entry"
        return item
    item["method"] = alias.get("method")
    if not alias.get("matched"):
        item["reason"] = "not_in_inventory"
        return item
    target = alias.get("inventoryName")
    if target not in bus_lines:
        item["reason"] = "alias_target_missing"
        return item
    rec = bus_lines[target]
    item["inventoryName"] = target
    item["grade"] = grade_label(rec["grades"])
    item["free"] = rec["free"]
    item["total"] = rec["total"]
    item["status"] = "available" if rec["free"] > 0 else "insufficient"
    return item


def metro_exit_status(exit_item):
    if exit_item.get("gradeUnknown") or not (exit_item.get("grade") or "").strip():
        return "grade_unknown"
    return "available" if as_int(exit_item.get("free")) > 0 else "insufficient"


def station_exit_aggregate(station_names, stations_map, metro_by_station):
    station_details = []
    exits = {}
    for station in sorted(station_names):
        value = stations_map.get(station)
        in_inventory = bool(value and value.get("inInventory"))
        inventory_ids = {row.get("metroNumber") for row in metro_by_station.get(station, [])}
        station_exits = value.get("exits", []) if in_inventory else []
        counts = Counter()
        for exit_item in station_exits:
            exit_id = exit_item.get("id")
            if exit_id in exits:
                continue
            status = metro_exit_status(exit_item)
            counts[status] += 1
            exits[exit_id] = {
                "id": exit_id,
                "station": station,
                "exit": exit_item.get("exit"),
                "grade": (exit_item.get("grade") or ""),
                "free": as_int(exit_item.get("free")),
                "total": as_int(exit_item.get("total")),
                "contract": as_int(exit_item.get("contract")),
                "reserved": as_int(exit_item.get("reserved")),
                "area": exit_item.get("area") or "",
                "status": status,
                "gradeUnknown": bool(exit_item.get("gradeUnknown")),
                "idInInventory": exit_id in inventory_ids,
            }
        station_details.append(
            {
                "station": station,
                "inInventory": in_inventory,
                "exitCount": len(station_exits),
                "available": counts["available"],
                "insufficient": counts["insufficient"],
                "gradeUnknown": counts["grade_unknown"],
                "inventoryExitCount": len(inventory_ids),
            }
        )
    return station_details, list(exits.values())


def build_join_report(manifest, bus, bus_lines, aliases, stations_map, metro_by_station):
    entries = sorted(
        manifest["coverage"],
        key=lambda item: (
            ANCHOR_ORDER.index(item["anchor"]) if item["anchor"] in ANCHOR_ORDER else 99,
            item["radius"],
        ),
    )
    anchors = []
    global_bus_names = set()
    global_stations = set()
    totals = {"coverageRows": 0, "busRows": 0, "metroRows": 0}

    for entry in entries:
        rows, meta = load_coverage_rows(entry)
        bus_rows = [row for row in rows if row.get("mediaType") == "bus"]
        metro_rows = [row for row in rows if row.get("mediaType") == "metro"]
        bus_names = sorted({(row.get("lineName") or "").strip() for row in bus_rows} - {""})
        station_names = sorted(
            {(row.get("nearestStaName") or "").strip() for row in metro_rows} - {""}
        )
        global_bus_names |= set(bus_names)
        global_stations |= set(station_names)
        totals["coverageRows"] += len(rows)
        totals["busRows"] += len(bus_rows)
        totals["metroRows"] += len(metro_rows)

        bus_items = [bus_item_for_alias(name, aliases, bus_lines) for name in bus_names]
        bus_available = sum(1 for item in bus_items if item["status"] == "available")
        bus_insufficient = sum(1 for item in bus_items if item["status"] == "insufficient")
        bus_not = sum(1 for item in bus_items if item["status"] == "not_in_inventory")
        bus_matched = bus_available + bus_insufficient
        unmatched_bus = [item["coverageName"] for item in bus_items if item["status"] == "not_in_inventory"]

        station_details, exit_items = station_exit_aggregate(
            station_names, stations_map, metro_by_station
        )
        metro_available = sum(1 for item in exit_items if item["status"] == "available")
        metro_insufficient = sum(1 for item in exit_items if item["status"] == "insufficient")
        metro_unknown = sum(1 for item in exit_items if item["status"] == "grade_unknown")
        metro_in = sum(1 for item in station_details if item["inInventory"])
        metro_not = sum(1 for item in station_details if not item["inInventory"])
        unmatched_stations = [item["station"] for item in station_details if not item["inInventory"]]

        anchors.append(
            {
                "id": entry["id"],
                "anchor": entry["anchor"],
                "radius": entry["radius"],
                "file": entry["file"],
                "coverageSource": meta,
                "coverageRows": len(rows),
                "busRows": len(bus_rows),
                "metroRows": len(metro_rows),
                "busCandidates": len(bus_names),
                "busMatched": bus_matched,
                "busAvailable": bus_available,
                "busInsufficient": bus_insufficient,
                "busNotInInventory": bus_not,
                "unmatchedNames": unmatched_bus,
                "matchedButZeroFreeNames": [
                    item["coverageName"] for item in bus_items if item["status"] == "insufficient"
                ],
                "busItems": bus_items,
                "metroStations": len(station_names),
                "metroInInventory": metro_in,
                "metroNotInInventory": metro_not,
                "metroExits": len(exit_items),
                "metroExitsAvailable": metro_available,
                "metroExitsInsufficient": metro_insufficient,
                "metroExitsGradeUnknown": metro_unknown,
                "metroExitsFreeZeroAll": sum(1 for item in exit_items if item["free"] == 0),
                "unmatchedStations": unmatched_stations,
                "stationDetails": station_details,
                "exitDetails": sorted(exit_items, key=lambda item: (item["station"], item["id"])),
                "reconciliation": {
                    "bus": {
                        "equation": "busCandidates = busAvailable + busInsufficient + busNotInInventory",
                        "left": len(bus_names),
                        "right": bus_available + bus_insufficient + bus_not,
                        "ok": len(bus_names) == bus_available + bus_insufficient + bus_not,
                    },
                    "metro": {
                        "equation": "metroExits = metroExitsAvailable + metroExitsInsufficient + metroExitsGradeUnknown",
                        "left": len(exit_items),
                        "right": metro_available + metro_insufficient + metro_unknown,
                        "ok": len(exit_items) == metro_available + metro_insufficient + metro_unknown,
                    },
                    "note": "grade 为空的口统一归入 gradeUnknown（即使 free=0），避免与 insufficient 重复计数；metroExitsFreeZeroAll 另列全部 free=0 口。",
                },
            }
        )

    # Global unique summary across all anchors.
    bus_items = [bus_item_for_alias(name, aliases, bus_lines) for name in sorted(global_bus_names)]
    bus_available = sum(1 for item in bus_items if item["status"] == "available")
    bus_insufficient = sum(1 for item in bus_items if item["status"] == "insufficient")
    bus_not = sum(1 for item in bus_items if item["status"] == "not_in_inventory")
    station_details, exit_items = station_exit_aggregate(
        global_stations, stations_map, metro_by_station
    )
    metro_available = sum(1 for item in exit_items if item["status"] == "available")
    metro_insufficient = sum(1 for item in exit_items if item["status"] == "insufficient")
    metro_unknown = sum(1 for item in exit_items if item["status"] == "grade_unknown")
    inventory_grade_unknown_ids = [
        row.get("metroNumber") or "SHDT-{}".format(row.get("resourceId"))
        for row in bus["metro"]["rows"]
        if not (row.get("grade") or "").strip()
    ]
    covered_grade_unknown_ids = {
        item["id"] for item in exit_items if item["status"] == "grade_unknown"
    }

    doc = {
        "generatedAt": now_str(),
        "inventory": {
            "file": "data/inventory_live.json",
            "fetchedAt": bus["fetchedAt"],
            "range": bus["range"],
            "busRows": len(bus["bus"]["rows"]),
            "metroRows": len(bus["metro"]["rows"]),
        },
        "sources": {
            "coverage": "data/coverage/*.json（缺失时按 GB18030/UTF-8 回退 CSV）",
            "busAliases": "data/bus_aliases.json",
            "metroStationMap": "data/metro_station_map.json",
            "manifest": "data/manifest.json",
        },
        "definitions": {
            "busCandidates": "覆盖结果中的唯一公交线路名数（按覆盖名去重，不按库存线路去重）",
            "busMatched": "别名/精确匹配到库存线路的覆盖名数",
            "busAvailable": "匹配且库存空位 free>0 的覆盖名数",
            "busInsufficient": "匹配但库存空位 free=0 的覆盖名数",
            "busNotInInventory": "未匹配到库存的覆盖名数",
            "metroStations": "覆盖结果中的唯一地铁站名数",
            "metroExits": "把在库站点展开成具体出入口后，按出口 id 去重的口数",
            "metroExitsAvailable": "free>0 且 grade 非空的口数",
            "metroExitsInsufficient": "free=0 且 grade 非空的口数",
            "metroExitsGradeUnknown": "grade 为空的口数（优先归类，不与 insufficient 重复）",
        },
        "summary": {
            "coverageFiles": len(entries),
            "coverageRows": totals["coverageRows"],
            "busRows": totals["busRows"],
            "metroRows": totals["metroRows"],
            "uniqueBusCandidates": len(global_bus_names),
            "busMatched": bus_available + bus_insufficient,
            "busAvailable": bus_available,
            "busInsufficient": bus_insufficient,
            "busNotInInventory": bus_not,
            "unmatchedBusNames": [
                item["coverageName"] for item in bus_items if item["status"] == "not_in_inventory"
            ],
            "uniqueMetroStations": len(global_stations),
            "metroInInventory": sum(1 for item in station_details if item["inInventory"]),
            "metroNotInInventory": sum(1 for item in station_details if not item["inInventory"]),
            "metroExits": len(exit_items),
            "metroExitsAvailable": metro_available,
            "metroExitsInsufficient": metro_insufficient,
            "metroExitsGradeUnknown": metro_unknown,
            "metroExitsFreeZeroAll": sum(1 for item in exit_items if item["free"] == 0),
            "inventoryGradeUnknownTotal": len(inventory_grade_unknown_ids),
            "inventoryGradeUnknownIds": sorted(inventory_grade_unknown_ids),
            "gradeUnknownOutsideCoverage": sorted(
                set(inventory_grade_unknown_ids) - covered_grade_unknown_ids
            ),
            "unmatchedStations": [
                item["station"] for item in station_details if not item["inInventory"]
            ],
            "sumPerAnchor": {
                "busCandidates": sum(a["busCandidates"] for a in anchors),
                "busMatched": sum(a["busMatched"] for a in anchors),
                "busAvailable": sum(a["busAvailable"] for a in anchors),
                "busInsufficient": sum(a["busInsufficient"] for a in anchors),
                "busNotInInventory": sum(a["busNotInInventory"] for a in anchors),
                "metroStations": sum(a["metroStations"] for a in anchors),
                "metroInInventory": sum(a["metroInInventory"] for a in anchors),
                "metroNotInInventory": sum(a["metroNotInInventory"] for a in anchors),
                "metroExits": sum(a["metroExits"] for a in anchors),
                "metroExitsAvailable": sum(a["metroExitsAvailable"] for a in anchors),
                "metroExitsInsufficient": sum(a["metroExitsInsufficient"] for a in anchors),
                "metroExitsGradeUnknown": sum(a["metroExitsGradeUnknown"] for a in anchors),
                "note": "sumPerAnchor 含同一线路/站点/口在多个 anchor 重复出现；与上方 unique 数不同。",
            },
            "reconciliation": {
                "bus": {
                    "equation": "uniqueBusCandidates = busAvailable + busInsufficient + busNotInInventory",
                    "left": len(global_bus_names),
                    "right": bus_available + bus_insufficient + bus_not,
                    "ok": len(global_bus_names) == bus_available + bus_insufficient + bus_not,
                },
                "metro": {
                    "equation": "metroExits = metroExitsAvailable + metroExitsInsufficient + metroExitsGradeUnknown",
                    "left": len(exit_items),
                    "right": metro_available + metro_insufficient + metro_unknown,
                    "ok": len(exit_items) == metro_available + metro_insufficient + metro_unknown,
                },
            },
            "note": "全局为跨 anchor 去重后的唯一数；逐 anchor 计数见 anchors[]。库存 5 个 grade 空口中，3 个出现在本次覆盖站点；陆家嘴 6/8 号口（SHDT-0229/SHDT-1283）不在覆盖内，已在 metro_station_map.json 标记 gradeUnknown，故不计入本报告的 metroExitsGradeUnknown。",
            "dataNotes": [
                "人民广场 1km 展开 13 口（人民广场站 10 + 一大会址·黄陂南路 3）；HANDOFF 旧口径 12 口（9+3）少算 1B 号口 SHDT-1205（area=0，free=1，A++）。",
                "迪士尼站在覆盖结果中存在，但 861 口库存中没有该站，因此 metroInInventory=0、metroExits=0 是库存事实，不是 join 失败。",
                "世纪大道、漕溪路同样不在 861 口库存中；北新泾/宝山路/真北路/虹桥路/虹漕路为 HANDOFF 已列的 5 个不在库站点。",
            ],
        },
        "anchors": anchors,
    }
    write_json(JOIN_REPORT_PATH, doc)
    return doc


def load_pricing():
    fallback_used = False
    if os.path.exists(PRICING_PATH):
        pricing = read_json(PRICING_PATH)
    else:
        fallback_used = True
        pricing = {
            "bus": {"S": 58000, "A++": 48000, "A+": 38000},
            "metro": {"A++": 300000, "A+": 200000},
            "production": {"bus": 5000, "metro": 2000},
            "discount": {"default": 1.0, "options": [0.92]},
            "tax": {"mode": "excluded", "rate": 0.06},
            "monitoring": {"rate": 0},
            "weeksPerMonth": 52 / 12,
        }
    return pricing, fallback_used


def quote(metro_n, bus_n, weeks, discount, pricing):
    wpm = float(pricing.get("weeksPerMonth") or (52 / 12))
    months = weeks / wpm
    metro_price = float(pricing["metro"]["A++"])
    bus_price = float(pricing["bus"]["A++"])
    metro_prod = float(pricing["production"]["metro"])
    bus_prod = float(pricing["production"]["bus"])
    media = (metro_n * metro_price + bus_n * bus_price) * months
    production = metro_n * metro_prod + bus_n * bus_prod
    gross = media + production
    net = gross * discount
    return {
        "months": round(months, 6),
        "media": money(media),
        "production": money(production),
        "gross": money(gross),
        "net": money(net),
        "discount": discount,
    }


def group_capacity(files, entries_by_id, bus_lines, aliases, stations_map, metro_by_station):
    bus_names = set()
    station_names = set()
    for coverage_id in files:
        entry = entries_by_id[coverage_id]
        rows, _meta = load_coverage_rows(entry)
        bus_names |= {
            (row.get("lineName") or "").strip()
            for row in rows
            if row.get("mediaType") == "bus" and (row.get("lineName") or "").strip()
        }
        station_names |= {
            (row.get("nearestStaName") or "").strip()
            for row in rows
            if row.get("mediaType") == "metro" and (row.get("nearestStaName") or "").strip()
        }

    target_to_coverage = defaultdict(list)
    unmatched = []
    for name in sorted(bus_names):
        item = bus_item_for_alias(name, aliases, bus_lines)
        if item["status"] in ("available", "insufficient"):
            target_to_coverage[item["inventoryName"]].append(name)
        else:
            unmatched.append(name)

    line_names = sorted(target_to_coverage)
    by_grade = {}
    for grade in ("S", "A++", "A+", "AA"):
        lines = [name for name in line_names if bus_lines[name]["grades"] == {grade}]
        by_grade[grade] = {
            "lines": len(lines),
            "freeVehicles": sum(bus_lines[name]["free"] for name in lines),
            "totalVehicles": sum(bus_lines[name]["total"] for name in lines),
        }
    available_lines = [name for name in line_names if bus_lines[name]["free"] > 0]
    insufficient_lines = [name for name in line_names if bus_lines[name]["free"] == 0]
    aplus_lines = [name for name in available_lines if bus_lines[name]["grades"] == {"A++"}]
    line_details = [
        {
            "line": name,
            "grade": grade_label(bus_lines[name]["grades"]),
            "free": bus_lines[name]["free"],
            "total": bus_lines[name]["total"],
            "contract": bus_lines[name]["contract"],
            "reserved": bus_lines[name]["reserved"],
            "coverageNames": target_to_coverage[name],
        }
        for name in line_names
    ]

    station_details, exit_items = station_exit_aggregate(
        station_names, stations_map, metro_by_station
    )
    metro_available = [item for item in exit_items if item["status"] == "available"]
    metro_insufficient = [item for item in exit_items if item["status"] == "insufficient"]
    metro_unknown = [item for item in exit_items if item["status"] == "grade_unknown"]
    aplus_exits = [item for item in metro_available if item["grade"] == "A++"]

    bus_capacity = {
        "coverageCandidates": len(bus_names),
        "coverageMatched": sum(len(names) for names in target_to_coverage.values()),
        "notInInventory": len(unmatched),
        "unmatchedNames": unmatched,
        "inventoryLines": len(line_names),
        "availableLines": len(available_lines),
        "insufficientLines": len(insufficient_lines),
        "freeVehicles": sum(bus_lines[name]["free"] for name in line_names),
        "totalVehicles": sum(bus_lines[name]["total"] for name in line_names),
        "contractVehicles": sum(bus_lines[name]["contract"] for name in line_names),
        "reservedVehicles": sum(bus_lines[name]["reserved"] for name in line_names),
        "aPlusPlus": {
            "availableLines": len(aplus_lines),
            "freeVehicles": sum(bus_lines[name]["free"] for name in aplus_lines),
            "totalVehicles": sum(bus_lines[name]["total"] for name in aplus_lines),
        },
        "byGrade": by_grade,
        "availableLineNames": available_lines,
        "aPlusPlusLineNames": aplus_lines,
        "zeroFreeLineNames": insufficient_lines,
        "lineDetails": line_details,
    }
    metro_capacity = {
        "stations": len(station_names),
        "inInventory": sum(1 for item in station_details if item["inInventory"]),
        "notInInventory": sum(1 for item in station_details if not item["inInventory"]),
        "unmatchedStations": [
            item["station"] for item in station_details if not item["inInventory"]
        ],
        "exits": len(exit_items),
        "availableExits": len(metro_available),
        "insufficientExits": len(metro_insufficient),
        "gradeUnknownExits": len(metro_unknown),
        "freeZeroAll": sum(1 for item in exit_items if item["free"] == 0),
        "aPlusPlus": {
            "availableExits": len(aplus_exits),
            "exitIds": sorted(item["id"] for item in aplus_exits),
        },
        "byGrade": {
            "A++": {
                "exits": sum(1 for item in exit_items if item["grade"] == "A++"),
                "availableExits": sum(
                    1 for item in exit_items if item["grade"] == "A++" and item["status"] == "available"
                ),
            },
            "A+": {
                "exits": sum(1 for item in exit_items if item["grade"] == "A+"),
                "availableExits": sum(
                    1 for item in exit_items if item["grade"] == "A+" and item["status"] == "available"
                ),
            },
            "unknown": {"exits": len(metro_unknown), "availableExits": 0},
        },
        "availableExitIds": sorted(item["id"] for item in metro_available),
        "stationDetails": station_details,
        "exitDetails": sorted(exit_items, key=lambda item: (item["station"], item["id"])),
    }
    return bus_capacity, metro_capacity


def eval_single_media(medium, budget, weeks, discount, bus_capacity, metro_capacity, pricing):
    if medium == "bus":
        price = float(pricing["bus"]["A++"])
        production = float(pricing["production"]["bus"])
        capacity_units = bus_capacity["freeVehicles"]
        capacity_label = "辆"
        capacity_used = {
            "availableLines": bus_capacity["availableLines"],
            "freeVehicles": bus_capacity["freeVehicles"],
            "aPlusPlusLines": bus_capacity["aPlusPlus"]["availableLines"],
            "aPlusPlusFreeVehicles": bus_capacity["aPlusPlus"]["freeVehicles"],
        }
    else:
        price = float(pricing["metro"]["A++"])
        production = float(pricing["production"]["metro"])
        capacity_units = metro_capacity["availableExits"]
        capacity_label = "口"
        capacity_used = {
            "availableExits": metro_capacity["availableExits"],
            "aPlusPlusExits": metro_capacity["aPlusPlus"]["availableExits"],
        }

    wpm = float(pricing.get("weeksPerMonth") or (52 / 12))
    months = weeks / wpm
    unit_gross = price * months + production
    unit_net = unit_gross * discount
    raw_quantity = budget / unit_net if unit_net else 0
    max_affordable = int(math.floor(raw_quantity + 1e-9))
    rounded_quantity = int(math.floor(raw_quantity + 0.5))
    deliverable = min(max_affordable, capacity_units)
    gap = max(0, max_affordable - capacity_units)
    feasible = max_affordable <= capacity_units
    cost_at_max = quote(0 if medium == "bus" else max_affordable, max_affordable if medium == "bus" else 0, weeks, discount, pricing)
    cost_at_deliverable = quote(
        0 if medium == "bus" else deliverable,
        deliverable if medium == "bus" else 0,
        weeks,
        discount,
        pricing,
    )

    if medium == "bus":
        note = "按 A++ 公交 48,000 元/辆/月 + 制作 5,000 元/辆；预算可买 {} 辆（四舍五入 {} 辆），库存可用 {} 辆/{} 线".format(
            max_affordable, rounded_quantity, capacity_units, bus_capacity["availableLines"]
        )
        if max_affordable > bus_capacity["availableLines"]:
            note += "；需多辆同线（约 {:.2f} 辆/线）".format(
                max_affordable / bus_capacity["availableLines"]
            ) if bus_capacity["availableLines"] else "；无可用线路"
    else:
        note = "按 A++ 地铁 300,000 元/口/月 + 制作 2,000 元/口；预算可买 {} 口（四舍五入 {} 口），库存可用 {} 口（A++ {} 口）".format(
            max_affordable,
            rounded_quantity,
            capacity_units,
            metro_capacity["aPlusPlus"]["availableExits"],
        )
    if feasible:
        note += "；可满足预算上限。"
        recommendation = None
    else:
        note += "；容量不足，缺口 {} {}；最多可投 {} {}，预算剩余 {} 元。".format(
            gap,
            capacity_label,
            deliverable,
            capacity_label,
            max(0, budget - cost_at_deliverable["net"]),
        )
        if medium == "bus":
            recommendation = "公交容量不足：建议缩小预算、扩大覆盖半径或改用并集锚点。"
        else:
            recommendation = "地铁口容量不足：建议改用公交、混用 A+ 口，或扩大半径/使用医院并集；0 口时地铁不可出方案。"

    return {
        "media": medium,
        "budget": budget,
        "weeks": weeks,
        "discount": discount,
        "unitPrice": price,
        "productionPerUnit": production,
        "unitGross": round(unit_gross, 2),
        "unitNet": round(unit_net, 2),
        "rawQuantity": round(raw_quantity, 4),
        "maxAffordableQuantity": max_affordable,
        "roundedQuantity": rounded_quantity,
        "deliverableQuantity": deliverable,
        "capacityUnits": capacity_units,
        "capacity": capacity_used,
        "feasible": feasible,
        "gap": {
            "metro": gap if medium == "metro" else None,
            "bus": gap if medium == "bus" else None,
        },
        "costAtMax": cost_at_max["net"],
        "costAtDeliverable": cost_at_deliverable["net"],
        "budgetRemaining": max(0, budget - cost_at_deliverable["net"]),
        "lineConstraint": {
            "availableLines": bus_capacity["availableLines"] if medium == "bus" else None,
            "targetVehicles": max_affordable if medium == "bus" else None,
            "oneVehiclePerLineFeasible": (
                max_affordable <= bus_capacity["availableLines"] if medium == "bus" else None
            ),
            "vehiclesPerLineIfDistinct": (
                round(max_affordable / bus_capacity["availableLines"], 2)
                if medium == "bus" and bus_capacity["availableLines"]
                else None
            ),
        },
        "recommendation": recommendation,
        "note": note,
    }


def make_fallback(target, budget, weeks, discount, bus_capacity, metro_capacity, pricing):
    metro_take = min(target["metro"], metro_capacity["availableExits"])
    bus_take = min(target["bus"], bus_capacity["freeVehicles"])
    base = quote(metro_take, bus_take, weeks, discount, pricing)
    remaining = max(0, budget - base["net"])
    wpm = float(pricing.get("weeksPerMonth") or (52 / 12))
    months = weeks / wpm
    bus_unit_net = (float(pricing["bus"]["A++"]) * months + float(pricing["production"]["bus"])) * discount
    metro_unit_net = (float(pricing["metro"]["A++"]) * months + float(pricing["production"]["metro"])) * discount

    extra_bus = 0
    if bus_unit_net > 0 and bus_capacity["freeVehicles"] > bus_take:
        extra_bus = min(
            int(math.floor(remaining / bus_unit_net + 1e-9)),
            bus_capacity["freeVehicles"] - bus_take,
        )
        bus_take += extra_bus
        remaining = max(0, remaining - extra_bus * bus_unit_net)

    extra_metro = 0
    if metro_unit_net > 0 and metro_capacity["availableExits"] > metro_take:
        extra_metro = min(
            int(math.floor(remaining / metro_unit_net + 1e-9)),
            metro_capacity["availableExits"] - metro_take,
        )
        metro_take += extra_metro
        remaining = max(0, remaining - extra_metro * metro_unit_net)

    fallback_cost = quote(metro_take, bus_take, weeks, discount, pricing)
    fallback_note = "按可用容量收缩后的兜底组合：{} 口 + {} 辆；成本 {} 元，预算剩余 {} 元。".format(
        metro_take, bus_take, fallback_cost["net"], max(0, budget - fallback_cost["net"])
    )
    if bus_capacity["availableLines"] and bus_take > bus_capacity["availableLines"]:
        fallback_note += "公交需约 {:.2f} 辆/线（允许同线多辆）。".format(
            bus_take / bus_capacity["availableLines"]
        )
    return {
        "metro": metro_take,
        "bus": bus_take,
        "cost": fallback_cost["net"],
        "budgetRemaining": max(0, budget - fallback_cost["net"]),
        "withinCapacity": (
            metro_take <= metro_capacity["availableExits"]
            and bus_take <= bus_capacity["freeVehicles"]
        ),
        "note": fallback_note,
    }


def eval_both(target, budget, weeks, discount, bus_capacity, metro_capacity, pricing, targets_meta):
    cost = quote(target["metro"], target["bus"], weeks, discount, pricing)
    metro_available = metro_capacity["availableExits"]
    bus_free = bus_capacity["freeVehicles"]
    bus_lines = bus_capacity["availableLines"]
    metro_gap = max(0, target["metro"] - metro_available)
    bus_gap = max(0, target["bus"] - bus_free)
    budget_ok = cost["net"] <= budget + 1
    metro_ok = target["metro"] <= metro_available
    bus_ok = target["bus"] <= bus_free
    feasible = bool(budget_ok and metro_ok and bus_ok)
    aplus_ok = (
        target["metro"] <= metro_capacity["aPlusPlus"]["availableExits"]
        and target["bus"] <= bus_capacity["aPlusPlus"]["freeVehicles"]
    )

    notes = []
    notes.append(
        "目标 {} 口 + {} 辆（{} 周，{} 折）".format(
            target["metro"], target["bus"], weeks, discount
        )
    )
    if budget_ok:
        notes.append("成本 {} 元，预算内，剩余 {} 元".format(cost["net"], budget - cost["net"]))
    else:
        notes.append("成本 {} 元，超预算 {} 元".format(cost["net"], cost["net"] - budget))
    if metro_ok:
        notes.append("地铁口可用 {} 个，满足".format(metro_available))
    else:
        notes.append("地铁口缺口 {}（可用 {}）".format(metro_gap, metro_available))
    if bus_ok:
        notes.append("公交空车 {} 辆，满足".format(bus_free))
    else:
        notes.append("公交空车缺口 {}（可用 {}）".format(bus_gap, bus_free))
    if metro_ok and not aplus_ok and target["metro"] > metro_capacity["aPlusPlus"]["availableExits"]:
        notes.append(
            "A++ 地铁口仅 {} 个，需混用 A+（仍按 A++ 计价，成本偏保守）".format(
                metro_capacity["aPlusPlus"]["availableExits"]
            )
        )
    if bus_ok and target["bus"] > bus_lines:
        notes.append(
            "可用线路 {} < {} 辆，需多辆同线（约 {:.2f} 辆/线）".format(
                bus_lines, target["bus"], target["bus"] / bus_lines
            )
        )
    if (
        target["bus"] <= bus_capacity["aPlusPlus"]["freeVehicles"]
        and target["metro"] <= metro_capacity["aPlusPlus"]["availableExits"]
    ):
        notes.append(
            "A++ 容量足够（A++ 公交 {} 辆 / A++ 地铁 {} 口）".format(
                bus_capacity["aPlusPlus"]["freeVehicles"],
                metro_capacity["aPlusPlus"]["availableExits"],
            )
        )
        if target["bus"] > bus_capacity["aPlusPlus"]["availableLines"]:
            notes.append(
                "A++ 线路仅 {} 条，{} 辆需约 {:.2f} 辆/线".format(
                    bus_capacity["aPlusPlus"]["availableLines"],
                    target["bus"],
                    target["bus"] / bus_capacity["aPlusPlus"]["availableLines"],
                )
            )

    result = {
        "target": {"metro": target["metro"], "bus": target["bus"]},
        "weeks": weeks,
        "discount": discount,
        "cost": cost["net"],
        "costDetail": cost,
        "budgetRemaining": budget - cost["net"],
        "budgetUtilization": round(cost["net"] / budget, 4),
        "feasible": feasible,
        "gap": {"metro": metro_gap, "bus": bus_gap},
        "capacityCheck": {
            "budgetOk": budget_ok,
            "metroOk": metro_ok,
            "busOk": bus_ok,
            "aPlusPlusSufficient": aplus_ok,
            "metroAvailableExits": metro_available,
            "metroAplusPlusExits": metro_capacity["aPlusPlus"]["availableExits"],
            "busAvailableLines": bus_lines,
            "busFreeVehicles": bus_free,
            "busAplusPlusLines": bus_capacity["aPlusPlus"]["availableLines"],
            "busAplusPlusFreeVehicles": bus_capacity["aPlusPlus"]["freeVehicles"],
            "oneVehiclePerLineFeasible": target["bus"] <= bus_lines,
        },
        "lineConstraint": {
            "availableLines": bus_lines,
            "targetVehicles": target["bus"],
            "oneVehiclePerLineFeasible": target["bus"] <= bus_lines,
            "vehiclesPerLineIfDistinct": (
                round(target["bus"] / bus_lines, 2) if bus_lines else None
            ),
            "note": (
                "目标 {} 辆 > 可用线路 {} 条；业务允许同线多辆（05 历史提案为 50 线 × 3 辆），公交按车辆容量可满足；若强制一车一线则公交分配不可行。".format(
                    target["bus"], bus_lines
                )
                if target["bus"] > bus_lines
                else "目标 {} 辆 <= 可用线路 {} 条，可按一车一线分配。".format(
                    target["bus"], bus_lines
                )
            ),
        },
        "targetsMeta": targets_meta,
        "note": ("可行：" if feasible else "不可行：") + "；".join(notes) + "。",
    }
    if not feasible:
        result["fallback"] = make_fallback(
            target, budget, weeks, discount, bus_capacity, metro_capacity, pricing
        )
    return result


def build_capacity_report(
    manifest, bus, bus_lines, aliases, stations_map, metro_by_station, pricing, fallback_used
):
    entries_by_id = {entry["id"]: entry for entry in manifest["coverage"]}
    groups_spec = [
        {
            "id": "meihua",
            "label": "美华",
            "kind": "single",
            "anchor": "上海美华妇儿医院",
            "fullName": "上海美华妇儿医院",
            "radius": 3000,
            "coverageIds": ["上海美华妇儿医院-3000"],
            "members": ["美华"],
        },
        {
            "id": "jiahui",
            "label": "嘉会",
            "kind": "single",
            "anchor": "上海嘉会国际医院",
            "fullName": "上海嘉会国际医院",
            "radius": 3000,
            "coverageIds": ["上海嘉会国际医院-3000"],
            "members": ["嘉会"],
        },
        {
            "id": "hemujia",
            "label": "和睦家",
            "kind": "single",
            "anchor": "上海和睦家医院",
            "fullName": "上海和睦家医院",
            "radius": 3000,
            "coverageIds": ["上海和睦家医院-3000"],
            "members": ["和睦家"],
        },
        {
            "id": "renmin-guangchang",
            "label": "人民广场",
            "kind": "single",
            "anchor": "人民广场",
            "fullName": "人民广场",
            "radius": 3000,
            "coverageIds": ["人民广场-3000"],
            "members": ["人民广场"],
        },
        {
            "id": "disney",
            "label": "迪士尼",
            "kind": "single",
            "anchor": "上海迪士尼度假区",
            "fullName": "上海迪士尼度假区",
            "radius": 5000,
            "coverageIds": ["上海迪士尼度假区-5000"],
            "members": ["迪士尼"],
            "radiusNote": "迪士尼地铁站在 861 口库存中不存在；3km 公交仅 39 辆可售，无法消化 500 万，故主用 5km。",
        },
        {
            "id": "lujiazui",
            "label": "陆家嘴",
            "kind": "single",
            "anchor": "陆家嘴金融城",
            "fullName": "陆家嘴金融城",
            "radius": 3000,
            "coverageIds": ["陆家嘴-3000"],
            "members": ["陆家嘴"],
        },
        {
            "id": "xujiahui",
            "label": "徐家汇",
            "kind": "single",
            "anchor": "徐家汇",
            "fullName": "徐家汇",
            "radius": 3000,
            "coverageIds": ["徐家汇-3000"],
            "members": ["徐家汇"],
        },
        {
            "id": "hospital-network",
            "label": "高端医疗网络 / 院区扩展",
            "kind": "union",
            "anchor": "美华 + 嘉会 + 和睦家",
            "fullName": "美华 + 嘉会 + 和睦家（3km 并集）",
            "radius": 3000,
            "coverageIds": [
                "上海美华妇儿医院-3000",
                "上海嘉会国际医院-3000",
                "上海和睦家医院-3000",
            ],
            "members": ["美华", "嘉会", "和睦家"],
            "note": "按 coverage id 并集后，对线路、站点、出入口去重。",
        },
    ]
    budget_specs = [
        {"label": "100", "budget": 1_000_000, "weeks": 4, "budgetWan": 100, "period": "4周"},
        {"label": "200", "budget": 2_000_000, "weeks": 6, "budgetWan": 200, "period": "6周"},
        {"label": "500", "budget": 5_000_000, "weeks": 6, "budgetWan": 500, "period": "6周"},
        {"label": "500_12w", "budget": 5_000_000, "weeks": 12, "budgetWan": 500, "period": "12周"},
    ]
    target_table = {
        "1.0": {
            "100": {"metro": 2, "bus": 8},
            "200": {"metro": 3, "bus": 10},
            "500": {"metro": 6, "bus": 34},
            "500_12w": {"metro": 3, "bus": 18},
        },
        "0.92": {
            "100": {"metro": 2, "bus": 10},
            "200": {"metro": 3, "bus": 12},
            "500": {"metro": 6, "bus": 39},
            "500_12w": {"metro": 3, "bus": 21},
        },
    }

    groups = {}
    for spec in groups_spec:
        bus_capacity, metro_capacity = group_capacity(
            spec["coverageIds"], entries_by_id, bus_lines, aliases, stations_map, metro_by_station
        )
        budget_output = {}
        for budget_spec in budget_specs:
            label = budget_spec["label"]
            budget = budget_spec["budget"]
            weeks = budget_spec["weeks"]
            budget_output[label] = {
                "budget": budget,
                "budgetWan": budget_spec["budgetWan"],
                "period": budget_spec["period"],
                "weeks": weeks,
                "bus": {},
                "metro": {},
                "both": {},
            }
            for discount in (1.0, 0.92):
                key = DKEY[discount]
                budget_output[label]["bus"][key] = eval_single_media(
                    "bus", budget, weeks, discount, bus_capacity, metro_capacity, pricing
                )
                budget_output[label]["metro"][key] = eval_single_media(
                    "metro", budget, weeks, discount, bus_capacity, metro_capacity, pricing
                )
                target = target_table[key][label]
                budget_output[label]["both"][key] = eval_both(
                    target,
                    budget,
                    weeks,
                    discount,
                    bus_capacity,
                    metro_capacity,
                    pricing,
                    {"source": "任务书目标组合", "weeks": weeks, "period": budget_spec["period"]},
                )
        groups[spec["id"]] = {
            "id": spec["id"],
            "label": spec["label"],
            "kind": spec["kind"],
            "anchor": spec["anchor"],
            "fullName": spec["fullName"],
            "radius": spec["radius"],
            "radiusNote": spec.get("radiusNote"),
            "members": spec["members"],
            "coverageIds": spec["coverageIds"],
            "coverageFiles": [entries_by_id[cid]["file"] for cid in spec["coverageIds"]],
            "note": spec.get("note"),
            "capacity": {"bus": bus_capacity, "metro": metro_capacity},
            "budgets": budget_output,
        }

    # Radius comparison for Disney, to justify 5km.
    disney_radii = {}
    for radius in (1000, 3000, 5000):
        cid = "上海迪士尼度假区-{}".format(radius)
        bus_capacity, metro_capacity = group_capacity(
            [cid], entries_by_id, bus_lines, aliases, stations_map, metro_by_station
        )
        max_bus = {}
        max_bus_12w = {}
        for discount in (1.0, 0.92):
            max_bus[DKEY[discount]] = eval_single_media(
                "bus", 5_000_000, 6, discount, bus_capacity, metro_capacity, pricing
            )["maxAffordableQuantity"]
            max_bus_12w[DKEY[discount]] = eval_single_media(
                "bus", 5_000_000, 12, discount, bus_capacity, metro_capacity, pricing
            )["maxAffordableQuantity"]
        disney_radii[str(radius)] = {
            "busAvailableLines": bus_capacity["availableLines"],
            "busFreeVehicles": bus_capacity["freeVehicles"],
            "busAplusPlusFreeVehicles": bus_capacity["aPlusPlus"]["freeVehicles"],
            "metroAvailableExits": metro_capacity["availableExits"],
            "maxBusAt500w": max_bus,
            "maxBusAt500wFeasible": {
                key: max_bus[key] <= bus_capacity["freeVehicles"] for key in max_bus
            },
            "maxBusGapAt500w": {
                key: max(0, max_bus[key] - bus_capacity["freeVehicles"]) for key in max_bus
            },
            "maxBusAt500w12w": max_bus_12w,
            "maxBusAt500w12wFeasible": {
                key: max_bus_12w[key] <= bus_capacity["freeVehicles"] for key in max_bus_12w
            },
            "maxBusGapAt500w12w": {
                key: max(0, max_bus_12w[key] - bus_capacity["freeVehicles"]) for key in max_bus_12w
            },
        }

    def both_result(group_id, budget, discount):
        return groups[group_id]["budgets"][budget]["both"][DKEY[discount]]

    hemujia_500 = {
        "1.0": both_result("hemujia", "500", 1.0),
        "0.92": both_result("hemujia", "500", 0.92),
    }
    hemujia_500_12w = {
        "1.0": both_result("hemujia", "500_12w", 1.0),
        "0.92": both_result("hemujia", "500_12w", 0.92),
    }
    network_500 = {
        "1.0": both_result("hospital-network", "500", 1.0),
        "0.92": both_result("hospital-network", "500", 0.92),
    }
    network_500_12w = {
        "1.0": both_result("hospital-network", "500_12w", 1.0),
        "0.92": both_result("hospital-network", "500_12w", 0.92),
    }

    def tier_summary(group_id):
        out = {}
        for label in ("100", "200", "500", "500_12w"):
            out[label] = {
                DKEY[discount]: {
                    "feasible": both_result(group_id, label, discount)["feasible"],
                    "gap": both_result(group_id, label, discount)["gap"],
                    "cost": both_result(group_id, label, discount)["cost"],
                    "target": both_result(group_id, label, discount)["target"],
                }
                for discount in (1.0, 0.92)
            }
        return out

    def all_targets_feasible(group_id, labels):
        return all(
            tier_summary(group_id)[label][key]["feasible"]
            for label in labels
            for key in ("1.0", "0.92")
        )

    max_media = {}
    for group_id in ("disney", "lujiazui", "xujiahui"):
        group = groups[group_id]
        max_media[group["label"]] = {
            "radius": group["radius"],
            "busAvailableLines": group["capacity"]["bus"]["availableLines"],
            "busFreeVehicles": group["capacity"]["bus"]["freeVehicles"],
            "busAplusPlusLines": group["capacity"]["bus"]["aPlusPlus"]["availableLines"],
            "busAplusPlusFreeVehicles": group["capacity"]["bus"]["aPlusPlus"]["freeVehicles"],
            "metroAvailableExits": group["capacity"]["metro"]["availableExits"],
            "metroAplusPlusExits": group["capacity"]["metro"]["aPlusPlus"]["availableExits"],
            "metroStationsInInventory": group["capacity"]["metro"]["inInventory"],
            "metroStationsNotInInventory": group["capacity"]["metro"]["unmatchedStations"],
            "totalMediaUnits": (
                group["capacity"]["bus"]["availableLines"]
                + group["capacity"]["metro"]["availableExits"]
            ),
            "maxQuantityBudget": "500万/6周",
            "maxBusAt500w": {
                DKEY[discount]: group["budgets"]["500"]["bus"][DKEY[discount]][
                    "maxAffordableQuantity"
                ]
                for discount in (1.0, 0.92)
            },
            "maxMetroAt500w": {
                DKEY[discount]: group["budgets"]["500"]["metro"][DKEY[discount]][
                    "maxAffordableQuantity"
                ]
                for discount in (1.0, 0.92)
            },
        }

    key_findings = {
        "hemujia_500w_feasible": hemujia_500["1.0"]["feasible"] and hemujia_500["0.92"]["feasible"],
        "hemujia_500w": {
            "target": "6 口 + 34 辆（1.0）/ 6 口 + 39 辆（0.92）",
            "feasible": {
                "1.0": hemujia_500["1.0"]["feasible"],
                "0.92": hemujia_500["0.92"]["feasible"],
            },
            "gap": {
                "1.0": hemujia_500["1.0"]["gap"],
                "0.92": hemujia_500["0.92"]["gap"],
            },
            "reason": "和睦家 3km 内可售地铁口仅 5 个（A++ 仅 1 个），目标 6 口，缺 1 口；公交 95 辆/16 线可满足 34–39 辆（约 2.1–2.4 辆/线），公交侧按车辆容量不是瓶颈，但地铁口是硬缺口。",
            "fallback": {
                "1.0": hemujia_500["1.0"].get("fallback"),
                "0.92": hemujia_500["0.92"].get("fallback"),
            },
        },
        "hemujia_500w_12w_feasible": hemujia_500_12w["1.0"]["feasible"] and hemujia_500_12w["0.92"]["feasible"],
        "hemujia_500w_12w": {
            "target": "3 口 + 18 辆（1.0）/ 3 口 + 21 辆（0.92）",
            "feasible": {
                "1.0": hemujia_500_12w["1.0"]["feasible"],
                "0.92": hemujia_500_12w["0.92"]["feasible"],
            },
            "gap": {
                "1.0": hemujia_500_12w["1.0"]["gap"],
                "0.92": hemujia_500_12w["0.92"]["gap"],
            },
            "reason": "12 周目标只需 3 口，和睦家 5 个可售口满足；公交 18/21 辆也低于 95 辆空车，故 500 万/12 周可行。",
        },
        "hospital_network_500w_feasible": network_500["1.0"]["feasible"] and network_500["0.92"]["feasible"],
        "hospital_network_500w_one_vehicle_per_line_feasible": all(
            network_500[key]["capacityCheck"]["oneVehiclePerLineFeasible"] for key in ("1.0", "0.92")
        ),
        "hospital_network_500w": {
            "target": "6 口 + 34 辆（1.0）/ 6 口 + 39 辆（0.92）",
            "feasible": {
                "1.0": network_500["1.0"]["feasible"],
                "0.92": network_500["0.92"]["feasible"],
            },
            "gap": {
                "1.0": network_500["1.0"]["gap"],
                "0.92": network_500["0.92"]["gap"],
            },
            "capacity": {
                "busAvailableLines": groups["hospital-network"]["capacity"]["bus"]["availableLines"],
                "busFreeVehicles": groups["hospital-network"]["capacity"]["bus"]["freeVehicles"],
                "busAplusPlusFreeVehicles": groups["hospital-network"]["capacity"]["bus"]["aPlusPlus"]["freeVehicles"],
                "metroAvailableExits": groups["hospital-network"]["capacity"]["metro"]["availableExits"],
                "metroAplusPlusExits": groups["hospital-network"]["capacity"]["metro"]["aPlusPlus"]["availableExits"],
            },
            "reason": "并集去重后 39 条可用公交线路 / 226 辆空车，36 个可用地铁口（A++ 28 个），6 口 + 34/39 辆可满足；1.0 与 0.92 均可行。",
        },
        "hospital_network_500w_12w_feasible": network_500_12w["1.0"]["feasible"] and network_500_12w["0.92"]["feasible"],
        "hospital_network_500w_12w": {
            "target": "3 口 + 18 辆（1.0）/ 3 口 + 21 辆（0.92）",
            "feasible": {
                "1.0": network_500_12w["1.0"]["feasible"],
                "0.92": network_500_12w["0.92"]["feasible"],
            },
            "gap": {
                "1.0": network_500_12w["1.0"]["gap"],
                "0.92": network_500_12w["0.92"]["gap"],
            },
            "reason": "12 周目标 3 口 + 18/21 辆，低于并集 36 口 / 39 线 / 226 辆容量，可行。",
        },
        "disney_metro_sufficient": False,
        "disney_must_use_5km_or_bus": True,
        "disney_500w_6w_feasible": both_result("disney", "500", 1.0)["feasible"] and both_result("disney", "500", 0.92)["feasible"],
        "disney_500w_12w_feasible": both_result("disney", "500_12w", 1.0)["feasible"] and both_result("disney", "500_12w", 0.92)["feasible"],
        "disney": {
            "metroAvailableExits": groups["disney"]["capacity"]["metro"]["availableExits"],
            "metroStationsInInventory": groups["disney"]["capacity"]["metro"]["inInventory"],
            "metroStationsNotInInventory": groups["disney"]["capacity"]["metro"]["unmatchedStations"],
            "reason": "覆盖返回“迪士尼”站，但 inventory_live.json 的 861 个地铁口中没有该站；地铁口 0。500 万/6 周目标 6 口，缺 6 口；500 万/12 周目标 3 口，缺 3 口。",
            "targets": {
                "500w_6w": {
                    "target": "6 口 + 34 辆（1.0）/ 6 口 + 39 辆（0.92）",
                    "feasible": {"1.0": both_result("disney", "500", 1.0)["feasible"], "0.92": both_result("disney", "500", 0.92)["feasible"]},
                    "gap": {"1.0": both_result("disney", "500", 1.0)["gap"], "0.92": both_result("disney", "500", 0.92)["gap"]},
                },
                "500w_12w": {
                    "target": "3 口 + 18 辆（1.0）/ 3 口 + 21 辆（0.92）",
                    "feasible": {"1.0": both_result("disney", "500_12w", 1.0)["feasible"], "0.92": both_result("disney", "500_12w", 0.92)["feasible"]},
                    "gap": {"1.0": both_result("disney", "500_12w", 1.0)["gap"], "0.92": both_result("disney", "500_12w", 0.92)["gap"]},
                },
            },
            "radiusComparison": disney_radii,
            "recommendation": "500 万/6 周必须公交为主并使用 5km 半径：5km 有 26 条可用线路 / 108 辆空车（A++ 10 条 / 61 辆），可消化 6 周公交预算（1.0 约 69 辆、0.92 约 76 辆）；3km 仅 39 辆空车，不足以消化 500 万/6 周。500 万/12 周目标仅 3 口 + 18/21 辆，公交侧 3km 的 39 辆也够，但地铁仍为 0，仍建议 5km/公交为主。",
        },
        "meihua_all_tiers_feasible": all(
            tier_summary("meihua")[label][key]["feasible"]
            for label in ("100", "200", "500")
            for key in ("1.0", "0.92")
        ),
        "meihua_500_12w_feasible": tier_summary("meihua")["500_12w"]["1.0"]["feasible"]
        and tier_summary("meihua")["500_12w"]["0.92"]["feasible"],
        "meihua_all_targets_feasible": all(
            tier_summary("meihua")[label][key]["feasible"]
            for label in ("100", "200", "500", "500_12w")
            for key in ("1.0", "0.92")
        ),
        "meihua_all_tiers_feasible_one_vehicle_per_line": all(
            groups["meihua"]["budgets"][label]["both"][key]["capacityCheck"][
                "oneVehiclePerLineFeasible"
            ]
            for label in ("100", "200", "500")
            for key in ("1.0", "0.92")
        ),
        "meihua_500_12w_one_vehicle_per_line_feasible": all(
            groups["meihua"]["budgets"]["500_12w"]["both"][key]["capacityCheck"][
                "oneVehiclePerLineFeasible"
            ]
            for key in ("1.0", "0.92")
        ),
        "jiahui_all_tiers_feasible": all(
            tier_summary("jiahui")[label][key]["feasible"]
            for label in ("100", "200", "500")
            for key in ("1.0", "0.92")
        ),
        "jiahui_500_12w_feasible": tier_summary("jiahui")["500_12w"]["1.0"]["feasible"]
        and tier_summary("jiahui")["500_12w"]["0.92"]["feasible"],
        "jiahui_all_targets_feasible": all(
            tier_summary("jiahui")[label][key]["feasible"]
            for label in ("100", "200", "500", "500_12w")
            for key in ("1.0", "0.92")
        ),
        "jiahui_all_tiers_feasible_one_vehicle_per_line": all(
            groups["jiahui"]["budgets"][label]["both"][key]["capacityCheck"][
                "oneVehiclePerLineFeasible"
            ]
            for label in ("100", "200", "500")
            for key in ("1.0", "0.92")
        ),
        "jiahui_500_12w_one_vehicle_per_line_feasible": all(
            groups["jiahui"]["budgets"]["500_12w"]["both"][key]["capacityCheck"][
                "oneVehiclePerLineFeasible"
            ]
            for key in ("1.0", "0.92")
        ),
        "renmin_guangchang_all_tiers_feasible": all_targets_feasible(
            "renmin-guangchang", ("100", "200", "500")
        ),
        "renmin_guangchang_all_targets_feasible": all_targets_feasible(
            "renmin-guangchang", ("100", "200", "500", "500_12w")
        ),
        "lujiazui_all_tiers_feasible": all_targets_feasible(
            "lujiazui", ("100", "200", "500")
        ),
        "lujiazui_all_targets_feasible": all_targets_feasible(
            "lujiazui", ("100", "200", "500", "500_12w")
        ),
        "xujiahui_all_tiers_feasible": all_targets_feasible(
            "xujiahui", ("100", "200", "500")
        ),
        "xujiahui_all_targets_feasible": all_targets_feasible(
            "xujiahui", ("100", "200", "500", "500_12w")
        ),
        "hospital_network_all_tiers_feasible": all_targets_feasible(
            "hospital-network", ("100", "200", "500")
        ),
        "hospital_network_all_targets_feasible": all_targets_feasible(
            "hospital-network", ("100", "200", "500", "500_12w")
        ),
        "meihua_tiers": tier_summary("meihua"),
        "jiahui_tiers": tier_summary("jiahui"),
        "meihua_tiers_caveat": "100/200/500 万（6 周）均按车辆容量可行；500/6 目标 34/39 辆分布在 28 条可用线路（A++ 10 条），需约 1.2–1.4 辆/线；500/12 目标 18/21 辆也低于 28 线，可一车一线。若强制一车一线，仅 500/6 不可行（28 线 < 34/39 辆），100/200/500-12周可行。",
        "jiahui_tiers_caveat": "100/200/500 万（6 周）均按车辆容量可行；500/6 目标 34/39 辆分布在 20 条可用线路（A++ 10 条），需约 1.7–2.0 辆/线；500/12 目标 18/21 辆，1.0 的 18 辆可一车一线，0.92 的 21 辆 >20 线。若强制一车一线，500/6 不可行，500/12 仅 1.0 可行。",
        "xujiahui_500w_caveat": "500/6 目标 34/39 辆 vs 27 条可用线路，需约 1.3–1.4 辆/线；500/12 目标 18/21 辆 <=27 线，可一车一线。A++ 公交空车 39 辆恰好等于 500/6 0.92 档的 39 辆目标，无冗余（A++ 仅 8 条线，约 4.9 辆/线）；500/12 的 21 辆则有余量。",
        "max_available_media": max_media,
        "notes": [
            "公交按“车辆数”判断容量；线路数不足时允许同线多辆（05 历史提案即为 50 线 × 3 辆），报告同时给出辆/线密度提示。",
            "地铁按“可售口数”判断容量；grade 为空的口不计入 available。",
            "金额按 A++ 刊例 + 制作费计算，税不含、监测费 0；0.92 为示例折扣。",
            "目标组合成本均按 A++ 计价；若混用 A+，实际成本更低。",
            "500 万有 6 周与 12 周两套目标：keyFindings.hemujia_500w 等默认指 6 周；500_12w 单列在 keyFindings 与 groups[*].budgets['500_12w']。",
        ],
    }

    doc = {
        "generatedAt": now_str(),
        "inputs": {
            "inventory": {
                "file": "data/inventory_live.json",
                "fetchedAt": bus["fetchedAt"],
                "range": bus["range"],
                "busRows": len(bus["bus"]["rows"]),
                "metroRows": len(bus["metro"]["rows"]),
            },
            "pricing": {
                "file": "data/config/pricing.json",
                "fallbackUsed": fallback_used,
            },
            "aliases": "data/bus_aliases.json",
            "stationMap": "data/metro_station_map.json",
            "manifest": "data/manifest.json",
        },
        "pricing": {
            "bus": pricing["bus"],
            "metro": pricing["metro"],
            "production": pricing["production"],
            "discount": pricing.get("discount"),
            "tax": pricing.get("tax"),
            "monitoring": pricing.get("monitoring"),
            "weeksPerMonth": pricing.get("weeksPerMonth"),
            "effectiveForThisReport": {
                "busUnit": "A++ {} 元/辆/月；制作 {} 元/辆".format(
                    pricing["bus"]["A++"], pricing["production"]["bus"]
                ),
                "metroUnit": "A++ {} 元/口/月；制作 {} 元/口".format(
                    pricing["metro"]["A++"], pricing["production"]["metro"]
                ),
                "taxMode": "excluded（{}% 单列，不并入净价）".format(
                    round(float(pricing["tax"]["rate"]) * 100)
                ),
                "monitoring": pricing.get("monitoring", {}).get("rate", 0),
                "weeksPerMonth": pricing.get("weeksPerMonth"),
            },
        },
        "assumptions": {
            "budgets": [
                {
                    "label": spec["label"],
                    "budget": spec["budget"],
                    "budgetWan": spec["budgetWan"],
                    "weeks": spec["weeks"],
                    "period": spec["period"],
                }
                for spec in budget_specs
            ],
            "discounts": [1.0, 0.92],
            "targetCombinations": target_table,
            "singleMediaQuantity": "按 A++ 单价 + 制作费，折扣后预算内最大整数；同时给出四舍五入值。",
            "singleMediaGapNote": "单媒体评估时，非该媒体的 gap 为 null；容量不足时另给 recommendation。",
            "capacityDefinition": "公交容量=匹配库存线路的空车总数（线路数另列）；地铁容量=可售口数（free>0 且 grade 非空）。主 feasible 按车辆/口数判定；同时给 oneVehiclePerLineFeasible，便于按“一车一线”严格口径复核。",
            "gradeMixNote": "主 feasible 使用全部可售口/车辆（含 A+/S）；A++ 不足时允许混用 A+，成本仍按 A++ 计价，偏保守。",
            "unionDefinition": "hospital-network = 美华/嘉会/和睦家 3km 覆盖并集，线路按库存线路名去重、站点按站名去重、出入口按 id 去重。",
            "dataNotes": [
                "库存 5 个 grade 空口：SHDT-0093（人民广场 16号口）、SHDT-0245（南京西路 9号口）、SHDT-0258（静安寺 8号口）在本次覆盖内；SHDT-0229/SHDT-1283（陆家嘴 6/8号口）不在本次覆盖内。5 个均已在 metro_station_map.json 标记 gradeUnknown，未猜级别。",
                "人民广场 1km 展开为 13 口（人民广场站 10 + 一大会址·黄陂南路 3），比 HANDOFF 旧口径 12 口多 1B 号口（SHDT-1205，area=0）；HANDOFF 的 9 口旧映射少算 1 口。",
                "迪士尼站在覆盖结果中存在，但 inventory_live.json 的 861 个地铁口中没有该站；不是 join 失败，而是库存确实无此站。",
            ],
        },
        "keyFindings": key_findings,
        "groups": groups,
    }
    write_json(CAPACITY_REPORT_PATH, doc)
    return doc


def main():
    capacity_only = "--capacity-only" in sys.argv[1:]
    os.makedirs(REPORTS, exist_ok=True)
    inv, bus_lines, metro_by_station = load_inventory()
    manifest = read_json(MANIFEST_PATH)
    pricing, fallback_used = load_pricing()

    coverage_names = set()
    coverage_station_names = set()
    for entry in manifest["coverage"]:
        rows, _meta = load_coverage_rows(entry)
        for row in rows:
            if row.get("mediaType") == "bus" and (row.get("lineName") or "").strip():
                coverage_names.add(row["lineName"].strip())
            if row.get("mediaType") == "metro" and (row.get("nearestStaName") or "").strip():
                coverage_station_names.add(row["nearestStaName"].strip())

    if capacity_only:
        # Read the existing join layer; do not rewrite aliases/station map/join report.
        alias_doc = read_json(ALIASES_PATH)
        station_doc = read_json(STATION_MAP_PATH)
        join_doc = None
    else:
        alias_doc = build_bus_aliases(inv, bus_lines, coverage_names)
        station_doc = build_station_map(metro_by_station, coverage_station_names)
        join_doc = build_join_report(
            manifest, inv, bus_lines, alias_doc["aliases"], station_doc["stations"], metro_by_station
        )
    aliases = alias_doc["aliases"]
    stations_map = station_doc["stations"]

    capacity_doc = build_capacity_report(
        manifest,
        inv,
        bus_lines,
        aliases,
        stations_map,
        metro_by_station,
        pricing,
        fallback_used,
    )

    print("bus_aliases: entries={} matched={} unmatched={} unmatchedNames={}".format(
        alias_doc["summary"]["aliasEntries"],
        alias_doc["summary"]["matched"],
        alias_doc["summary"]["unmatched"],
        alias_doc["summary"]["unmatchedNames"],
    ))
    print("metro_station_map: stations={} inInventory={} exits={} gradeUnknown={}".format(
        station_doc["summary"]["stations"],
        station_doc["summary"]["inInventory"],
        station_doc["summary"]["exits"],
        station_doc["summary"]["gradeUnknownExits"],
    ))
    if join_doc is not None:
        summary = join_doc["summary"]
        print("coverage_join: files={} rows={} busRows={} metroRows={}".format(
            summary["coverageFiles"],
            summary["coverageRows"],
            summary["busRows"],
            summary["metroRows"],
        ))
        print("  bus: candidates={} matched={} available={} insufficient={} notInInventory={} unmatched={}".format(
            summary["uniqueBusCandidates"],
            summary["busMatched"],
            summary["busAvailable"],
            summary["busInsufficient"],
            summary["busNotInInventory"],
            summary["unmatchedBusNames"],
        ))
        print("  metro: stations={} inInventory={} notInInventory={} exits={} available={} insufficient={} gradeUnknown={} unmatched={}".format(
            summary["uniqueMetroStations"],
            summary["metroInInventory"],
            summary["metroNotInInventory"],
            summary["metroExits"],
            summary["metroExitsAvailable"],
            summary["metroExitsInsufficient"],
            summary["metroExitsGradeUnknown"],
            summary["unmatchedStations"],
        ))
        print("  reconciliation bus={} metro={}".format(
            summary["reconciliation"]["bus"]["ok"], summary["reconciliation"]["metro"]["ok"]
        ))
    print("capacity: groups={} hemujia500={} network500={} disneyMetro={}".format(
        len(capacity_doc["groups"]),
        capacity_doc["keyFindings"]["hemujia_500w_feasible"],
        capacity_doc["keyFindings"]["hospital_network_500w_feasible"],
        capacity_doc["keyFindings"]["disney_metro_sufficient"],
    ))
    # Validate JSON round-trip. In capacity-only mode, only the rewritten report
    # is guaranteed to be current.
    paths = [CAPACITY_REPORT_PATH]
    if not capacity_only:
        paths = [ALIASES_PATH, STATION_MAP_PATH, JOIN_REPORT_PATH, CAPACITY_REPORT_PATH]
    for path in paths:
        read_json(path)
    print("JSON validation: OK")


if __name__ == "__main__":
    main()
