# 新云 AI 提案工作台 · 前端（src/）

> INTERCITY HACK 湖州场 · AI＋办公 · 上海新云传媒命题
> 静态单页工作台：选行业 → 品牌固定、锚点结构按行业切换（单点 / 多网点）→ 预算/媒体/档期/报价口径 → 从红豆库存与大数据覆盖里选点 → 方案表 + 报价 + 排期 → 导出 CSV / HTML 提案。

## 主入口

**`src/index-atlas.html`（ATLAS · 预算落图：`styles-atlas.css` + `atlas.js`）是唯一演示入口。**
`index.html`（B 原版）、`index-b2.html`（B 修订）保留可运行、不精修；三者共用 `app.js / engine.js / data.js / realmap.js`，新增 DOM（报价口径、触达列）三个 HTML 都有，`app.js` 对可选节点做了空值保护。

## 运行

```bash
cd 新云AI提案工作台
python src/build_data.py          # 从 ../data 重新生成 src/data.js（window.APP_DATA）
node src/test_engine.js           # 引擎自测，必须 ALL PASS
python -m http.server 8788
# 打开 http://127.0.0.1:8788/src/index-atlas.html
```

不改运行时加载方式：数据仍是 `data.js` 脚本注入（不 fetch），`file://` 双击可用（导出时底图内嵌需要 http）。
`python src/build_maps.py` 只在锚点中心变化时需要重跑（要网络；已存在的图片会复用）。
`python src/build_tiles.py` 下载 z13–16 离线瓦片（要网络；已存在的 tile 会复用）；默认地图用它，可缩放。
`python src/build_network_map.py` 拼中心三网点静态底图（读本地 z14 瓦片，输出 `assets/map-network-central.jpg` + `map-network.js`），导出 HTML 和多网点静态图用它。

## 五行业阵容（默认银行）

每个行业**一个品牌**；锚点可以是单点，也可以是多网点 bundle。选行业后品牌固定，不再出现品牌 chips；和睦家/嘉会数据保留但不进 UI。

| 行业 | 品牌 | 锚点 | 半径 | 文案来源 | 触达口径 |
|---|---|---|---|---|---|
| 银行保险（默认） | 浦发银行 | 3 真实支行：上海分行（浦东南路588号）+ 九江路支行（湖北路258号）+ 徐家汇支行（虹桥路188号） | 每点 1km | industries.json + anchor_bundles.json | 平台 2023-05（3 点，线路/出口级缓存） |
| 私立医院 | 上海美华妇儿医院 | 美华 | 1/3km | industries.json | 平台 2023-05 |
| 食品饮料 | 农夫山泉（饮用水，对外只说“同品类”） | 3 商圈：人民广场商圈 + 徐家汇商圈 + 陆家嘴商圈 | 每点 1km | industries.json + anchor_bundles.json | 平台 2023-05（3 点） |
| 保健品 | 汤臣倍健 | 徐家汇 | 1/3km | industries.json | 平台 2023-05 |
| 乐园 | 上海迪士尼 | 4 枢纽：人民广场 + 陆家嘴 + 徐家汇 + 迪士尼；另加全城 24 个在库地铁站 | 3/5km | industries.json + anchor_bundles.json | 平台 2023-05（4 点；20/24 站有数据） |

- 单一来源 = `data/config/industries.json` + `data/config/anchor_bundles.json`。`app.js` 里的硬编码 INDUSTRIES 已删除，改读 `APP_DATA.industries`。
- 多网点：`industries.json` 的 `anchorBundleIds` 指向 bundle；每个 member 有 `anchor / label / radius / weight`。银行三个网点是真实支行，覆盖按网点坐标 1km 重抓（2026-11-21），见 `data/coverage/覆盖分析_浦发银行*_1000米.json`；人流按平台 2023-05 线路/出口级缓存复用（`data/footfall/spdb-*_202305.json`）。引擎 `anchorsOf()` 把成员并成一个候选池，同一条公交线/同一个地铁口只留一次，距离和触达按最近的网点归位（`anchorLabel / reachAnchor`），评分用各网点自己的半径。`status: sample` 表示网点组合是演示假设。
- 单点行业（医院/保健）不配 bundle；乐园是 `disney-city` bundle（`citywide: true`）：4 枢纽负责公交，地铁候选扩到 24 个在库站并按区铺开。
- `build_data.py` 里有显式 `DEMO_LINEUP`：当 industries.json 的默认品牌/锚点与上表不一致或 `status≠ready` 时兜底，并打印 `[warn]`。industries.json 已与上表对齐，当前无 fallback；DEMO_LINEUP 只作兜底。
- 合规文案优先取配置 `compliance[].requirement`；银行额外加“对外只说「浦发上海分行在陆家嘴」，不说总部”。insight：ready 行业取配置 narrative，兜底行业用 DEMO_LINEUP 文案。
- deep link：`?industry=bank|hospital|food|health|park`（或完整 id）。

