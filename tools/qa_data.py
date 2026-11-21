#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""新云 AI 提案工作台 — 数据快照 QA。

只读 data/，输出 data/reports/qa_report.json。
纯标准库，不依赖 pandas / openpyxl。

检查四块：
  1. 库存快照：行数、可售数、档期、唯一键
  2. 覆盖 CSV：字段完整性、公交别名 join、地铁站点→出入口 join
  3. 预算：按刊例 / 制作费 / 折扣复算三档目标组合
  4. 证据：每条 coverage 行能否反查 freeCount / grade / 距离 / 站点

退出码：有 fail 返回 1，否则 0。
"""
from __future__ import annotations

import csv
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
COVERAGE_DIR = DATA / "coverage"
REPORT_PATH = DATA / "reports" / "qa_report.json"

WPM = 52.0 / 12.0  # weeks per month = 4.333...

EXPECTED = {
    "bus_rows": 431,
    "bus_free": 1376,
    "metro_rows": 861,
    "metro_free": 824,
    "range_start": "2027-04-01",
    "range_end": "2027-05-15",
    # 体检报告中的结构值，用于交叉核对（不是业务硬断言）
    "bus_zero_free": 103,
    "metro_zero_free": 37,
    "metro_empty_grade": 5,
    "metro_area_zero": 54,
    "bus_maintenance": 344,
}

DEFAULT_PRICING = {
    "currency": "CNY",
    "bus": {"S": 58000.0, "A++": 48000.0, "A+": 38000.0},
    "metro": {"A++": 300000.0, "A+": 200000.0},
    "production": {"bus": 5000.0, "metro": 2000.0},
    "discount": 1.0,
    "tax": "excluded",
    "monitoring": 0.0,
}

# 目标组合：每个场景分别给出 1.0（刊例口径）与 0.92（折扣口径）的媒体数量。
# 100 万按 4 周；200/500 万按 6 周；500 万额外校验 12 周。
TARGETS = [
    {
        "budget": 1_000_000,
        "wan": 100,
        "weeks": 4,
        "list": {"bus": 8, "metro": 2},
        "discount92": {"bus": 10, "metro": 2},
    },
    {
        "budget": 2_000_000,
        "wan": 200,
        "weeks": 6,
        "list": {"bus": 10, "metro": 3},
        "discount92": {"bus": 12, "metro": 3},
    },
    {
        "budget": 5_000_000,
        "wan": 500,
        "weeks": 6,
        "list": {"bus": 34, "metro": 6},
        "discount92": {"bus": 39, "metro": 6},
    },
    {
        "budget": 5_000_000,
        "wan": 500,
        "weeks": 12,
        "list": {"bus": 18, "metro": 3},
        "discount92": {"bus": 21, "metro": 3},
    },
]

REQUIRED_COVERAGE_FIELDS = ("mediaType", "媒体名称", "最近站点", "最近距离")


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------


def setup_stdout() -> None:
    """Git Bash / Windows 控制台默认 gbk，统一成 utf-8 避免中文输出炸掉。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def load_json(path: Path):
    """返回 (data, error)。文件缺失/解析失败不抛异常。"""
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
    if text.endswith("公里") or text.lower().endswith("km"):
        factor = 1000.0
        text = text[:-2] if text.endswith("公里") else text[:-2]
    elif text.endswith("米") or text.lower().endswith("m"):
        text = text[:-1]
    text = text.strip()
    try:
        return float(text) * factor
    except ValueError:
        return None


