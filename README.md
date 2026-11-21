# 新云 AI 提案工作台

> INTERCITY HACK · 湖州场｜AI＋办公赛道｜企业命题方：上海新云传媒
> 2026.11.21–22 · 湖州南太湖 CBD

## 一句话

给户外媒体公司造一个工作台：选行业、给预算、定档期，系统从红豆真实库存里挑线路和点位，90 秒生成一份能直接给客户讲的 HTML 投放提案；评委现场改预算/换行业，当场重算。

## 目录结构

```text
新云AI提案工作台/
├─ README.md                 # 本文件
├─ HANDOFF.md                # ★ 项目交接：边界 / 数据契约 / 预算真相 / 演示
├─ docs/                     # 分析、介绍页、提交文档
│  ├─ 00_项目分析.md          # 赛题拆解 / 评分反推 / 技术方案 / 48h 计划
│  ├─ 开发任务书.md            # ★ P0 功能与验收标准（DS Harness 必读）
│  ├─ 01_项目介绍.html        # 单文件项目介绍页（可离线打开）
│  ├─ 项目介绍_通俗版.html     # 通俗讲解版
│  ├─ 数据接入说明.md          # 红豆 API / 大数据接口实测与刷新策略
│  ├─ 银行数据包_陆家嘴.md     # ★ 银行 P0：锚点/人流/画像/容量
│  ├─ 02_项目体检报告.md       # 数据口径 / 预算硬伤 / P0 阻断项
│  ├─ DS_HARNESS_启动.md      # API Key 配置 + 开发任务启动命令
│  └─ 一页纸_模板.md          # 提交物「一页纸」待填模板
├─ data/                     # 结构化数据（进 Git）
│  ├─ README.md               # 数据说明 / 重新生成命令
│  ├─ bus_inventory_2027Q2.csv
│  ├─ metro_inventory_2027Q2.csv
│  ├─ inventory_summary.json
│  ├─ inventory_live.json     # CLI 实时拉取结果（431/861）
│  ├─ manifest.json           # 数据索引（库存 + 覆盖）
│  ├─ bus_aliases.json        # 覆盖公交名 → 库存线路名
│  ├─ metro_station_map.json  # 覆盖站点 → 库存出入口
│  ├─ app_data.json           # ★ 给原型的单文件数据包（库存+配置+覆盖）
│  ├─ config/                 # pricing / contract / schedule / anchors / industries / footfall
│  ├─ reports/                # qa / capacity / coverage_join 报告
│  ├─ coverage/               # 10 个锚点，1/3km（迪士尼 5km；浦发 3 支行各 1km）
│  ├─ footfall/               # 平台 2023-05 人流/画像快照（8 个点位）
│  ├─ geo/                    # 线路折线/站点/地铁口坐标（8 个点位）
│  └─ raw/                    # 红豆原始导出 xlsx（不进 Git）
├─ materials/                # 赛题资料包 00–08（不进 Git）
├─ extracted/                # 资料包文本/页面图（不进 Git）
├─ tools/                    # 数据脚本
│  ├─ extract_docs.py         # docx/xlsx/pptx/pdf → txt
│  ├─ parse_inventory.py      # 红豆 xlsx → CSV + 汇总
│  ├─ fetch_hongdou.py        # 红豆 API CLI（分页 + 去重 + 补漏）
│  ├─ quote_reality.py        # 预算现实校验
│  ├─ build_manifest.py       # 生成 data/manifest.json
│  ├─ build_links.py          # 生成 bus_aliases / metro_station_map
│  ├─ qa_data.py              # 库存/join/预算/证据 QA
│  └─ build_app_data.py       # 生成 data/app_data.json
└─ src/                      # ★ 原型代码（DS Harness 负责）
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

- [x] 资料包 00–08 下载/解析
- [x] 红豆公交 431 / 地铁 861 真实库存导出
- [x] 红豆 API 命令行已验证（`tools/fetch_hongdou.py`：431 条 / 可售 1,376；861 / 824）
- [x] 2027 Q2 档期空车数/合同/预定拆分
- [x] 大数据覆盖：人民广场 + 和睦家/嘉会/美华 + 迪士尼/陆家嘴/徐家汇，1/3km
- [x] 覆盖→库存映射：`bus_aliases.json`（156 条 / 152 匹配）、`metro_station_map.json`（27/35 站在库）
- [x] 陆家嘴人流：70 条公交 + 49 个地铁口（2023-05，平台指标）+ 陆家嘴站人群画像
- [x] 配置层：pricing / contract / schedule / anchors / industries / footfall
- [x] 数据 QA / 容量报告 / `data/app_data.json`
- [x] 银行垂类：浦发 + 陆家嘴 ready（当前默认行业）
- [x] 项目分析、体检报告、介绍页、数据接入说明
- [x] 预算现实校验（默认 1.0 与 92 折示例均已复算）
- [ ] 原型：输入 → 选点 → 报价 → HTML 提案（DS Harness 负责）
- [ ] 5 行业模板 / 品牌锚点
- [ ] 预算滑块 / 客户-销售双视图 / 导出
- [ ] 演示脚本 / 一页纸 / README 运行说明

## 运行

当前只有介绍页和数据脚本：

```bash
# 预览介绍页
cd 新云AI提案工作台
python -m http.server 8788
# 打开 http://127.0.0.1:8788/docs/01_项目介绍.html

# 重新解析库存
python -I tools/parse_inventory.py

# 从红豆 API 实时拉取（需要 config.local.json 的 token）
python -I tools/fetch_hongdou.py --start 2027-04-01 --end 2027-05-15

# 重新提取资料包文本
python -I tools/extract_docs.py
```

> `materials/`、`extracted/`、`data/raw/` 体积较大，默认不纳入 Git；`data/*.csv` 与 `inventory_summary.json` 纳入。

## 下一步

1. 定主打行业/品牌（建议：私立医院 + 和睦家/嘉会，200 万，2027 Q2）。
2. 跑 3 个医院锚点的覆盖分析。
3. 搭 P0：真实库存 → 预算组合 → 报价 → HTML 提案 → 预算滑块。
4. 再扩乐园/银行现场变招、双视图、导出。