## 数据接入（build_data.py）

| 输入 | 处理 |
|---|---|
| `inventory_live.json` | 红豆 431 公交 / 861 地铁口；快照 2026-11-21 11:31:36；档期 2027-04-01～05-15 |
| `coverage/*.json` + `manifest.json` | 按 `anchors.json coverageIds → manifest → 文件` 定位，键 = anchors.json fullName（陆家嘴 = “陆家嘴金融城”）；**BD-09 → WGS84** |
| `bus_aliases.json` / `metro_station_map.json` | join：**公交 152/156**（4 条不在库：911路双层、旅游1/2/10线），**地铁站 27/35** |
| `config/industries,anchors,pricing,footfall.json` | 行业阵容、锚点别名、价格/折扣、05 样本级别均值 |
| `footfall/*.json`（**全部文件**，按 `anchorId` 归属） | 公交按线路名经 aliases 匹配库存线；地铁按 站 + 出口（“3A号口”=“3A口”）匹配库存口 id |
| `geo/*_media_geo.json`（**全部文件**） | 公交折线 + 地铁口坐标，**GCJ-02 → WGS84**（与覆盖的 BD-09 转换是两个函数，不混用） |

- 陆家嘴金融城 3km = **87 条（76 公交 / 11 地铁）**，不是旧的 84；build 时打印校验。
- 新的人流/几何文件放进 `data/footfall/`、`data/geo/` 重跑 `build_data.py` 即接入，无需改代码。当前：人流只有陆家嘴（公交 70/70、地铁口 34/49 对上库存口）；几何已有陆家嘴/人民广场/徐家汇/美华/迪士尼五份。
- `data.js` 当前约 0.94 MB；超过 2 MB 会自动只保留覆盖圈 1.6 倍范围内的折线点。

### 坐标抽查（GCJ-02 → WGS84）

用 OSM `railway=subway_entrance`（2026-11-21 Overpass）对陆家嘴站 7 个口、浦东大道站 8 个口抽查（build 时自动打印）：

- 原始 GCJ-02 与 OSM 偏差约 **450–530m**；转换后 **中位 20m，最大 67m**（浦东大道 5/6 号口，疑似 OSM 口位标注差异）。
- 覆盖（BD-09）的既有实证：451 路人民广场站转换后与 OSM 差 11.5m；个别“最近站”100–400m 残差来自平台最近站点与 OSM 停靠点不同。

## 人流 / 触达口径

- 条目字段 `dailyReach` = 平台 2023-05「触达人群-日均人次」：公交按**线路**，地铁按**出入口**。**无平台标签 → `null`，显示“无数据”，绝不写 0**（如世纪大道、豫园 3A 号口、旅游线、840 路）。
- 方案 `summary.reach`：
  - **有平台人流的锚点**（当前仅陆家嘴）：公交 = 车辆数 × 线路日均触达（沿用 footfall.json 公式）；地铁单口用该口值，**同站 ≥2 口不相加**，用站点 `aggregateReach`（合并去重），且不低于其中最大单口（去重并集不可能小于任一组成口）。例：陆家嘴站 2+3 号口单口 188,974 + 200,490，计 200,490 而不是 389,464。标“平台 2023-05”。
  - **没有平台人流的锚点**：公交按 05 历史提案样本级别均值（S 12.53 / A++ 9.69 / A+ 8.72 万/辆/日）估算，地铁不计，标“样本估算”。
- 公交与地铁之间未去重；**2023 数据仅作相对权重，不代表 2027 绝对值，不构成合同承诺**（页面、CSV、导出 HTML 都写明）。
- ATLAS 头部一行按口径区分“平台数据 / 样本估算”。

## 公交 = 线路（地图表达）

- 选中公交 = **整条线路折线**（`--map-bus`，3.5px），候选公交 = 极淡细线（`--map-cand`）；不再画公交圆点，删除“锚点→站点”虚线。
- 线路最近经过锚点处只画一个很小的刻度；悬停/标签为“线路 · 最近经过 XX站 · 距锚点 xxm”。
- 地铁口：有几何的用**真实出入口坐标**（空心环 = 已选）；无几何的锚点用覆盖里的站点坐标。
- 锚点无几何文件 → 地图角落提示“该锚点线路几何待补，公交见右侧清单”；有几何但个别选中线路缺折线 → “N 条选中线路无几何，见清单”，清单该行标“线路几何缺失”。**不用直线/假路径冒充线路。**
- 在线 Leaflet、离线快照、导出 HTML 的 SVG 三处一致；颜色只用 `theme()` 读的 CSS 变量。
- `window.ProposalApp.markers`：`metro:<出口id>` → circleMarker；`bus:<线路>` → polyline。ATLAS 悬停联动对 polyline 加粗/提亮/置顶。

