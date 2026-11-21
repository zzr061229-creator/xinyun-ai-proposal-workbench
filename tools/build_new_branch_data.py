#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build the real SPDB branch anchors from newly fetched coverage.

Inputs (already fetched on 2026-11-21, IAB session):
  data/coverage/覆盖分析_浦发银行上海分行_1000米.json
  data/coverage/覆盖分析_浦发银行九江路支行_1000米.json
  data/coverage/覆盖分析_浦发银行徐家汇支行_1000米.json

What it does:
  1. normalizes the old station name 浦东南路(原东昌路) -> 浦东南路
  2. reuses platform 2023-05 line/exit-level footfall cache for the new
     coverage (same line/exit labels, not a new estimate)
  3. writes data/footfall/spdb-*_202305.json
  4. writes matching CSV + manifest entries + anchors.json entries

Run once after the Java backend returns; idempotent.
"""
from __future__ import annotations

import csv
import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
COV = DATA / "coverage"
FF = DATA / "footfall"

BRANCHES = [
    {
        "anchorId": "spdb-shanghai-hq",
        "fullName": "浦发银行上海分行",
        "name": "浦发上海分行",
        "address": "上海市浦东新区浦东南路588号",
        "lng": 121.51860213073695,
        "lat": 31.24078633476442,
        "note": "浦发银行上海分行（浦东南路588号）；1km 覆盖按本网点坐标重抓。",
    },
    {
        "anchorId": "spdb-jiujiang",
        "fullName": "浦发银行九江路支行",
        "name": "浦发九江路支行",
        "address": "上海市黄浦区湖北路258号",
        "lng": 121.48663215628125,
        "lat": 31.24057808314718,
        "note": "浦发银行九江路支行（湖北路258号，人民广场旁）；1km 覆盖按本网点坐标重抓。",
    },
    {
        "anchorId": "spdb-xujiahui",
        "fullName": "浦发银行徐家汇支行",
        "name": "浦发徐家汇支行",
        "address": "上海市徐汇区虹桥路188号",
        "lng": 121.43848756230452,
        "lat": 31.1983808216449,
        "note": "浦发银行徐家汇支行（虹桥路188号）；1km 覆盖按本网点坐标重抓。",
    },
]

STATION_ALIAS = {"浦东南路(原东昌路)": "浦东南路"}


def load(p: Path, default=None):
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def dump(p: Path, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def norm_exit(name: str) -> str:
    s = str(name or "").strip()
    # 宜山路等站点在红豆里改名：6号口(4号线)(原1号口) -> 平台旧标签 1号口
    m = re.search(r"原([0-9A-Za-z]+)号口", s)
    if m:
        return m.group(1).upper()
    s = re.sub(r"\([^)]*\)", "", s)
    s = s.replace("出入口", "").replace("出口", "").replace("号口", "").replace("号", "")
    if s.endswith("口"):
        s = s[:-1]
    return s.strip().upper()


def build_global_cache():
    aliases = load(DATA / "bus_aliases.json", {}).get("aliases") or {}
    gbus, gst, gexit = {}, {}, {}
    for p in sorted(FF.glob("*.json")):
        raw = load(p, {})
        for line in (raw.get("bus") or {}).get("lines") or []:
            name = (line.get("name") or "").strip()
            a = aliases.get(name) or {}
            inv = a.get("inventoryName") if a.get("matched") else None
            if inv and line.get("dailyReach") is not None:
                gbus.setdefault(inv, line)
        for st in (raw.get("metro") or {}).get("stations") or []:
            name = (st.get("station") or "").strip()
            if st.get("aggregateReach") is not None:
                gst.setdefault(name, st)
            for e in st.get("exits") or []:
                key = (name, norm_exit(e.get("exit")))
                if e.get("dailyReach") is not None:
                    gexit.setdefault(key, e)
    return aliases, gbus, gst, gexit


def build_one(b, aliases, gbus, gst, gexit):
    raw = load(COV / f"覆盖分析_{b['fullName']}_1000米.json")
    if not raw:
        raise SystemExit(f"missing coverage for {b['fullName']}")

    # 1) normalize station names inside the raw coverage copy
    for row in raw.get("list") or []:
        st = (row.get("nearestStaName") or "").strip()
        if st in STATION_ALIAS:
            row["nearestStaName"] = STATION_ALIAS[st]
    dump(COV / f"覆盖分析_{b['fullName']}_1000米.json", raw)

    bus_lines, seen_bus, missing_bus = [], set(), []
    station_names, seen_st = [], set()
    for row in raw.get("list") or []:
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
            bus_lines.append({
                "name": name,
                "labelId": rec.get("labelId"),
                "grade": rec.get("grade"),
                "dailyTrips": rec.get("dailyTrips"),
                "dailyPeople": rec.get("dailyPeople"),
                "dailyReach": rec.get("dailyReach"),
                "flowByPeriod": rec.get("flowByPeriod") or [0, 0, 0, 0],
            })
        elif row.get("mediaType") == "metro":
            st = (row.get("nearestStaName") or "").strip()
            if st and st not in seen_st:
                seen_st.add(st)
                station_names.append(st)

    stations_raw = load(DATA / "metro_station_map.json", {}).get("stations") or {}
    stations, missing_stations, exit_total, exit_hit = [], [], 0, 0
    for st_name in station_names:
        inv_st = stations_raw.get(st_name)
        exits = []
        if inv_st:
            for e in inv_st.get("exits") or []:
                exit_total += 1
                rec = gexit.get((st_name, norm_exit(e.get("exit"))))
                if rec:
                    exit_hit += 1
                exits.append({
                    "station": st_name,
                    "exit": e.get("exit"),
                    "labelId": (rec or {}).get("labelId"),
                    "grade": e.get("grade") or (rec or {}).get("grade"),
                    "dailyTrips": (rec or {}).get("dailyTrips"),
                    "dailyPeople": (rec or {}).get("dailyPeople"),
                    "dailyReach": (rec or {}).get("dailyReach"),
                    "flowByPeriod": (rec or {}).get("flowByPeriod") or [0, 0, 0, 0],
                })
        agg = gst.get(st_name) or {}
        if not inv_st or (agg.get("aggregateReach") is None and not any(x.get("dailyReach") is not None for x in exits)):
            missing_stations.append(st_name)
        stations.append({
            "station": st_name,
            "exitCount": len(exits),
            "dailyTrips": agg.get("dailyTrips"),
            "dailyPeople": agg.get("dailyPeople"),
            "aggregateReach": agg.get("aggregateReach"),
            "exits": exits,
        })

    footfall = {
        "version": "1.0.0",
        "anchorId": b["anchorId"],
        "anchorName": b["fullName"],
        "month": "2023-05",
        "dataMonth": "202305",
        "fetchedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "新云大数据平台 2023-05 触达人群-日均人次（线路/出口级缓存）",
        "method": "新覆盖按线路/出口名复用同标签已抓值；无标签保持 null，不估算。",
        "notes": [
            "覆盖为 2026-11-21 按真实网点坐标重抓的 1km。",
            "人流为平台 2023-05 线路/出口级值，不是按网点重新生成。",
            "无平台标签的口/站保持 null，页面显示“无数据”。",
        ],
        "summary": {
            "busLines": len(bus_lines),
            "busLinesTotal": len(seen_bus),
            "metroStations": len(stations),
            "metroExits": exit_hit,
            "metroExitsTotal": exit_total,
            "metroMissingStations": missing_stations,
        },
        "bus": {"lines": bus_lines},
        "metro": {"stations": stations},
        "areaProfile": None,
        "missingBusLines": missing_bus,
    }
    dump(FF / f"{b['anchorId']}_202305.json", footfall)
    return raw, footfall, missing_bus, missing_stations


def write_csv(b, raw):
    path = COV / f"覆盖分析_{b['fullName']}_1000米.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["媒体类型", "媒体名称", "覆盖点数", "覆盖中心点", "覆盖半径", "最近距离",
                    "最近命中中心点", "最近站点", "站点距离", "站点经度", "站点纬度", "mediaType"])
        for r in raw.get("list") or []:
            media = "公交线路" if r.get("mediaType") == "bus" else "地铁线路"
            w.writerow([
                media, r.get("lineName"), 1, r.get("centerName"), "1.00公里",
                str(round(float(r.get("minDistance") or 0))) + "米",
                r.get("centerName"), r.get("nearestStaName"),
                str(round(float(r.get("nearestStaDistance") or 0))) + "米",
                r.get("nearestStaLng"), r.get("nearestStaLat"), r.get("mediaType"),
            ])


def update_manifest(branches):
    path = DATA / "manifest.json"
    m = load(path, {})
    cov = m.get("coverage") or []
    by_id = {c.get("id"): c for c in cov}
    for b, raw in branches:
        rows = raw.get("list") or []
        cid = f"{b['fullName']}-1000"
        by_id[cid] = {
            "id": cid,
            "anchor": b["fullName"],
            "radius": 1000,
            "file": f"coverage/覆盖分析_{b['fullName']}_1000米.csv",
            "count": len(rows),
            "bus": sum(1 for x in rows if x.get("mediaType") == "bus"),
            "metro": sum(1 for x in rows if x.get("mediaType") == "metro"),
        }
    m["coverage"] = list(by_id.values())
    m["generatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
    dump(path, m)


def update_anchors(branches):
    path = DATA / "config" / "anchors.json"
    cfg = load(path, {})
    anchors = cfg.get("anchors") or []
    by_id = {a.get("anchorId"): a for a in anchors}
    for b, raw in branches:
        rows = raw.get("list") or []
        buses = sum(1 for x in rows if x.get("mediaType") == "bus")
        metros = len(rows) - buses
        by_id[b["anchorId"]] = {
            "anchorId": b["anchorId"],
            "name": b["name"],
            "fullName": b["fullName"],
            "type": "bank_branch",
            "typeLabel": "支行网点",
            "brandIds": ["spdb"],
            "industryIds": ["bank-insurance"],
            "address": b["address"],
            "lng": b["lng"],
            "lat": b["lat"],
            "weight": 1.0,
            "radii": [1000],
            "coverageIds": {"1000": f"{b['fullName']}-1000"},
            "coverageSummary": {"1000": {"total": len(rows), "bus": buses, "metro": metros}},
            "status": "verified",
            "source": "大数据平台 geocode + 覆盖分析（IAB API，2026-11-21）",
            "verifiedAt": "2026-11-21",
            "notes": [
                b["note"],
                "真实支行网点，不是商圈演示点；覆盖按网点坐标 1km 重抓。",
                "覆盖 1km；人流按平台 2023-05 线路/出口级缓存复用。",
            ],
        }
    cfg["anchors"] = list(by_id.values())
    dump(path, cfg)


def main():
    aliases, gbus, gst, gexit = build_global_cache()
    branches = []
    for b in BRANCHES:
        raw, ff, miss_bus, miss_st = build_one(b, aliases, gbus, gst, gexit)
        write_csv(b, raw)
        branches.append((b, raw))
        print(f"[ok] {b['fullName']}: coverage={len(raw.get('list') or [])} "
              f"bus={len(raw.get('list') or []) - sum(1 for x in raw.get('list') or [] if x.get('mediaType') == 'metro')} "
              f"metro={sum(1 for x in raw.get('list') or [] if x.get('mediaType') == 'metro')} "
              f"| footfall bus={ff['summary']['busLines']}/{ff['summary']['busLinesTotal']} "
              f"exits={ff['summary']['metroExits']}/{ff['summary']['metroExitsTotal']} "
              f"missingStations={miss_st} missingBus={miss_bus}")
    update_manifest(branches)
    update_anchors(branches)
    print("[ok] manifest + anchors.json updated")


if __name__ == "__main__":
    main()
