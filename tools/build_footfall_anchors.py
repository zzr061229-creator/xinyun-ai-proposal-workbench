#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成人民广场/徐家汇/美华/迪士尼的人流快照（格式对齐 lujiazui_202305.json）。

输入（data/raw/footfall/，不进 Git）：
  media_geo_anchors_raw.json          覆盖公交名 → 平台标签 ID
  footfall_bus_anchors_raw.json       公交标签人流缓存
  metro_geo_footfall_anchors_raw.json 地铁口标签、坐标、单口人流
  station_profile_anchors_raw.json    站点合并触达 + 核心站画像

输出：data/footfall/<anchorId>_202305.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw" / "footfall"
OUT_DIR = DATA / "footfall"

POI_NAMES = {"1": "学校", "2": "医疗", "3": "小区", "4": "景点", "5": "餐饮", "0": "其他"}

CORE_STATION = {
    "renmin-guangchang": "人民广场",
    "xujiahui": "徐家汇",
    "meihua": "宋园路",
    "disney": None,
}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def flow_of(item):
    if not item:
        return None
    f = item.get("flow")
    if not f:
        return None
    return [f.get("v1"), f.get("v2"), f.get("v3"), f.get("v4")]


def profile_of(raw_profile: dict, preferred_district: str | None = None):
    if not raw_profile or raw_profile.get("error"):
        return None
    data = raw_profile.get("data") or {}
    age = ((data.get("crowdAge") or {}).get("data") or [{}])[0]
    gender = ((data.get("crowdGender") or {}).get("data") or [{}])[0]
    consumption = ((data.get("crowdConsumption") or {}).get("data") or [{}])[0]
    house = ((data.get("crowdHouse") or {}).get("data") or [{}])[0]
    region = ((data.get("regionAttribute") or {}).get("data") or [])
    circle = ((data.get("circleCross") or {}).get("data") or [])

    districts = []
    for item in circle:
        border = item.get("BORDER") or ""
        polygon = []
        for pair in border.split(","):
            parts = pair.strip().split()
            if len(parts) == 2:
                try:
                    polygon.append([float(parts[0]), float(parts[1])])
                except ValueError:
                    pass
        districts.append({"name": item.get("NAME"), "polygon": polygon})
    business = None
    if districts:
        business = districts[0]
        if preferred_district:
            business = next((d for d in districts if preferred_district in (d.get("name") or "")), business)

    return {
        "basis": None,
        "businessDistricts": districts,
        "labelIds": raw_profile.get("labelIds"),
        "age": {
            "under20": age.get("age1"),
            "age20to30": age.get("age2"),
            "age30to40": age.get("age3"),
            "age40to50": age.get("age4"),
            "over50": age.get("age5"),
        },
        "gender": {"female": gender.get("female"), "male": gender.get("male")},
        "consumption": {
            "high": consumption.get("ihigh"),
            "highMid": consumption.get("imiddle"),
            "mid": consumption.get("ilow1"),
            "lowMid": consumption.get("ilow2"),
            "low": consumption.get("ilow3"),
        },
        "house": {
            "none": house.get("zero"),
            "one": house.get("one"),
            "two": house.get("two"),
            "more": house.get("more"),
        },
        "poi": [
            {
                "type": x.get("type"),
                "name": POI_NAMES.get(str(x.get("type")), "未分类"),
                "count": x.get("num"),
            }
            for x in region
        ],
        "businessDistrict": business,
    }


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    geo_raw = load(RAW / "media_geo_anchors_raw.json")
    bus_raw = load(RAW / "footfall_bus_anchors_raw.json").get("cache") or {}
    metro_raw = load(RAW / "metro_geo_footfall_anchors_raw.json")
    station_raw = load(RAW / "station_profile_anchors_raw.json")

    station_map = metro_raw.get("stationMap") or {}
    metro_cache = metro_raw.get("cache") or {}
    station_agg = station_raw.get("stationAgg") or {}
    profiles = station_raw.get("profile") or {}
    disney_profile_path = RAW / "disney_bus_profile_raw.json"
    disney_profile = load(disney_profile_path) if disney_profile_path.exists() else None
    anchor_stations = {
        aid: (meta or {}).get("stations") or []
        for aid, meta in (metro_raw.get("anchors") or {}).items()
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for anchor_id, meta in geo_raw["anchors"].items():
        anchor_name = meta["anchorName"]
        bus_names = meta.get("busNames") or []
        matched = meta.get("matched") or []
        unmatched = meta.get("unmatched") or []

        bus_lines = []
        for item in matched:
            hit = bus_raw.get(str(item["labelId"])) or {}
            if hit.get("pv") is None:
                continue
            bus_lines.append(
                {
                    "name": item["name"],
                    "labelId": item["labelId"],
                    "grade": item.get("grade"),
                    "dailyTrips": hit.get("pv"),
                    "dailyPeople": hit.get("uv"),
                    "dailyReach": hit.get("accurate"),
                    "flowByPeriod": flow_of(hit),
                }
            )
        bus_lines.sort(key=lambda x: (x["dailyReach"] or 0), reverse=True)

        stations = []
        missing_stations = []
        for st in (meta.get("stations") or anchor_stations.get(anchor_id, [])):
            sm = station_map.get(st) or {}
            exits_raw = sm.get("exits") or []
            if not exits_raw:
                missing_stations.append(st)
                continue
            exits = []
            for e in exits_raw:
                c = metro_cache.get(str(e["labelId"])) or {}
                if c.get("pv") is None:
                    continue
                exits.append(
                    {
                        "station": st,
                        "exit": e["exit"],
                        "labelId": e["labelId"],
                        "grade": e.get("grade"),
                        "dailyTrips": c.get("pv"),
                        "dailyPeople": c.get("uv"),
                        "dailyReach": c.get("accurate"),
                        "flowByPeriod": flow_of(c),
                    }
                )
            if not exits:
                missing_stations.append(st)
                continue
            agg = station_agg.get(st) or {}
            stations.append(
                {
                    "station": st,
                    "exitCount": len(exits),
                    "dailyTrips": max(x["dailyTrips"] or 0 for x in exits),
                    "dailyPeople": max(x["dailyPeople"] or 0 for x in exits),
                    "aggregateReach": agg.get("accurate"),
                    "exits": exits,
                }
            )

        core = CORE_STATION.get(anchor_id)
        area_profile = None
        if core:
            p = profile_of(profiles.get(core))
            if p:
                s = next((x for x in stations if x["station"] == core), None)
                p["basis"] = f"{core}站 {s['exitCount'] if s else 0} 个出入口合并区域"
                area_profile = p
        if not area_profile and anchor_id == "disney" and disney_profile:
            p = profile_of(disney_profile, preferred_district="迪士尼")
            if p:
                p["basis"] = f"迪士尼 {len(bus_lines)} 条公交线路合并区域（线路跨市区，含陆家嘴/迪士尼商圈）"
                area_profile = p

        notes = [
            "2023-05 平台数据，只作相对权重与预估，不代表 2027 绝对值。",
            "同一地铁站各出入口 PV/UV 基本相同；站点 aggregateReach 为多口合并去重触达，不把各口相加。",
            "公交 PV 是线路沿线区域口径，数值偏大；方案优先用 dailyReach（触达人次）。",
            "分时客流为平台 visitorsFlowrate 四段原值，平台未标单位，只作相对比较。",
            "无平台标签的站点/线路显示“无数据”，不估算。",
        ]
        if unmatched:
            notes.append("覆盖有、平台无标签的公交线：" + "、".join(unmatched) + "。")
        if missing_stations:
            notes.append("无平台标签的地铁站：" + "、".join(missing_stations) + "。")
        if not area_profile:
            notes.append("该锚点无可用地铁站标签，未取人群画像。")
        if anchor_id == "disney" and area_profile:
            notes.append("迪士尼无地铁标签；画像取 31 条公交线路合并区域，线路跨市区，含陆家嘴/迪士尼商圈，仅作参考。")

        doc = {
            "version": "1.0.0",
            "anchorId": anchor_id,
            "anchorName": anchor_name,
            "month": "2023-05",
            "dataMonth": "202305",
            "fetchedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": "新云大数据平台指标接口（visitorsFlowrateAndcrowdSpeed / crowdAge / crowdGender / crowdConsumption / crowdHouse / regionAttribute / circleCross）",
            "method": "覆盖分析里的公交线路名/地铁站名 → 平台标签 ID；按 2023-05、500m 网格查询区域人流与画像。",
            "notes": notes,
            "summary": {
                "busLines": len(bus_lines),
                "busRequested": len(bus_names),
                "metroStations": len(stations),
                "metroExits": sum(s["exitCount"] for s in stations),
                "metroMissingStations": missing_stations,
            },
            "bus": {"lines": bus_lines},
            "metro": {"stations": stations},
            "areaProfile": area_profile,
        }

        out = OUT_DIR / f"{anchor_id}_202305.json"
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(
            f"{anchor_id}: bus {len(bus_lines)}/{len(bus_names)} "
            f"metro {len(stations)}站/{sum(s['exitCount'] for s in stations)}口 "
            f"missing {missing_stations} size {out.stat().st_size/1024:.1f}KB"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())