## 报价 / 折扣口径

- 默认 **1.0 刊例**（媒体费 + 制作费，不打折）；可切 **0.92 示例**，页面标「示例假设，待销售确认」；**0.88 只在销售视图当底线**。
- `engine.js`：折扣由 `brief.discount` 传入（兼容 `brief.pricing.discount`），默认取 `pricing.json discount.default`；单价/制作费也从 `APP_DATA.pricing` 读。
- 报价卡、瀑布图、方案表、CSV、导出 HTML 全部跟随当前折扣，不再写死“92%”。不含税（6% 专票另计），监测费 0。
- deep link：`?discount=0.92`。

## 档期

四档期（开门红 / 春季 Q2 / 暑期 / 中秋国庆），每档 6 周内可选 4/6 周；按行业默认档期，切档期换库存快照。12 周只在引擎测试里跑。

## AI brief 解析（已启用：规则 + 可选在线模型）

主入口首屏有「一句话」输入框；实现见 `src/brief.js`，用法见 `docs/brief解析接入.md`。

```js
ProposalApp.parseBrief(text)   // 离线规则解析，返回结构化 brief；无法解析返回 null
ProposalApp.applyBrief(brief)  // 结构化 brief → 状态 → 重算，返回实际生效字段
```

默认走离线规则；把 `index-atlas.html` 里 `brief.js` 的 `data-ai` 指向 `tools/brief_proxy.py` 时走在线模型，失败/超时自动回退规则解析。AI 只做参数翻译；价格、库存、触达仍由 `engine.js` 计算。

答案下方的「AI 解释」由 `src/ai-explain.js` 负责：把已算好的方案压成 payload，POST `/api/explain`，让 DeepSeek 写 120–180 字 WHY；没配 AI 时用模板。它只解释，不改数字。

约定 `parseBrief` 的返回格式（字段可缺省 = 保持当前值；无法解析返回 `null`）：

```js
{
  industryId: "bank-insurance" | "private-hospital" | "food-beverage" | "health-supplement" | "theme-park", // 也接受 bank/hospital/food/health/park
  budget: 2000000,          // 元（100–500 万）；也接受“万”数值 100–500
  weeks: 4 | 6,             // 在所选档期窗口内截取
  windowId: "kaimenhong" | "q2" | "summer" | "midautumn", // 缺省按行业默认
  media: { bus: true, metro: true } | "bus" | "metro" | "both",
  radius: 3000,             // 米，须是该锚点已有覆盖半径
  discount: 1 | 0.92        // 刊例 / 92 折示例
}
```

## 实测（node src/test_engine.js）

五行业默认演示 · 200 万 / 6 周 · 折扣 1.0：

| 行业 | 组合 | 净价 | 触达口径 |
|---|---|---:|---|
| 银行 · 3 真实支行（开门红） | 2 口 + 15 辆 | 197.6 万 | 平台 2023-05（3 点），日均约 156.9 万人次 |
| 医院 · 美华（Q2） | 2 口 + 15 辆 | 199.0 万 | 平台 2023-05 |
| 食品 · 3 商圈（暑期，按人流 40/38/22） | 1 口 + 21 辆 | 198.7 万 | 平台 2023-05（3 点），日均约 281.1 万人次 |
| 保健品 · 徐家汇（中秋国庆） | 1 口 + 20 辆 | 197.1 万 | 平台 2023-05 |
| 乐园 · 全城 4 枢纽 + 24 站（暑期） | 5 口 + 42 辆 | 497.8 万 | 平台 2023-05（4 点；20/24 站有数据，4 站标“—”；迪士尼站本身无地铁口 → 环园公交） |

单锚点回归（测试用，陆家嘴金融城 3km）：

| 预算 / 周期 | 1.0 刊例 | 0.92 示例 |
|---|---|---|
| 100 万 / 4 周 | 2 口 + 8 辆 · 95.2 万 | 2 口 + 10 辆 · 96.7 万 |
| 200 万 / 6 周 | 2 口 + 16 辆 · 199.2 万 | 3 口 + 12 辆 · 195.4 万 |
| 500 万 / 6 周 | 5 口 + 39 辆 · 492.9 万 | 6 口 + 39 辆 · 494.4 万 |
| 500 万 / 12 周（仅测试） | 2 口 + 23 辆 · 489.3 万 | 3 口 + 20 辆 · 488.7 万 |

