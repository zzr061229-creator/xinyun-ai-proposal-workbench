#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""新云 AI 提案工作台 — 打包前端静态数据。

输入：
  data/inventory_live.json
  data/config/*.json（存在则读，缺失写 null）
  data/manifest.json
  data/coverage/*.csv

输出：
  data/app_data.json（UTF-8，缩进 2）

纯标准库；可重复运行。
"""
from __future__ import annotations

import csv
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONFIG_DIR = DATA / "config"
COVERAGE_DIR = DATA / "coverage"
FOOTFALL_DIR = DATA / "footfall"
GEO_DIR = DATA / "geo"
OUT_PATH = DATA / "app_data.json"

CONFIG_KEYS = (
    "pricing",
    "contract_terms",
    "schedule_rules",
    "anchors",
    "industries",
    "footfall",
    "briefs",
)

COVERAGE_FILENAME_RE = re.compile(r"^覆盖分析_(?P<anchor>.+)_(?P<radius>\d+)米$")


def setup_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def load_json_file(path: Path):
    """返回 (data, error)。"""
    if not path.exists():
        return None, f"文件不存在: {path}"
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")), None
    except json.JSONDecodeError as exc:
        return None, f"JSON 解析失败: {exc}"
    except OSError as exc:
        return None, f"读取失败: {exc}"


def clean_cell(value) -> str:
    """去空白、去 BOM、还原 Excel 的 ="..." 公式包裹。"""
    if value is None:
        return ""
    text = str(value).strip().lstrip("\ufeff").strip()
    if text.startswith('="') and text.endswith('"'):
        text = text[2:-1]
    elif text.startswith("="):
        text = text[1:].strip()
        if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
            text = text[1:-1]
    return text.strip()


def parse_distance(value):
    """'62米' / '1.00公里' / '0' → 米（float）；无法解析返回 None。"""
    text = clean_cell(value).replace(",", "").replace("，", "")
    if not text:
        return None
    factor = 1.0
    lower = text.lower()
    if text.endswith("公里") or lower.endswith("km"):
        factor = 1000.0
        text = text[:-2]
    elif text.endswith("米") or lower.endswith("m"):
        text = text[:-1]
    try:
        return float(text.strip()) * factor
    except ValueError:
        return None


def parse_number(value):
    text = clean_cell(value).replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def media_type_of(row: dict) -> str:
    raw = clean_cell(row.get("mediaType")).lower()
    if raw in ("bus", "metro"):
        return raw
    label = clean_cell(row.get("媒体类型"))
    if "公交" in label:
        return "bus"
    if "地铁" in label:
        return "metro"
    return raw


def read_coverage(path: Path):
    """读取覆盖 CSV，兼容旧版首行 '汇总分析' 与 ="..." 坐标。"""
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    skipped_summary = False
    if lines and clean_cell(lines[0]).strip('"').strip() == "汇总分析":
        lines = lines[1:]
        skipped_summary = True

    rows = []
    if lines:
        reader = csv.DictReader(lines)
        for raw in reader:
            row = {}
            for key, value in raw.items():
                if key is None:
                    continue
                row[clean_cell(key)] = clean_cell(value)
            if any(row.values()):
                rows.append(row)
    return rows, skipped_summary


def normalize_coverage_row(row: dict, anchor: str, radius: int) -> dict:
    """保留 CSV 原始列，追加 mediaType 与数值化派生字段，方便前端直接用。"""
    normalized = dict(row)
    media_type = media_type_of(row)
    normalized["mediaType"] = media_type

    nearest_distance = parse_distance(row.get("最近距离"))
    station_distance = parse_distance(row.get("站点距离"))
    radius_meters = parse_distance(row.get("覆盖半径"))
    coverage_points = parse_number(row.get("覆盖点数"))
    longitude = parse_number(row.get("站点经度"))
    latitude = parse_number(row.get("站点纬度"))

    normalized["coverageAnchor"] = clean_cell(row.get("覆盖中心点")) or anchor
    normalized["radiusMeters"] = int(radius_meters) if radius_meters is not None else radius
    normalized["coveragePointCount"] = int(coverage_points) if coverage_points is not None else None
    normalized["nearestDistanceMeters"] = (
        int(nearest_distance) if nearest_distance is not None else None
    )
    normalized["stationDistanceMeters"] = (
        int(station_distance) if station_distance is not None else None
    )
    normalized["longitude"] = longitude
    normalized["latitude"] = latitude
    return normalized


def load_config(warnings: list) -> dict:
    config = {key: None for key in CONFIG_KEYS}
    if not CONFIG_DIR.exists():
        for key in CONFIG_KEYS:
            warnings.append(f"缺少 data/config/{key}.json，config.{key}=null")
        return config

    for path in sorted(CONFIG_DIR.glob("*.json")):
        key = path.stem
        data, error = load_json_file(path)
        if error:
            warnings.append(f"config.{key} 读取失败：{error}")
            if key in config:
                config[key] = None
            continue
        config[key] = data

    for key in CONFIG_KEYS:
        if config[key] is None:
            warnings.append(f"缺少 data/config/{key}.json，config.{key}=null")
    return config


def coverage_id(anchor: str, radius: int) -> str:
    return f"{anchor}-{radius}"


def build_coverage(warnings: list) -> dict:
    manifest, manifest_error = load_json_file(DATA / "manifest.json")
    entries = []
    seen_files = set()

    if manifest_error:
        warnings.append(f"manifest.json 不可用，改为扫描 data/coverage/*.csv：{manifest_error}")
    else:
        for item in (manifest or {}).get("coverage") or []:
            rel = clean_cell(item.get("file"))
            if not rel:
                warnings.append("manifest.coverage 中存在缺少 file 的条目")
                continue
            entries.append(
                {
                    "id": clean_cell(item.get("id")),
                    "anchor": clean_cell(item.get("anchor")),
                    "radius": parse_number(item.get("radius")),
                    "file": rel,
                    "manifestCount": parse_number(item.get("count")),
                    "manifestBus": parse_number(item.get("bus")),
                    "manifestMetro": parse_number(item.get("metro")),
                }
            )
            seen_files.add(rel)

    # manifest 没登记的 CSV 也要打包，避免数据静默丢失
    for path in sorted(COVERAGE_DIR.glob("*.csv")):
        rel = path.relative_to(DATA).as_posix()
        if rel in seen_files:
            continue
        match = COVERAGE_FILENAME_RE.match(path.stem)
        anchor = match.group("anchor") if match else path.stem
        radius = int(match.group("radius")) if match else None
        warnings.append(f"{rel} 未登记在 manifest，按文件名推断 id={coverage_id(anchor, radius or 0)}")
        entries.append(
            {
                "id": coverage_id(anchor, radius or 0),
                "anchor": anchor,
                "radius": radius,
                "file": rel,
                "manifestCount": None,
                "manifestBus": None,
                "manifestMetro": None,
            }
        )
        seen_files.add(rel)

    coverage = {}
    for entry in entries:
        path = DATA / entry["file"]
        if not path.exists():
            warnings.append(f"manifest 指向的覆盖文件不存在：{entry['file']}")
            continue
        rows, skipped_summary = read_coverage(path)
        match = COVERAGE_FILENAME_RE.match(path.stem)
        anchor = entry["anchor"] or (match.group("anchor") if match else path.stem)
        radius = entry["radius"]
        if radius is None:
            radius = int(match.group("radius")) if match else 0
        radius = int(radius)
        item_id = entry["id"] or coverage_id(anchor, radius)

        normalized_rows = [normalize_coverage_row(row, anchor, radius) for row in rows]
        type_counter = Counter(row.get("mediaType") for row in normalized_rows)
        bus_count = type_counter.get("bus", 0)
        metro_count = type_counter.get("metro", 0)

        if entry["manifestCount"] is not None and int(entry["manifestCount"]) != len(normalized_rows):
            warnings.append(
                f"{entry['file']} 实际 {len(normalized_rows)} 行，manifest 记 {int(entry['manifestCount'])}"
            )
        if entry["manifestBus"] is not None and int(entry["manifestBus"]) != bus_count:
            warnings.append(
                f"{entry['file']} 公交实际 {bus_count} 行，manifest 记 {int(entry['manifestBus'])}"
            )
        if entry["manifestMetro"] is not None and int(entry["manifestMetro"]) != metro_count:
            warnings.append(
                f"{entry['file']} 地铁实际 {metro_count} 行，manifest 记 {int(entry['manifestMetro'])}"
            )

        if item_id in coverage:
            warnings.append(f"coverage id 重复：{item_id}，后者覆盖前者")
        coverage[item_id] = {
            "anchor": anchor,
            "radius": radius,
            "file": entry["file"],
            "rowCount": len(normalized_rows),
            "busCount": bus_count,
            "metroCount": metro_count,
            "skippedSummaryRow": skipped_summary,
            "rows": normalized_rows,
        }

    return coverage


def build_footfall(warnings: list) -> dict:
    """打包 data/footfall/*.json（大数据平台人流/画像快照）。"""
    footfall = {}
    if not FOOTFALL_DIR.exists():
        return footfall
    for path in sorted(FOOTFALL_DIR.glob("*.json")):
        data, error = load_json_file(path)
        if error:
            warnings.append(f"footfall.{path.stem} 读取失败：{error}")
            continue
        footfall[path.stem] = {
            "file": path.relative_to(DATA).as_posix(),
            "data": data,
        }
    return footfall


def build_geo(warnings: list) -> dict:
    """打包 data/geo/*.json（线路/站点几何）。"""
    geo = {}
    if not GEO_DIR.exists():
        return geo
    for path in sorted(GEO_DIR.glob("*.json")):
        data, error = load_json_file(path)
        if error:
            warnings.append(f"geo.{path.stem} 读取失败：{error}")
            continue
        geo[path.stem] = {
            "file": path.relative_to(DATA).as_posix(),
            "data": data,
        }
    return geo


def main() -> int:
    setup_stdout()
    warnings = []

    inventory, inventory_error = load_json_file(DATA / "inventory_live.json")
    if inventory_error:
        print(f"[FAIL] inventory_live.json 不可用：{inventory_error}", file=sys.stderr)
        return 1
    if not isinstance(inventory, dict):
        print("[FAIL] inventory_live.json 顶层不是对象", file=sys.stderr)
        return 1

    bus_rows = list((inventory.get("bus") or {}).get("rows") or [])
    metro_rows = list((inventory.get("metro") or {}).get("rows") or [])
    if not bus_rows or not metro_rows:
        print("[FAIL] inventory_live.json 缺少 bus.rows 或 metro.rows", file=sys.stderr)
        return 1

    config = load_config(warnings)
    coverage = build_coverage(warnings)
    footfall = build_footfall(warnings)
    geo = build_geo(warnings)

    coverage_rows = sum(item["rowCount"] for item in coverage.values())
    coverage_bus = sum(item["busCount"] for item in coverage.values())
    coverage_metro = sum(item["metroCount"] for item in coverage.values())

    generated_at = time.strftime("%Y-%m-%d %H:%M:%S")
    snapshot_at = clean_cell(inventory.get("fetchedAt"))
    window = inventory.get("range") or {}

    config_missing = [key for key in CONFIG_KEYS if config.get(key) is None]
    app_data = {
        "meta": {
            "generatedAt": generated_at,
            "snapshotAt": snapshot_at,
            "range": {
                "start": clean_cell(window.get("start")),
                "end": clean_cell(window.get("end")),
            },
            "source": "红豆库存快照 data/inventory_live.json + 大数据覆盖分析 data/coverage/*.csv",
            "counts": {
                "bus": len(bus_rows),
                "metro": len(metro_rows),
                "coverageFiles": len(coverage),
                "coverageRows": coverage_rows,
                "footfallFiles": len(footfall),
                "geoFiles": len(geo),
            },
            "configMissing": config_missing,
            "warnings": warnings,
        },
        "inventory": {"bus": bus_rows, "metro": metro_rows},
        "config": config,
        "coverage": coverage,
        "footfall": footfall,
        "geo": geo,
    }

    try:
        text = json.dumps(app_data, ensure_ascii=False, indent=2, allow_nan=False)
    except (TypeError, ValueError) as exc:
        print(f"[FAIL] 序列化 app_data 失败：{exc}", file=sys.stderr)
        return 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text + "\n")

    size_bytes = OUT_PATH.stat().st_size
    print(f"app_data：{OUT_PATH}")
    print(f"大小：{size_bytes / 1024 / 1024:.2f} MB（{size_bytes} bytes）")
    print(f"库存：公交 {len(bus_rows)} 行 / 地铁 {len(metro_rows)} 行")
    print(
        f"覆盖：{len(coverage)} 个条目 / {coverage_rows} 行"
        f"（公交 {coverage_bus} / 地铁 {coverage_metro}）"
    )
    for key in CONFIG_KEYS:
        state = "null" if config.get(key) is None else "ok"
        print(f"config.{key}：{state}")
    if warnings:
        print(f"警告：{len(warnings)} 条")
        for warning in warnings:
            print(f"  - {warning}")
    else:
        print("警告：0 条")

    return 0


if __name__ == "__main__":
    sys.exit(main())