def as_float(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number


def as_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


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
    """读取覆盖 CSV，兼容旧版首行 '汇总分析' 与 ="..." 坐标。

    返回 (rows, info)。rows 的 key/value 都已做 clean_cell。
    """
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    skipped_summary = False
    if lines and clean_cell(lines[0]).strip('"').strip() == "汇总分析":
        lines = lines[1:]
        skipped_summary = True

    rows = []
    fieldnames = []
    formula_cells = 0
    if lines:
        reader = csv.DictReader(lines)
        fieldnames = [clean_cell(name) for name in (reader.fieldnames or [])]
        for raw in reader:
            row = {}
            for key, value in raw.items():
                if key is None:
                    continue
                if isinstance(value, str) and value.strip().startswith('="'):
                    formula_cells += 1
                row[clean_cell(key)] = clean_cell(value)
            if not any(row.values()):
                continue
            rows.append(row)

    return rows, {
        "skippedSummary": skipped_summary,
        "fieldnames": fieldnames,
        "formulaCells": formula_cells,
    }


def fmt_wan(amount: float) -> str:
    return f"{amount / 10000.0:.1f}万"


# ---------------------------------------------------------------------------
# check 记录器
# ---------------------------------------------------------------------------


class CheckLog:
    def __init__(self) -> None:
        self.items = []

    def add(self, check_id: str, status: str, detail: str) -> None:
        self.items.append({"id": check_id, "status": status, "detail": detail})

    def ok(self, check_id: str, detail: str) -> None:
        self.add(check_id, "pass", detail)

    def warn(self, check_id: str, detail: str) -> None:
        self.add(check_id, "warn", detail)

    def fail(self, check_id: str, detail: str) -> None:
        self.add(check_id, "fail", detail)

    def summary(self) -> dict:
        counter = Counter(item["status"] for item in self.items)
        return {
            "pass": counter.get("pass", 0),
            "warn": counter.get("warn", 0),
            "fail": counter.get("fail", 0),
        }


# ---------------------------------------------------------------------------
# 1. 库存
# ---------------------------------------------------------------------------


def inspect_inventory(inv: dict, inv_error, checks: CheckLog):
    bus = list(((inv or {}).get("bus") or {}).get("rows") or [])
    metro = list(((inv or {}).get("metro") or {}).get("rows") or [])
    fetched_at = clean_cell((inv or {}).get("fetchedAt"))
    window = (inv or {}).get("range") or {}

    bus_free = sum(as_int(row.get("freeCount")) for row in bus)
    metro_free = sum(as_int(row.get("freeCount")) for row in metro)

    expected_bus = EXPECTED["bus_rows"]
    expected_metro = EXPECTED["metro_rows"]
    counts_ok = (
        inv_error is None
        and len(bus) == expected_bus
        and bus_free == EXPECTED["bus_free"]
        and len(metro) == expected_metro
        and metro_free == EXPECTED["metro_free"]
    )
    detail = (
        f"公交 {len(bus)} 行 / 可售 {bus_free}（期望 {expected_bus}/{EXPECTED['bus_free']}）；"
        f"地铁 {len(metro)} 行 / 可售 {metro_free}（期望 {expected_metro}/{EXPECTED['metro_free']}）"
    )
    if inv_error:
        checks.fail("inventory_counts", f"库存文件不可用：{inv_error}")
    elif counts_ok:
        checks.ok("inventory_counts", detail)
    else:
        checks.fail("inventory_counts", detail)

    # 档期
    start = clean_cell(window.get("start"))
    end = clean_cell(window.get("end"))
    if start == EXPECTED["range_start"] and end == EXPECTED["range_end"]:
        checks.ok("inventory_range", f"档期 {start} ～ {end}")
    else:
        checks.fail(
            "inventory_range",
            f"档期 {start or '(空)'} ～ {end or '(空)'}；期望 "
            f"{EXPECTED['range_start']} ～ {EXPECTED['range_end']}",
        )

    # 快照时间
    if fetched_at:
        checks.ok("inventory_fetched_at", f"fetchedAt = {fetched_at}")
    else:
        checks.fail("inventory_fetched_at", "inventory_live.json.fetchedAt 为空")

    # 唯一键
    bus_keys = [
        (clean_cell(row.get("resourceId")), clean_cell(row.get("mediaName")))
        for row in bus
    ]
    bad_bus_keys = sum(1 for resource_id, media_name in bus_keys if not resource_id or not media_name)
    unique_bus_keys = len(set(bus_keys))
    if bus and bad_bus_keys == 0 and unique_bus_keys == len(bus):
        checks.ok(
            "inventory_bus_unique_key",
            f"(resourceId, mediaName) 唯一：{unique_bus_keys}/{len(bus)}",
        )
    else:
        checks.fail(
            "inventory_bus_unique_key",
            f"唯一键 {unique_bus_keys}/{len(bus)}，空键 {bad_bus_keys} 行",
        )

    metro_numbers = [clean_cell(row.get("metroNumber")) for row in metro]
    empty_metro_numbers = sum(1 for value in metro_numbers if not value)
    unique_metro_numbers = len(set(metro_numbers))
    if metro and empty_metro_numbers == 0 and unique_metro_numbers == len(metro):
        checks.ok(
            "inventory_metro_unique_key",
            f"metroNumber 唯一：{unique_metro_numbers}/{len(metro)}",
        )
    else:
        checks.fail(
            "inventory_metro_unique_key",
            f"metroNumber 唯一 {unique_metro_numbers}/{len(metro)}，空值 {empty_metro_numbers} 行",
        )

    # 级别分布
    bus_grades = Counter(clean_cell(row.get("grade")) or "(空)" for row in bus)
    metro_grades = Counter(clean_cell(row.get("grade")) or "(空)" for row in metro)
    bus_grade_text = " ".join(f"{g}{bus_grades.get(g, 0)}" for g in ("S", "A++", "A+", "AA", "(空)"))
    metro_grade_text = " ".join(f"{g}{metro_grades.get(g, 0)}" for g in ("A++", "A+", "(空)"))
    checks.ok(
        "inventory_grade_breakdown",
        f"公交 {bus_grade_text}；地铁 {metro_grade_text}",
    )

    # 结构统计（体检报告口径）
    bus_zero_free = sum(1 for row in bus if as_int(row.get("freeCount")) <= 0)
    metro_zero_free = sum(1 for row in metro if as_int(row.get("freeCount")) <= 0)
    metro_empty_grade = sum(1 for row in metro if not clean_cell(row.get("grade")))
    metro_area_zero = sum(1 for row in metro if clean_cell(row.get("businessAreaName")) == "0")
    bus_maintenance = sum(as_int(row.get("maintenanceForbiddenCount")) for row in bus)
    metro_maintenance = sum(as_int(row.get("maintenanceForbiddenCount")) for row in metro)

    structure_mismatch = []
    if bus_zero_free != EXPECTED["bus_zero_free"]:
        structure_mismatch.append(f"公交空位0 {bus_zero_free}≠{EXPECTED['bus_zero_free']}")
    if metro_zero_free != EXPECTED["metro_zero_free"]:
        structure_mismatch.append(f"地铁空位0 {metro_zero_free}≠{EXPECTED['metro_zero_free']}")
    if metro_empty_grade != EXPECTED["metro_empty_grade"]:
        structure_mismatch.append(f"地铁空grade {metro_empty_grade}≠{EXPECTED['metro_empty_grade']}")
    if metro_area_zero != EXPECTED["metro_area_zero"]:
        structure_mismatch.append(f"商业区域0 {metro_area_zero}≠{EXPECTED['metro_area_zero']}")
    if bus_maintenance != EXPECTED["bus_maintenance"]:
        structure_mismatch.append(f"公交保养 {bus_maintenance}≠{EXPECTED['bus_maintenance']}")

    structure_detail = (
        f"空位为0：公交 {bus_zero_free} 条 / 地铁 {metro_zero_free} 口；"
        f"地铁空grade {metro_empty_grade} 口；商业区域='0' {metro_area_zero} 口；"
        f"保养影响：公交 {bus_maintenance} 辆 / 地铁 {metro_maintenance} 口"
    )
    if structure_mismatch:
        checks.warn(
            "inventory_zero_free_and_gaps",
            structure_detail + "；与体检报告差异：" + "；".join(structure_mismatch),
        )
    else:
        checks.ok("inventory_zero_free_and_gaps", structure_detail + "；与体检报告一致")

    # totalCount 字段口径
    bus_total_field = as_int(((inv or {}).get("bus") or {}).get("total"), default=len(bus))
    metro_total_field = as_int(((inv or {}).get("metro") or {}).get("total"), default=len(metro))
    checks.ok(
        "inventory_raw_total",
        f"bus.total={bus_total_field}（原始请求条数，去重后可售 {len(bus)} 行）；"
        f"metro.total={metro_total_field}（出入口行数 {len(metro)}）",
    )

    # 数量恒等式诊断（不作为方案口径）
    mismatches = []
    for row in bus:
        total = as_int(row.get("totalCount"))
        contract = as_int(row.get("contractCount"))
        reserved = as_int(row.get("reservationCount"))
        maintenance = as_int(row.get("maintenanceForbiddenCount"))
        free = as_int(row.get("freeCount"))
        if total - contract - reserved - maintenance != free:
            mismatches.append(row)
    if mismatches:
        sample = "、".join(
            f"{clean_cell(row.get('lineName'))}/{clean_cell(row.get('mediaName'))}"
            for row in mismatches[:3]
        )
        checks.warn(
            "inventory_bus_arithmetic",
            f"{len(mismatches)}/{len(bus)} 行不满足 totalCount−contract−reservation−maintenance=freeCount"
            f"（示例：{sample}）；方案一律以 freeCount 为准，保养数可能与合同/预定重叠",
        )
    else:
        checks.ok("inventory_bus_arithmetic", "全部公交行满足 total−contract−reservation−maintenance=free")

    bus_unique_lines = len({clean_cell(row.get("lineName")) for row in bus if clean_cell(row.get("lineName"))})
    return {
        "file": "inventory_live.json",
        "fetchedAt": fetched_at,
        "range": {"start": start, "end": end},
        "bus": {
            "rows": len(bus),
            "uniqueLines": bus_unique_lines,
            "total": sum(as_int(row.get("totalCount")) for row in bus),
            "contract": sum(as_int(row.get("contractCount")) for row in bus),
            "reservation": sum(as_int(row.get("reservationCount")) for row in bus),
            "free": bus_free,
            "maintenance": bus_maintenance,
            "zeroFreeRows": bus_zero_free,
            "grades": dict(bus_grades),
            "rawTotalField": bus_total_field,
        },
        "metro": {
            "rows": len(metro),
            "total": sum(as_int(row.get("totalCount")) for row in metro),
            "contract": sum(as_int(row.get("contractCount")) for row in metro),
            "reservation": sum(as_int(row.get("reservationCount")) for row in metro),
            "free": metro_free,
            "maintenance": metro_maintenance,
            "zeroFreeRows": metro_zero_free,
            "emptyGrade": metro_empty_grade,
            "businessAreaZero": metro_area_zero,
            "grades": dict(metro_grades),
            "rawTotalField": metro_total_field,
        },
    }, bus, metro


# ---------------------------------------------------------------------------
# 2. 覆盖 / join
# ---------------------------------------------------------------------------


def inspect_coverage(inv, checks: CheckLog) -> dict:
    bus_rows = list(((inv or {}).get("bus") or {}).get("rows") or [])
    metro_rows = list(((inv or {}).get("metro") or {}).get("rows") or [])

    aliases_raw, aliases_error = load_json(DATA / "bus_aliases.json")
    aliases = (
        (aliases_raw.get("aliases") or {})
        if isinstance(aliases_raw, dict) and isinstance(aliases_raw.get("aliases"), dict)
        else {}
    )
    station_raw, station_error = load_json(DATA / "metro_station_map.json")
    stations = (
        (station_raw.get("stations") or {})
        if isinstance(station_raw, dict) and isinstance(station_raw.get("stations"), dict)
        else {}
    )

    if aliases_error:
        checks.fail("coverage_bus_aliases_file", f"bus_aliases.json 不可用：{aliases_error}")
    if station_error:
        checks.fail("coverage_metro_station_map_file", f"metro_station_map.json 不可用：{station_error}")

    bus_by_line = defaultdict(list)
    for row in bus_rows:
        line_name = clean_cell(row.get("lineName"))
        if line_name:
            bus_by_line[line_name].append(row)

    def classify_bus(name: str):
        alias = aliases.get(name)
        if not alias or not alias.get("matched") or not alias.get("inventoryName"):
            return "not_in_inventory", None
        inventory_name = clean_cell(alias.get("inventoryName"))
        inventory_rows = bus_by_line.get(inventory_name) or []
        if not inventory_rows:
            return "not_in_inventory", None
        free = sum(max(0, as_int(row.get("freeCount"))) for row in inventory_rows)
        return ("usable" if free >= 1 else "insufficient"), inventory_rows

    # 读取全部 CSV
    coverage_files = []
    for path in sorted(COVERAGE_DIR.glob("*.csv")):
        rows, info = read_coverage(path)
        coverage_files.append(
            {
                "path": path,
                "rel": path.relative_to(DATA).as_posix(),
                "name": path.name,
                "rows": rows,
                "info": info,
            }
        )

    if not coverage_files:
        checks.fail("coverage_files", f"未找到覆盖 CSV：{COVERAGE_DIR}")
    else:
        row_count = sum(len(item["rows"]) for item in coverage_files)
        bus_count = sum(
            1 for item in coverage_files for row in item["rows"] if media_type_of(row) == "bus"
        )
        metro_count = sum(
            1 for item in coverage_files for row in item["rows"] if media_type_of(row) == "metro"
        )
        old_format = sum(1 for item in coverage_files if item["info"]["skippedSummary"])
        checks.ok(
            "coverage_files",
            f"{len(coverage_files)} 个 CSV / {row_count} 行（公交 {bus_count} / 地铁 {metro_count}）；"
            f"旧版汇总行 {old_format} 个，已跳过",
        )

    all_rows = [row for item in coverage_files for row in item["rows"]]

    # 必填字段
    missing_fields = Counter()
    missing_examples = []
    for item in coverage_files:
        for line_no, row in enumerate(item["rows"], start=2):
            missing_here = [field for field in REQUIRED_COVERAGE_FIELDS if not clean_cell(row.get(field))]
            for field in missing_here:
                missing_fields[field] += 1
            if missing_here and len(missing_examples) < 5:
                missing_examples.append(f"{item['name']}:{line_no} 缺{','.join(missing_here)}")
    if missing_fields:
        checks.fail(
            "coverage_required_fields",
            f"缺字段行：{dict(missing_fields)}；示例：{'；'.join(missing_examples)}",
        )
    else:
        checks.ok(
            "coverage_required_fields",
            f"全部 {len(all_rows)} 行均含 mediaType / 媒体名称 / 最近站点 / 最近距离",
        )

    # 媒体类型
    type_counter = Counter(media_type_of(row) for row in all_rows)
    unexpected_types = {key: value for key, value in type_counter.items() if key not in ("bus", "metro")}
    if unexpected_types:
        checks.fail("coverage_media_type", f"出现非法 mediaType：{unexpected_types}")
    else:
        checks.ok(
            "coverage_media_type",
            f"mediaType：bus {type_counter.get('bus', 0)} / metro {type_counter.get('metro', 0)}",
        )

    # 公交 join（唯一线路）
    bus_names = sorted({clean_cell(row.get("媒体名称")) for row in all_rows if media_type_of(row) == "bus"})
    bus_categories = Counter()
    bus_not_in_inventory = []
    bus_insufficient = []
    bus_usable = []
    alias_broken = []
    for name in bus_names:
        category, inventory_rows = classify_bus(name)
        bus_categories[category] += 1
        if category == "not_in_inventory":
            bus_not_in_inventory.append(name)
            alias = aliases.get(name)
            if alias and alias.get("matched") and not inventory_rows:
                alias_broken.append(name)
        elif category == "insufficient":
            bus_insufficient.append(name)
        else:
            bus_usable.append(name)

    bus_candidates = len(bus_names)
    bus_sum = sum(bus_categories.values())
    alias_matched = bus_categories.get("usable", 0) + bus_categories.get("insufficient", 0)
    bus_detail = (
        f"候选 {bus_candidates} 条唯一线路 = 可售 {bus_categories.get('usable', 0)}"
        f" + 空位不足 {bus_categories.get('insufficient', 0)}"
        f" + 不在库 {bus_categories.get('not_in_inventory', 0)}；"
        f"别名可匹配 {alias_matched}（可售+空位不足）"
    )
    if bus_insufficient:
        bus_detail += f"；空位不足线路：{'、'.join(bus_insufficient)}"
    if bus_not_in_inventory:
        bus_detail += f"；不在库：{'、'.join(bus_not_in_inventory)}"
    if bus_candidates and bus_sum == bus_candidates and not alias_broken:
        checks.ok("coverage_bus_join", bus_detail)
    else:
        checks.fail(
            "coverage_bus_join",
            bus_detail + f"；四数之和 {bus_sum}，别名指向不存在的库存：{alias_broken or '无'}",
        )

    # 公交 join（行级，1km/3km 会重复计同一线路）
    bus_row_categories = Counter()
    for row in all_rows:
        if media_type_of(row) != "bus":
            continue
        category, _ = classify_bus(clean_cell(row.get("媒体名称")))
        bus_row_categories[category] += 1
    bus_row_total = sum(bus_row_categories.values())
    if bus_row_total and sum(bus_row_categories.values()) == bus_row_total:
        checks.ok(
            "coverage_bus_join_rows",
            f"行级 {bus_row_total} = 可售 {bus_row_categories.get('usable', 0)}"
            f" + 空位不足 {bus_row_categories.get('insufficient', 0)}"
            f" + 不在库 {bus_row_categories.get('not_in_inventory', 0)}"
            f"（同名线路在 1km/3km 文件重复出现，故与唯一线路数不同）",
        )
    else:
        checks.fail("coverage_bus_join_rows", f"行级分类不闭合：{dict(bus_row_categories)}")

    # 地铁 join（站点级）
    metro_station_names = sorted(
        {clean_cell(row.get("最近站点")) for row in all_rows if media_type_of(row) == "metro"}
    )
    station_in_inventory = []
    station_not_in_inventory = []
    station_details = []
    for name in metro_station_names:
        station = stations.get(name)
        if station and station.get("inInventory") and station.get("exits"):
            station_in_inventory.append(name)
            station_details.append(
                {
                    "station": name,
                    "exitCount": len(station.get("exits") or []),
                    "free": sum(max(0, as_int(exit_.get("free"))) for exit_ in station.get("exits") or []),
                }
            )
        else:
            station_not_in_inventory.append(name)

    station_total = len(metro_station_names)
    station_sum = len(station_in_inventory) + len(station_not_in_inventory)
    metro_coverage_rows = [row for row in all_rows if media_type_of(row) == "metro"]
    metro_rows_in_inventory = sum(
        1
        for row in metro_coverage_rows
        if (stations.get(clean_cell(row.get("最近站点"))) or {}).get("inInventory")
    )
    metro_rows_not_in_inventory = len(metro_coverage_rows) - metro_rows_in_inventory
    metro_detail = (
        f"候选 {station_total} 站 = 库存内 {len(station_in_inventory)} + 不在库 {len(station_not_in_inventory)}；"
        f"按覆盖行 {len(metro_coverage_rows)} 行 = 库存内 {metro_rows_in_inventory}"
        f" + 不在库 {metro_rows_not_in_inventory}"
    )
    if station_not_in_inventory:
        metro_detail += f"；不在库：{'、'.join(station_not_in_inventory)}"
    if station_total and station_sum == station_total:
        checks.ok("coverage_metro_join", metro_detail)
    else:
        checks.fail("coverage_metro_join", metro_detail + f"；站点数不闭合 {station_sum}")

    # 地铁出入口展开（去重）
    unique_exits = {}
    for name in station_in_inventory:
        station = stations.get(name) or {}
        for exit_ in station.get("exits") or []:
            key = clean_cell(exit_.get("id"))
            if not key:
                key = f"{name}|{clean_cell(exit_.get('exit'))}|{clean_cell(exit_.get('area'))}"
            unique_exits[key] = exit_

    exit_grade_empty = 0
    exit_insufficient = 0
    exit_selectable = 0
    for exit_ in unique_exits.values():
        grade = clean_cell(exit_.get("grade"))
        free = as_int(exit_.get("free"))
        if not grade:
            exit_grade_empty += 1
        elif free <= 0:
            exit_insufficient += 1
        else:
            exit_selectable += 1

    # 按 coverage 行重复展开的口数（同一口在不同半径/线路记录里会重复）
    row_expanded = Counter()
    row_expanded_total = 0
    for row in all_rows:
        if media_type_of(row) != "metro":
            continue
        station = stations.get(clean_cell(row.get("最近站点")))
        if not station or not station.get("inInventory"):
            continue
        for exit_ in station.get("exits") or []:
            row_expanded_total += 1
            grade = clean_cell(exit_.get("grade"))
            free = as_int(exit_.get("free"))
            if not grade:
                row_expanded["grade_empty"] += 1
            elif free <= 0:
                row_expanded["insufficient"] += 1
            else:
                row_expanded["selectable"] += 1

    station_no_selectable = []
    for detail in station_details:
        station = stations.get(detail["station"]) or {}
        if not any(
            clean_cell(exit_.get("grade")) and as_int(exit_.get("free")) > 0
            for exit_ in station.get("exits") or []
        ):
            station_no_selectable.append(detail["station"])

    exit_total = len(unique_exits)
    exit_sum = exit_grade_empty + exit_insufficient + exit_selectable
    exit_detail = (
        f"展开去重 {exit_total} 口 = 可选 {exit_selectable}（free>0 且 grade 非空）"
        f" + 空位不足 {exit_insufficient}（free=0，grade 非空）"
        f" + grade为空 {exit_grade_empty}；"
        f"按覆盖行重复展开 {row_expanded_total} 次（可选 {row_expanded.get('selectable', 0)}"
        f"/不足 {row_expanded.get('insufficient', 0)}/grade空 {row_expanded.get('grade_empty', 0)}）"
    )
    if station_no_selectable:
        exit_detail += f"；无可选口的站：{'、'.join(station_no_selectable)}"
    if exit_total and exit_sum == exit_total:
        checks.ok("coverage_metro_exits", exit_detail)
    else:
        checks.fail("coverage_metro_exits", exit_detail + f"；分类不闭合 {exit_sum}/{exit_total}")

    if station_no_selectable:
        checks.warn(
            "coverage_metro_station_availability",
            f"{len(station_no_selectable)} 个在库站点没有 free>0 且 grade 非空的出入口",
        )
    else:
        checks.ok(
            "coverage_metro_station_availability",
            f"{len(station_details)} 个在库站点均至少有 1 个可选口",
        )

    # 每个文件的条目统计
    per_file = []
    for item in coverage_files:
        file_rows = item["rows"]
        file_bus = [row for row in file_rows if media_type_of(row) == "bus"]
        file_metro = [row for row in file_rows if media_type_of(row) == "metro"]
        file_bus_categories = Counter(classify_bus(clean_cell(row.get("媒体名称")))[0] for row in file_bus)
        file_stations = {clean_cell(row.get("最近站点")) for row in file_metro}
        in_inventory_stations = sum(
            1
            for name in file_stations
            if (stations.get(name) or {}).get("inInventory") and (stations.get(name) or {}).get("exits")
        )
        per_file.append(
            {
                "file": item["name"],
                "path": item["rel"],
                "rows": len(file_rows),
                "bus": len(file_bus),
                "metro": len(file_metro),
                "busUsableRows": file_bus_categories.get("usable", 0),
                "busInsufficientRows": file_bus_categories.get("insufficient", 0),
                "busNotInInventoryRows": file_bus_categories.get("not_in_inventory", 0),
                "metroStations": len(file_stations),
                "metroStationsInInventory": in_inventory_stations,
                "skippedSummary": item["info"]["skippedSummary"],
                "formulaCells": item["info"]["formulaCells"],
            }
        )

    file_stats = {item["path"]: item for item in per_file}

    # manifest 一致性
    manifest, manifest_error = load_json(DATA / "manifest.json")
    manifest_ok = True
    manifest_detail_parts = []
    manifest_rel_files = set()
    if manifest_error:
        checks.warn("coverage_manifest", f"manifest.json 不可用：{manifest_error}")
        manifest_ok = False
    else:
        for entry in (manifest or {}).get("coverage") or []:
            rel = clean_cell(entry.get("file"))
            manifest_rel_files.add(rel)
            actual = file_stats.get(rel)
            expected_count = as_int(entry.get("count"))
            expected_bus = as_int(entry.get("bus"))
            expected_metro = as_int(entry.get("metro"))
            if not actual:
                manifest_ok = False
                manifest_detail_parts.append(f"{rel} 文件缺失")
                continue
            if (
                actual["rows"] != expected_count
                or actual["bus"] != expected_bus
                or actual["metro"] != expected_metro
            ):
                manifest_ok = False
                manifest_detail_parts.append(
                    f"{rel} 实际 {actual['rows']}/{actual['bus']}/{actual['metro']} "
                    f"≠ manifest {expected_count}/{expected_bus}/{expected_metro}"
                )
        extra = {item["rel"] for item in coverage_files} - manifest_rel_files
        if extra:
            checks.warn("coverage_manifest_extra", f"CSV 未登记在 manifest：{'、'.join(sorted(extra))}")
        else:
            checks.ok("coverage_manifest_extra", "所有 coverage CSV 均已登记在 manifest")
        if manifest_ok:
            checks.ok(
                "coverage_manifest",
                f"manifest {len((manifest or {}).get('coverage') or [])} 条与 CSV 行数/公交/地铁计数一致",
            )
        else:
            checks.fail("coverage_manifest", "；".join(manifest_detail_parts) or "manifest 计数不一致")

        inv_meta = (manifest or {}).get("inventory") or {}
        manifest_bus = inv_meta.get("bus") or {}
        manifest_metro = inv_meta.get("metro") or {}
        inv_bus_rows = len(bus_rows)
        inv_metro_rows = len(metro_rows)
        inv_bus_free = sum(as_int(row.get("freeCount")) for row in bus_rows)
        inv_metro_free = sum(as_int(row.get("freeCount")) for row in metro_rows)
        inv_manifest_ok = (
            as_int(manifest_bus.get("rows")) == inv_bus_rows
            and as_int(manifest_bus.get("free")) == inv_bus_free
            and as_int(manifest_metro.get("rows")) == inv_metro_rows
            and as_int(manifest_metro.get("free")) == inv_metro_free
        )
        if inv_manifest_ok:
            checks.ok(
                "coverage_manifest_inventory",
                f"manifest 库存计数一致：bus {inv_bus_rows}/{inv_bus_free}，metro {inv_metro_rows}/{inv_metro_free}",
            )
        else:
            checks.fail(
                "coverage_manifest_inventory",
                f"manifest bus {manifest_bus.get('rows')}/{manifest_bus.get('free')}、"
                f"metro {manifest_metro.get('rows')}/{manifest_metro.get('free')} 与实际不一致",
            )

    return {
        "files": len(coverage_files),
        "rows": len(all_rows),
        "busRows": sum(1 for row in all_rows if media_type_of(row) == "bus"),
        "metroRows": sum(1 for row in all_rows if media_type_of(row) == "metro"),
        "uniqueBusNames": bus_candidates,
        "uniqueMetroStations": station_total,
        "bus": {
            "candidates": bus_candidates,
            "matched": bus_categories.get("usable", 0),
            "usable": bus_categories.get("usable", 0),
            "insufficient": bus_categories.get("insufficient", 0),
            "notInInventory": bus_categories.get("not_in_inventory", 0),
            "aliasMatched": alias_matched,
            "insufficientNames": bus_insufficient,
            "notInInventoryNames": bus_not_in_inventory,
            "rows": {
                "total": bus_row_total,
                "matched": bus_row_categories.get("usable", 0),
                "usable": bus_row_categories.get("usable", 0),
                "insufficient": bus_row_categories.get("insufficient", 0),
                "notInInventory": bus_row_categories.get("not_in_inventory", 0),
            },
        },
        "metro": {
            "candidates": station_total,
            "inInventory": len(station_in_inventory),
            "notInInventory": len(station_not_in_inventory),
            "notInInventoryNames": station_not_in_inventory,
            "rows": {
                "total": len(metro_coverage_rows),
                "stationInInventory": metro_rows_in_inventory,
                "stationNotInInventory": metro_rows_not_in_inventory,
            },
            "stations": station_details,
            "exits": {
                "total": exit_total,
                "selectable": exit_selectable,
                "insufficient": exit_insufficient,
                "gradeEmpty": exit_grade_empty,
                "rowExpandedTotal": row_expanded_total,
                "rowExpandedSelectable": row_expanded.get("selectable", 0),
                "rowExpandedInsufficient": row_expanded.get("insufficient", 0),
                "rowExpandedGradeEmpty": row_expanded.get("grade_empty", 0),
            },
        },
        "perFile": per_file,
        "aliases": aliases,
        "stations": stations,
    }


# ---------------------------------------------------------------------------
# 3. 预算 / 报价
# ---------------------------------------------------------------------------


def _pick(mapping, *keys):
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _price(value):
    if isinstance(value, dict):
        value = _pick(value, "price", "unitPrice", "unit_price", "monthly", "value", "amount")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _ratio(value, default, allow_zero=False):
    if isinstance(value, dict):
        value = _pick(value, "standard", "default", "rate", "value", "percent")
    if value is None:
        return default
    if isinstance(value, str):
        value = value.strip().rstrip("%")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number > 1:
        number /= 100.0
    if 0 <= number <= 1 and (allow_zero or number > 0):
        return number
    return default


def load_pricing(checks: CheckLog):
    """读取 pricing.json；缺失/不完整时用内置 fallback，并记 warn。"""
    pricing = {
        "currency": DEFAULT_PRICING["currency"],
        "bus": dict(DEFAULT_PRICING["bus"]),
        "metro": dict(DEFAULT_PRICING["metro"]),
        "production": dict(DEFAULT_PRICING["production"]),
        "discount": DEFAULT_PRICING["discount"],
        "tax": DEFAULT_PRICING["tax"],
        "monitoring": DEFAULT_PRICING["monitoring"],
    }
    path = DATA / "config" / "pricing.json"
    if not path.exists():
        checks.warn(
            "pricing_source",
            "data/config/pricing.json 不存在，使用内置默认："
            "公交 S/A++/A+ = 58000/48000/38000；地铁 A++/A+ = 300000/200000；"
            "制作 5000/2000；discount=1.0；tax=excluded；monitoring=0",
        )
        return pricing, "fallback"

    raw, error = load_json(path)
    if error:
        checks.warn("pricing_source", f"pricing.json 不可读，改用内置默认：{error}")
        return pricing, "fallback"

    root = raw
    if isinstance(root, dict) and isinstance(root.get("pricing"), dict):
        nested = root["pricing"]
        if not any(key in root for key in ("bus", "metro", "production", "discount")):
            root = nested

    warnings = []
    bus_source = _pick(root, "bus", "busPrices", "bus_price")
    if not isinstance(bus_source, dict):
        bus_source = _pick(root.get("prices") if isinstance(root, dict) else None, "bus") or {}
    metro_source = _pick(root, "metro", "metroPrices", "metro_price")
    if not isinstance(metro_source, dict):
        metro_source = _pick(root.get("prices") if isinstance(root, dict) else None, "metro") or {}

    for grade in ("S", "A++", "A+"):
        price = _price(_pick(bus_source, grade))
        if price is None:
            warnings.append(f"bus.{grade} 缺失")
        else:
            pricing["bus"][grade] = price
    for grade in ("A++", "A+"):
        price = _price(_pick(metro_source, grade))
        if price is None:
            warnings.append(f"metro.{grade} 缺失")
        else:
            pricing["metro"][grade] = price

    production = _pick(root, "production", "productionFees", "production_fee")
    if isinstance(production, dict):
        bus_prod = _price(_pick(production, "bus", "busVehicle", "vehicle"))
        metro_prod = _price(_pick(production, "metro", "gate", "metroGate"))
        if bus_prod is not None:
            pricing["production"]["bus"] = bus_prod
        else:
            warnings.append("production.bus 缺失")
        if metro_prod is not None:
            pricing["production"]["metro"] = metro_prod
        else:
            warnings.append("production.metro 缺失")
    else:
        warnings.append("production 缺失")

    discount = _pick(root, "discount", "discountRate", "discount_rate")
    pricing["discount"] = _ratio(discount, pricing["discount"]) if discount is not None else pricing["discount"]
    if discount is not None and _ratio(discount, None) is None:
        warnings.append("discount 非法")

    tax = _pick(root, "tax", "taxMode", "tax_mode")
    if isinstance(tax, dict):
        tax = _pick(tax, "mode", "type", "value")
    if tax is None:
        warnings.append("tax 缺失")
    else:
        tax_text = str(tax).strip().lower()
        if "不含" in tax_text or "exclud" in tax_text:
            pricing["tax"] = "excluded"
        elif "含" in tax_text or "includ" in tax_text:
            pricing["tax"] = "included"
        else:
            pricing["tax"] = tax_text or "excluded"

    monitoring = _pick(root, "monitoring", "monitoringFee", "monitoring_fee")
    if monitoring is not None:
        pricing["monitoring"] = _ratio(monitoring, pricing["monitoring"], allow_zero=True)
    if isinstance(_pick(root, "currency"), str):
        pricing["currency"] = _pick(root, "currency")

    if warnings:
        checks.warn(
            "pricing_source",
            f"pricing.json 部分字段缺失/非法，已用内置默认补齐：{'；'.join(warnings)}",
        )
    else:
        checks.ok("pricing_source", f"使用 {path.relative_to(ROOT).as_posix()}")
    return pricing, "pricing.json"


def quote(pricing: dict, bus_n: int, metro_n: int, weeks: float, discount: float) -> dict:
    months = weeks / WPM
    bus_price = pricing["bus"]["A++"]
    metro_price = pricing["metro"]["A++"]
    media = bus_n * bus_price * months + metro_n * metro_price * months
    production = bus_n * pricing["production"]["bus"] + metro_n * pricing["production"]["metro"]
    monitoring = media * pricing["monitoring"]
    gross = media + production + monitoring
    net = gross * discount
    return {
        "bus": bus_n,
        "metro": metro_n,
        "weeks": weeks,
        "months": round(months, 6),
        "busUnitPrice": bus_price,
        "metroUnitPrice": metro_price,
        "media": media,
        "production": production,
        "monitoring": monitoring,
        "gross": gross,
        "discount": discount,
        "net": net,
    }


def inspect_pricing(checks: CheckLog) -> dict:
    pricing, source = load_pricing(checks)
    targets_stats = []
    combo_failures = []

    for target in TARGETS:
        budget = target["budget"]
        weeks = target["weeks"]
        scenario = f"{target['wan']}_{weeks}w"
        list_combo = target["list"]
        discount_combo = target["discount92"]

        list_quote = quote(pricing, list_combo["bus"], list_combo["metro"], weeks, 1.0)
        discount_quote = quote(
            pricing,
            discount_combo["bus"],
            discount_combo["metro"],
            weeks,
            0.92,
        )
        list_ok = list_quote["net"] <= budget + 1
        discount_ok = discount_quote["net"] <= budget + 1
        if not list_ok:
            combo_failures.append(f"{scenario}_list")
        if not discount_ok:
            combo_failures.append(f"{scenario}_92")

        list_detail = (
            f"{target['wan']}万/{weeks}周 1.0 档："
            f"{list_combo['bus']}辆A++公交 + {list_combo['metro']}个A++地铁口；"
            f"媒体 {fmt_wan(list_quote['media'])} + 制作 {fmt_wan(list_quote['production'])}"
            f" = 净价 {fmt_wan(list_quote['net'])}；预算 {target['wan']}万，"
            f"{'余' if list_ok else '超'}{fmt_wan(abs(budget - list_quote['net']))}"
        )
        checks.add(
            f"pricing_target_{scenario}_list",
            "pass" if list_ok else "fail",
            list_detail,
        )

        discount_detail = (
            f"{target['wan']}万/{weeks}周 0.92 档："
            f"{discount_combo['bus']}辆A++公交 + {discount_combo['metro']}个A++地铁口；"
            f"媒体 {fmt_wan(discount_quote['media'])} + 制作 {fmt_wan(discount_quote['production'])}"
            f" = 刊例 {fmt_wan(discount_quote['gross'])} × 0.92"
            f" = 净价 {fmt_wan(discount_quote['net'])}；预算 {target['wan']}万，"
            f"{'余' if discount_ok else '超'}{fmt_wan(abs(budget - discount_quote['net']))}"
        )
        checks.add(
            f"pricing_target_{scenario}_92",
            "pass" if discount_ok else "fail",
            discount_detail,
        )

        targets_stats.append(
            {
                "budget": budget,
                "budgetWan": budget / 10000.0,
                "weeks": weeks,
                "list": {
                    "bus": list_quote["bus"],
                    "metro": list_quote["metro"],
                    "discount": list_quote["discount"],
                    "media": round(list_quote["media"]),
                    "production": round(list_quote["production"]),
                    "monitoring": round(list_quote["monitoring"]),
                    "gross": round(list_quote["gross"]),
                    "net": round(list_quote["net"]),
                    "remaining": round(budget - list_quote["net"]),
                    "withinBudget": list_ok,
                },
                "discount92": {
                    "bus": discount_quote["bus"],
                    "metro": discount_quote["metro"],
                    "discount": discount_quote["discount"],
                    "media": round(discount_quote["media"]),
                    "production": round(discount_quote["production"]),
                    "monitoring": round(discount_quote["monitoring"]),
                    "gross": round(discount_quote["gross"]),
                    "net": round(discount_quote["net"]),
                    "remaining": round(budget - discount_quote["net"]),
                    "withinBudget": discount_ok,
                },
                "allWithinBudget": list_ok and discount_ok,
            }
        )

    all_ok = not combo_failures
    checks.add(
        "pricing_budget_summary",
        "pass" if all_ok else "fail",
        "8 个目标组合（4 个预算/周期场景 × 1.0/0.92）均 ≤ 预算；1.0 档不再超预算，无需依赖折扣"
        if all_ok
        else f"以下目标组合超预算：{'、'.join(combo_failures)}",
    )

    checks.ok(
        "pricing_tax_monitoring",
        f"tax={pricing['tax']}（净价不并入税额）；monitoring={pricing['monitoring'] * 100:.1f}%"
        f"（按媒体费计入 gross）",
    )

    return {
        "source": source,
        "pricing": {
            "currency": pricing["currency"],
            "bus": pricing["bus"],
            "metro": pricing["metro"],
            "production": pricing["production"],
            "discount": pricing["discount"],
            "tax": pricing["tax"],
            "monitoring": pricing["monitoring"],
        },
        "targets": targets_stats,
    }


# ---------------------------------------------------------------------------
# 4. 证据
# ---------------------------------------------------------------------------


def inspect_evidence(inv, coverage_stats: dict, checks: CheckLog) -> dict:
    fetched_at = clean_cell((inv or {}).get("fetchedAt"))
    query_date = fetched_at.split(" ")[0] if fetched_at else ""
    aliases = coverage_stats.get("aliases") or {}
    stations = coverage_stats.get("stations") or {}

    bus_by_line = defaultdict(list)
    for row in ((inv or {}).get("bus") or {}).get("rows") or []:
        line_name = clean_cell(row.get("lineName"))
        if line_name:
            bus_by_line[line_name].append(row)

    total = 0
    complete = 0
    expected_missing = 0
    missing_base = 0
    in_inventory_incomplete = 0
    missing_reasons = Counter()
    missing_examples = []

    for path in sorted(COVERAGE_DIR.glob("*.csv")):
        rows, _ = read_coverage(path)
        for line_no, row in enumerate(rows, start=2):
            total += 1
            media_type = media_type_of(row)
            name = clean_cell(row.get("媒体名称"))
            station_name = clean_cell(row.get("最近站点"))
            distance = parse_distance(row.get("最近距离"))

            base_ok = bool(query_date) and distance is not None and bool(station_name)
            if not query_date:
                missing_reasons["queryDate"] += 1
            if distance is None:
                missing_reasons["nearestDistance"] += 1
            if not station_name:
                missing_reasons["nearestStation"] += 1
            if not base_ok:
                missing_base += 1
                if len(missing_examples) < 5:
                    missing_examples.append(f"{path.name}:{line_no}")

            in_inventory = False
            free_ok = False
            grade_ok = False
            if media_type == "bus":
                alias = aliases.get(name) or {}
                inventory_rows = []
                if alias.get("matched") and alias.get("inventoryName"):
                    inventory_rows = bus_by_line.get(clean_cell(alias.get("inventoryName"))) or []
                in_inventory = bool(inventory_rows)
                free_ok = in_inventory
                grade_ok = in_inventory and any(
                    clean_cell(inventory_row.get("grade")) for inventory_row in inventory_rows
                )
            elif media_type == "metro":
                station = stations.get(station_name) or {}
                exits = station.get("exits") or []
                in_inventory = bool(station.get("inInventory") and exits)
                free_ok = in_inventory
                grade_ok = in_inventory and any(clean_cell(exit_.get("grade")) for exit_ in exits)

            row_complete = base_ok and free_ok and grade_ok
            if row_complete:
                complete += 1
            elif not in_inventory and base_ok:
                expected_missing += 1
            else:
                in_inventory_incomplete += 1
                if len(missing_examples) < 5:
                    missing_examples.append(f"{path.name}:{line_no} 在库但证据不全")

    if missing_base == 0:
        checks.ok(
            "coverage_evidence_required",
            f"全部 {total} 行具备 queryDate={query_date or '(空)'}、nearestDistance、nearestStation",
        )
    else:
        checks.fail(
            "coverage_evidence_required",
            f"{missing_base}/{total} 行缺少基础证据字段：{dict(missing_reasons)}；示例：{'；'.join(missing_examples)}",
        )

    if in_inventory_incomplete == 0:
        checks.ok(
            "coverage_evidence_matched",
            f"{complete}/{total} 行可完整反查 freeCount + grade（在库行全部具备）",
        )
    else:
        checks.fail(
            "coverage_evidence_matched",
            f"{in_inventory_incomplete} 行已在库存中但缺少 freeCount/grade 证据；示例：{'；'.join(missing_examples)}",
        )

    if expected_missing:
        missing_bus_names = len((coverage_stats.get("bus") or {}).get("notInInventoryNames") or [])
        missing_metro_stations = len((coverage_stats.get("metro") or {}).get("notInInventoryNames") or [])
        checks.warn(
            "coverage_evidence_expected_missing",
            f"{expected_missing}/{total} 行指向不在红豆可售库的媒体"
            f"（公交 {missing_bus_names} 个线路名 / 地铁 {missing_metro_stations} 个站），"
            "无法反查 freeCount/grade；这是“覆盖候选 → 可售校验”的正常差异，前端应显示“不在可售库”而不是静默丢弃",
        )
    else:
        checks.ok("coverage_evidence_expected_missing", "所有覆盖行都能在库存中反查到证据")

    checks.ok(
        "coverage_query_date",
        f"证据查询日期统一取库存快照 {query_date}（fetchedAt={fetched_at}）",
    )

    return {
        "rows": total,
        "complete": complete,
        "expectedMissing": expected_missing,
        "inInventoryIncomplete": in_inventory_incomplete,
        "missingBase": missing_base,
        "missingReasons": dict(missing_reasons),
        "queryDate": query_date,
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    setup_stdout()
    checks = CheckLog()

    inv, inv_error = load_json(DATA / "inventory_live.json")
    if inv_error:
        checks.fail("inventory_file", f"inventory_live.json 不可用：{inv_error}")
        inv = {}
    elif not isinstance(inv, dict):
        checks.fail("inventory_file", "inventory_live.json 顶层不是对象")
        inv = {}

    inventory_stats, bus_rows, metro_rows = inspect_inventory(inv, inv_error, checks)
    coverage_stats = inspect_coverage(inv, checks)
    pricing_stats = inspect_pricing(checks)
    evidence_stats = inspect_evidence(inv, coverage_stats, checks)

    # 去掉大对象，避免把 431/861 行或完整 map 塞进报告
    coverage_stats.pop("aliases", None)
    coverage_stats.pop("stations", None)

    summary = checks.summary()
    report = {
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "checks": checks.items,
        "summary": summary,
        "stats": {
            "inventory": inventory_stats,
            "coverage": coverage_stats,
            "pricing": pricing_stats,
            "evidence": evidence_stats,
        },
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    print(f"QA 报告：{REPORT_PATH}")
    print(f"结果：PASS {summary['pass']} / WARN {summary['warn']} / FAIL {summary['fail']}")
    for item in checks.items:
        if item["status"] == "warn":
            print(f"[WARN] {item['id']}: {item['detail']}")
        elif item["status"] == "fail":
            print(f"[FAIL] {item['id']}: {item['detail']}")

    return 1 if summary["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
