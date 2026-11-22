# data/ 数据说明

> 所有数据来自赛题账号（红豆 + 新云大数据平台）与资料包 00–08；价格/合同为脱敏口径。

## 主数据

| 文件 | 内容 |
|---|---|
| `inventory_live.json` | 红豆库存（Q2）：bus 431 行 / metro 861 行；档期 2027-04-01～05-15；快照 2026-11-21 11:31 |
| `inventory_kaimenhong.json` | 开门红：2027-01-04～02-14；公交 1,242 辆 / 地铁 743 口可售 |
| `inventory_summer.json` | 暑期：2027-07-01～08-11；公交 1,442 辆 / 地铁 845 口可售 |
| `inventory_midautumn.json` | 中秋国庆：2027-08-30～10-10；公交 1,580 辆 / 地铁 823 口可售 |
| `manifest.json` | 15 个覆盖文件的索引（anchor/radius/count/bus/metro） |
| `bus_aliases.json` | 覆盖公交名 → 库存线路名（156 条，152 匹配） |
| `metro_station_map.json` | 覆盖站点 → 库存出入口（31 站/93 口查找表） |
| `app_data.json` | **历史单文件包**（2026-11-21 19:27，5 份人流 / 15 份覆盖）；前端实际读 `src/data.js`，演示不要用这个文件 |
| `footfall/lujiazui_202305.json` | 大数据平台 2023-05：70 条公交 + 49 个地铁口人流/触达，陆家嘴站画像与商圈边界 |
| `footfall/<anchorId>_202305.json` | 人民广场/徐家汇/美华/迪士尼：公交线 + 地铁口 `dailyReach`、站点 `aggregateReach`、核心站画像；迪士尼无地铁标签 |
| `geo/lujiazui_media_geo.json` | 陆家嘴：70 条公交折线（简化后 8,043 点）+ 1,779 个站点 + 49 个地铁口坐标 |
| `geo/*_media_geo.json` | 人民广场 66 线/31 口、徐家汇 30 线/14 口、美华 30 线/26 口、迪士尼 31 线/0 口；公交折线+站点+地铁口坐标 |

## 配置 `config/`

| 文件 | 用途 |
|---|---|
| `pricing.json` | 公交/地铁单价、制作费、折扣（默认 1.0，0.92 示例）、税 6% excluded、监测 0 |
| `contract_terms.json` | 直客 vs 4A：税、验收、监测 SLA、损一补一/误一补二 |
| `schedule_rules.json` | T-14、夜间分批、雨天、T+1/T+5、直客/4A；引用 windows.json |
| `windows.json` | 四个已验证档期：开门红/春季Q2/暑期/中秋国庆（起止、行业、锚点、库存文件） |
| `anchors.json` | 五行业各一：美华/陆家嘴/人民广场/徐家汇/迪士尼；嘉会/和睦家保留为数据样本 |
| `industries.json` | 五行业各一：银行=浦发/陆家嘴（默认）、医院=美华、食品=农夫山泉/人民广场、保健品=汤臣倍健/徐家汇、乐园=上海迪士尼/迪士尼 |
| `briefs.json` | 五行业 campaign 假设书（七要素、KPI 口径、参考 brief 差异、合规、100/200/500 复用）；对应 `docs/campaign假设书_五行业.md` |
| `footfall.json` | 公交 05 级别均值 + 5 个锚点平台人流索引；2023 免责 |

## 报告 `reports/`

| 文件 | 内容 |
|---|---|
| `qa_report.json` | 33 PASS / 2 WARN / 0 FAIL；警告为公交数量恒等式差异、覆盖候选不在库（正常） |
| `capacity_report.json` | 8 锚点组 × 4 预算项 × 3 媒体 × 2 折扣；并集 500 万可行；和睦家单锚点 500 万缺 1 口；迪士尼无红豆地铁口 |
| `coverage_join_report.json` | 公交 156 = 132 可售 + 20 空位不足 + 4 不在库；地铁 93 口 = 82 + 6 + 5 grade 空 |

## 重新生成

```bash
python -I tools/build_manifest.py
python -I tools/build_links.py
python -I data/reports/_build_reports.py
python -I tools/build_footfall.py
python -I tools/build_geo.py
python -I tools/build_geo_anchors.py
python -I tools/qa_data.py
python -I tools/build_app_data.py
```

> 陆家嘴人流原始 JSON（`footfall_*_raw.json`）由 ZCode 在 IAB 里抓取；`build_footfall.py` 只做合并。

> `data/raw/`、`materials/`、`extracted/` 不进 Git；`data/*.json`、`data/coverage/*` 进 Git。
