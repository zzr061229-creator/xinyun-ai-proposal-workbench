# 新云 AI 提案工作台

> INTERCITY HACK · 湖州场｜AI＋办公赛道｜企业命题方：上海新云传媒
> 2026.11.21–22 · 湖州南太湖 CBD

## 一句话

给户外媒体公司造一个工作台：选行业、给预算、定档期，系统从红豆真实库存里挑线路和点位，90 秒生成一份能直接给客户讲的 HTML 投放提案；评委现场改预算/换行业，当场重算。

## 目录结构

```text
新云AI提案工作台/
├─ README.md / HANDOFF.md / CLAUDE.md
├─ src/
│  ├─ index-atlas.html        # ★ 演示入口
│  ├─ index.html / index-b2.html  # 旧设计备份，不作为演示入口
│  ├─ styles-atlas.css / app.js / engine.js / atlas.js
│  ├─ brief.js / ai-explain.js / realmap.js / map.js
│  ├─ map-network.js / map-citywide.js / map-assets.js
│  ├─ data.js / tile-assets.js（生成物）
│  ├─ vendor/                 # Leaflet 本地文件
│  ├─ assets/tiles/           # z12–z16 离线瓦片（约 44MB，zip 不含）
│  ├─ assets/map-*.png|jpg    # 静态底图
│  ├─ build_data.py / build_tiles.py / build_citywide_map.py
│  └─ test_engine.js          # 自测：node src/test_engine.js
├─ data/
│  ├─ config/                 # industries / anchors / bundles / windows / briefs / pricing
│  ├─ coverage/               # 10 个锚点覆盖（1/3km，迪士尼 5km）
│  ├─ footfall/               # 2023-05 人流（5 行业 + 浦发 3 支行）
│  ├─ geo/                    # 公交折线 / 地铁口坐标（8 个点位）
│  ├─ inventory_*.json        # 四档期库存快照
│  └─ reports/                # QA / 容量 / join 报告
├─ docs/                      # 分析、路演、一页纸、合规、档期、campaign
├─ docs/submission/           # 提交包（一页纸 PDF / 截图 / zip）
├─ tools/                     # 红豆/数据/QA 脚本
└─ materials/ extracted/ data/raw/   # 不进 Git
```

## 数据快照

库存查询档期：**2027-04-01 ～ 2027-05-15**（红豆系统）。

| 媒体 | 条数 | 总量 | 可售 | 合同占用 | 预定占用 |
|---|---:|---:|---:|---:|---:|
| 公交 | 431 条线路 | 2,525 辆 | 1,376 辆 | 571 辆 | 371 辆 |
| 地铁 | 861 个出入口 | 861 个 | 824 个 | 35 个 | 2 个 |

公交分级：

| 级别 | 线路数 | 总车辆 | 可售 | 合同 | 预定 |
|---|---:|---:|---:|---:|---:|
| A++ | 200 | 1,431 | 757 | 356 | 218 |
| A+ | 181 | 556 | 310 | 166 | 1 |
| S | 48 | 511 | 286 | 45 | 152 |
| AA | 2 | 27 | 23 | 4 | 0 |

覆盖分析样板：人民广场 1km，30 条公交/地铁媒体，含最近距离、站点、经纬度。

## 关键口径（已从资料包提取）

- 公交实际报价：S 58,000 / A++ 48,000 / A+ 38,000 元/辆/月；制作费 5,000 元/辆。
- 地铁刊例：A++ 25–35 万/点/月；A+ 15–25 万/点/月；制作费 100 元/㎡。
- 直客合同：6% 增值税专票；预付 + 验收后尾款；车辆损坏「损一补一」；雨天/政府管制顺延。
- 4A 框架：非甲方原因延误/制作不合格/维护不及时「误一补二」；上刊证明 T+1、上刊监测 T+5、下刊 T+5、月监测。
- 排期卡点：夜间施工、分批安装、雨天停工，提案需预留制作/审批/安装窗口。

## 当前状态

- [x] 红豆公交 431 / 地铁 861 真实库存导出；四档期快照（开门红/春季/暑期/中秋国庆）
- [x] 大数据覆盖 10 个锚点；5 个行业 / 浦发 3 支行 2023-05 人流；139 条公交几何/人流；24 个在库站坐标
- [x] 五行业配置：银行 3 支行、食品 3 商圈、乐园 4 枢纽 + 24 站、医院/保健单锚点
- [x] ATLAS 前端：预算条、地图联动、客户/销售双视图、CSV/HTML 导出、离线瓦片
- [x] QA：`node src/test_engine.js` 2208 项 ALL PASS；`python tools/qa_data.py` 33 PASS / 2 WARN / 0 FAIL
- [x] GitHub Pages 已上线全城版（远端 `2179a43`，Pages 从 master 发布）
- [x] 团队名已填（404 Not Found：朱周睿 / 黄婷蕊）；一页纸分工表待确认
- [ ] `data/app_data.json` 仍是旧单文件包；前端实际用 `src/data.js`，不影响演示

## 运行

```bash
cd 新云AI提案工作台
python -m http.server 8788
# 打开 http://127.0.0.1:8788/src/index-atlas.html
# 乐园全城：http://127.0.0.1:8788/src/index-atlas.html?industry=park
```

重建数据（可选）：

```bash
python src/build_data.py        # 从 ../data 生成 src/data.js
python src/build_tiles.py       # 下载/补齐离线瓦片（需要网络）
python src/build_citywide_map.py # 生成全城静态底图
```

自测（交付前跑）：

```bash
node src/test_engine.js   # 引擎/报价/排期，当前 2208 项 ALL PASS
python tools/qa_data.py   # 库存/覆盖/join，当前 33 PASS / 2 WARN / 0 FAIL
```

> `materials/`、`extracted/`、`data/raw/` 体积较大，默认不纳入 Git；`data/*.csv` 与 `inventory_summary.json` 纳入。`src/assets/tiles/` 约 44MB，保留用于离线演示，但不打进提交 zip。

## 当前入口

- 主入口：`src/index-atlas.html`（ATLAS 皮肤）
- 线上：https://zzr061229-creator.github.io/xinyun-ai-proposal-workbench/
- 导出：页面「导出提案」生成单文件 HTML；「导出 CSV」出明细
- 交接：`HANDOFF.md`；演示：`docs/路演脚本_4分钟.md`
