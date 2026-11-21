#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把大数据平台抓到的陆家嘴人流原始 JSON 合并成一份可交付数据文件。

输入：
  data/raw/footfall/footfall_bus_raw.json      公交线路（70 条）区域人流
  data/raw/footfall/footfall_metro_raw.json    地铁出入口（50 个）区域人流
  data/raw/footfall/footfall_profile_raw.json  陆家嘴站多口合并的人群画像

输出：
  data/footfall/lujiazui_202305.json

口径（大数据平台 2023-05，网格 500m）：
  coverPeoplesPV        区域覆盖人群-日均人次
  coverPeoplesUV        区域覆盖人群-日均人数
  coverPeoplesPVAccurate 触达人群-日均人次
  visitorsFlowrate      四段分时原值（平台未标单位，仅作相对比较）
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT_DIR = DATA / "footfall"
OUT_PATH = OUT_DIR / "lujiazui_202305.json"

POI_NAMES = {"1": "学校", "2": "医疗", "3": "小区", "4": "景点", "5": "餐饮", "0": "其他"}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def clean_flow(flow):
    if not flow:
        return None
    return [flow.get("v1"), flow.get("v2"), flow.get("v3"), flow.get("v4")]


def clean_media(item: dict) -> dict:
    return {
        "name": item["name"],
        "labelId": item["labelId"],
        "grade": item.get("grade"),
        "dailyTrips": item.get("pv"),
        "dailyPeople": item.get("uv"),
        "dailyReach": item.get("accurate"),
        "flowByPeriod": clean_flow(item.get("flow")),
    }


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    bus_raw = load(DATA / "raw" / "footfall" / "footfall_bus_raw.json")
    metro_raw = load(DATA / "raw" / "footfall" / "footfall_metro_raw.json")
    profile_raw = load(DATA / "raw" / "footfall" / "footfall_profile_raw.json")

    bus_lines = [clean_media(x) for x in bus_raw["result"] if x.get("pv") is not None]
    bus_lines.sort(key=lambda x: (x["dailyReach"] or 0), reverse=True)

    metro_exits = []
    for x in metro_raw["result"]:
        if x.get("pv") is None:
            continue
        metro_exits.append(
            {
                "station": x["station"],
                "exit": x["exit"],
                "labelId": x["labelId"],
                "grade": x.get("grade"),
                "dailyTrips": x.get("pv"),
                "dailyPeople": x.get("uv"),
                "dailyReach": x.get("accurate"),
                "flowByPeriod": clean_flow(x.get("flow")),
            }
        )

    station_raw_path = DATA / "raw" / "footfall" / "footfall_metro_station_raw.json"
    station_agg = {}
    if station_raw_path.exists():
        for item in load(station_raw_path):
            station_agg[item["station"]] = item

    stations = []
    for station in sorted({x["station"] for x in metro_exits}):
        exits = [x for x in metro_exits if x["station"] == station]
        agg = station_agg.get(station) or {}
        stations.append(
            {
                "station": station,
                "exitCount": len(exits),
                "dailyTrips": max(x["dailyTrips"] or 0 for x in exits),
                "dailyPeople": max(x["dailyPeople"] or 0 for x in exits),
                "aggregateReach": agg.get("accurate"),
                "exits": exits,
            }
        )

    covered_stations = {x["station"] for x in metro_raw["result"]}
    coverage_csv = DATA / "coverage" / "覆盖分析_陆家嘴_3000米.csv"
    all_stations = []
    if coverage_csv.exists():
        import csv

        with coverage_csv.open(encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                if (row.get("mediaType") or "").strip() == "metro":
                    station = (row.get("最近站点") or "").strip()
                    if station and station not in all_stations:
                        all_stations.append(station)
    missing_stations = [s for s in all_stations if s not in covered_stations]

    data = profile_raw["data"]
    age = data["crowdAge"]["data"][0]
    gender = data["crowdGender"]["data"][0]
    consumption = data["crowdConsumption"]["data"][0]
    house = data["crowdHouse"]["data"][0]
    region = data["regionAttribute"]["data"]
    circle = (data.get("circleCross") or {}).get("data") or []

    business = None
    if circle:
        border = circle[0].get("BORDER") or ""
        polygon = []
        for pair in border.split(","):
            parts = pair.strip().split()
            if len(parts) == 2:
                try:
                    polygon.append([float(parts[0]), float(parts[1])])
                except ValueError:
                    pass
        business = {"name": circle[0].get("NAME"), "polygon": polygon}

    result = {
        "version": "1.0.0",
        "anchorId": "lujiazui",
        "anchorName": "陆家嘴金融城",
        "month": "2023-05",
        "dataMonth": "202305",
        "fetchedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "新云大数据平台指标接口（visitorsFlowrateAndcrowdSpeed / crowdAge / crowdGender / crowdConsumption / crowdHouse / regionAttribute / circleCross）",
        "method": "对覆盖分析中的公交线路、地铁出入口按名称匹配平台标签，按标签 ID 查询 2023-05、500m 网格的区域人流与人群画像。",
        "notes": [
            "2023-05 数据只作相对权重与预估，不代表 2027 绝对值，也不构成合同承诺。",
            "同一地铁站各出入口的『区域覆盖人群』PV/UV 基本相同（同一片区域），『触达人群』按口不同；站点 aggregateReach 为该站多口合并去重后的触达，不把各口相加。",
            "公交 PV 是线路沿线区域口径，数值偏大；方案里优先用 dailyReach（触达人次）。",
            "分时客流为平台 visitorsFlowrate 四段原值，平台未标单位，只作早晚高峰相对比较。",
            "世纪大道站平台无标签，无法取人流；UI 显示『无数据』，不得估算。",
            "旅游 1/2/10 线、840 路在平台无对应标签，未取到人流。",
        ],
        "summary": {
            "busLines": len(bus_lines),
            "busRequested": bus_raw.get("total"),
            "metroStations": len(stations),
            "metroExits": len(metro_exits),
            "metroMissingStations": missing_stations,
        },
        "bus": {"lines": bus_lines},
        "metro": {"stations": stations},
        "areaProfile": {
            "basis": "陆家嘴站 11 个出入口合并区域",
            "labelIds": profile_raw.get("labelIds"),
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
        },
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"output: {OUT_PATH}")
    print(f"bus lines: {len(bus_lines)} / requested {bus_raw.get('total')}")
    print(f"metro stations: {len(stations)} / exits: {len(metro_exits)}")
    print(f"missing metro stations: {missing_stations}")
    print(f"business district: {business and business.get('name')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())