> 这是引擎按打分实际选出的组合；路演讲数时以页面实时结果为准。当前银行 200 万 = 2 口 + 15 辆、197.6 万。

测试覆盖（当前 **ALL PASS**，2208 项检查）：五行业 × 100/200/500 万 × 4/6 周不超预算；银行真实 3 支行并集去重、200/500 万三网点均覆盖、`reachAnchor` 分网点触达；乐园全城 500 万 ≥4 口/≥4 站/≥3 区 + 100/200 万地铁公交均 >0；只地铁 / 只公交（单锚点迪士尼只地铁 = 空方案 + “只地铁不可行” warning）；折扣 1.0 与 0.92（行净价 = (刊例+制作)×折扣）；同站 ≤2 口；qty ≤ 空位；行净价和 = 总净价；地铁同站触达不相加；无标签 = null；陆家嘴 87 条、join 152/156 与 24/31。

## 浏览器 QA（Edge headless）

```bash
EDGE="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
"$EDGE" --headless=new --window-size=1440,900 --virtual-time-budget=9000 --dump-dom "http://127.0.0.1:8788/src/index-atlas.html?qa=export"
"$EDGE" --headless=new --window-size=1440,900 --virtual-time-budget=12000 --screenshot=shot.png "http://127.0.0.1:8788/src/index-atlas.html?industry=bank"
```

- 三个入口 `?qa=export`：`data-planrows=13`、`data-export-has-basemap=true`、`data-export-has-quote=true`；scrollWidth = clientWidth（无横向滚动）；DOM 无 NaN/undefined；控制台无报错。
- ATLAS 五行业 `?qa=export&industry=…` 同样通过；`?discount=0.92`、`?map=offline` 通过。
- 1440×900 首屏截图：`design/design-demos/shots/atlas-{bank,hospital,food,health,park}.png`（五张都能看到选中公交折线）。headless 最小宽约 500，390 截图会被裁，不算 bug。
- `?qa=1` 写 scrollWidth/rows/mapmode/tiles；`?qa=export` 额外写导出 HTML/CSV 长度与是否含地图/底图/报价。导出 HTML 约 1.1–3.1 MB（含底图 data URI 与折线）。

## 文件

```text
src/
├─ index-atlas.html / styles-atlas.css / atlas.js   # 主入口 ATLAS
├─ brief.js      # 一句话 brief 解析（离线规则 + 可选在线模型回退）
├─ ai-explain.js # AI 解释：把已算好的方案压成 payload，生成 WHY；无 AI 时模板兜底
├─ index.html / styles.css                          # B 原版（保留）
├─ index-b2.html / styles-b2.css                    # B 修订（保留）
├─ app.js        # 状态、渲染、地图（线路折线）、双视图、导出；window.ProposalApp
├─ engine.js     # 纯函数：候选/打分/组合/报价/触达/排期（Node + 浏览器）
├─ realmap.js    # 离线快照 SVG（同样画线路折线），导出复用
├─ map.js        # 无底图时的示意投影兜底
├─ data.js       # build_data.py 生成物（不要手改）
├─ map-assets.js / assets/   # build_maps.py 生成的 OSM z14 静态快照（导出/兜底）
├─ tile-assets.js / assets/tiles/  # build_tiles.py 生成的 z13–16 离线瓦片（默认地图，可缩放）
├─ build_data.py / build_maps.py / build_tiles.py / test_engine.js
└─ vendor/       # Leaflet 1.9.4（本地）
```

## 已知限制

1. 库存是 2026-11-21 的四段快照（Q2 11:31、其余 17:04–17:05）；四档期独立，签约前回红豆复核。
2. 平台人流已覆盖五个锚点（陆家嘴/人民广场/徐家汇/美华/迪士尼，2023-05）；无平台标签的口/站显示“无数据”，不估算。
3. 地铁触达是平台“区域触达”口径，不是闸机客流；公交 PV 偏大，方案只用 dailyReach。
4. 92 / 88 折无资料依据，均为示例；报价不含税；监测费 0。
5. 医疗/金融/食品/保健品/乐园合规文案为通用清单，未经法务复核。
6. **默认用内置离线瓦片（OSM z13–16，可缩放，不依赖网络）**；点“切在线地图”才请求 OSM。静态 z14 SVG 仍用于导出/兜底。底图 © OpenStreetMap contributors (ODbL)；Leaflet BSD-2。
