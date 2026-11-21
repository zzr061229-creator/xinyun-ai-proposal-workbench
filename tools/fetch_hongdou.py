#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Fetch live Hongdou inventory via its internal HTTP API.

Usage:
  python -I tools/fetch_hongdou.py --start 2027-04-01 --end 2027-05-15

Requires config.local.json with {baseUrl, token, tenant} (gitignored).
"""
import argparse
import csv
import json
import os
import time
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "config.local.json"
OUT = ROOT / "data" / "inventory_live.json"
PAGE_SIZE = 100
MAX_PAGES = 20


def load_cfg():
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    proxy = cfg.get("proxy") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    session = requests.Session()
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
    session.headers.update({
        "Authorization": f"Bearer {cfg['token']}",
        "tenant-id": str(cfg["tenant"]),
    })
    return cfg, session


def get_json(session, url, retries=5, timeout=30):
    last = None
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # proxy/connection flakiness
            last = e
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"GET failed after {retries} tries: {url}") from last


def collect(cfg, session, kind, start, end):
    extra = (
        "lineId=&lineName=&lineLevel=&mediaType=&keyword=&extendState=&agentName=&companyId="
        if kind == "bus"
        else "lineId=&lineName=&lineLevel=&mediaType=&keyword=&pointFeatureKeyword=&extendState=&agentName=&companyId="
    )
    base = cfg["baseUrl"]
    rows = []
    seen = set()
    total = None
    for page in range(1, MAX_PAGES + 1):
        url = (
            f"{base}/admin-api/orders/media-inventory/{kind}/page"
            f"?pageNo={page}&pageSize={PAGE_SIZE}&{extra}"
            f"&startDate={start}&endDate={end}"
        )
        data = get_json(session, url).get("data") or {}
        if total is None:
            total = data.get("total")
        batch = data.get("list") or []
        if not batch:
            break
        for item in batch:
            key = (
                item.get("resourceId"),
                item.get("mediaName"),
                item.get("metroNumber") or item.get("lineName"),
            )
            if key in seen:
                continue
            seen.add(key)
            rows.append(item)
        if total is not None and len(rows) >= total:
            break
        time.sleep(0.25)
    return rows, total


def fill_missing_bus(cfg, session, rows, start, end):
    """Hongdou pagination can skip a row at page boundaries; fill from the baseline route list."""
    baseline = ROOT / "data" / "bus_inventory_2027Q2.csv"
    if not baseline.exists():
        return 0
    have = {(r.get("lineName"), r.get("mediaName")) for r in rows}
    seen = {(r.get("resourceId"), r.get("mediaName")) for r in rows}
    missing = []
    for r in csv.DictReader(baseline.open(encoding="utf-8-sig")):
        key = (r.get("线路"), r.get("媒体类型"))
        if key not in have:
            missing.append(key)
    filled = 0
    for line, media in missing:
        extra = (
            f"lineId=&lineName={quote(str(line))}&lineLevel=&mediaType=&keyword="
            "&extendState=&agentName=&companyId="
        )
        url = (
            f"{cfg['baseUrl']}/admin-api/orders/media-inventory/bus/page"
            f"?pageNo=1&pageSize=100&{extra}&startDate={start}&endDate={end}"
        )
        data = get_json(session, url).get("data") or {}
        for item in data.get("list") or []:
            if item.get("lineName") != line or item.get("mediaName") != media:
                continue
            rid = item.get("resourceId")
            dedup = (rid, item.get("mediaName"))
            if dedup in seen:
                continue
            seen.add(dedup)
            rows.append(item)
            filled += 1
    return filled


def load_grade_maps():
    bus = {}
    p = ROOT / "data" / "bus_inventory_2027Q2.csv"
    if p.exists():
        for r in csv.DictReader(p.open(encoding="utf-8-sig")):
            bus[(r.get("线路"), r.get("媒体类型"))] = r.get("线路等级")
            bus.setdefault(r.get("线路"), r.get("线路等级"))
    metro = {}
    p = ROOT / "data" / "metro_inventory_2027Q2.csv"
    if p.exists():
        for r in csv.DictReader(p.open(encoding="utf-8-sig")):
            metro[r.get("地铁编号")] = r.get("媒体等级")
    return bus, metro


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2027-04-01")
    ap.add_argument("--end", default="2027-05-15")
    ap.add_argument("--out", default=str(OUT), help="output JSON path (default data/inventory_live.json)")
    ap.add_argument("--window", default=None, help="window id, e.g. kaimenhong/summer/midautumn")
    args = ap.parse_args()

    cfg, session = load_cfg()
    bus_map, metro_map = load_grade_maps()

    bus, bus_total = collect(cfg, session, "bus", args.start, args.end)
    bus_filled = fill_missing_bus(cfg, session, bus, args.start, args.end)
    metro, metro_total = collect(cfg, session, "metro", args.start, args.end)

    for r in bus:
        r["grade"] = bus_map.get((r.get("lineName"), r.get("mediaName"))) or bus_map.get(r.get("lineName"))
    for r in metro:
        r["grade"] = metro_map.get(r.get("metroNumber"))

    payload = {
        "fetchedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "range": {"start": args.start, "end": args.end},
        "bus": {"total": bus_total, "rows": bus},
        "metro": {"total": metro_total, "rows": metro},
    }
    if args.window:
        payload["window"] = args.window
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "saved": str(out),
        "bus": {"total": bus_total, "rows": len(bus), "filled": bus_filled, "free": sum(float(r.get("freeCount") or 0) for r in bus)},
        "metro": {"total": metro_total, "rows": len(metro), "free": sum(float(r.get("freeCount") or 0) for r in metro)},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
